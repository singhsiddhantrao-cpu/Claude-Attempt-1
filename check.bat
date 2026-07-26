@echo off
setlocal
cd /d "%~dp0"

echo ============================================================
echo    Tracing diagnostic  -  theagentos.space
echo ============================================================
echo.
echo This checks why traces are not showing up on the dashboard.
echo It does NOT call any AI model, so it costs nothing.
echo.

REM Use the same virtualenv run.bat creates (outside the project folder).
set "VENV=%LOCALAPPDATA%\msa-venv"
if not defined LOCALAPPDATA set "VENV=%SystemDrive%\msa-venv"

REM Fall back to an older project-local .venv if that is what exists.
if not exist "%VENV%\Scripts\activate.bat" (
    if exist ".venv\Scripts\activate.bat" (
        set "VENV=%CD%\.venv"
    ) else (
        echo [ERROR] No virtual environment found.
        echo         Run run.bat first to set the project up, then try again.
        echo.
        pause
        exit /b 1
    )
)

call "%VENV%\Scripts\activate.bat"

if not exist "check_tracing.py" (
    echo [ERROR] check_tracing.py is missing from this folder.
    echo         Download the latest project files and copy it here.
    echo.
    pause
    exit /b 1
)

python check_tracing.py

echo.
echo ============================================================
echo  Copy everything above and send it over for help reading it.
echo ============================================================
echo.
pause
