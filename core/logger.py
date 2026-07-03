import os
import time
import threading

# Paths
APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOGS_DIR = os.path.join(APP_DIR, "logs")
DEFAULT_DOWNLOAD_DIR = os.path.join(APP_DIR, "download")

# Ensure required directories exist
os.makedirs(LOGS_DIR, exist_ok=True)
os.makedirs(DEFAULT_DOWNLOAD_DIR, exist_ok=True)

# In-memory log queue
LOG_QUEUE = []
LOG_LOCK = threading.Lock()

def add_log(message):
    """Append a message to the logging queue and write to file"""
    timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
    log_line = f"[{timestamp}] {message}"
    
    # Print to CMD console
    try:
        print(log_line, flush=True)
    except Exception:
        try:
            import sys
            encoding = sys.stdout.encoding or 'utf-8'
            clean_line = log_line.encode(encoding, errors='replace').decode(encoding)
            print(clean_line, flush=True)
        except Exception:
            pass
    
    # Write to daily log file
    try:
        log_filename = f"downloader_{time.strftime('%Y-%m-%d')}.log"
        log_filepath = os.path.join(LOGS_DIR, log_filename)
        with open(log_filepath, "a", encoding="utf-8") as f:
            f.write(log_line + "\n")
    except Exception:
        pass
        
    # Add to log queue (limit size to prevent memory bloat)
    with LOG_LOCK:
        LOG_QUEUE.append(log_line)
        if len(LOG_QUEUE) > 1000:
            LOG_QUEUE.pop(0)

def get_new_logs():
    """Retrieve and clear all accumulated logs in the queue"""
    global LOG_QUEUE
    with LOG_LOCK:
        logs = list(LOG_QUEUE)
        LOG_QUEUE.clear()
    return logs

def cleanup_old_logs():
    """Delete log files older than 3 days"""
    try:
        now = time.time()
        three_days_ago = now - 3 * 86400  # 3 days in seconds
        for filename in os.listdir(LOGS_DIR):
            if filename.startswith("downloader_") and filename.endswith(".log"):
                filepath = os.path.join(LOGS_DIR, filename)
                if os.path.getmtime(filepath) < three_days_ago:
                    os.remove(filepath)
    except Exception:
        pass
