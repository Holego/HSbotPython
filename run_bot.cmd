@echo off
setlocal
cd /d "%~dp0"

set "BOT_PYTHON=.venv\Scripts\python.exe"

if not exist "%BOT_PYTHON%" (
    py -3.13 -m venv .venv
    if errorlevel 1 goto setup_error
)

"%BOT_PYTHON%" -c "import pyautogui, psutil, cv2" >nul 2>&1
if errorlevel 1 (
    "%BOT_PYTHON%" -m pip install --upgrade pip
    "%BOT_PYTHON%" -m pip install -r requirements.txt
    if errorlevel 1 goto setup_error
)

"%BOT_PYTHON%" SimpleBot.py
if errorlevel 1 pause
exit /b

:setup_error
echo.
echo Could not prepare Python 3.13. Install Python 3.13 x64 and try again.
pause
exit /b 1
