@echo off
echo ========================================
echo  Building Software Checker Standalone EXE
echo ========================================
echo.

:: Check if PyInstaller is installed
python -c "import PyInstaller" 2>nul
if errorlevel 1 (
    echo PyInstaller not found. Installing...
    pip install pyinstaller
)

:: Upewnij się, że folder user_data istnieje dla trybu skryptu
if not exist "app\user_data" mkdir "app\user_data"

echo.
echo Building with spec file...
pyinstaller --noconfirm --clean SoftwareChecker.spec

echo.
echo ========================================
echo  Build Complete!
echo ========================================
echo.
echo Executable location: dist\SoftwareChecker.exe
echo.
echo To distribute:
echo 1. Copy dist\SoftwareChecker.exe
echo 2. User runs the exe - it will create user_data/ folder automatically
echo 3. User configures paths in Settings (they will be saved locally)
echo 4. Application is fully portable - move the folder anywhere!
echo.
pause
