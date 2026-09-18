@echo off
setlocal
if not exist "%~dp0.venv\Scripts\python.exe" (
    echo Project environment is missing. Run setup.bat first.
    pause
    exit /b 1
)
"%~dp0.venv\Scripts\python.exe" "%~dp0scripts\create_launcher.py"
if errorlevel 1 (
    pause
    exit /b 1
)
