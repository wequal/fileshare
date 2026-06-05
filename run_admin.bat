@echo off
cd /d "%~dp0"
if not exist config.yaml (
  copy config.example.yaml config.yaml
  echo Created config.yaml from example.
)
python -m venv venv 2>nul
call venv\Scripts\activate.bat
pip install -r requirements.txt -q
pip install -r admin_app\requirements-admin.txt -q
python -m admin_app
