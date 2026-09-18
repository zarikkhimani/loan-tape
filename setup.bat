@echo off
setlocal
if "%~1"=="" (
    if exist "%~dp0.tools\Scripts\python.exe" (
        "%~dp0.tools\Scripts\python.exe" "%~dp0scripts\setup.py"
    ) else (
        py -3.12 "%~dp0scripts\setup.py"
    )
) else (
    "%~1" "%~dp0scripts\setup.py"
)
if errorlevel 1 (
    echo Setup failed. Use setup.bat "C:\path\to\Python312\python.exe" with an existing Python 3.12 installation.
    exit /b 1
)
