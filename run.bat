@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ============================================================
echo    Multi-Agent Stock Analysis  -  one-click launcher
echo ============================================================
echo.

REM --- 1. Find Python -------------------------------------------------------
set "PY="
where python >nul 2>nul && set "PY=python"
if not defined PY (
    where py >nul 2>nul && set "PY=py"
)
if not defined PY (
    echo [ERROR] Python was not found.
    echo.
    echo   Install Python 3.11+ from https://www.python.org/downloads/
    echo   During install, TICK the box "Add Python to PATH", then run this again.
    echo.
    pause
    exit /b 1
)
echo Using Python: %PY%
echo.

REM --- 2. Create the virtual environment (first run only) ------------------
if not exist ".venv\Scripts\activate.bat" (
    echo Creating virtual environment ^(.venv^) ...
    %PY% -m venv .venv
    if errorlevel 1 (
        echo [ERROR] Could not create the virtual environment.
        pause
        exit /b 1
    )
)

REM --- 3. Activate it -------------------------------------------------------
call ".venv\Scripts\activate.bat"

REM --- 4. Install dependencies (first run, or after requirements change) ---
if not exist ".venv\.deps-installed" (
    echo Installing dependencies. The first time this can take a few minutes...
    python -m pip install --upgrade pip
    python -m pip install -r requirements.txt
    if errorlevel 1 (
        echo [ERROR] Dependency installation failed - see the messages above.
        pause
        exit /b 1
    )
    echo installed > ".venv\.deps-installed"
    echo.
)

REM --- 5. Make sure .env exists and has an API key ------------------------
if not exist ".env" (
    copy ".env.example" ".env" >nul
    echo.
    echo A new .env file was created for your Anthropic API key.
    echo Notepad will open - paste your key after  ANTHROPIC_API_KEY=  then Save and close.
    echo   ^(Get a key at https://console.anthropic.com  ->  Settings  ->  API Keys^)
    echo.
    pause
    notepad ".env"
)

findstr /r /c:"ANTHROPIC_API_KEY=sk-" ".env" >nul 2>nul
if errorlevel 1 (
    echo.
    echo [WARNING] No Anthropic API key detected in .env.
    echo Opening it - paste your key after  ANTHROPIC_API_KEY=  then Save and close.
    pause
    notepad ".env"
    findstr /r /c:"ANTHROPIC_API_KEY=sk-" ".env" >nul 2>nul
    if errorlevel 1 (
        echo [ERROR] Still no key found. Edit .env, then run this script again.
        pause
        exit /b 1
    )
)

REM --- 6. Warn if the frontend build is missing ---------------------------
if not exist "frontend\dist\index.html" (
    echo [WARNING] frontend\dist not found - the web page may not load.
    echo   If you have Node installed:  cd frontend  ^&^&  npm install  ^&^&  npm run build
    echo.
)

REM --- 7. Start the server and open the browser --------------------------
echo.
echo ------------------------------------------------------------
echo  Starting server at  http://localhost:7779
echo  Your browser will open in a few seconds.
echo.
echo  KEEP THIS WINDOW OPEN while you use the app.
echo  Press Ctrl+C here (or close the window) to stop the server.
echo ------------------------------------------------------------
echo.

start "" cmd /c "timeout /t 5 >nul & start http://localhost:7779"

python -m uvicorn stock_service:app --port 7779

echo.
echo Server stopped.
pause
