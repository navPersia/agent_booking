# auth_init.py
import os
import json
import sys
from google_auth_oauthlib.flow import InstalledAppFlow

# Full read/write access to your calendar.
SCOPES = ["https://www.googleapis.com/auth/calendar"]

CLIENT_FILE = "client_secret.json"
TOKEN_FILE = "token.json"

def main():
    # 1) Check client secret exists
    if not os.path.exists(CLIENT_FILE):
        print(f"❌ {CLIENT_FILE} not found. Put your Google OAuth client JSON here and name it '{CLIENT_FILE}'.")
        sys.exit(1)

    # 2) Launch the local OAuth flow (opens browser)
    #    If port 8000 is busy, change port below.
    flow = InstalledAppFlow.from_client_secrets_file(CLIENT_FILE, SCOPES)
    try:
        creds = flow.run_local_server(port=8000, prompt="consent")
    except OSError:
        # Fallback: try a different port
        creds = flow.run_local_server(port=8081, prompt="consent")

    # 3) Save token.json (contains refresh token for headless use)
    with open(TOKEN_FILE, "w", encoding="utf-8") as f:
        f.write(creds.to_json())

    print(f"✅ OAuth complete. Token saved to '{TOKEN_FILE}'.")
    print("You can now run:  python mcp_calendar_server.py")

if __name__ == "__main__":
    main()