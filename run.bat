@echo off
setlocal
if not exist "%~dp0.venv\Scripts\python.exe" (
    echo Project environment is missing. Run setup.bat first.
    exit /b 1
)
"%~dp0.venv\Scripts\python.exe" -m loan_tape %*
exit /b %errorlevel%
