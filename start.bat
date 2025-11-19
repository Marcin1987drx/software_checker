@echo off
setlocal EnableDelayedExpansion

:: Detect script directory
SET "APP_DIR=%~dp0"
SET "PORT_FILE=%APP_DIR%app\user_data\app_port.txt"
SET "FALLBACK_PORT=5001"
SET "TIMEOUT_SECONDS=5"

:: Try to find Python (venv first, then system)
if exist "%APP_DIR%venv\Scripts\pythonw.exe" (
    SET "PYTHON_EXE=%APP_DIR%venv\Scripts\pythonw.exe"
    echo Found Python in venv
) else (
    where pythonw.exe >nul 2>&1
    if !errorlevel! equ 0 (
        SET "PYTHON_EXE=pythonw.exe"
        echo Using system Python
    ) else (
        echo ERROR: Python not found! Install Python or use SoftwareChecker.exe
        pause
        exit /b 1
    )
)

echo === Step 1: Killing any old servers... ===
taskkill /F /IM python.exe /T > nul 2>&1
taskkill /F /IM pythonw.exe /T > nul 2>&1

echo === Step 2: Starting the server... ===
start "SoftwareCheckerServer_v2" /B "!PYTHON_EXE!" "%APP_DIR%app\server.py"

echo === Step 3: Waiting %TIMEOUT_SECONDS% seconds for server initialization... ===
timeout /t %TIMEOUT_SECONDS% /nobreak > nul

SET "PORT_TO_USE=%FALLBACK_PORT%"
if exist "%PORT_FILE%" (
    for /f %%i in ('type "%PORT_FILE%"') do (
        SET "PORT_TO_USE=%%i"
    )
    echo -> Server is running on dynamically assigned port: !PORT_TO_USE!
) else (
    echo -> WARNING: Port file not found after %TIMEOUT_SECONDS%s. Using fallback port: %FALLBACK_PORT%
)

echo === Step 4: Opening the application in your browser! ===
start http://127.0.0.1:!PORT_TO_USE!

echo.
echo Done. The server is running in the background. Check browser tab.
endlocal
