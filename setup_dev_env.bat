@echo off
echo ========================================
echo  Software Checker - Environment Setup
echo ========================================
echo.

:: 1. Sprawdzenie czy Python jest zainstalowany
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python is NOT installed or not in PATH.
    echo Please install Python 3.10+ from python.org and check "Add Python to PATH".
    echo.
    pause
    exit /b
)

echo [OK] Python found:
python --version
echo.

:: 2. Aktualizacja pip
echo [STEP 1/3] Updating pip...
python -m pip install --upgrade pip

:: 3. Instalacja bibliotek z requirements.txt (jesli istnieje)
if exist requirements.txt (
    echo.
    echo [STEP 2/3] Installing dependencies from requirements.txt...
    python -m pip install -r requirements.txt
) else (
    echo [INFO] requirements.txt not found. Skipping specific requirements.
)

:: 4. Instalacja dodatkowych przydatnych bibliotek
echo.
echo [STEP 3/3] Installing common development libraries...
echo Installing: pyinstaller (for EXE building)...
python -m pip install pyinstaller
echo Installing: black (code formatter)...
python -m pip install black
echo Installing: flake8 (linter)...
python -m pip install flake8
echo Installing: pytest (testing)...
python -m pip install pytest
echo Installing: requests (HTTP client)...
python -m pip install requests
echo Installing: pandas (data analysis)...
python -m pip install pandas
echo Installing: openpyxl (Excel support for pandas)...
python -m pip install openpyxl
echo Installing: python-dotenv (environment variables)...
python -m pip install python-dotenv

echo.
echo ========================================
echo  Setup Complete!
echo ========================================
echo.
pause

