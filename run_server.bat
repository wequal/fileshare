@echo off
cd /d "%~dp0"
if not exist config.yaml (
  copy config.example.yaml config.yaml
  echo Created config.yaml from example. Edit bootstrap_admin_password before use.
)
python -m venv venv 2>nul
call venv\Scripts\activate.bat
pip install -r requirements.txt -q
REM Runs server.main:main(), which reads host/port from config.yaml and
REM enables HTTPS (auto-generating a self-signed cert) when use_https is set.
python -m server
