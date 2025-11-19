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
    # Wszystko obok EXE, bez subfolderów!
    EXE_DIR = Path(sys.executable).parent
    BUNDLE_DIR = Path(sys._MEIPASS) if hasattr(sys, '_MEIPASS') else EXE_DIR
    
    # User data bezpośrednio obok EXE (portable)
    USER_DATA_DIR = EXE_DIR / 'user_data'
    USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
else:
    # Running as Python script (start.bat)
    BUNDLE_DIR = Path(__file__).parent  # app/
    USER_DATA_DIR = BUNDLE_DIR / 'user_data'  # app/user_data

LOG_DIR = USER_DATA_DIR / 'logs'
LOG_DIR.mkdir(parents=True, exist_ok=True)
# PLIKI I PARAMETRY KRYTYCZNE
PORT_FILE = USER_DATA_DIR / 'app_port.txt'

# NOWY PLIK: Log dla ręcznych skanów
MANUAL_SCAN_LOG_FILE = USER_DATA_DIR / 'manual_scans_log.json' 

# ZMIENNE DLA PULSU SIECIOWEGO
NETWORK_PULSE_INTERVAL = 30 
# ZMIENNE DLA OUTLOOKA
OUTLOOK_WAIT_SECONDS = 15
OUTLOOK_POLL_INTERVAL = 1


# --- EARLY LOGGING ---
logging.basicConfig(
    filename=LOG_DIR / 'app.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logging.info("========================================")
logging.info(f"=== PID: {os.getpid()} Starting Software Checker Server (v2.4.1 + Final Logics) ===")
logging.info("Step 1: Early logging initialized. Attempting library imports...")
# --- END EARLY LOGGING ---

# Global observer instance for watchdog restart functionality
watchdog_observer = None
watchdog_lock = threading.Lock()


try:
    from lxml import etree as ET
    from flask import Flask, request, jsonify, send_from_directory
    from flask_cors import CORS
    import tkinter as tk
    from tkinter import filedialog


    # IMPORT for E-mail (Outlook/pywin32)
    try:
        import win32com.client as win32
        import pywintypes
        logging.info("Import 'pywin32' (Outlook) successful.")
    except ImportError:
        logging.error("!!! CRITICAL ERROR: 'pywin32' library not found. Run 'pip install pywin32'. !!!")
        win32 = None


    # IMPORT for Watchdog
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler
    logging.info(f"Import 'watchdog' successful. Observer: {Observer}")


    # IMPORT for Windows Toasts
    try:
        from windows_toasts import WindowsToaster, Toast
        WINDOWS_TOASTS_ENABLED = True
        logging.info("Import 'windows-toasts' successful. Desktop notifications enabled.")
    except ImportError:
        WINDOWS_TOASTS_ENABLED = False
        logging.warning("!!! 'windows-toasts' library not found. Run 'pip install windows-toasts' to enable desktop notifications. !!!")


except ImportError as e:
    logging.critical(f"=== CRITICAL IMPORT FAILURE: {e} ===")
    logging.critical("Server cannot start. Missing key library.")
    sys.exit()


logging.info("Step 2: All key libraries imported successfully.")


# --- Configuration ---
STATIC_FILES_DIR = BUNDLE_DIR / 'files'  # Static files from bundle
JSON_DIR = USER_DATA_DIR / 'json'
CONFIG_FILE = JSON_DIR / 'config.json'


SECURE_PARSER = ET.XMLParser(resolve_entities=False)


# Czysta konfiguracja
DEFAULT_CONFIG = {
  "settingsFolder": "",
  "reportsFolder": "",
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


if win32 is None:
    logging.warning("Limited Functionality Mode: Outlook email is DISABLED (pywin32 not found or registered).")


 
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


 
# === Helper Functions (bez zmian) ===
def canon_hex(s):
    if not s: return ""
    only = re.sub(r'[^0-9A-F]', '', str(s).upper())
    return ' '.join(a+b for a,b in zip(only[::2], only[1::2]))


 
def parse_id_to_hex(id_str):
    if not id_str: return ""
    parts = id_str.split("_")
    if len(parts) < 3: return ""
    mid = re.sub(r'[^0-9A-Fa-f]', '', parts[1]); mid = mid[-4:] if len(mid) > 4 else mid
    mid_bytes = [mid[i:i+2] for i in range(0, len(mid), 2)]
    dec_bytes = [f"{int(d):02X}" for d in parts[2].split('.') if d.isdigit()]
    return canon_hex("".join(mid_bytes + dec_bytes))


 
def extract_bytes_from_teststep(t):
    if not t: return ""
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
        logging.warning("CSV path not set in config.json. Skipping CSV log.")
        return
    try:
        csv_path = Path(csv_path_str)
        if csv_path.is_dir():
            csv_path = csv_path / "results.csv"
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        results = {r['Field']: r for r in data['results']}
        row = [
            timestamp, data.get('dmc', 'N/A'), data.get('snr', 'N/A'), data.get('finalResult', 'N/A'),
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
            logging.info(f"Saved result for DMC {data.get('dmc')} to CSV: {csv_path}")
    except Exception as e:
        logging.error(f"Critical error during CSV write ({csv_path_str}): {e}", exc_info=True)


 
# === LOGIKA: Logowanie Ręcznych Skanów (do pliku JSON) ===

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
            "errorMessage": data.get('errorMessage', '') # Dodano do obsługi błędów
        }
        
        with manual_scan_lock:
            scans = _get_recent_manual_scans() # Wczytuje istniejące
            
            # Usuń najstarsze, jeśli limit przekroczony
            scans.insert(0, data_to_log)
            if len(scans) > MAX_MANUAL_SCANS:
                scans = scans[:MAX_MANUAL_SCANS]
            
            with open(MANUAL_SCAN_LOG_FILE, 'w', encoding='utf-8') as f:
                json.dump(scans, f, indent=2)
            
            logging.info(f"Logged manual scan for DMC {data_to_log['dmc']} to JSON.")
            
    except Exception as e:
        logging.error(f"Critical error during manual scan log write: {e}", exc_info=True)


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


 
# === Outlook Email Logic ===
def get_outlook_app():
    global win32
    if win32 is None:
        logging.warning("Cannot get Outlook app: pywin32 library is missing.")
        return None
   
    with outlook_lock:
        try:
            # 1. Próba połączenia z już aktywnym Outlookiem
            outlook = win32.GetActiveObject('outlook.application')
            logging.info("Outlook is already running. Connected to active object.")
            return outlook
        except pywintypes.com_error:
            # 2. Outlook nieaktywny, próba uruchomienia i czekania w pętli
            logging.info("Outlook is not running. Attempting to launch...")
            try:
                os.startfile("outlook")
               
                # Czekamy w pętli, sprawdzając co sekundę (max 15s)
                for i in range(OUTLOOK_WAIT_SECONDS):
                    time.sleep(OUTLOOK_POLL_INTERVAL)
                    try:
                        outlook = win32.GetActiveObject('outlook.application')
                        logging.info(f"Outlook connected after {i+1} seconds.")
                        return outlook
                    except pywintypes.com_error:
                        continue # Nadal się ładuje
                       
                logging.error(f"Failed to connect to Outlook after {OUTLOOK_WAIT_SECONDS} seconds.")
                return None
            except Exception as e_start:
                logging.error(f"Failed to start Outlook process: {e_start}", exc_info=True)
                return None
        except Exception as e_generic:
            logging.error(f"Generic error checking Outlook status: {e_generic}", exc_info=True)
            return None


 
def send_nok_email(recipients, data):
    try:
        outlook = get_outlook_app()
        if not outlook:
            logging.error("Email skipped: Could not get Outlook instance.")
            return
        if not recipients:
            logging.warning("No email recipients in config.json. Skipping send.")
            return
        snr = data.get('snr', 'N/A')
        dmc = data.get('dmc', 'N/A')
        results_html = "<table border='1' cellpadding='5' cellspacing='0' style='border-collapse: collapse;'>"
        results_html += "<tr style='background-color: #f2f2f2;'><th>Field</th><th>Report</th><th>Settings</th><th>Result</th></tr>"
        for r in data.get('results', []):
            result_style = "color: red; font-weight: bold;" if r['Result'] == 'NOK' else "color: green;"
            results_html += f"<tr><td>{r['Field']}</td><td>{r['Report'] or 'N/A'}</td><td>{r['Settings'] or 'N/A'}</td><td style='{result_style}'>{r['Result']}</td></tr>"
        results_html += "</table>"
        body = f"""
        <html><body>
        <p>A <strong>NOK</strong> result was detected by the Software Checker.</p>
        <p><strong>SNR:</strong> {snr}<br><strong>DMC:</strong> {dmc}</p>
        {results_html}
        <p><strong>Report File:</strong> {data.get('reportFile', 'N/A')}<br><strong>Settings File:</strong> {data.get('settingsFile', 'N/A')}</p>
        <hr><p style='font-size: 0.8em; color: #777;'>This is an automated message from SoftwareChecker v2.</p>
        </body></html>
        """
        logging.info(f"Attempting to send NOK email for SNR {snr} via Outlook...")
        mail = outlook.CreateItem(0)
        mail.To = "; ".join(recipients)
        mail.Subject = f"[SoftwareChecker] NOK for SNR {snr}"
        mail.HTMLBody = body
        mail.Send()
        logging.info(f"Email command for SNR {snr} passed to Outlook.")
    except Exception as e:
        logging.error(f"Critical error sending Outlook email for SNR {snr}: {e}", exc_info=True)


 
def send_error_email(recipients, error_msg, dmc, report_file):
    try:
        outlook = get_outlook_app()
        if not outlook:
            logging.error("Email skipped: Could not get Outlook instance.")
            return
        if not recipients:
            logging.warning("No email recipients in config.json. Skipping send.")
            return
        body = f"""
        <html><body>
        <p>The Software Checker encountered an <strong>ERROR</strong> while processing a file.</p>
        <p><strong>Error:</strong> <span style='color: red; font-weight: bold;'>{error_msg}</span><br>
           <strong>DMC:</strong> {dmc or 'N/A'}<br>
           <strong>Report File:</strong> {report_file or 'N/A'}</p>
        <p>Please check the application logs for more details.</p>
        <hr><p style='font-size: 0.8em; color: #777;'>This is an automated message from SoftwareChecker v2.</p>
        </body></html>
        """
        logging.info(f"Attempting to send ERROR email for DMC {dmc} via Outlook...")
        mail = outlook.CreateItem(0)
        mail.To = "; ".join(recipients)
        mail.Subject = f"[SoftwareChecker] ERROR processing DMC {dmc}"
        mail.HTMLBody = body
        mail.Send()
        logging.info(f"Error email command for DMC {dmc} passed to Outlook.")
    except Exception as e:
        logging.error(f"Critical error sending Outlook ERROR email for DMC {dmc}: {e}", exc_info=True)


 
# === Config Management (bez zmian) ===
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


 
# === GŁÓWNA LOGIKA APLIKACJI (MÓZG - bez zmian) ===
def process_core_logic(report_file_path, settings_folder_str, dmc_code):
    try:
        report_file = Path(report_file_path)
        settings_folder = Path(settings_folder_str)
        if not (report_file.exists() and settings_folder.is_dir()):
            # To powinno być przechwycone przez /api/run-check wcześniej, ale zostawmy
            return {"success": False, "error": "msgPathsNotSet", "dmc": dmc_code} 
    
        tree = ET.parse(str(report_file), SECURE_PARSER); root = tree.getroot()
        snr_node = root.find(".//info[name='BMW PartNumber']/description")
        snr = snr_node.text if snr_node is not None else None
        if not snr:
            return {"success": False, "error": "msgSnrNotFound", "dmc": dmc_code, "reportFile": str(report_file)}
    
        all_text = " ".join(node.text for node in root.findall(".//teststep") if node.text)
        report_values = {
            "HWEL": extract_bytes_from_teststep(re.search(r'.*(HWEL.*)', all_text, re.IGNORECASE).group(1) if re.search(r'.*(HWEL.*)', all_text, re.IGNORECASE) else None),
            "BTLD": extract_bytes_from_teststep(re.search(r'.*(BTLD.*)', all_text, re.IGNORECASE).group(1) if re.search(r'.*(BTLD.*)', all_text, re.IGNORECASE) else None),
            "SWFL": extract_bytes_from_teststep(re.search(r'.*(SWFL.*)', all_text, re.IGNORECASE).group(1) if re.search(r'.*(SWFL.*)', all_text, re.IGNORECASE) else None)
        }
    
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
            except Exception: pass
    
        logging.info(f"[Core] Settings search took: {time.time() - start_time:.4f} s.")
    
        if not settings_file or found_hardware_node is None:
            logging.warning(f"[Core] No settings found for SNR: {snr}")
            return {"success": False, "error": "msgSettingsNotFound", "snr": snr, "dmc": dmc_code, "reportFile": str(report_file)}


 
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


 
        results = [{"Field": key, "Report": report_values.get(key), "Settings": settings_values.get(key), "Result": "OK" if report_values.get(key) == settings_values.get(key) else "NOK"} for key in ["HWEL", "BTLD", "SWFL"]]
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
        return {"success": False, "error": "msgInvalidReportXML", "dmc": dmc_code, "reportFile": str(report_file_path), "message": str(e)}
    except Exception as e:
        logging.error(f"[Core] Critical error in 'process_core_logic' for DMC {dmc_code}: {e}", exc_info=True)
        return {"success": False, "error": "internalError", "dmc": dmc_code, "reportFile": str(report_file_path), "message": str(e)}


 
def process_file_wrapper(report_file_path, config, is_manual_check=False):
    """Główny wrapper. Dodano logikę zapisu dla manualnych skanów."""
    logging.info(f"[Wrapper] Entered wrapper for: {report_file_path} (Manual: {is_manual_check})")
    try:
        report_path = Path(report_file_path)
        if not report_path.exists():
            logging.warning(f"[Wrapper] File {report_path} no longer exists. Might be a temp file.")
            return {"success": False, "error": "File not found"}
    
        dmc_code = report_path.parts[-3]
 
    except IndexError:
        logging.error(f"[Wrapper CRITICAL] Could not extract DMC from path: {report_file_path}. Expected .../Machine/Timestamp/file.xml", exc_info=True)
        return {"success": False, "error": "Invalid file structure"}
    except Exception as e_init:
        logging.error(f"[Wrapper CRITICAL] Unexpected error at wrapper start for {report_file_path}: {e_init}", exc_info=True)
        return {"success": False, "error": "Wrapper initialization failed"}


 
    logging.info(f"[Wrapper] Processing file: {report_path} for DMC: {dmc_code} (Manual: {is_manual_check})")
    settings_folder = config.get('settingsFolder')
    core_result = process_core_logic(report_path, settings_folder, dmc_code)
    recipients = config.get('mailRecipients')


    try:
        if core_result["success"]:
            response_data = core_result["data"]
            csv_path_to_use = config.get('csvPath')
            
            # --- Akcje po SUCCESS ---
            if not is_manual_check:
                threading.Thread(target=log_to_csv, args=(csv_path_to_use, response_data)).start()
            
            # Logowanie manualnego skanu do dedykowanego pliku JSON
            if is_manual_check:
                threading.Thread(target=log_manual_scan, args=(response_data,)).start()
            
            if response_data.get('finalResult') == "NOK":
                if not is_manual_check:
                    threading.Thread(target=send_nok_email, args=(recipients, response_data)).start()
                send_toast(
                    title="NOK Detected!",
                    line1=f"SNR: {response_data.get('snr', 'N/A')}",
                    line2=f"DMC: {response_data.get('dmc', 'N/A')}"
                )
        
        else:
            # --- Akcje po ERROR ---
            error_msg_key = core_result.get("error", "internalError")
            error_message = {
                "msgPathsNotSet": "Paths not set in config",
                "msgSnrNotFound": "SNR not found in report",
                "msgSettingsNotFound": "Settings not found for SNR",
                "msgInvalidReportXML": "Corrupt XML Report",
                "internalError": "Internal Server Error"
            }.get(error_msg_key, "Unknown Error")
        
            # Zapisz BŁĄD do logu manualnego skanowania
            if is_manual_check:
                 error_data = {
                     "dmc": dmc_code,
                     "snr": core_result.get('snr', 'N/A'),
                     "finalResult": "ERROR",
                     "reportFile": str(report_path),
                     "errorMessage": error_message
                 }
                 threading.Thread(target=log_manual_scan, args=(error_data,)).start()
        
            if error_msg_key == "msgInvalidReportXML":
                logging.warning(f"Parse error for {report_path.name}. Mail NOT sent in case it was a copy-race condition.")
            else:
                if not is_manual_check:
                    threading.Thread(target=send_error_email, args=(recipients, error_message, dmc_code, str(report_path))).start()
        
            send_toast(
                title="Processing ERROR!",
                line1=f"Error: {error_message}",
                line2=f"File: {report_path.name}"
            )
    except Exception as e:
        logging.error(f"[Wrapper] Error during post-processing (CSV/Email/Toast) for {dmc_code}: {e}", exc_info=True)

    # W przypadku manualnego skanowania, pełny wynik (również błąd) jest zwracany do front-endu
    return core_result


 
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
            data['mailRecipients'] = [
                email.strip() for email in data['mailRecipients']
                if email.strip() and '@' in email
            ]
     
        current_config = load_config_from_file()
      
        for key in current_config.keys(): # Zmieniono na iterowanie po current_config
            if key in data:
                 current_config[key] = data[key]
     
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(current_config, f, indent=2)
        
        if 'reportsFolder' in data:
            logging.info("[API] reportsFolder changed, restarting watchdog...")
            restart_result = restart_watchdog()
            
            # ✅ NOWE: Automatyczne tworzenie pliku CSV z nagłówkami, jeśli nie istnieje
            try:
                csv_path = _get_csv_path(current_config)
                if csv_path:
                    csv_path.parent.mkdir(parents=True, exist_ok=True)
                    if not csv_path.exists():
                        with open(csv_path, 'w', newline='', encoding='utf-8-sig') as f:
                            writer = csv.writer(f)
                            writer.writerow(CSV_HEADER)
                        logging.info(f"[API] Auto-created new CSV results file: {csv_path}")
            except Exception as e_csv:
                logging.warning(f"[API] Failed to auto-create CSV: {e_csv}")

            return jsonify({"success": True, "watchdog": restart_result})
         
        return jsonify({"success": True})
    except Exception as e:
        logging.error("Error saving config.json: %s", e)
        return jsonify({"error": str(e)}), 500


 
@app.route('/api/browse-folder', methods=['GET'])
def browse_folder():
    try:
        root = tk.Tk()
        root.withdraw(); root.attributes("-topmost", True)
        path = filedialog.askdirectory(title="Select folder")
        root.destroy()
        return jsonify({"success": True, "path": path}) if path else jsonify({"success": False, "error": "Cancelled"})
    except Exception as e:
        logging.error("Error in browse_folder: %s", e)
        return jsonify({"success": False, "error": str(e)}), 500


 
@app.route('/api/run-check', methods=['POST'])
def run_check():
    data = request.json
    dmc = data.get('dmc')
    config = load_config_from_file()
    settings_folder_str = config.get('settingsFolder')
    reports_folder_str = config.get('reportsFolder')
  
    if not (dmc and settings_folder_str and reports_folder_str):
        return jsonify({"success": False, "error": "msgDmcEmptyOrPathsInvalid"})


    settings_folder, reports_folder = Path(settings_folder_str), Path(reports_folder_str)


    if not (settings_folder.is_dir() and reports_folder.is_dir()):
         return jsonify({"success": False, "error": "msgDmcEmptyOrPathsInvalid"})


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
            # W przypadku błędu nieznalezienia raportu też zwracamy dane, żeby zapisały się w logu manualnym
            error_data = {"dmc": dmc, "finalResult": "ERROR", "errorMessage": "msgReportNotFound"}
            threading.Thread(target=log_manual_scan, args=(error_data,)).start()
            return jsonify({"success": False, "error": "msgReportNotFound", "dmc": dmc})

    
        result = process_file_wrapper(report_file, config, is_manual_check=True)
        return jsonify(result)


    except Exception as e:
        logging.error(f"Critical error in /api/run-check for DMC {dmc}: {e}", exc_info=True)
        return jsonify({"success": False, "error": "internalError", "message": str(e)}), 500


@app.route('/api/get-manual-scans', methods=['GET'])
def get_manual_scans():
    """NOWY ENDPOINT: Zwraca ostatnie ręczne skany dla panelu bocznego."""
    scans = _get_recent_manual_scans()
    return jsonify(scans)


 
def _get_csv_path(config_data):
    csv_path_str = config_data.get('csvPath')
    if not csv_path_str: return None
    csv_path = Path(csv_path_str)
    return csv_path / "results.csv" if csv_path.is_dir() else csv_path


 
@app.route('/api/get-history', methods=['GET'])
def get_history():
    csv_path = _get_csv_path(load_config_from_file())
    if not csv_path or not csv_path.exists(): return jsonify([])
    try:
        data = []
        with open(csv_path, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader: data.append(row)
        return jsonify(data)
    except Exception as e:
        logging.error(f"Error reading history CSV {csv_path}: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500

# NOWY ENDPOINT DLA EKSPORTU CSV Z WIDOKU FILTROWANEGO (zabezpieczenie eksportu)
 
@app.route('/api/export-history-csv', methods=['POST'])
def export_history_csv():
    """Endpoint przyjmuje filtrowane dane z front-endu i zwraca plik CSV."""
    try:
        data = request.json
        filtered_data = data.get('data', [])
        
        if not filtered_data:
            return jsonify({"success": False, "error": "No data to export"}), 400

        # Nagłówki, które front-end oczekuje do eksportu
        header = ["timestamp", "dmc", "snr", "final", "report_file", "settings_file"]
        
        # Używamy csv.writer do bezpiecznego cytowania pól
        import io
        output = io.StringIO()
        writer = csv.writer(output, delimiter=',', quoting=csv.QUOTE_MINIMAL)
        
        # Nagłówki
        writer.writerow(header)
        
        for row in filtered_data:
            writer.writerow([
                row.get('timestamp', ''),
                row.get('dmc', ''),
                row.get('snr', ''),
                row.get('final', ''),
                row.get('report_file', ''),
                row.get('settings_file', '')
            ])
            
        csv_string = output.getvalue()

        return jsonify({"success": True, "csv_data": csv_string})

    except Exception as e:
        logging.error(f"Error during CSV export: {e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500
 
@app.route('/api/get-stats', methods=['GET'])
def get_stats():
    stats = { "total_ok": 0, "total_nok": 0, "nok_details": defaultdict(int), "last_result": "N/A", "last_timestamp": "N/A" }
    csv_path = _get_csv_path(load_config_from_file())
    if not csv_path or not csv_path.exists(): return jsonify(stats)
    try:
        with open(csv_path, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            history = list(reader)

            if history:
                latest = history[-1]
                stats['last_result'] = latest.get('final', 'N/A')
                stats['last_timestamp'] = latest.get('timestamp', 'N/A')

            for row in history:
                if row.get('final') == 'OK': stats['total_ok'] += 1
                elif row.get('final') == 'NOK':
                    stats['total_nok'] += 1
                    if row.get('hwel_report') != row.get('hwel_set'): stats['nok_details']['HWEL'] += 1
                    if row.get('btld_report') != row.get('btld_set'): stats['nok_details']['BTLD'] += 1
                    if row.get('swfl_report') != row.get('swfl_set'): stats['nok_details']['SWFL'] += 1

        return jsonify(stats)
    except Exception as e:
        logging.error(f"Error calculating stats from CSV {csv_path}: {e}", exc_info=True)
        return jsonify({"error": str(e)}), 500


 
SMAC_TEMPLATE = { "documentVersion": "1.0", "comment": "", "testStepResults": [ { "step": 1, "description": "apiJob(\"F01\",\"STATUS_SVK_SMACS_CURRENT_FUNKTIONAL\",\"\",\"\")", "iterations": [ { "iteration": 1, "resultItems": [ { "name": "Set : 2", "type": "", "value": "", "resultItems": [ { "name": "SMAC_ID[0]", "type": "BINARY", "value": "00 51" }, { "name": "SGBM_ID[0][0]", "type": "TEXT", "value": "PLACEHOLDER_HWEL" }, { "name": "SGBM_ID[0][1]", "type": "TEXT", "value": "PLACEHOLDER_BTLD" }, { "name": "SGBM_ID[0][2]", "type": "TEXT", "value": "PLACEHOLDER_SWFL" }, { "name": "PROGRAMMING_DEPENDENCIES_CHECKED[0]", "type": "TEXT", "value": "0x01" }, { "name": "PROGRAMMING_DEPENDENCIES_CHECKED_TEXT[0]", "type": "TEXT", "value": "correct Result" } ] } ] } ] } ] }


 
def _convert_id_to_smac_format(original_id):
    if not original_id: return ""
    parts = original_id.split('_', 2)
    return f"{parts[0]}-{parts[1]}-{parts[2]}" if len(parts) == 3 else original_id


 
@app.route('/api/generate-smac-json', methods=['POST'])
def generate_smac_json():
    try:
        data = request.json
        smac_json = json.loads(json.dumps(SMAC_TEMPLATE))
        items_list = smac_json["testStepResults"][0]["iterations"][0]["resultItems"][0]["resultItems"]
        for item in items_list:
            if item["name"] == "SGBM_ID[0][0]": item["value"] = _convert_id_to_smac_format(data.get('hwelId', ''))
            elif item["name"] == "SGBM_ID[0][1]": item["value"] = _convert_id_to_smac_format(data.get('btldId', ''))
            elif item["name"] == "SGBM_ID[0][2]": item["value"] = _convert_id_to_smac_format(data.get('swflId', ''))
        logging.info(f"Generated SMAC JSON for HWEL: {data.get('hwelId', '')}")
        return jsonify(smac_json)
    except Exception as e:
        logging.error(f"Error generating SMAC JSON: {e}", exc_info=True)
        return jsonify({"error": "Failed to generate SMAC JSON"}), 500


 
@app.route('/api/factory-reset', methods=['POST'])
def factory_reset():
    logging.warning("=== FACTORY RESET TRIGGERED BY USER ===")
    try:
        csv_path_to_delete = None
        if CONFIG_FILE.exists():
            try:
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    config_data = json.load(f)
                    csv_path_to_delete = _get_csv_path(config_data)
            except Exception as e: logging.error(f"Error reading config for reset: {e}")
        with csv_lock:
            files_to_delete = [CONFIG_FILE, USER_DATA_DIR / 'watcher_state.json', PORT_FILE, MANUAL_SCAN_LOG_FILE] # Dodano log manualnych skanów
            if csv_path_to_delete and csv_path_to_delete.exists(): files_to_delete.append(csv_path_to_delete)
            for f in files_to_delete:
                try:
                    if f and f.exists(): os.remove(f); logging.info(f"[FactoryReset] Deleted: {f}")
                except Exception as e: logging.error(f"[FactoryReset] Failed to delete {f}: {e}")
        for log_file in LOG_DIR.glob('*'):
            if log_file.name != 'app.log':
                try: os.remove(log_file); logging.info(f"[FactoryReset] Deleted log: {log_file}")
                except Exception: pass
        logging.info("Factory reset complete. Awaiting app reload.")
        return jsonify({"success": True, "message": "Factory reset complete."})
    except Exception as e:
        logging.error(f"Critical error during factory reset: {e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500


 
@app.route('/api/status', methods=['GET'])
def get_status():
    """Endpoint do sprawdzania statusu i budzenia dysku sieciowego przez puls JS."""
    config = load_config_from_file()
    reports_folder_str = config.get('reportsFolder')
    settings_folder_str = config.get('settingsFolder')


    # Status 1: Czy ustawienia są krytyczne?
    if not reports_folder_str or not settings_folder_str:
        return jsonify({
            "status": "SETUP_REQUIRED",
            "message": "Reports/Settings paths missing in config.",
            "is_available": False,
            "reports_folder": reports_folder_str
        })


    # Status 2: Czy folder jest dostępny (wykonywany przez puls JS / ten request)
    reports_path = Path(reports_folder_str)
    try:
        is_available = reports_path.is_dir()
       
        if is_available:
            return jsonify({
                "status": "READY",
                "message": "All paths set and network share is active.",
                "is_available": True,
                "reports_folder": reports_folder_str
            })
        else:
            return jsonify({
                "status": "DISCONNECTED",
                "message": "Reports Folder not found (check network/share name).",
                "is_available": False,
                "reports_folder": reports_folder_str
            })
    except Exception as e:
        logging.warning(f"Status check failed to access reports folder: {e}")
        return jsonify({
            "status": "NETWORK_ERROR",
            "message": "Cannot access reports share (I/O error/Timeout).",
            "is_available": False,
            "reports_folder": reports_folder_str
        })


@app.route('/api/restart-watchdog', methods=['POST'])
def api_restart_watchdog():
    """Endpoint do ręcznego restartu watchdoga."""
    result = restart_watchdog()
    if result["success"]:
        return jsonify(result), 200
    else:
        return jsonify(result), 400


 
# === Watchdog Logic (bez zmian) ===


 
class ReportHandler(FileSystemEventHandler):


    def __init__(self, config_provider):
        self.config_provider = config_provider
        self.processed_folders = set()
        logging.info("[Watchdog] ReportHandler initialized (NON-recursive, Latest only).")


    def find_latest_report(self, dmc_folder):
        timestamp_folders = sorted(
            [
                d for d in dmc_folder.iterdir()
                if d.is_dir() and is_timestamp_folder(d.name)
            ],
            key=lambda p: p.name,
            reverse=True
        )


        if not timestamp_folders:
            logging.warning(f"[Watchdog Core] No valid timestamp folder found in {dmc_folder.name}.")
            return None


        latest_timestamp_folder = timestamp_folders[0]
        logging.info(f"[Watchdog Core] Found latest timestamp folder: {latest_timestamp_folder.name}")


        xml_files = list(latest_timestamp_folder.rglob("*.xml"))
        if not xml_files:
            logging.warning(f"[Watchdog Core] No XML file found in {latest_timestamp_folder.name}.")
            return None

      
        return xml_files[0]


 
    def process_folder(self, folder_path_str):
        folder_path = Path(folder_path_str)

      
        if folder_path_str in self.processed_folders:
            logging.info(f"[Watchdog Core] Folder {folder_path.name} already processed. Skipping.")
            return


        DELAY_SECONDS = 3
        logging.info(f"[Watchdog Core] Waiting {DELAY_SECONDS} seconds for file copy to complete...")
        time.sleep(DELAY_SECONDS)


        report_file_to_process = self.find_latest_report(folder_path)


        if not report_file_to_process:
            send_toast("Watchdog Error!", f"No latest report found in:", f"{folder_path.name}")
            return


        if not (report_file_to_process.exists() and report_file_to_process.stat().st_size > 0):
            logging.warning(f"[Watchdog Core] XML {report_file_to_process.name} is empty or inaccessible after delay. Skipping.")
            send_toast("Watchdog Error!", f"XML empty/inaccessible:", f"{report_file_to_process.name}")
            return

          
        logging.info(f"[Watchdog Core] Processing LATEST file: {report_file_to_process}")


        try:
            current_config = self.config_provider()
            threading.Thread(
                target=process_file_wrapper,
                args=(report_file_to_process, current_config, False),
                daemon=True
            ).start()
            self.processed_folders.add(folder_path_str)
        except Exception as e_proc:
            logging.error(f"[Watchdog Core] Error starting processing thread for {report_file_to_process}: {e_proc}", exc_info=True)


    def on_created(self, event):
        if not event.is_directory:
            return


        created_path = Path(event.src_path)

      
        config = self.config_provider()
        reports_folder = Path(config.get('reportsFolder', ''))

      
        if reports_folder and created_path.parent != reports_folder:
            return
         
        folder_path_str = str(created_path)

     
        logging.info(f"[Watchdog] New DMC folder detected: {created_path.name}. Starting delayed processing.")

     
        threading.Thread(target=self.process_folder, args=[folder_path_str], daemon=True).start()


 
def restart_watchdog():
    """Restartuje watchdoga z nową konfiguracją."""
    global watchdog_observer
    
    with watchdog_lock:
        # Zatrzymaj istniejący observer
        if watchdog_observer and watchdog_observer.is_alive():
            logging.info("[Watchdog Restart] Stopping existing observer...")
            watchdog_observer.stop()
            watchdog_observer.join(timeout=3)
            watchdog_observer = None
            logging.info("[Watchdog Restart] Stopped.")
        
        # Wczytaj nową konfigurację
        config = load_config_from_file()
        reports_folder_str = config.get('reportsFolder')
        
        # Sprawdź czy ścieżka jest poprawna
        if not reports_folder_str:
            logging.warning("[Watchdog Restart] No reportsFolder in config. Watchdog not started.")
            return {"success": False, "message": "reportsFolder not set"}
        
        reports_path = Path(reports_folder_str)
        if not reports_path.is_dir():
            logging.error(f"[Watchdog Restart] Path does not exist: {reports_folder_str}")
            return {"success": False, "message": f"Path does not exist: {reports_folder_str}"}
        
        # Uruchom nowego observera
        try:
            event_handler = ReportHandler(load_config_from_file)
            watchdog_observer = Observer()
            logging.info(f"[Watchdog Restart] Observer initialized: {type(watchdog_observer)}")
            watchdog_observer.schedule(event_handler, str(reports_path), recursive=False)
            watchdog_observer.start()
            
            logging.info(f"[Watchdog Restart] ✅ ACTIVE on folder: {reports_path}")
            send_toast(
                title="Watchdog RESTARTED!",
                line1=f"Now monitoring: {reports_path.name}",
                line2="Ready to process new reports"
            )
            return {"success": True, "message": f"Watchdog monitoring: {reports_folder_str}"}
        
        except Exception as e:
            logging.error(f"[Watchdog Restart] Failed to start: {e}", exc_info=True)
            return {"success": False, "message": str(e)}


# === Server Startup (Z pętlą sprawdzającą porty) ===


if __name__ == '__main__':
    INITIAL_PORT = 5001
    MAX_PORT_ATTEMPTS = 5
    ACTUAL_PORT = None

    # Przed startem usuń stary plik portu, żeby nie było pomyłek
    if PORT_FILE.exists():
        try:
            os.remove(PORT_FILE)
            logging.info("Cleaned up old port file.")
        except Exception as e:
            logging.warning(f"Failed to remove old port file: {e}")

    try:
        config = load_config_from_file()
        reports_folder_str = config.get('reportsFolder')
    
        # === AUTOMATYCZNE ZNAJDOWANIE PORTU I START FLASKA ===
        for i in range(MAX_PORT_ATTEMPTS):
            test_port = INITIAL_PORT + i
          
            # 1. Start Watchdoga (tylko raz, przy pierwszej udanej próbie, lub przed każdą próbą)
            if i == 0 or watchdog_observer is None:
                if reports_folder_str and Path(reports_folder_str).is_dir():
                    reports_folder = Path(reports_folder_str)
                    event_handler = ReportHandler(load_config_from_file)
                    watchdog_observer = Observer()
                    logging.info(f"[Startup] Observer initialized: {type(watchdog_observer)}")
                    watchdog_observer.schedule(event_handler, str(reports_folder), recursive=False)
                    watchdog_observer.start()
                  
                    if i == 0:
                         logging.info(f"=== WATCHDOG ACTIVE on folder: {reports_folder} (3s delay) ===")
                         send_toast(title="Watchdog ACTIVE", line1=f"Monitoring: {reports_folder}", line2="Mode: LATEST REPORT ONLY")
                elif i == 0:
                    logging.error("!!! WATCHDOG NOT STARTED: 'reportsFolder' not set or invalid !!!")

            try:
                logging.info(f"Step 4: Attempting to start Flask server on port: {test_port}")
              
                # ZAPIS PORTU DO PLIKU PRZED STARTEM (jeśli Flask go użyje)
                with open(PORT_FILE, 'w', encoding='utf-8') as f:
                    f.write(str(test_port))
                logging.info(f"Step 4a: Wrote tentative port ({test_port}) to {PORT_FILE.name}")

                ACTUAL_PORT = test_port
              
                # === AUTO-START BROWSER ===
                import webbrowser
                
                def open_browser():
                    """Opens browser after 5 second delay."""
                    time.sleep(5)
                    webbrowser.open(f'http://127.0.0.1:{ACTUAL_PORT}')
                    logging.info(f"Browser opened for http://127.0.0.1:{ACTUAL_PORT}")
                
                threading.Thread(target=open_browser, daemon=True).start()
                logging.info("Browser launch scheduled (5s delay)...")
                # === END AUTO-START ===
              
                # Próba startu Flask
                app.run(port=ACTUAL_PORT, debug=False, host='127.0.0.1', use_reloader=False, threaded=True)
              
                # Jeśli app.run() wystartuje, pętla zostaje przerwana
                break

            except OSError as e:
                # Błąd portu: 'Address already in use'
                if "Address already in use" in str(e):
                    logging.warning(f"Port {test_port} is busy. Trying next port...")
                    # Zatrzymanie Watchdoga, bo w przypadku błędu portu, jego wątki mogą się zawiesić.
                    if watchdog_observer and watchdog_observer.is_alive():
                        watchdog_observer.stop()
                        watchdog_observer.join()
                        watchdog_observer = None
                    if i == MAX_PORT_ATTEMPTS - 1:
                        logging.critical(f"Failed to find a free port after {MAX_PORT_ATTEMPTS} attempts.")
                        send_toast("CRITICAL ERROR", f"Failed to start server:", "Ports 5001-5005 busy.")
                        sys.exit()
                    continue
                else:
                    # Inny błąd - przerwij
                    raise e

    except Exception as e:
        logging.critical(f"=== CRITICAL FLASK STARTUP FAILURE: {e} ===", exc_info=True)

    finally:
        if watchdog_observer and watchdog_observer.is_alive():
            watchdog_observer.stop()
            watchdog_observer.join()
            logging.info("Watchdog stopped.")
