# Software Checker - Portable Application

## For Users (Running the Application)

### Option 1: Standalone EXE (Recommended)
1. Download `SoftwareChecker.exe`
2. Double-click to run
3. Configure paths in Settings
4. Done! The application will create necessary folders automatically

### Option 2: Run from Source
1. Ensure Python 3.11+ is installed
2. Run `start.bat`

## For Developers (Building the EXE)

### Prerequisites
- Python 3.11+
- All dependencies installed: `pip install -r requirements.txt`

### Build Steps
1. Run `build_exe.bat`
2. Find the executable in `dist/SoftwareChecker.exe`
3. Distribute the exe file

### Build with spec file (advanced)
```bash
pyinstaller SoftwareChecker.spec
```

## Features
- Automatic folder monitoring (Watchdog)
- Email notifications via Outlook
- Desktop notifications (Windows Toast)
- CSV logging
- Web-based UI
- Portable - works on any Windows PC

## Portable EXE Structure

Po zbudowaniu, dystrybuuj:
```
SoftwareChecker.exe      ← Główny plik
user_data/               ← Tworzone automatycznie przy pierwszym uruchomieniu
  ├── config.json
  ├── results.csv
  └── app_port.txt
```

Aplikacja jest w pełni portable - nie wymaga instalacji ani subfolderów `app/`.

## Configuration
All settings are saved in `user_data/json/config.json` next to the executable (for EXE mode) or in `app/user_data/json/config.json` (for script mode).
Each user has their own configuration.
