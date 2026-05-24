@echo off
cd /d "%~dp0"
if not exist config.yaml (
  copy config.example.yaml config.yaml
  echo Created config.yaml from example. Edit bootstrap_admin_password before use.
)
python -m venv venv 2>nul
call venv\Scripts\activate.bat
pip install -r requirements.txt -q
python -m uvicorn server.main:app --host 0.0.0.0 --port 8443
