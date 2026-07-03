import os
import sys

# Ensure local imports work under portable embedded Python
root_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, root_dir)
sys.path.insert(0, os.path.join(root_dir, "core"))

import time
import socket
import threading
import webbrowser
from http.server import HTTPServer
from logger import cleanup_old_logs, add_log
from web_server import WebHandler

def find_free_port():
    """Find an available port dynamically"""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(('', 0))
    port = s.getsockname()[1]
    s.close()
    return port

if __name__ == "__main__":
    # Clean up old log files on start
    cleanup_old_logs()
    
    # Run the HTTP Web Server
    PORT = find_free_port()
    server_address = ('127.0.0.1', PORT)
    httpd = HTTPServer(server_address, WebHandler)
    
    # Write initial startup logs
    add_log(f"【服务器启动】本地 Web 服务器已在 127.0.0.1:{PORT} 开启")
    add_log("准备自动打开默认浏览器访问下载器控制台...")
    
    # Auto-open browser window after a tiny delay
    def open_browser():
        time.sleep(0.5)
        webbrowser.open(f"http://127.0.0.1:{PORT}/")
    
    threading.Thread(target=open_browser, daemon=True).start()
    
    try:
        # Blocks and keeps running
        httpd.serve_forever()
    except KeyboardInterrupt:
        add_log("【服务器关闭】正在关闭网络服务...")
        httpd.server_close()
