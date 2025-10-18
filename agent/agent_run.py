import os, json, re, requests
from typing import Dict, Any
from dotenv import load_dotenv
from openai import AzureOpenAI
from datetime import datetime, timedelta
from datetime import datetime, timedelta
try:
    from zoneinfo import ZoneInfo
except Exception:
    ZoneInfo = None

import tzlocal  # add this

TIMEZONE = os.getenv("TIMEZONE", "Europe/Brussels")  # Antwerp/Belgium
DEFAULT_DURATION_MIN = int(os.getenv("DEFAULT_DURATION_MIN", "60"))
load_dotenv()

def get_zoneinfo(tz_name: str):
    """Return a tzinfo, falling back to local tz or UTC if IANA data missing."""
    # Try requested IANA name
    if ZoneInfo:
        try:
            return ZoneInfo(tz_name)
        except Exception:
            pass
    # Try system local zone (via tzlocal)
    try:
        local_name = tzlocal.get_localzone_name()
        if ZoneInfo:
            return ZoneInfo(local_name)
    except Exception:
        pass
    # Last resort UTC
    if ZoneInfo:
        return ZoneInfo("UTC")
    # Very last: naive (no tz) — not ideal, but avoids crash
    return None

# ===== Azure OpenAI =====
AZURE_OPENAI_ENDPOINT   = os.getenv("AZURE_OPENAI_ENDPOINT")
AZURE_OPENAI_API_KEY    = os.getenv("AZURE_OPENAI_API_KEY")
AZURE_OPENAI_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT")  # e.g. gpt-4o-mini

client = AzureOpenAI(
    api_key=AZURE_OPENAI_API_KEY,
    api_version="2024-08-01-preview",
    azure_endpoint=AZURE_OPENAI_ENDPOINT,
)

# ===== MCP servers =====
CAL_BASE   = os.getenv("CALENDAR_SERVER", "http://localhost:8080")
EMAIL_BASE = os.getenv("EMAIL_SERVER", "http://localhost:8090")

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

def extract_email(text: str) -> str | None:
    m = EMAIL_RE.search(text or "")
    return m.group(0) if m else None

def list_tools(base, ns):
    """Fetch /tools and build a usable schema for OpenAI tools."""
    r = requests.get(f"{base}/tools", timeout=10)
    r.raise_for_status()
    tools = r.json().get("tools", [])
    out = []
    for t in tools:
        name = t["name"]
        if not name.startswith(ns + "."):
            name = f"{ns}.{name}"

        props, required = {}, []
        input_desc = t.get("input", {}) or {}
        for k, v in input_desc.items():
            is_optional = str(v).endswith("?")
            base_type = str(v)[:-1] if is_optional else str(v)
            json_type = {"string": "string", "int": "integer", "bool": "boolean"}.get(base_type, "string")
            props[k] = {"type": json_type}
            if not is_optional:
                required.append(k)

        out.append({
            "type": "function",
            "function": {
                "name": name,
                "description": t.get("description", ""),
                "parameters": {
                    "type": "object",
                    "properties": props,
                    "required": required,
                    "additionalProperties": True
                }
            }
        })
    return out

# load tools
CAL_TOOLS   = list_tools(CAL_BASE,   "calendar")
EMAIL_TOOLS = list_tools(EMAIL_BASE, "email")
ALL_TOOLS   = CAL_TOOLS + EMAIL_TOOLS

TIME_RE = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b", re.I)

TIMEZONE = os.getenv("TIMEZONE", "Europe/Brussels")
DEFAULT_DURATION_MIN = int(os.getenv("DEFAULT_DURATION_MIN", "60"))

def get_zoneinfo(tz_name: str):
    if ZoneInfo:
        try:
            return ZoneInfo(tz_name)
        except Exception:
            pass
    try:
        local_name = tzlocal.get_localzone_name()
        if ZoneInfo:
            return ZoneInfo(local_name)
    except Exception:
        pass
    if ZoneInfo:
        return ZoneInfo("UTC")
    from datetime import timezone as _tz
    return _tz.utc

TZINFO = get_zoneinfo(TIMEZONE)

def parse_when(text: str, tzinfo=TZINFO) -> datetime | None:
    if not text:
        return None
    text_l = text.lower()
    base = datetime.now(tzinfo)
    if "tomorrow" in text_l:
        base = (base + timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
    m = TIME_RE.search(text_l)
    if not m:
        return None
    h = int(m.group(1)); mnt = int(m.group(2) or 0); ampm = (m.group(3) or "").lower()
    if ampm == "am" and h == 12: h = 0
    elif ampm == "pm" and h < 12: h += 12
    dtc = base.replace(hour=h, minute=mnt, second=0, microsecond=0)
    if "tomorrow" not in text_l and dtc <= datetime.now(tzinfo):
        dtc = dtc + timedelta(days=1)
    return dtc

def make_window_for(dt: datetime, duration_min: int, span_minutes: int = 240) -> tuple[str,str]:
    """
    Builds a window around the desired start. Default ±2h (240 min total).
    """
    start_w = (dt - timedelta(minutes=span_minutes//2)).isoformat()
    end_w   = (dt + timedelta(minutes=span_minutes//2)).isoformat()
    return start_w, end_w

def normalize_booking_args(args: dict, last_user_intent: str | None, tz: str) -> dict:
    """
    Ensure start/end are present, are in the *future*, and include timezone offset.
    Fills defaults: duration=60min, title='Appointment' unless provided.
    """
    args = dict(args or {})
    summary = args.get("summary") or args.get("title") or "Appointment"

    # detect when
    start_dt = None
    # 1) trust provided start_iso if it includes timezone
    provided = args.get("start_iso")
    if isinstance(provided, str):
        try:
            # if provided lacks offset, we’ll replace below
            start_dt = datetime.fromisoformat(provided.replace("Z", "+00:00"))
        except Exception:
            start_dt = None

    # 2) parse from the last user text if needed
    if start_dt is None and last_user_intent:
        start_dt = parse_when(last_user_intent, tz)

    # fallback: tomorrow 10:00
    tzinfo = get_zoneinfo(TIMEZONE)
    if start_dt is None:
        start_dt = (datetime.now(tzinfo) + timedelta(days=1)).replace(hour=10, minute=0, second=0, microsecond=0)

    # ensure tz-aware
    if start_dt.tzinfo is None:
        start_dt = start_dt.replace(tzinfo=tzinfo)

    # default duration
    duration_min = int(args.get("duration_minutes") or DEFAULT_DURATION_MIN)
    end_dt = start_dt + timedelta(minutes=duration_min)

    # build ISO strings with timezone
    args["summary"] = summary
    args["start_iso"] = start_dt.isoformat()
    args["end_iso"] = end_dt.isoformat()

    # clean optional fields
    for k in ("title", "duration_minutes"):
        if k in args:
            args.pop(k, None)

    return args

def call_tool(name: str, args: Dict[str, Any], verified: bool = False) -> Dict[str, Any]:
    """Unified /call for both servers. Adds X-Verified for calendar once verified."""
    base = EMAIL_BASE if name.startswith("email.") else CAL_BASE
    payload = {
        "name": name if name.startswith("email.") else name.split(".", 1)[1],
        "arguments": args or {}
    }
    headers = {}
    if name.startswith("calendar.") and verified:
        headers["X-Verified"] = "true"

    r = requests.post(f"{base}/call", json=payload, headers=headers, timeout=30)
    print(f"→ Calling {name} @ {base} | Payload: {payload} | Status: {r.status_code}")
    if r.status_code >= 400:
        print("← Error:", r.text)
    r.raise_for_status()
    data = r.json()
    print("← Response:", data)
    return data.get("result", data)

# ===== Session (FSM + conversation) =====
SESSION = {
    "state": "idle",         # idle | collecting_email | otp_sent | verified
    "email": None,
    "verified": False,
    "history": []
}

SYSTEM_PROMPT = (
    "You are a friendly booking assistant.\n"
    "Conversation rules:\n"
    "• Start by asking what the user needs help with if they haven't asked anything yet.\n"
    "• Before any calendar.* booking, you MUST verify the user's email via OTP.\n"
    "• If the user provides an email, call email.send_email_otp with {email}.\n"
    "• Only ask for the OTP code AFTER you've sent one (i.e., after email.send_email_otp).\n"
    "• When the user provides a code, call email.verify_email_otp with {email, code}.\n"
    "• After verification: if booking details are incomplete (missing title or duration), ASK concise follow-up questions to collect them.\n"
    "• If the user agrees to defaults, use title='Appointment' and duration=60 minutes.\n"
    "• Once details are sufficient, call calendar.* tools to book.\n"
    "• Keep responses short and specific.\n"
)

def run_turn(user_text: str) -> str:
    # Detect email in user message
    maybe_email = extract_email(user_text)
    if maybe_email:
        SESSION["email"] = maybe_email
        if SESSION["state"] == "idle":
            SESSION["state"] = "collecting_email"

    if not SESSION["history"]:
        SESSION["history"].append({"role": "system", "content": SYSTEM_PROMPT})
    SESSION["history"].append({"role": "user", "content": user_text})

    resp = client.chat.completions.create(
        model=AZURE_OPENAI_DEPLOYMENT,
        messages=SESSION["history"],
        tools=ALL_TOOLS,
        tool_choice="auto",
        temperature=0.2,
    )
    msg = resp.choices[0].message
    tool_calls = msg.tool_calls or []

    if tool_calls:
        tool_messages = []

        for tc in tool_calls:
            name = tc.function.name
            args = json.loads(tc.function.arguments or "{}")

            # --- FSM guards ---
            if name == "email.verify_email_otp" and SESSION["state"] != "otp_sent":
                assistant_text = "I need to send you a verification code first. What is your email address?"
                SESSION["history"].append({"role": "assistant", "content": assistant_text})
                return assistant_text

            if name == "email.send_email_otp" and not args.get("email"):
                if SESSION["email"]:
                    args["email"] = SESSION["email"]
                else:
                    assistant_text = "What email address should I send the verification code to?"
                    SESSION["history"].append({"role": "assistant", "content": assistant_text})
                    return assistant_text

            if name.startswith("calendar.") and not SESSION["verified"]:
                assistant_text = "Please verify your email first. What is your email address?"
                SESSION["history"].append({"role": "assistant", "content": assistant_text})
                return assistant_text

            # --- Execute tool ---
            if name.startswith("calendar."):
    # Find last user intent text
                last_intent = None
                for msg_prev in reversed(SESSION["history"]):
                    if msg_prev["role"] == "user":
                        last_intent = msg_prev["content"] or ""
                        break
                desired_dt = parse_when(last_intent, TZINFO)

                # If user asked to "check availability" / "is the slot free" → prefer find_free_slot
                wants_availability = any(w in (last_intent or "").lower()
                                        for w in ("free", "availability", "available", "find slot", "check slot"))

                if name == "calendar.find_free_slot" or wants_availability:
                    # Force correct tool and arguments
                    name = "calendar.find_free_slot"
                    duration = int(args.get("duration_minutes") or DEFAULT_DURATION_MIN)
                    if not desired_dt:
                        desired_dt = (datetime.now(TZINFO) + timedelta(days=1)).replace(hour=10, minute=0, second=0, microsecond=0)
                    window_start_iso, window_end_iso = make_window_for(desired_dt, duration, span_minutes=240)
                    args = {
                        "duration_minutes": duration,
                        "window_start_iso": window_start_iso,
                        "window_end_iso": window_end_iso,
                        "pad_minutes": int(args.get("pad_minutes") or 0),
                    }
                    result = call_tool(name, args, verified=SESSION["verified"])

                    # If a slot is found, ask to confirm booking (or auto-book if you prefer)
                    slot = result if isinstance(result, dict) else {}
                    if slot.get("start") and slot.get("end"):
                        # Cache proposed times into session for next step
                        SESSION["proposed_start_iso"] = slot["start"]
                        SESSION["proposed_end_iso"] = slot["end"]
                        confirm_text = (f"I found a free slot from "
                                        f"{slot['start']} to {slot['end']}. "
                                        f"Do you want me to book it?")
                        SESSION["history"].append({"role":"assistant","content":confirm_text})
                        return confirm_text
                    else:
                        no_text = "I couldn't find a free slot in that window. Would you like me to search a wider time range?"
                        SESSION["history"].append({"role":"assistant","content":no_text})
                        return no_text

                # Otherwise, proceed with create_calendar_event using either proposed slot or parsed time
                if name == "calendar.create_calendar_event":
                    # If we have a proposed slot from availability check, use it
                    if SESSION.get("proposed_start_iso") and SESSION.get("proposed_end_iso"):
                        args["start_iso"] = SESSION.pop("proposed_start_iso")
                        args["end_iso"]   = SESSION.pop("proposed_end_iso")
                    else:
                        # Build start/end if missing
                        if desired_dt is None:
                            desired_dt = (datetime.now(TZINFO) + timedelta(days=1)).replace(hour=10, minute=0, second=0, microsecond=0)
                        duration = int(args.get("duration_minutes") or DEFAULT_DURATION_MIN)
                        args["start_iso"] = desired_dt.isoformat()
                        args["end_iso"] = (desired_dt + timedelta(minutes=duration)).isoformat()
                    args.setdefault("summary", args.get("title") or "Appointment")
                    args.pop("title", None)

            result = call_tool(name, args, verified=SESSION["verified"])

            # --- Update FSM ---
            if name == "email.send_email_otp":
                SESSION["state"] = "otp_sent"
                SESSION["email"] = args.get("email", SESSION["email"])
            elif name == "email.verify_email_otp":
                ok = bool(result.get("ok") and result.get("verified"))
                SESSION["verified"] = ok
                SESSION["state"] = "verified" if ok else "otp_sent"

                if ok:
                    # ✅ Auto-resume last user intent
                    last_user_intent = None
                    for msg_prev in reversed(SESSION["history"]):
                        if msg_prev["role"] == "user":
                            last_user_intent = msg_prev["content"]
                            break
                    if last_user_intent:
                        followup = (
                            f"The user's email is verified. "
                            f"Please continue with their last request: '{last_user_intent}'."
                        )
                        SESSION["history"].append({"role": "system", "content": followup})
                        SESSION["history"].append({
                                "role": "system",
                                "content": (
                                    "If the request lacks title or duration, ask for them now. "
                                    "Offer defaults (title='Appointment', duration=60 minutes) if user prefers."
                                ),
                            })
                        print("✅ Email verified — resuming previous intent.")

            tool_messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "name": name,
                "content": json.dumps(result),
            })

        SESSION["history"].append({
            "role": "assistant",
            "content": msg.content or "",
            "tool_calls": [tc.model_dump() for tc in tool_calls],
        })
        SESSION["history"].extend(tool_messages)

        # Second completion after tool execution
        resp2 = client.chat.completions.create(
            model=AZURE_OPENAI_DEPLOYMENT,
            messages=SESSION["history"],
            tools=ALL_TOOLS,
            tool_choice="auto",
            temperature=0.2,
        )
        final = resp2.choices[0].message.content or "(no response)"
        SESSION["history"].append({"role": "assistant", "content": final})
        return final

    assistant_text = msg.content or "(no response)"
    SESSION["history"].append({"role": "assistant", "content": assistant_text})
    return assistant_text


# ===== Interactive loop =====
if __name__ == "__main__":
    print("🤖 Agent: Hello! What can I do for you today?")
    print("Type 'exit' to quit.\n")

    while True:
        user_input = input("You: ").strip()
        if not user_input:
            continue
        if user_input.lower() in {"exit", "quit"}:
            print("🤖 Agent: Goodbye!")
            break
        try:
            reply = run_turn(user_input)
            print(f"🤖 Agent: {reply}")
        except Exception as e:
            print(f"❌ Error: {e}")