import os
import sys
import logging
from pathlib import Path
import json
import re
import time
import csv
import threading
from datetime import datetime
from collections import defaultdict


# --- ZMIENNE GLOBALNE I WSTĘPNA KONFIGURACJA ---
# Detect if running as PyInstaller bundle or as script
if getattr(sys, 'frozen', False):
    # Running as compiled exe (PyInstaller) - PORTABLE MODE
    EXE_DIR = Path(sys.executable).parent
    BUNDLE_DIR = Path(sys._MEIPASS) if hasattr(sys, '_MEIPASS') else EXE_DIR
    USER_DATA_DIR = EXE_DIR / 'user_data'
    USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
else:
    # Running as Python script (start.bat)
    BUNDLE_DIR = Path(__file__).parent  # app/
    USER_DATA_DIR = BUNDLE_DIR / 'user_data'  # app/user_data

LOG_DIR = USER_DATA_DIR / 'logs'
LOG_DIR.mkdir(parents=True, exist_ok=True)

PORT_FILE = USER_DATA_DIR / 'app_port.txt'
MANUAL_SCAN_LOG_FILE = USER_DATA_DIR / 'manual_scans_log.json'
PDI_CHECK_LOG_FILE = USER_DATA_DIR / 'pdi_checks_log.json'


# --- EARLY LOGGING ---
logging.basicConfig(
    filename=LOG_DIR / 'app.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logging.info("========================================")
logging.info(f"=== PID: {os.getpid()} Starting Software Checker Server (v3.0.0 - PDI Check) ===")
logging.info("Step 1: Early logging initialized. Attempting library imports...")

# Check if we should use WebView (native app window) instead of browser
USE_WEBVIEW = True  # Set to False to use browser instead


try:
    from lxml import etree as ET
    from flask import Flask, request, jsonify, send_from_directory
    from flask_cors import CORS
    
    # IMPORT for tkinter (optional - for file dialogs)
    try:
        import tkinter as tk
        from tkinter import filedialog
        TKINTER_AVAILABLE = True
        logging.info("Import 'tkinter' successful.")
    except ImportError:
        TKINTER_AVAILABLE = False
        logging.warning("'tkinter' not available. File browse dialogs disabled.")
        tk = None
        filedialog = None

    # IMPORT for Excel reading
    try:
        import openpyxl
        logging.info("Import 'openpyxl' successful.")
    except ImportError:
        logging.error("!!! CRITICAL ERROR: 'openpyxl' library not found. Run 'pip install openpyxl'. !!!")
        openpyxl = None

    # IMPORT for E-mail (Outlook/pywin32)
    try:
        import win32com.client as win32
        import pywintypes
        logging.info("Import 'pywin32' (Outlook) successful.")
    except ImportError:
        logging.warning("'pywin32' library not found. Email functionality disabled.")
        win32 = None
        pywintypes = None

    # IMPORT for Windows Toasts
    try:
        from windows_toasts import WindowsToaster, Toast
        WINDOWS_TOASTS_ENABLED = True
        logging.info("Import 'windows-toasts' successful. Desktop notifications enabled.")
    except ImportError:
        WINDOWS_TOASTS_ENABLED = False
        logging.warning("'windows-toasts' library not found. Desktop notifications disabled.")

    # IMPORT for WebView (native app window)
    try:
        import webview
        WEBVIEW_AVAILABLE = True
        logging.info("Import 'webview' successful. Native window mode available.")
    except ImportError:
        WEBVIEW_AVAILABLE = False
        logging.warning("'webview' library not found. Will use browser mode.")
        webview = None

except ImportError as e:
    logging.critical(f"=== CRITICAL IMPORT FAILURE: {e} ===")
    logging.critical("Server cannot start. Missing key library.")
    sys.exit()


logging.info("Step 2: All key libraries imported successfully.")


# --- Configuration ---
STATIC_FILES_DIR = BUNDLE_DIR / 'files'
JSON_DIR = USER_DATA_DIR / 'json'
CONFIG_FILE = JSON_DIR / 'config.json'

SECURE_PARSER = ET.XMLParser(resolve_entities=False)

# Konfiguracja domyślna
DEFAULT_CONFIG = {
    "settingsFolder": "",
    "reportsFolder": "",
    "excelFilePath": "",
    "csvPath": str(USER_DATA_DIR),
    "language": "en",
    "theme": "light",
    "mailRecipients": [],
}

# --- Setup folders and locks ---
JSON_DIR.mkdir(parents=True, exist_ok=True)
csv_lock = threading.Lock()
outlook_lock = threading.Lock()
manual_scan_lock = threading.Lock()
pdi_check_lock = threading.Lock()


# --- Flask Application ---
app = Flask(__name__, static_folder=STATIC_FILES_DIR, static_url_path='')
CORS(app)
logging.info("Step 3: Flask application initialized.")


# === Toast Notification Helper ===
def send_toast(title, line1, line2=""):
    """Wysyła powiadomienie Windows Toast w osobnym wątku."""
    if not WINDOWS_TOASTS_ENABLED:
        return

    def toast_thread():
        try:
            toaster = WindowsToaster('Software Checker')
            new_toast = Toast()
            new_toast.text_fields = [title, line1, line2]
            toaster.show_toast(new_toast)
            logging.info(f"Sent toast notification: {title} - {line1}")
        except Exception as e:
            logging.warning(f"Failed to show toast notification: {e}", exc_info=True)

    threading.Thread(target=toast_thread, daemon=True).start()


# === Helper Functions ===
def canon_hex(s):
    if not s:
        return ""
    only = re.sub(r'[^0-9A-F]', '', str(s).upper())
    return ' '.join(a + b for a, b in zip(only[::2], only[1::2]))


def parse_id_to_hex(id_str):
    """Parse Settings ID format: PREFIX_0000XXXX_YYY.YYY.YYY -> returns HEX part"""
    if not id_str:
        return ""
    parts = id_str.split("_")
    if len(parts) < 3:
        return ""
    # Extract HEX part (last 4 chars)
    mid = re.sub(r'[^0-9A-Fa-f]', '', parts[1])[-4:]
    # Extract DEC part
    dec_bytes = [f"{int(d):02X}" for d in parts[2].split('.') if d.isdigit()]
    # Combine HEX + DEC
    return canon_hex(mid + "".join(dec_bytes))


def parse_id_components(id_str):
    """Parse Settings ID format: PREFIX_0000XXXX_YYY.YYY.YYY -> returns (hex_part, dec_part)"""
    if not id_str:
        return ("", "")
    parts = id_str.split("_")
    if len(parts) < 3:
        return ("", "")
    # HEX part - last 4 chars
    hex_full = parts[1]
    hex_part = hex_full[-4:] if len(hex_full) >= 4 else hex_full
    # DEC part
    dec_part = parts[2]
    return (hex_part.upper(), dec_part)


def extract_bytes_from_teststep(t):
    if not t:
        return ""
    match = re.search(r'([0-9A-F]{2}(?:\s*[0-9A-F]{2}){2,})', t, re.IGNORECASE)
    return canon_hex(match.group(1)) if match else ""


def extract_date_from_name(file_path):
    if not isinstance(file_path, Path):
        file_path = Path(file_path)
    match = re.search(r'_(\d{14})\.xml$', file_path.name)
    if match:
        try:
            dt = datetime.strptime(match.group(1), '%Y%m%d%H%M%S')
            return dt.strftime('%Y-%m-%d %H:%M:%S')
        except ValueError:
            return "N/A (Invalid Date)"
    return "N/A"


def is_timestamp_folder(folder_name):
    """Sprawdza, czy nazwa folderu zawiera sensowny wzorzec daty/czasu."""
    patterns = [
        r'^\d{4}-\d{2}-\d{2}[-_]\d{2}[-_]\d{2}[-_]\d{2}$',
        r'^\d{4}-\d{2}-\d{2}$',
        r'^\d{4}\d{2}\d{2}\d{6}$'
    ]
    if folder_name and folder_name[0].isdigit():
        for pattern in patterns:
            if re.match(pattern, folder_name):
                return True
    return False


# === CSV Logic ===
CSV_HEADER = [
    "timestamp", "dmc", "snr", "final",
    "hwel_report", "hwel_set",
    "btld_report", "btld_set",
    "swfl_report", "swfl_set",
    "report_file", "settings_file"
]


def log_to_csv(csv_path_str, data):
    if not csv_path_str:
        return
    try:
        csv_path = Path(csv_path_str)
        if csv_path.is_dir():
            csv_path = csv_path / "results.csv"
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        
        results = {r['Field']: r for r in data['results']}
        row = [
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            data.get('dmc', 'N/A'), data.get('snr', 'N/A'), data.get('finalResult', 'N/A'),
            results.get('HWEL', {}).get('Report', ''), results.get('HWEL', {}).get('Settings', ''),
            results.get('BTLD', {}).get('Report', ''), results.get('BTLD', {}).get('Settings', ''),
            results.get('SWFL', {}).get('Report', ''), results.get('SWFL', {}).get('Settings', ''),
            str(data.get('reportFile', 'N/A')), str(data.get('settingsFile', 'N/A'))
        ]
        
        with csv_lock:
            file_exists = csv_path.exists()
            with open(csv_path, 'a', newline='', encoding='utf-8-sig') as f:
                writer = csv.writer(f)
                if not file_exists:
                    writer.writerow(CSV_HEADER)
                writer.writerow(row)
    except Exception as e:
        logging.error(f"CSV write error: {e}")


# === Manual Scans Log ===
MAX_MANUAL_SCANS = 10


def log_manual_scan(data):
    """Zapisuje ostatni ręczny skan do dedykowanego pliku JSON."""
    try:
        data_to_log = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "dmc": data.get('dmc', 'N/A'),
            "snr": data.get('snr', 'N/A'),
            "finalResult": data.get('finalResult', 'ERROR'),
            "reportFile": data.get('reportFile', 'N/A'),
            "settingsFile": data.get('settingsFile', 'N/A'),
            "results": data.get('results', []),
            "errorMessage": data.get('errorMessage', '')
        }

        with manual_scan_lock:
            scans = _get_recent_manual_scans()
            scans.insert(0, data_to_log)
            scans = scans[:MAX_MANUAL_SCANS]

            with open(MANUAL_SCAN_LOG_FILE, 'w', encoding='utf-8') as f:
                json.dump(scans, f, indent=2)
    except Exception as e:
        logging.error(f"Manual scan log error: {e}")


def _get_recent_manual_scans():
    """Wczytuje listę ostatnich skanów z pliku JSON."""
    if not MANUAL_SCAN_LOG_FILE.exists():
        return []
    try:
        with open(MANUAL_SCAN_LOG_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logging.error(f"Error reading manual scans log: {e}")
        return []


# === PDI Check Log ===
MAX_PDI_CHECKS = 10


def log_pdi_check(data):
    """Zapisuje ostatni PDI check do dedykowanego pliku JSON."""
    try:
        data_to_log = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "snr": data.get('snr', 'N/A'),
            "finalResult": data.get('finalResult', 'ERROR'),
            "excelFile": data.get('excelFile', 'N/A'),
            "settingsFile": data.get('settingsFile', 'N/A'),
            "results": data.get('results', []),
            "errorMessage": data.get('errorMessage', '')
        }

        with pdi_check_lock:
            checks = _get_recent_pdi_checks()
            checks.insert(0, data_to_log)
            checks = checks[:MAX_PDI_CHECKS]

            with open(PDI_CHECK_LOG_FILE, 'w', encoding='utf-8') as f:
                json.dump(checks, f, indent=2)
    except Exception as e:
        logging.error(f"PDI check log error: {e}")


def _get_recent_pdi_checks():
    """Wczytuje listę ostatnich PDI checks z pliku JSON."""
    if not PDI_CHECK_LOG_FILE.exists():
        return []
    try:
        with open(PDI_CHECK_LOG_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logging.error(f"Error reading PDI checks log: {e}")
        return []


# === Outlook Email Logic ===
OUTLOOK_WAIT_SECONDS = 15
OUTLOOK_POLL_INTERVAL = 1


def get_outlook_app():
    global win32, pywintypes
    if win32 is None:
        return None

    with outlook_lock:
        try:
            return win32.GetActiveObject('outlook.application')
        except pywintypes.com_error:
            try:
                os.startfile("outlook")
                for i in range(OUTLOOK_WAIT_SECONDS):
                    time.sleep(OUTLOOK_POLL_INTERVAL)
                    try:
                        return win32.GetActiveObject('outlook.application')
                    except pywintypes.com_error:
                        continue
                logging.error(f"Outlook connection timeout ({OUTLOOK_WAIT_SECONDS}s)")
                return None
            except Exception as e:
                logging.error(f"Outlook start failed: {e}")
                return None
        except Exception as e:
            logging.error(f"Outlook error: {e}")
            return None


def send_nok_email(recipients, data):
    if not recipients:
        return
    try:
        outlook = get_outlook_app()
        if not outlook:
            return
        
        snr = data.get('snr', 'N/A')
        dmc = data.get('dmc', 'N/A')
        
        rows = []
        for r in data.get('results', []):
            style = "color: red; font-weight: bold;" if r['Result'] == 'NOK' else "color: green;"
            rows.append(f"<tr><td>{r['Field']}</td><td>{r.get('Report', 'N/A')}</td><td>{r.get('Settings', 'N/A')}</td><td style='{style}'>{r['Result']}</td></tr>")
        
        body = f"""
        <html><body>
        <p>A <strong>NOK</strong> result was detected.</p>
        <p><strong>SNR:</strong> {snr}<br><strong>DMC:</strong> {dmc}</p>
        <table border='1' cellpadding='5' cellspacing='0' style='border-collapse: collapse;'>
        <tr style='background-color: #f2f2f2;'><th>Field</th><th>Report</th><th>Settings</th><th>Result</th></tr>
        {''.join(rows)}
        </table>
        <p><strong>Report:</strong> {data.get('reportFile', 'N/A')}<br><strong>Settings:</strong> {data.get('settingsFile', 'N/A')}</p>
        </body></html>
        """
        
        mail = outlook.CreateItem(0)
        mail.To = "; ".join(recipients)
        mail.Subject = f"[SoftwareChecker] NOK - SNR {snr}"
        mail.HTMLBody = body
        mail.Send()
        logging.info(f"Email sent for SNR {snr}")
    except Exception as e:
        logging.error(f"Email send error: {e}")


# === Config Management ===
def load_config_from_file():
    config = DEFAULT_CONFIG.copy()
    if not CONFIG_FILE.exists():
        return config
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            saved_config = json.load(f)

        for key in config.keys():
            if key in saved_config:
                config[key] = saved_config[key]

    except Exception as e:
        logging.error(f"Critical error loading config.json: {e}")
        return DEFAULT_CONFIG
    return config


# === GŁÓWNA LOGIKA MANUAL CHECK (z raportami XML) ===
def process_core_logic(report_file_path, settings_folder_str, dmc_code):
    try:
        report_file = Path(report_file_path)
        settings_folder = Path(settings_folder_str)
        if not (report_file.exists() and settings_folder.is_dir()):
            return {"success": False, "error": "msgPathsNotSet", "dmc": dmc_code}

        tree = ET.parse(str(report_file), SECURE_PARSER)
        root = tree.getroot()
        snr_node = root.find(".//info[name='BMW PartNumber']/description")
        snr = snr_node.text if snr_node is not None else None
        if not snr:
            return {"success": False, "error": "msgSnrNotFound", "dmc": dmc_code, "reportFile": str(report_file)}

        all_text = " ".join(node.text for node in root.findall(".//teststep") if node.text)
        report_values = {}
        for prefix in ["HWEL", "BTLD", "SWFL"]:
            match = re.search(rf'.*({prefix}.*)', all_text, re.IGNORECASE)
            report_values[prefix] = extract_bytes_from_teststep(match.group(1) if match else None)

        logging.info(f"[Core] Searching for SNR: {snr} in {settings_folder}")
        start_time = time.time()
        settings_file, found_hardware_node = None, None
        all_xml_files = list(settings_folder.rglob("*.xml"))
        sorted_xml_files = sorted(all_xml_files, key=lambda p: p.stat().st_mtime, reverse=True)
        logging.info(f"[Core] Found {len(all_xml_files)} XML files, sorted by MODIFICATION DATE.")

        for xml_path in sorted_xml_files:
            try:
                tree_settings = ET.parse(str(xml_path), SECURE_PARSER)
                hardware_node_match = tree_settings.find(f".//hardware[@snr='{snr}']")
                if hardware_node_match is not None:
                    settings_file, found_hardware_node = xml_path, hardware_node_match
                    logging.info(f"[Core] MATCH FOUND! File: {xml_path}")
                    break
            except Exception:
                pass

        logging.info(f"[Core] Settings search took: {time.time() - start_time:.4f} s.")

        if not settings_file or found_hardware_node is None:
            logging.warning(f"[Core] No settings found for SNR: {snr}")
            return {"success": False, "error": "msgSettingsNotFound", "snr": snr, "dmc": dmc_code,
                    "reportFile": str(report_file)}

        settings_values = {}
        settings_original_ids = {}
        for prefix in ["HWEL", "BTLD", "SWFL"]:
            te_nodes = found_hardware_node.xpath(f".//te[starts-with(@id, '{prefix}')]")
            te_node = te_nodes[0] if te_nodes else None
            if te_node is not None:
                original_id = te_node.get('id')
                settings_values[prefix] = parse_id_to_hex(original_id)
                settings_original_ids[prefix] = original_id
            else:
                settings_values[prefix] = ""
                settings_original_ids[prefix] = ""

        results = [{"Field": key, "Report": report_values.get(key), "Settings": settings_values.get(key),
                    "Result": "OK" if report_values.get(key) == settings_values.get(key) else "NOK"} for key in
                   ["HWEL", "BTLD", "SWFL"]]
        final_result = "NOK" if any(r["Result"] == "NOK" for r in results) else "OK"
        logging.info(f"[Core] DMC: {dmc_code} | SNR: {snr} | RESULT: {final_result}")

        response_data = {
            "dmc": dmc_code, "snr": snr, "results": results,
            "finalResult": final_result, "reportFile": str(report_file),
            "settingsFile": str(settings_file),
            "settingsDate": extract_date_from_name(settings_file),
            "settingsHwelOriginalId": settings_original_ids.get("HWEL", ""),
            "settingsBtldOriginalId": settings_original_ids.get("BTLD", ""),
            "settingsSwflOriginalId": settings_original_ids.get("SWFL", "")
        }
        return {"success": True, "data": response_data}

    except ET.ParseError as e:
        logging.error(f"[Core] Failed to parse XML {report_file_path}: {e}", exc_info=True)
        return {"success": False, "error": "msgInvalidReportXML", "dmc": dmc_code, "reportFile": str(report_file_path),
                "message": str(e)}
    except Exception as e:
        logging.error(f"[Core] Critical error in 'process_core_logic' for DMC {dmc_code}: {e}", exc_info=True)
        return {"success": False, "error": "internalError", "dmc": dmc_code, "reportFile": str(report_file_path),
                "message": str(e)}


def process_file_wrapper(report_file_path, config, is_manual_check=False):
    """Główny wrapper dla Manual Check."""
    logging.info(f"[Wrapper] Entered wrapper for: {report_file_path} (Manual: {is_manual_check})")
    try:
        report_path = Path(report_file_path)
        if not report_path.exists():
            logging.warning(f"[Wrapper] File {report_path} no longer exists.")
            return {"success": False, "error": "File not found"}

        dmc_code = report_path.parts[-3]

    except IndexError:
        logging.error(f"[Wrapper CRITICAL] Could not extract DMC from path: {report_file_path}.", exc_info=True)
        return {"success": False, "error": "Invalid file structure"}
    except Exception as e_init:
        logging.error(f"[Wrapper CRITICAL] Unexpected error at wrapper start for {report_file_path}: {e_init}",
                      exc_info=True)
        return {"success": False, "error": "Wrapper initialization failed"}

    logging.info(f"[Wrapper] Processing file: {report_path} for DMC: {dmc_code} (Manual: {is_manual_check})")
    settings_folder = config.get('settingsFolder')
    core_result = process_core_logic(report_path, settings_folder, dmc_code)
    recipients = config.get('mailRecipients')

    try:
        if core_result["success"]:
            response_data = core_result["data"]
            csv_path_to_use = config.get('csvPath')

            # Zapisz do CSV (Manual Check trafia do bazy danych)
            if csv_path_to_use:
                threading.Thread(target=log_to_csv, args=(csv_path_to_use, response_data)).start()

            if is_manual_check:
                threading.Thread(target=log_manual_scan, args=(response_data,)).start()

            if response_data.get('finalResult') == "NOK":
                # Wysłanie emaila NOK
                if recipients:
                    threading.Thread(target=send_nok_email, args=(recipients, response_data)).start()
                
                send_toast(
                    title="NOK Detected!",
                    line1=f"SNR: {response_data.get('snr', 'N/A')}",
                    line2=f"DMC: {response_data.get('dmc', 'N/A')}"
                )
        else:
            error_msg_key = core_result.get("error", "internalError")
            error_message = {
                "msgPathsNotSet": "Paths not set in config",
                "msgSnrNotFound": "SNR not found in report",
                "msgSettingsNotFound": "Settings not found for SNR",
                "msgInvalidReportXML": "Corrupt XML Report",
                "internalError": "Internal Server Error"
            }.get(error_msg_key, "Unknown Error")

            if is_manual_check:
                error_data = {
                    "dmc": dmc_code,
                    "snr": core_result.get('snr', 'N/A'),
                    "finalResult": "ERROR",
                    "reportFile": str(report_path),
                    "errorMessage": error_message
                }
                threading.Thread(target=log_manual_scan, args=(error_data,)).start()

            send_toast(
                title="Processing ERROR!",
                line1=f"Error: {error_message}",
                line2=f"File: {report_path.name}"
            )
    except Exception as e:
        logging.error(f"[Wrapper] Error during post-processing for {dmc_code}: {e}", exc_info=True)

    return core_result


# === PDI CHECK LOGIC (Excel vs Settings) ===
def process_pdi_check(excel_file_path, settings_folder_str):
    """
    PDI Check: Reads Excel file and compares values with Settings XML.
    
    Excel cells:
    - M5: Sachnumber (SNR)
    - M8: HWEL HEX
    - M9: HWEL DEC
    - M14: BTLD HEX
    - M15: BTLD DEC
    - M16: SWFL HEX
    - M17: SWFL DEC
    """
    try:
        excel_path = Path(excel_file_path)
        settings_folder = Path(settings_folder_str)

        if not excel_path.exists():
            return {"success": False, "error": "msgExcelNotFound", "excelFile": str(excel_path)}

        if not settings_folder.is_dir():
            return {"success": False, "error": "msgSettingsFolderNotSet"}

        if openpyxl is None:
            return {"success": False, "error": "msgOpenpyxlNotInstalled"}

        # Read Excel file
        logging.info(f"[PDI Check] Opening Excel file: {excel_path}")
        wb = openpyxl.load_workbook(str(excel_path), data_only=True)
        sheet = wb.active

        # Read values from Excel
        snr = str(sheet['M5'].value or '').strip()
        hwel_hex_excel = str(sheet['M8'].value or '').strip().upper()
        hwel_dec_excel = str(sheet['M9'].value or '').strip()
        btld_hex_excel = str(sheet['M14'].value or '').strip().upper()
        btld_dec_excel = str(sheet['M15'].value or '').strip()
        swfl_hex_excel = str(sheet['M16'].value or '').strip().upper()
        swfl_dec_excel = str(sheet['M17'].value or '').strip()

        wb.close()

        logging.info(f"[PDI Check] Excel values - SNR: {snr}")
        logging.info(f"[PDI Check] HWEL: HEX={hwel_hex_excel}, DEC={hwel_dec_excel}")
        logging.info(f"[PDI Check] BTLD: HEX={btld_hex_excel}, DEC={btld_dec_excel}")
        logging.info(f"[PDI Check] SWFL: HEX={swfl_hex_excel}, DEC={swfl_dec_excel}")

        if not snr:
            return {"success": False, "error": "msgSnrNotFoundInExcel", "excelFile": str(excel_path)}

        # Search for SNR in Settings XML files
        logging.info(f"[PDI Check] Searching for SNR: {snr} in {settings_folder}")
        start_time = time.time()
        settings_file, found_hardware_node = None, None
        all_xml_files = list(settings_folder.rglob("*.xml"))
        sorted_xml_files = sorted(all_xml_files, key=lambda p: p.stat().st_mtime, reverse=True)

        for xml_path in sorted_xml_files:
            try:
                tree_settings = ET.parse(str(xml_path), SECURE_PARSER)
                hardware_node_match = tree_settings.find(f".//hardware[@snr='{snr}']")
                if hardware_node_match is not None:
                    settings_file, found_hardware_node = xml_path, hardware_node_match
                    logging.info(f"[PDI Check] MATCH FOUND! File: {xml_path}")
                    break
            except Exception:
                pass

        logging.info(f"[PDI Check] Settings search took: {time.time() - start_time:.4f} s.")

        if not settings_file or found_hardware_node is None:
            logging.warning(f"[PDI Check] No settings found for SNR: {snr}")
            return {"success": False, "error": "msgSettingsNotFound", "snr": snr, "excelFile": str(excel_path)}

        # Extract values from Settings XML
        settings_values = {}
        for prefix in ["HWEL", "BTLD", "SWFL"]:
            te_nodes = found_hardware_node.xpath(f".//te[starts-with(@id, '{prefix}')]")
            te_node = te_nodes[0] if te_nodes else None
            if te_node is not None:
                original_id = te_node.get('id')
                hex_part, dec_part = parse_id_components(original_id)
                settings_values[prefix] = {
                    "hex": hex_part,
                    "dec": dec_part,
                    "original_id": original_id
                }
            else:
                settings_values[prefix] = {"hex": "", "dec": "", "original_id": ""}

        logging.info(f"[PDI Check] Settings values: {settings_values}")

        # Compare Excel vs Settings (both HEX middle part and DEC end part)
        results = []

        # HWEL comparison - both parts must match
        hwel_hex_match = hwel_hex_excel == settings_values["HWEL"]["hex"]
        hwel_dec_match = hwel_dec_excel == settings_values["HWEL"]["dec"]
        hwel_overall = hwel_hex_match and hwel_dec_match
        results.append({
            "Field": "HWEL",
            "ExcelHex": hwel_hex_excel,
            "ExcelDec": hwel_dec_excel,
            "SettingsHex": settings_values["HWEL"]["hex"],
            "SettingsDec": settings_values["HWEL"]["dec"],
            "HexMatch": "OK" if hwel_hex_match else "NOK",
            "DecMatch": "OK" if hwel_dec_match else "NOK",
            "Result": "OK" if hwel_overall else "NOK"
        })

        # BTLD comparison - both parts must match
        btld_hex_match = btld_hex_excel == settings_values["BTLD"]["hex"]
        btld_dec_match = btld_dec_excel == settings_values["BTLD"]["dec"]
        btld_overall = btld_hex_match and btld_dec_match
        results.append({
            "Field": "BTLD",
            "ExcelHex": btld_hex_excel,
            "ExcelDec": btld_dec_excel,
            "SettingsHex": settings_values["BTLD"]["hex"],
            "SettingsDec": settings_values["BTLD"]["dec"],
            "HexMatch": "OK" if btld_hex_match else "NOK",
            "DecMatch": "OK" if btld_dec_match else "NOK",
            "Result": "OK" if btld_overall else "NOK"
        })

        # SWFL comparison - both parts must match
        swfl_hex_match = swfl_hex_excel == settings_values["SWFL"]["hex"]
        swfl_dec_match = swfl_dec_excel == settings_values["SWFL"]["dec"]
        swfl_overall = swfl_hex_match and swfl_dec_match
        results.append({
            "Field": "SWFL",
            "ExcelHex": swfl_hex_excel,
            "ExcelDec": swfl_dec_excel,
            "SettingsHex": settings_values["SWFL"]["hex"],
            "SettingsDec": settings_values["SWFL"]["dec"],
            "HexMatch": "OK" if swfl_hex_match else "NOK",
            "DecMatch": "OK" if swfl_dec_match else "NOK",
            "Result": "OK" if swfl_overall else "NOK"
        })

        final_result = "NOK" if any(r["Result"] == "NOK" for r in results) else "OK"
        logging.info(f"[PDI Check] SNR: {snr} | RESULT: {final_result}")

        response_data = {
            "snr": snr,
            "results": results,
            "finalResult": final_result,
            "excelFile": str(excel_path),
            "settingsFile": str(settings_file),
            "settingsDate": extract_date_from_name(settings_file),
            "settingsHwelOriginalId": settings_values["HWEL"]["original_id"],
            "settingsBtldOriginalId": settings_values["BTLD"]["original_id"],
            "settingsSwflOriginalId": settings_values["SWFL"]["original_id"]
        }

        # Log the PDI check to JSON
        threading.Thread(target=log_pdi_check, args=(response_data,)).start()

        # Log to CSV
        config = load_config_from_file()
        if config.get('csvPath'):
            csv_data = {
                "dmc": "PDI_CHECK",
                "snr": snr,
                "finalResult": final_result,
                "results": [
                    {"Field": "HWEL", "Report": hwel_hex_excel, "Settings": settings_values["HWEL"]["hex"]},
                    {"Field": "BTLD", "Report": btld_hex_excel, "Settings": settings_values["BTLD"]["hex"]},
                    {"Field": "SWFL", "Report": swfl_hex_excel, "Settings": settings_values["SWFL"]["hex"]}
                ],
                "reportFile": str(excel_path),
                "settingsFile": str(settings_file)
            }
            threading.Thread(target=log_to_csv, args=(config['csvPath'], csv_data)).start()

        if final_result == "NOK":
            recipients = config.get('mailRecipients', [])
            if recipients:
                email_data = {
                    "snr": snr,
                    "dmc": "PDI_CHECK",
                    "results": [
                        {"Field": "HWEL", "Report": hwel_hex_excel, "Settings": settings_values["HWEL"]["hex"], "Result": results[0]["Result"]},
                        {"Field": "BTLD", "Report": btld_hex_excel, "Settings": settings_values["BTLD"]["hex"], "Result": results[1]["Result"]},
                        {"Field": "SWFL", "Report": swfl_hex_excel, "Settings": settings_values["SWFL"]["hex"], "Result": results[2]["Result"]}
                    ],
                    "reportFile": str(excel_path),
                    "settingsFile": str(settings_file)
                }
                threading.Thread(target=send_nok_email, args=(recipients, email_data)).start()
            
            send_toast(
                title="PDI Check NOK!",
                line1=f"SNR: {snr}",
                line2="Values mismatch detected"
            )
        else:
            send_toast(
                title="PDI Check OK",
                line1=f"SNR: {snr}",
                line2="All values match"
            )

        return {"success": True, "data": response_data}

    except Exception as e:
        logging.error(f"[PDI Check] Critical error: {e}", exc_info=True)
        return {"success": False, "error": "internalError", "message": str(e)}


# === API Endpoints ===

@app.route('/')
def serve_index():
    return send_from_directory(STATIC_FILES_DIR, 'index.html')


@app.route('/api/load-config', methods=['GET'])
def load_config():
    return jsonify(load_config_from_file())


@app.route('/api/save-config', methods=['POST'])
def save_config():
    try:
        data = request.json
        if 'mailRecipients' in data and isinstance(data['mailRecipients'], list):
            data['mailRecipients'] = [e.strip() for e in data['mailRecipients'] if e.strip() and '@' in e]

        current_config = load_config_from_file()
        current_config.update({k: v for k, v in data.items() if k in current_config})

        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(current_config, f, indent=2)

        return jsonify({"success": True})
    except Exception as e:
        logging.error("Config save error: %s", e)
        return jsonify({"error": str(e)}), 500


@app.route('/api/browse-folder', methods=['GET'])
def browse_folder():
    if not TKINTER_AVAILABLE:
        return jsonify({"success": False, "error": "File dialogs not available (tkinter missing)"}), 500
    try:
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        path = filedialog.askdirectory(title="Select folder")
        root.destroy()
        return jsonify({"success": True, "path": path}) if path else jsonify({"success": False, "error": "Cancelled"})
    except Exception as e:
        logging.error("Error in browse_folder: %s", e)
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/browse-file', methods=['GET'])
def browse_file():
    """Browse for Excel file."""
    if not TKINTER_AVAILABLE:
        return jsonify({"success": False, "error": "File dialogs not available (tkinter missing)"}), 500
    try:
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        file_types = [("Excel files", "*.xlsx *.xlsm"), ("All files", "*.*")]
        path = filedialog.askopenfilename(title="Select Excel file", filetypes=file_types)
        root.destroy()
        return jsonify({"success": True, "path": path}) if path else jsonify({"success": False, "error": "Cancelled"})
    except Exception as e:
        logging.error("Error in browse_file: %s", e)
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/run-check', methods=['POST'])
def run_check():
    """Manual Check endpoint (DMC-based) - używa reportsFolder z config."""
    data = request.json
    dmc = data.get('dmc')
    config = load_config_from_file()
    settings_folder_str = config.get('settingsFolder')
    reports_folder_str = config.get('reportsFolder', '')

    if not dmc or not settings_folder_str or not reports_folder_str:
        return jsonify({"success": False, "error": "msgPathsNotSet"})

    reports_folder = Path(reports_folder_str)
    settings_folder = Path(settings_folder_str)

    if not settings_folder.is_dir():
        return jsonify({"success": False, "error": "msgDmcEmptyOrPathsInvalid"})

    if not reports_folder.is_dir():
        return jsonify({"success": False, "error": "msgReportsFolderNotSet"})

    try:
        report_file = None
        dmc_folders = sorted(reports_folder.glob(f"{dmc}*"), key=lambda p: p.stat().st_mtime, reverse=True)

        if dmc_folders:
            dmc_folder = dmc_folders[0]
            timestamp_folders = sorted(
                [d for d in dmc_folder.iterdir() if d.is_dir() and is_timestamp_folder(d.name)],
                key=lambda p: p.name,
                reverse=True
            )

            if timestamp_folders:
                xml_files = list(timestamp_folders[0].rglob("*.xml"))
                if xml_files:
                    report_file = xml_files[0]

        if not report_file:
            error_data = {"dmc": dmc, "finalResult": "ERROR", "errorMessage": "msgReportNotFound"}
            threading.Thread(target=log_manual_scan, args=(error_data,)).start()
            return jsonify({"success": False, "error": "msgReportNotFound", "dmc": dmc})

        result = process_file_wrapper(report_file, config, is_manual_check=True)
        return jsonify(result)

    except Exception as e:
        logging.error(f"Critical error in /api/run-check for DMC {dmc}: {e}", exc_info=True)
        return jsonify({"success": False, "error": "internalError", "message": str(e)}), 500


@app.route('/api/pdi-check', methods=['POST'])
def pdi_check():
    """PDI Check endpoint (Excel-based)."""
    config = load_config_from_file()
    excel_file_path = config.get('excelFilePath')
    settings_folder_str = config.get('settingsFolder')

    if not excel_file_path:
        return jsonify({"success": False, "error": "msgExcelPathNotSet"})

    if not settings_folder_str:
        return jsonify({"success": False, "error": "msgSettingsFolderNotSet"})

    result = process_pdi_check(excel_file_path, settings_folder_str)
    return jsonify(result)


@app.route('/api/get-manual-scans', methods=['GET'])
def get_manual_scans():
    """Zwraca ostatnie ręczne skany."""
    scans = _get_recent_manual_scans()
    return jsonify(scans)


@app.route('/api/get-pdi-checks', methods=['GET'])
def get_pdi_checks():
    """Zwraca ostatnie PDI checks."""
    checks = _get_recent_pdi_checks()
    return jsonify(checks)


def _get_csv_path(config_data):
    csv_path_str = config_data.get('csvPath')
    if not csv_path_str:
        return None
    csv_path = Path(csv_path_str)
    return csv_path / "results.csv" if csv_path.is_dir() else csv_path


@app.route('/api/get-history', methods=['GET'])
def get_history():
    csv_path = _get_csv_path(load_config_from_file())
    if not csv_path or not csv_path.exists():
        return jsonify([])
    try:
        data = []
        with open(csv_path, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                data.append(row)
        return jsonify(data)
    except Exception as e:
        logging.error(f"Error reading history CSV {csv_path}: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


@app.route('/api/export-history-csv', methods=['POST'])
def export_history_csv():
    try:
        filtered_data = request.json.get('data', [])
        if not filtered_data:
            return jsonify({"success": False, "error": "No data to export"}), 400

        import io
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["timestamp", "dmc", "snr", "final", "report_file", "settings_file"])
        
        for row in filtered_data:
            writer.writerow([row.get(k, '') for k in ['timestamp', 'dmc', 'snr', 'final', 'report_file', 'settings_file']])

        return jsonify({"success": True, "csv_data": output.getvalue()})
    except Exception as e:
        logging.error(f"CSV export error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/get-stats', methods=['GET'])
def get_stats():
    stats = {"total_ok": 0, "total_nok": 0, "nok_details": defaultdict(int), "last_result": "N/A",
             "last_timestamp": "N/A"}
    csv_path = _get_csv_path(load_config_from_file())
    if not csv_path or not csv_path.exists():
        return jsonify(stats)
    try:
        with open(csv_path, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            history = list(reader)

            if history:
                latest = history[-1]
                stats['last_result'] = latest.get('final', 'N/A')
                stats['last_timestamp'] = latest.get('timestamp', 'N/A')

            for row in history:
                if row.get('final') == 'OK':
                    stats['total_ok'] += 1
                elif row.get('final') == 'NOK':
                    stats['total_nok'] += 1
                    if row.get('hwel_report') != row.get('hwel_set'):
                        stats['nok_details']['HWEL'] += 1
                    if row.get('btld_report') != row.get('btld_set'):
                        stats['nok_details']['BTLD'] += 1
                    if row.get('swfl_report') != row.get('swfl_set'):
                        stats['nok_details']['SWFL'] += 1

        return jsonify(stats)
    except Exception as e:
        logging.error(f"Error calculating stats from CSV {csv_path}: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


SMAC_TEMPLATE = {"documentVersion": "1.0", "comment": "", "testStepResults": [{"step": 1,
                                                                               "description": "apiJob(\"F01\",\"STATUS_SVK_SMACS_CURRENT_FUNKTIONAL\",\"\",\"\")",
                                                                               "iterations": [{"iteration": 1,
                                                                                               "resultItems": [{
                                                                                                   "name": "Set : 2",
                                                                                                   "type": "",
                                                                                                   "value": "",
                                                                                                   "resultItems": [{
                                                                                                       "name": "SMAC_ID[0]",
                                                                                                       "type": "BINARY",
                                                                                                       "value": "00 51"},
                                                                                                       {
                                                                                                           "name": "SGBM_ID[0][0]",
                                                                                                           "type": "TEXT",
                                                                                                           "value": "PLACEHOLDER_HWEL"},
                                                                                                       {
                                                                                                           "name": "SGBM_ID[0][1]",
                                                                                                           "type": "TEXT",
                                                                                                           "value": "PLACEHOLDER_BTLD"},
                                                                                                       {
                                                                                                           "name": "SGBM_ID[0][2]",
                                                                                                           "type": "TEXT",
                                                                                                           "value": "PLACEHOLDER_SWFL"},
                                                                                                       {
                                                                                                           "name": "PROGRAMMING_DEPENDENCIES_CHECKED[0]",
                                                                                                           "type": "TEXT",
                                                                                                           "value": "0x01"},
                                                                                                       {
                                                                                                           "name": "PROGRAMMING_DEPENDENCIES_CHECKED_TEXT[0]",
                                                                                                           "type": "TEXT",
                                                                                                           "value": "correct Result"}]}]}]}]}


def _convert_id_to_smac_format(original_id):
    if not original_id:
        return ""
    parts = original_id.split('_', 2)
    return f"{parts[0]}-{parts[1]}-{parts[2]}" if len(parts) == 3 else original_id


@app.route('/api/generate-smac-json', methods=['POST'])
def generate_smac_json():
    try:
        data = request.json
        smac_json = json.loads(json.dumps(SMAC_TEMPLATE))
        items_list = smac_json["testStepResults"][0]["iterations"][0]["resultItems"][0]["resultItems"]
        for item in items_list:
            if item["name"] == "SGBM_ID[0][0]":
                item["value"] = _convert_id_to_smac_format(data.get('hwelId', ''))
            elif item["name"] == "SGBM_ID[0][1]":
                item["value"] = _convert_id_to_smac_format(data.get('btldId', ''))
            elif item["name"] == "SGBM_ID[0][2]":
                item["value"] = _convert_id_to_smac_format(data.get('swflId', ''))
        logging.info(f"Generated SMAC JSON for HWEL: {data.get('hwelId', '')}")
        return jsonify(smac_json)
    except Exception as e:
        logging.error(f"Error generating SMAC JSON: {e}", exc_info=True)
        return jsonify({"error": "Failed to generate SMAC JSON"}), 500


@app.route('/api/download-smac-json', methods=['POST'])
def download_smac_json():
    """Generate and download SMAC JSON file (WebView compatible)."""
    try:
        data = request.json
        snr = data.get('snr', 'unknown')
        
        smac_json = json.loads(json.dumps(SMAC_TEMPLATE))
        items_list = smac_json["testStepResults"][0]["iterations"][0]["resultItems"][0]["resultItems"]
        for item in items_list:
            if item["name"] == "SGBM_ID[0][0]":
                item["value"] = _convert_id_to_smac_format(data.get('hwelId', ''))
            elif item["name"] == "SGBM_ID[0][1]":
                item["value"] = _convert_id_to_smac_format(data.get('btldId', ''))
            elif item["name"] == "SGBM_ID[0][2]":
                item["value"] = _convert_id_to_smac_format(data.get('swflId', ''))
        
        from flask import Response
        json_str = json.dumps(smac_json, indent=2)
        
        return Response(
            json_str,
            mimetype='application/json',
            headers={
                'Content-Disposition': f'attachment; filename=SMAC_{snr}.json'
            }
        )
    except Exception as e:
        logging.error(f"Error downloading SMAC JSON: {e}", exc_info=True)
        return jsonify({"error": "Failed to download SMAC JSON"}), 500


@app.route('/api/download-screenshot', methods=['POST'])
def download_screenshot():
    """Download screenshot as JPEG (WebView compatible)."""
    try:
        data = request.json
        image_data = data.get('imageData', '')
        dmc = data.get('dmc', 'unknown')
        
        if not image_data or not image_data.startswith('data:image'):
            return jsonify({"error": "Invalid image data"}), 400
        
        # Remove data URL prefix
        import base64
        header, encoded = image_data.split(',', 1)
        image_bytes = base64.b64decode(encoded)
        
        from flask import Response
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        return Response(
            image_bytes,
            mimetype='image/jpeg',
            headers={
                'Content-Disposition': f'attachment; filename=Report_DMC_{dmc}_{timestamp}.jpg'
            }
        )
    except Exception as e:
        logging.error(f"Error downloading screenshot: {e}", exc_info=True)
        return jsonify({"error": "Failed to download screenshot"}), 500


@app.route('/api/factory-reset', methods=['POST'])
def factory_reset():
    logging.warning("=== FACTORY RESET ===")
    try:
        csv_path = None
        if CONFIG_FILE.exists():
            try:
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    csv_path = _get_csv_path(json.load(f))
            except Exception:
                pass
        
        with csv_lock:
            files = [CONFIG_FILE, PORT_FILE, MANUAL_SCAN_LOG_FILE, PDI_CHECK_LOG_FILE]
            if csv_path and csv_path.exists():
                files.append(csv_path)
            
            for f in files:
                if f and f.exists():
                    try:
                        os.remove(f)
                    except Exception:
                        pass
        
        for log in LOG_DIR.glob('*'):
            if log.name != 'app.log':
                try:
                    os.remove(log)
                except Exception:
                    pass
        
        return jsonify({"success": True})
    except Exception as e:
        logging.error(f"Factory reset error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/status', methods=['GET'])
def get_status():
    """Endpoint do sprawdzania statusu konfiguracji - sprawdza wszystkie 3 ścieżki."""
    config = load_config_from_file()
    settings_folder_str = config.get('settingsFolder', '')
    reports_folder_str = config.get('reportsFolder', '')
    excel_file_path = config.get('excelFilePath', '')

    # Sprawdź które ścieżki są ustawione
    settings_ok = settings_folder_str and Path(settings_folder_str).is_dir()
    reports_ok = reports_folder_str and Path(reports_folder_str).is_dir()
    excel_ok = excel_file_path and Path(excel_file_path).is_file()

    # Status: READY jeśli wszystkie 3 ścieżki OK
    if settings_ok and reports_ok and excel_ok:
        return jsonify({
            "status": "READY",
            "message": "All paths configured correctly.",
            "settings_folder": settings_folder_str,
            "reports_folder": reports_folder_str,
            "excel_file": excel_file_path
        })
    else:
        # SETUP_REQUIRED jeśli brakuje którejś ścieżki
        missing = []
        if not settings_ok: missing.append("Settings Folder")
        if not reports_ok: missing.append("Reports Folder")
        if not excel_ok: missing.append("Excel File")
        
        return jsonify({
            "status": "SETUP_REQUIRED",
            "message": f"Missing or invalid: {', '.join(missing)}",
            "settings_folder": settings_folder_str,
            "reports_folder": reports_folder_str,
            "excel_file": excel_file_path
        })


# === Server Startup ===
if __name__ == '__main__':
    INITIAL_PORT = 5001
    MAX_PORT_ATTEMPTS = 5
    ACTUAL_PORT = None

    if PORT_FILE.exists():
        try:
            os.remove(PORT_FILE)
            logging.info("Cleaned up old port file.")
        except Exception as e:
            logging.warning(f"Failed to remove old port file: {e}")

    try:
        for i in range(MAX_PORT_ATTEMPTS):
            test_port = INITIAL_PORT + i

            try:
                logging.info(f"Step 4: Attempting to start Flask server on port: {test_port}")

                with open(PORT_FILE, 'w', encoding='utf-8') as f:
                    f.write(str(test_port))
                logging.info(f"Step 4a: Wrote tentative port ({test_port}) to {PORT_FILE.name}")

                ACTUAL_PORT = test_port

                # === START UI (WebView or Browser) ===
                if USE_WEBVIEW and WEBVIEW_AVAILABLE:
                    # Native app window mode
                    logging.info("Starting in WebView (native window) mode...")
                    
                    def start_server():
                        """Start Flask server in background thread."""
                        app.run(port=ACTUAL_PORT, debug=False, host='127.0.0.1', use_reloader=False, threaded=True)
                    
                    # Start Flask in background
                    server_thread = threading.Thread(target=start_server, daemon=True)
                    server_thread.start()
                    
                    # Wait for server to start
                    time.sleep(2)
                    
                    # Create native window
                    webview.create_window(
                        'Software Checker',
                        f'http://127.0.0.1:{ACTUAL_PORT}',
                        width=1200,
                        height=800,
                        resizable=True,
                        fullscreen=False,
                        min_size=(800, 600)
                    )
                    webview.start()
                    logging.info("WebView window closed. Shutting down...")
                    
                else:
                    # Browser mode (fallback)
                    logging.info("Starting in Browser mode...")
                    try:
                        import webbrowser

                        def open_browser():
                            """Opens browser after 5 second delay."""
                            try:
                                time.sleep(5)
                                webbrowser.open(f'http://127.0.0.1:{ACTUAL_PORT}')
                                logging.info(f"Browser opened for http://127.0.0.1:{ACTUAL_PORT}")
                            except Exception as e:
                                logging.warning(f"Could not open browser: {e}")

                        threading.Thread(target=open_browser, daemon=True).start()
                        logging.info("Browser launch scheduled (5s delay)...")
                    except Exception as e:
                        logging.warning(f"Browser auto-launch disabled: {e}")

                    app.run(port=ACTUAL_PORT, debug=False, host='127.0.0.1', use_reloader=False, threaded=True)
                break

            except OSError as e:
                if "Address already in use" in str(e):
                    logging.warning(f"Port {test_port} is busy. Trying next port...")
                    if i == MAX_PORT_ATTEMPTS - 1:
                        logging.critical(f"Failed to find a free port after {MAX_PORT_ATTEMPTS} attempts.")
                        send_toast("CRITICAL ERROR", f"Failed to start server:", "Ports 5001-5005 busy.")
                        sys.exit()
                    continue
                else:
                    raise e

    except Exception as e:
        logging.critical(f"=== CRITICAL FLASK STARTUP FAILURE: {e} ===", exc_info=True)
