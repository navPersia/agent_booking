Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.venv\Scripts\activate
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
python -m venv .venv 
pip install --upgrade pip
python calendar_api_server.py