import os, time, secrets, string, hashlib
import uvicorn

from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional

from dotenv import load_dotenv
from azure.communication.email import EmailClient

# MCP server
from fastmcp import FastMCP

# Optional HTTP facade for quick testing
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, EmailStr
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
load_dotenv()

PORT  = int(os.getenv("PORT", "8090"))
ACS   = os.getenv("ACS_CONNECTION_STRING")
FROM  = os.getenv("FROM_EMAIL")
TTL_S = int(os.getenv("OTP_TTL_SECONDS", "600"))
MAX_SENDS_PER_HOUR = int(os.getenv("MAX_SENDS_PER_HOUR", "5"))
MAX_ATTEMPTS       = int(os.getenv("MAX_ATTEMPTS", "5"))

def _now(): return datetime.now(timezone.utc)
def _hash(s: str) -> str: return hashlib.sha256(s.encode("utf-8")).hexdigest()
def _otp(n=6) -> str: return "".join(secrets.choice(string.digits) for _ in range(n))
def _key(email: str, suffix: str) -> str: return f"otp:{email.lower()}:{suffix}"

# -------- In-memory store (no Redis) --------
STORE: Dict[str, Any] = {}

def _get(k: str): return STORE.get(k)
def _set(k: str, v: Any): STORE[k] = v
def _del(k: str): STORE.pop(k, None)

def _incr_bucket(email: str) -> int:
    k = _key(email, "bucket")
    rec = _get(k)
    now = time.time()
    if not rec or now - rec["start"] > 3600:
        rec = {"count": 0, "start": now}
    rec["count"] += 1
    _set(k, rec)
    return rec["count"]

# -------- Core business logic (pure funcs) --------
def _send_email_otp_impl(email: str, locale: str = "en") -> dict:
    if not ACS or not FROM:
        raise RuntimeError("ACS or FROM_EMAIL not configured")
    # rate-limit per email
    if _incr_bucket(email) > MAX_SENDS_PER_HOUR:
        return {"ok": False, "reason": "too_many_requests"}

    code = _otp(6)
    meta = {
        "hash": _hash(code),
        "exp": (_now() + timedelta(seconds=TTL_S)).isoformat(),
        "attempts": 0,
    }
    _set(_key(email, "meta"), meta)

    client = EmailClient.from_connection_string(ACS)
    minutes = max(1, TTL_S // 60)
    subject = "Your verification code"
    body_text = f"Your verification code is: {code}\nThis code expires in {minutes} minutes."
    body_html = f"<p>Your verification code is: <b>{code}</b></p><p>It expires in {minutes} minutes.</p>"

    poller = client.begin_send({
        "senderAddress": FROM,
        "recipients": {"to": [{"address": email}]},
        "content": {"subject": subject, "plainText": body_text, "html": body_html},
    })
    res = poller.result()
    return {"ok": True, "messageId": getattr(res, "message_id", None), "ttlSeconds": TTL_S}

def _verify_email_otp_impl(email: str, code: str) -> dict:
    meta = _get(_key(email, "meta"))
    if not meta:
        return {"ok": False, "reason": "no_pending"}
    if _now() > datetime.fromisoformat(meta["exp"]):
        _del(_key(email, "meta"))
        return {"ok": False, "reason": "expired"}
    meta["attempts"] += 1
    if meta["attempts"] > MAX_ATTEMPTS:
        _set(_key(email, "meta"), meta)
        return {"ok": False, "reason": "too_many_attempts"}
    if _hash(code) != meta["hash"]:
        _set(_key(email, "meta"), meta)
        return {"ok": False, "reason": "incorrect_code"}
    _del(_key(email, "meta"))
    return {"ok": True, "verified": True}

# -------- MCP server (FastMCP) --------
app_mcp = FastMCP(name="email-otp-mcp", version="1.0.0")

# NOTE: Some FastMCP versions don't support 'schema='; use type hints only.
@app_mcp.tool(name="email.send_email_otp", description="Send a verification code to the user's email.")
def send_email_otp(email: str, locale: str = "en") -> dict:
    return _send_email_otp_impl(email, locale)

@app_mcp.tool(name="email.verify_email_otp", description="Verify the OTP code received by email.")
def verify_email_otp(email: str, code: str) -> dict:
    return _verify_email_otp_impl(email, code)

# -------- Optional HTTP facade for quick testing --------
api = FastAPI(title="Email OTP MCP Server (HTTP facade)")

TOOLS_HTTP = [
    {
        "name": "email.send_email_otp",
        "description": "Send a verification code to the user's email.",
        "input": {"email": "string", "locale": "string?"},
    },
    {
        "name": "email.verify_email_otp",
        "description": "Verify the OTP code received by email.",
        "input": {"email": "string", "code": "string"},
    },
]

class CallPayload(BaseModel):
    name: str
    arguments: dict

@api.get("/health")
def health(): return {"ok": True}

@api.get("/tools")
def tools(): return {"tools": TOOLS_HTTP}

@api.post("/call")
def call(payload: CallPayload):
    try:
        if payload.name == "email.send_email_otp":
            return {"ok": True, "result": _send_email_otp_impl(**(payload.arguments or {}))}
        elif payload.name == "email.verify_email_otp":
            return {"ok": True, "result": _verify_email_otp_impl(**(payload.arguments or {}))}
        raise HTTPException(status_code=404, detail=f"Unknown tool: {payload.name}")
    except HTTPException:
        raise
    except TypeError as e:
        raise HTTPException(status_code=400, detail=f"Bad args: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
# ----- Simple HTTP facade so you can curl /tools and /call -----

api = FastAPI(title="Email OTP MCP (facade)")

TOOLS_HTTP = [
    {
        "name": "email.send_email_otp",
        "description": "Send a verification code to the user's email.",
        "input": {"email": "string", "locale": "string?"},
    },
    {
        "name": "email.verify_email_otp",
        "description": "Verify the OTP code received by email.",
        "input": {"email": "string", "code": "string"},
    },
]

class CallPayload(BaseModel):
    name: str
    arguments: dict

@api.get("/health")
def health(): return {"ok": True}

@api.get("/tools")
def tools(): return {"tools": TOOLS_HTTP}

@api.post("/call")
def call(payload: CallPayload):
    try:
        if payload.name == "email.send_email_otp":
            return {"ok": True, "result": _send_email_otp_impl(**(payload.arguments or {}))}
        elif payload.name == "email.verify_email_otp":
            return {"ok": True, "result": _verify_email_otp_impl(**(payload.arguments or {}))}
        raise HTTPException(status_code=404, detail=f"Unknown tool: {payload.name}")
    except HTTPException:
        raise
    except TypeError as e:
        raise HTTPException(status_code=400, detail=f"Bad args: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
if __name__ == "__main__":

    # Try to get an ASGI app from FastMCP and mount it at /mcp
    asgi = None
    for attr in ("http_app", "asgi_app", "app", "asgi", "build_asgi_app"):
        if hasattr(app_mcp, attr):
            asgi = getattr(app_mcp, attr)
            if callable(asgi):  # build_asgi_app()
                asgi = asgi()
            break

    if asgi is not None:
        api.mount("/mcp", asgi)  # MCP endpoints (for MCP-native clients)

    uvicorn.run(api, host="0.0.0.0", port=PORT)