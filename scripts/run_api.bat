@echo off
REM Activate venv and run Uvicorn for FastAPI app
SETLOCAL
IF EXIST .venv\Scripts\activate.bat (
  call .venv\Scripts\activate.bat
) ELSE (
  REM fallback: use python executable directly
  echo "venv activate script not found; using .venv python"
)
.
%~dp0.venv\Scripts\python.exe -m uvicorn src.app.api:app --host 127.0.0.1 --port 8088
ENDLOCAL
  