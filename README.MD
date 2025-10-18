look# 🧠 Open Booking Agent (MCP + AI + Calendar + Email OTP)

### “An AI-powered open booking system that verifies, checks availability, and books appointments automatically.”

---

## 🌍 Overview

This project explores a new approach to appointment scheduling — using **AI agents and the Model Context Protocol (MCP)** to create an **open, conversational booking system**.

Instead of clicking through forms or waiting for confirmations, users can simply say:

> “Book me an appointment tomorrow at 15:00.”

The agent will:
1. Verify the user’s email via OTP  
2. Check availability in Google Calendar  
3. Book the slot if it’s free  
4. Send back a confirmation link  

All automatically — using modular, connectable MCP services.

---

## ✨ Key Features

- **AI Conversational Interface**  
  Users interact naturally (“tomorrow 3pm”, “check if 10am is free”).

- **Email Verification (OTP)**  
  A secure verification flow using Azure Communication Services.

- **Google Calendar Integration**  
  Real-time free slot detection and event creation.

- **MCP (Model Context Protocol)**  
  Standard interface for connecting external tools and AI models.

- **State-Aware Agent (FSM)**  
  Keeps conversation context and logical flow intact.

- **Modular Microservices**  
  Each service (Agent, Calendar, Email) runs independently and can be extended.

---

## 🧩 Architecture

```text
User
  ↓
AI Agent (FastMCP Client)
  ├── email_otp_mcp_server  → send_email_otp / verify_email_otp
  └── calendar_mcp_server   → find_free_slot / create_calendar_event

  ⚙️ Tech Stack
Component	Technology
AI Orchestrator	Python 3.11 + FastMCP
Email Service	Azure Communication Services
Calendar Service	Google Calendar API
Timezone & Date Handling	tzlocal, tzdata
Agent State	In-memory FSM
Hosting	Azure Container Apps (optional)
🏗️ Installation
1️⃣ Clone the project
git clone https://github.com/<your-username>/open-booking-agent.git
cd open-booking-agent

2️⃣ Set up virtual environments

Each service can run separately:

python -m venv .venv
.venv\Scripts\activate   # Windows

3️⃣ Install dependencies
Agent
pip install -r agent/requirements.txt

Calendar Server
pip install -r calendar_mcp_server/requirements.txt

Email OTP Server
pip install -r email_otp_server/requirements.txt

🔑 Environment Variables
Agent
TIMEZONE=Europe/Brussels
DEFAULT_DURATION_MIN=60
CALENDAR_URL=http://localhost:8080
EMAIL_URL=http://localhost:8090

Calendar MCP Server
CALENDAR_ID=primary
GOOGLE_CLIENT_SECRET=client_secret.json
GOOGLE_TOKEN=token.json
PORT=8080
TIMEZONE=Europe/Brussels

Email OTP MCP Server
AZURE_COMM_CONNECTION_STRING=your_connection_string_here
PORT=8090

🚀 Run Locally

In separate terminals:

1️⃣ Start Calendar Server
cd calendar_mcp_server
python mcp_calendar_server.py

2️⃣ Start Email OTP Server
cd email_otp_server
python email-otp-mcp-server.py

3️⃣ Start Agent
cd agent
python agent_run.py


Then chat interactively:

🤖 Agent: Hello! What can I do for you today?
You: I want to book an appointment tomorrow at 15:00

📅 Example Flow
You: I want to book an appointment tomorrow at 15:00
Agent: Please provide your email for verification.
→ OTP sent via Azure Communication Services
You: 123456
Agent: Verified! I found a free slot from 15:00 to 16:00 tomorrow. Book it?
You: yes
Agent: Appointment confirmed ✅
Open in Google Calendar: https://calendar.google.com/...

🧠 Project Philosophy

This project is more than a demo — it’s a prototype for open, trustworthy AI systems that can:

Reason like humans

Communicate naturally

Act autonomously and safely

It combines AI reasoning, secure verification, and real-world action through modular microservices.

“The future of software won’t have buttons — it will have conversations.”

🧩 Next Steps

 Add multi-user and team calendars

 Add natural language duration parsing

 Integrate voice and SMS channels

 Package MCP servers as reusable Docker containers

🤝 Contributing

Pull requests are welcome!
If you’d like to extend this system (e.g., add a Teams, Outlook, or Notion connector), open a discussion first.

💬 Author

Navid Radkusha
 | StudioStreamX