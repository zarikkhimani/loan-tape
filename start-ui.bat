@echo off
setlocal
if not exist "%~dp0.venv\Scripts\pythonw.exe" (
    echo Project environment is missing. Run setup.bat first.
    pause
    exit /b 1
)
start "" /D "%~dp0" "%~dp0.venv\Scripts\pythonw.exe" -I "%~dp0scripts\launch_desktop.py" %*
