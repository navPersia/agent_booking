import os, json, datetime as dt
from typing import Any, Dict, List, Optional, Callable

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
import datetime as dt
import tzlocal  # 👈 add this at the top of your file with other imports

load_dotenv()

PORT = int(os.getenv("PORT", "8080"))
CALENDAR_ID = os.getenv("CALENDAR_ID", "primary")
SCOPES = ["https://www.googleapis.com/auth/calendar"]
CLIENT_FILE = "client_secret.json"
TOKEN_FILE = "token.json"

# ---------- Google helpers ----------
def _svc():
    if not os.path.exists(CLIENT_FILE):
        raise FileNotFoundError("client_secret.json not found (place it next to this file)")
    if not os.path.exists(TOKEN_FILE):
        raise FileNotFoundError("token.json not found; run auth_init.py first")
    with open(TOKEN_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    creds = Credentials.from_authorized_user_info(data, SCOPES)
    return build("calendar", "v3", credentials=creds, cache_discovery=False)

def _iso(s: str) -> dt.datetime:
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))

# ---------- Tool implementations ----------
def list_calendar_events(timeMin: str, timeMax: str, maxResults: int = 50):
    svc = _svc()
    res = svc.events().list(
        calendarId=CALENDAR_ID,
        timeMin=timeMin,
        timeMax=timeMax,
        singleEvents=True,
        orderBy="startTime",
        maxResults=maxResults
    ).execute()
    items = res.get("items", [])
    return [
        {
            "id": e.get("id"),
            "summary": e.get("summary"),
            "start": e.get("start", {}).get("dateTime") or e.get("start", {}).get("date"),
            "end": e.get("end", {}).get("dateTime") or e.get("end", {}).get("date"),
            "htmlLink": e.get("htmlLink"),
        } for e in items
    ]

def create_calendar_event(summary: str, start_iso: str, end_iso: str,
                          description: Optional[str] = None,
                          attendees: Optional[List[str]] = None,
                          location: Optional[str] = None):
    svc = _svc()

    local_tz = tzlocal.get_localzone_name()  # e.g., "Europe/Brussels"

    body: Dict[str, Any] = {
        "summary": summary,
        "start": {"dateTime": start_iso, "timeZone": local_tz},
        "end": {"dateTime": end_iso, "timeZone": local_tz},
    }
    if description:
        body["description"] = description
    if attendees:
        body["attendees"] = [{"email": a} for a in attendees]
    if location:
        body["location"] = location
    ev = svc.events().insert(calendarId=CALENDAR_ID, body=body).execute()
    return {"id": ev.get("id"), "htmlLink": ev.get("htmlLink")}

def delete_calendar_event(event_id: str):
    svc = _svc()
    svc.events().delete(calendarId=CALENDAR_ID, eventId=event_id).execute()
    return {"deleted": True, "id": event_id}

def find_free_slot(duration_minutes: int, window_start_iso: str, window_end_iso: str, pad_minutes: int = 0):
    svc = _svc()
    fb = svc.freebusy().query(
        body={"timeMin": window_start_iso, "timeMax": window_end_iso, "items": [{"id": CALENDAR_ID}]}
    ).execute()
    busy = fb["calendars"][CALENDAR_ID].get("busy", [])
    start = _iso(window_start_iso); end = _iso(window_end_iso)
    blocks, cursor = [], start
    for b in busy:
        bs, be = _iso(b["start"]), _iso(b["end"])
        if bs > cursor: blocks.append((cursor, bs))
        if be > cursor: cursor = be
    if cursor < end: blocks.append((cursor, end))
    need = dt.timedelta(minutes=duration_minutes + pad_minutes * 2)
    for fs, fe in blocks:
        if fe - fs >= need:
            s = fs + dt.timedelta(minutes=pad_minutes)
            e = s + dt.timedelta(minutes=duration_minutes)
            return {"start": s.isoformat(), "end": e.isoformat()}
    return {"start": None, "end": None}

# ---------- FastAPI HTTP layer ----------
app = FastAPI(title="Calendar Tools API")

class CallPayload(BaseModel):
    name: str
    arguments: dict

TOOL_DEFS = [
    {
        "name": "list_calendar_events",
        "description": "List events in a time range (ISO-8601 with timezone).",
        "input": {"timeMin": "str", "timeMax": "str", "maxResults": "int?"},
    },
    {
        "name": "create_calendar_event",
        "description": "Create a Google Calendar event.",
        "input": {"summary": "str", "start_iso": "str", "end_iso": "str", "description": "str?", "attendees": "list[str]?", "location": "str?"},
    },
    {
        "name": "delete_calendar_event",
        "description": "Delete an event by ID.",
        "input": {"event_id": "str"},
    },
    {
        "name": "find_free_slot",
        "description": "Find the first free slot of given duration within a window.",
        "input": {"duration_minutes": "int", "window_start_iso": "str", "window_end_iso": "str", "pad_minutes": "int?"},
    },
]

HANDLERS: Dict[str, Callable[..., Dict[str, Any]]] = {
    "list_calendar_events": list_calendar_events,
    "create_calendar_event": create_calendar_event,
    "delete_calendar_event": delete_calendar_event,
    "find_free_slot": find_free_slot,
}

@app.get("/health")
def health():
    return {"ok": True}

@app.get("/tools")
def tools():
    return {"tools": TOOL_DEFS}

@app.post("/call")
def call(payload: CallPayload):
    name = payload.name
    args = payload.arguments or {}
    fn = HANDLERS.get(name)
    if not fn:
        raise HTTPException(status_code=404, detail=f"Unknown tool: {name}")
    try:
        result = fn(**args)
        return {"ok": True, "result": result}
    except TypeError as e:
        raise HTTPException(status_code=400, detail=f"Bad arguments: {e}")
    except FileNotFoundError as e:
        # Most common cause of 500s earlier: missing client_secret.json or token.json
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=repr(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)