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

REM --- 2. Create the virtual environment ------------------------------------
REM The venv lives OUTSIDE the project folder, at a deliberately short path
REM (%LOCALAPPDATA%\msa-venv). Some packages ship very long file names, and a
REM venv inside a deeply-nested folder (e.g. an unzipped download sitting in
REM Downloads) pushes them past Windows' 260-character path limit, which makes
REM pip fail with "No such file or directory". Keeping the venv short means the
REM project itself can be extracted and run from anywhere.
set "VENV=%LOCALAPPDATA%\msa-venv"
if not defined LOCALAPPDATA set "VENV=%SystemDrive%\msa-venv"

if not exist "%VENV%\Scripts\activate.bat" (
    echo Creating virtual environment at:
    echo   %VENV%
    %PY% -m venv "%VENV%"
    if errorlevel 1 (
        echo [ERROR] Could not create the virtual environment.
        pause
        exit /b 1
    )
    echo.
)

REM A .venv from an older version of this script may still sit in the project
REM folder. It is no longer used and can be deleted to reclaim disk space.
if exist ".venv\Scripts\activate.bat" (
    echo [note] An old .venv folder exists inside this project and is no longer
    echo        used. You can safely delete it to free up disk space.
    echo.
)

REM --- 3. Activate it -------------------------------------------------------
call "%VENV%\Scripts\activate.bat"

REM --- 4. Install dependencies (first run, or after requirements change) ---
if not exist "%VENV%\.deps-installed" (
    echo Installing dependencies. The first time this can take a few minutes...
    python -m pip install --upgrade pip
    python -m pip install -r requirements.txt
    if errorlevel 1 (
        echo [ERROR] Dependency installation failed - see the messages above.
        pause
        exit /b 1
    )
    echo installed > "%VENV%\.deps-installed"
    echo.
)

REM Ensure the provider client libraries are present (needed for the free
REM providers). Covers setups whose deps were installed before these were added.
python -c "import openai" 2>nul
if errorlevel 1 (
    echo Installing the openai client for NVIDIA support...
    python -m pip install openai
    echo.
)
python -c "import google.genai" 2>nul
if errorlevel 1 (
    echo Installing the google-genai client for Google Gemini support...
    python -m pip install google-genai
    echo.
)
python -c "import groq" 2>nul
if errorlevel 1 (
    echo Installing the groq client for Groq support...
    python -m pip install groq
    echo.
)

REM --- 5. Make sure .env exists and has a provider key --------------------
REM Accept EITHER an Anthropic key or an NVIDIA key. If .env already has one of
REM them we leave the file untouched (so a hand-edited NVIDIA_API_KEY survives).
if not exist ".env" copy ".env.example" ".env" >nul

set "HASKEY="
for /f "usebackq tokens=1,* delims==" %%A in (".env") do (
    if /i "%%A"=="ANTHROPIC_API_KEY" if not "%%B"=="" set "HASKEY=1"
    if /i "%%A"=="NVIDIA_API_KEY" if not "%%B"=="" set "HASKEY=1"
    if /i "%%A"=="GOOGLE_API_KEY" if not "%%B"=="" set "HASKEY=1"
    if /i "%%A"=="GROQ_API_KEY" if not "%%B"=="" set "HASKEY=1"
)

if not defined HASKEY (
    echo.
    echo ------------------------------------------------------------
    echo  A model provider key is needed. Free options:
    echo    1^) Groq          ^(free^) - https://console.groq.com     ^(gsk_...^)  RECOMMENDED
    echo    2^) Google Gemini ^(free^) - https://aistudio.google.com  ^(AIza...^)
    echo    3^) NVIDIA        ^(free^) - https://build.nvidia.com     ^(nvapi-...^)
    echo    4^) Anthropic            - https://console.anthropic.com ^(sk-ant-..., needs credit^)
    echo  For a FREE option, press Enter here, then put your key on the matching
    echo  line ^(GROQ_API_KEY=, GOOGLE_API_KEY=, or NVIDIA_API_KEY=^) in .env and re-run.
    echo ------------------------------------------------------------
    set /p "APIKEY=Paste an Anthropic (sk-ant-) key, or press Enter to skip: "
    if "!APIKEY!"=="" (
        echo No key entered. Edit .env, set ANTHROPIC_API_KEY= or NVIDIA_API_KEY=, then re-run.
        pause
        exit /b 1
    )
    > ".env" echo ANTHROPIC_API_KEY=!APIKEY!
    >> ".env" echo NVIDIA_API_KEY=
    >> ".env" echo AGENTOS_API_KEY=
    >> ".env" echo AGENTOS_AGENT_ID=
    echo Key saved. Continuing...
    echo.
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
echo  Check out the demo at  http://localhost:7779
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
