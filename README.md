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
- **Optional**: `logo.png` file in root folder (for custom icon)

### Build Steps (Local)
1. **(Optional)** Place `logo.png` in project root
2. Run `build_exe.bat`
3. Script will automatically convert logo.png → icon.ico
4. Find the executable in `dist/SoftwareChecker.exe`
5. Distribute the exe file

### Build with GitHub Actions (Automated)
1. Push to `main` branch or create a tag (e.g., `v3.0`)
2. GitHub Actions automatically builds EXE for Windows
3. Download artifact from Actions tab or Release page
4. Tag releases (e.g., `v3.0`) create automatic GitHub Releases with ZIP

### Manual build with spec file
```bash
# With icon (if logo.png exists)
python convert_logo_to_icon.py
pyinstaller SoftwareChecker.spec

# Without icon
pyinstaller SoftwareChecker.spec
```

## Features
- **Manual Check**: Verify software on finished parts (DMC-based search in Reports folder)
- **PDI Check**: Pre-installation validation from Excel file (M5-M17 cells vs Settings XML)
- **Database Viewer**: Browse complete history of all checks with date filtering
- **Analysis**: Statistical charts (OK vs NOK pie chart, NOK breakdown bar chart)
- **Email Notifications**: Automatic Outlook emails for NOK results (Manual + PDI)
- **Desktop Notifications**: Windows Toast alerts for NOK detection
- **Multi-language**: Polish, English, German, Romanian UI
- **Portable**: Works on any Windows PC without installation

## Recent Changes (v3.0)
- ✅ **Removed**: Watchdog automatic monitoring
- ✅ **Added**: PDI Check feature for Excel validation (M5, M8, M9, M14, M15, M16, M17 cells)
- ✅ **Added**: Manual Check and PDI Check save to Database (CSV History)
- ✅ **Added**: Email notifications for NOK in both Manual Check and PDI Check
- ✅ **Updated**: Status indicator based on 3 paths (Settings, Reports, Excel)
- ✅ **Updated**: Settings UI - 3 folders: Settings, Reports, Excel
- ✅ **Updated**: All translations for 4 languages (PL, EN, DE, RO)

## Configuration
In Settings (⚙️ button):
1. **Settings Folder** - XML files with reference software versions
2. **Reports Folder** - DMC-based folders with XML reports (for Manual Check)
3. **Excel File Path** - .xlsm file with PDI data (for PDI Check)
4. **Email Recipients** - Outlook addresses for NOK notifications
5. **CSV Path** - Location for results.csv database

## Usage
### Manual Check (Left Panel)
1. Enter or scan DMC code
2. Click "CHECK SOFTWARE"
3. App searches Reports folder for DMC → finds newest folder → validates XML
4. Results shown + saved to Database
5. If NOK → Email sent automatically

### PDI Check (Tab)
1. Click "PDI Check" tab
2. Click "RUN PDI CHECK"
3. App reads Excel cells M5-M17 → compares with Settings XML
4. Results table shows HEX/DEC comparisons
5. If NOK → Email sent automatically

### Database (Tab)
- View all Manual + PDI checks history
- Filter by date
- Export to CSV

### Analysis (Tab)
- OK vs NOK pie chart
- NOK breakdown by component (HWEL, BTLD, SWFL)

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
