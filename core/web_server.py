import os
import json
import urllib.parse
import threading
import subprocess
from http.server import BaseHTTPRequestHandler, HTTPServer
from logger import add_log, get_new_logs, APP_DIR, DEFAULT_DOWNLOAD_DIR
from downloader_engine import engine, get_ffmpeg_details

CONFIG_FILE = os.path.join(APP_DIR, "config.jsonc")

def load_config():
    default_config = {
        "python_path": "",
        "ffmpeg_path": "",
        "save_dir": DEFAULT_DOWNLOAD_DIR,
        "format": "MP3 (320kbps)",
        "overwrite_existing": True,
        "theme": "dark",
        "lang": "zh",
        "proxy_enable": False,
        "proxy": "http://127.0.0.1:7890",
        "cookie_bili_raw": "",
        "cookie_yt_raw": "",
        "delay_max_bili": 10,
        "delay_max_yt": 10
    }
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                content = f.read()
            # Strip comments
            lines = content.splitlines()
            clean_lines = []
            for line in lines:
                idx = line.find("//")
                while idx != -1:
                    if idx > 0 and line[idx-1] == ':':
                        idx = line.find("//", idx + 2)
                    else:
                        line = line[:idx]
                        break
                clean_lines.append(line)
            data = json.loads("\n".join(clean_lines))
            for k, v in data.items():
                default_config[k] = v
        except Exception as e:
            add_log(f"【系统错误】解析 config.jsonc 失败: {str(e)}")
    return default_config

def save_config(config_data):
    try:
        content = f"""{{
    // =========================================================================
    // 软件核心运行路径配置 (Software Core Paths Configuration)
    // =========================================================================
    
    // 自定义 Python 解释器可执行文件路径。
    // 留空 "" 则自动探测同级目录下的 venv、python_env 或系统全局 Python 环境。
    // (Custom Python interpreter path. Leave empty "" for auto-detection).
    "python_path": {json.dumps(config_data.get('python_path', ''))},

    // 自定义 FFmpeg 目录或可执行文件路径（例如 "C:\\\\tools\\\\ffmpeg" 或 "C:\\\\tools\\\\ffmpeg.exe"）。
    // 留空 "" 则自动使用软件根目录下的 ffmpeg.exe 与 ffprobe.exe。
    // (Custom FFmpeg path. Leave empty "" to use local ffmpeg.exe).
    "ffmpeg_path": {json.dumps(config_data.get('ffmpeg_path', ''))},

    // =========================================================================
    // 下载与保存选项 (Download and Save Options)
    // =========================================================================
    
    // 音频文件保存目录路径。
    // (Directory path where downloaded audio files will be saved).
    "save_dir": {json.dumps(config_data.get('save_dir', DEFAULT_DOWNLOAD_DIR))},

    // 默认提取输出格式。支持："MP3 (320kbps)"、"FLAC (无损)"、"M4A (原音质)"。
    // (Default audio extraction output format).
    "format": "{config_data.get('format', 'MP3 (320kbps)')}",

    // 已存在同名音频文件时的处理方式 (true 表示覆盖重新下载，false 表示跳过)。
    // (Action when output file already exists: true to overwrite, false to skip).
    "overwrite_existing": {str(config_data.get('overwrite_existing', True)).lower()},

    // =========================================================================
    // 界面与语言设置 (UI Theme and Language Options)
    // =========================================================================
    
    // 界面视觉主题。支持："dark" (深邃暗黑) 或 "light" (极简明亮)。
    // (Visual layout theme: "dark" or "light").
    "theme": "{config_data.get('theme', 'dark')}",

    // 默认显示语言。支持："zh" (简体中文) 或 "en" (English)。
    // (Interface language: "zh" or "en").
    "lang": "{config_data.get('lang', 'zh')}",

    // =========================================================================
    // 网络代理设置 (Network Proxy Options)
    // =========================================================================
    
    // 是否启用网络代理 (true / false)。
    // (Toggle switch to enable/disable network proxy).
    "proxy_enable": {str(config_data.get('proxy_enable', False)).lower()},

    // 代理连接服务器地址。支持 HTTP, HTTPS 或 SOCKS5（默认推荐 http://127.0.0.1:7890）。
    // (Proxy server address. Supports HTTP, HTTPS, or SOCKS5).
    "proxy": "{config_data.get('proxy', 'http://127.0.0.1:7890')}",

    // =========================================================================
    // 账号授权 Cookie (B站/YouTube 独立配置)
    // =========================================================================
    
    // 粘贴的 B站 Cookie 原始字符串。
    // (Pasted raw Cookie string for Bilibili).
    "cookie_bili_raw": {json.dumps(config_data.get('cookie_bili_raw', ''))},

    // 粘贴的 YouTube Cookie 原始字符串。
    // (Pasted raw Cookie string for YouTube).
    "cookie_yt_raw": {json.dumps(config_data.get('cookie_yt_raw', ''))},

    // =========================================================================
    // 分P防风控随机延时上限（单位：秒，最低为 6）
    // =========================================================================
    
    // B站批量下载多分P时的防风控随机延时最大秒数上限。
    // (Bilibili maximum randomized sleep interval in seconds, minimum 6).
    "delay_max_bili": {config_data.get('delay_max_bili', 10)},

    // YouTube下载歌单/批量任务时的防风控随机延时最大秒数上限。
    // (YouTube maximum randomized sleep interval in seconds, minimum 6).
    "delay_max_yt": {config_data.get('delay_max_yt', 10)}
}}"""
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            f.write(content)
        return True
    except Exception as e:
        add_log(f"【系统错误】保存 config.jsonc 失败: {str(e)}")
        return False

# ==========================================
# Web HTTP Server Routing Handler
# ==========================================
class WebHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Suppress logging HTTP requests in the console to avoid cluttering logs
        pass

    def do_GET(self):
        parsed_url = urllib.parse.urlparse(self.path)
        path = parsed_url.path
        query = urllib.parse.parse_qs(parsed_url.query)
        
        if path == "/":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            try:
                html_path = os.path.join(APP_DIR, "index.html")
                with open(html_path, "r", encoding="utf-8") as f:
                    content = f.read()
                self.wfile.write(content.encode('utf-8'))
            except Exception as e:
                self.wfile.write(f"Error loading index.html: {str(e)}".encode('utf-8'))
            
        elif path == "/api/config":
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            config_data = load_config()
            config_data["default_dir"] = config_data["save_dir"]
            self.wfile.write(json.dumps(config_data).encode('utf-8'))
            
        elif path == "/api/browse":
            # Pop up native askdirectory dialog using powershell without tkinter dependency
            selected_dir = ""
            try:
                ps_cmd = (
                    "[System.Reflection.Assembly]::LoadWithPartialName('System.windows.forms') | Out-Null;"
                    "$dialog = New-Object System.Windows.Forms.FolderBrowserDialog;"
                    "$dialog.Description = '请选择音频保存目录 (Select Audio Save Directory)';"
                    "$dialog.ShowNewFolderButton = $true;"
                    "if ($dialog.ShowDialog() -eq 'OK') { $dialog.SelectedPath }"
                )
                startupinfo = None
                if os.name == 'nt':
                    startupinfo = subprocess.STARTUPINFO()
                    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                
                proc = subprocess.Popen(
                    ["powershell", "-Command", ps_cmd],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    startupinfo=startupinfo
                )
                stdout, stderr = proc.communicate()
                d = stdout.strip()
                if d and os.path.exists(d):
                    selected_dir = os.path.abspath(d)
            except Exception as e:
                add_log(f"【浏览目录失败】无法调起系统文件夹选取器: {str(e)}")
                
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps({"path": selected_dir}).encode('utf-8'))
            
        elif path == "/api/search":
            platform = query.get("platform", ["Bilibili"])[0]
            keyword = query.get("keyword", [""])[0]
            proxy = query.get("proxy", [""])[0]
            results = []
            error_msg = ""
            
            if keyword.strip():
                try:
                    add_log(f"【搜索启动】正在从 {platform} 检索: '{keyword}'...")
                    if platform == "Bilibili":
                        results = engine.search_bilibili_api(keyword, proxy=proxy)
                    elif platform == "YouTube":
                        results = engine.search_youtube(keyword, proxy=proxy)
                    else:
                        results = engine.search_netease_api(keyword, proxy=proxy)
                    add_log(f"【搜索完毕】成功检索到 {len(results)} 条记录。")
                except Exception as e:
                    error_msg = str(e)
                    add_log(f"【搜索出错】发生异常: {error_msg}")
                    
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps({"results": results, "error": error_msg}).encode('utf-8'))
            
        elif path == "/api/logs":
            logs = get_new_logs()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps({"logs": logs}).encode('utf-8'))
            
        elif path == "/api/status":
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            status_data = {
                "in_progress": engine.download_in_progress,
                "paused": engine.download_paused,
                "active_task": engine.active_task
            }
            self.wfile.write(json.dumps(status_data).encode('utf-8'))
            
        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Not Found")

    def do_POST(self):
        parsed_url = urllib.parse.urlparse(self.path)
        path = parsed_url.path
        
        if path == "/api/download":
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length)
            params = json.loads(post_data.decode('utf-8'))
            
            link = params.get("link", "").strip()
            save_dir = params.get("save_dir", "").strip() or DEFAULT_DOWNLOAD_DIR
            format_sel = params.get("format", "MP3 (320kbps)")
            delay_max = params.get("delay_max", 10)
            proxy = params.get("proxy", "").strip()
            try:
                delay_max = float(delay_max)
                if delay_max < 6.0:
                    delay_max = 6.0
            except Exception:
                delay_max = 10.0
            
            if not link:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(json.dumps({"error": "请输入有效的目标链接！"}).encode('utf-8'))
                return
                
            if engine.download_in_progress:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(json.dumps({"error": "当前有下载任务正在进行中，请耐心等待！"}).encode('utf-8'))
                return
                
            # Create directories if not exists
            try:
                os.makedirs(save_dir, exist_ok=True)
            except Exception as e:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(json.dumps({"error": f"无法创建保存目录: {str(e)}"}).encode('utf-8'))
                return
                
            config_data = load_config()
            ffmpeg_path = config_data.get("ffmpeg_path", "")
            overwrite_existing = config_data.get("overwrite_existing", True)
            
            overwrite_text = "覆盖重新下载" if overwrite_existing else "跳过忽略"
            add_log("-" * 50)
            add_log(f"【任务启动】正在解析并提取目标: {link}")
            add_log(f"【配置信息】保存格式: {format_sel} | 保存位置: {save_dir} | 同名处理: {overwrite_text} | 防风控随机延时: 5.0s - {delay_max:.1f}s")
            if proxy:
                add_log(f"【网络代理】已启用代理: {proxy}")
            # Spawn download in separate daemon thread
            threading.Thread(
                target=engine.run_download_thread,
                args=(link, save_dir, format_sel, delay_max, proxy, ffmpeg_path, overwrite_existing),
                daemon=True
            ).start()
            
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "started"}).encode('utf-8'))
        elif path == "/api/pause":
            engine.pause_task()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "paused"}).encode('utf-8'))
            
        elif path == "/api/resume":
            engine.resume_task()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "resumed"}).encode('utf-8'))
            
        elif path == "/api/cancel":
            engine.cancel_task()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "cancelled"}).encode('utf-8'))
            
        elif path == "/api/open_browser_login":
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length)
            params = json.loads(post_data.decode('utf-8'))
            browser = params.get("browser", "无 (None)").lower()
            platform = params.get("platform", "bilibili").lower()
            
            success = False
            error_msg = ""
            
            if browser in ["edge", "chrome", "firefox"]:
                import winreg
                url = "https://www.youtube.com" if platform == "youtube" else "https://www.bilibili.com"
                
                try:
                    if browser == "edge":
                        edge_prefix = "microsoft-edge:"
                        subprocess.Popen(f'cmd /c start {edge_prefix}{url}', shell=True)
                        success = True
                    else:
                        browser_exe = "chrome.exe" if browser == "chrome" else "firefox.exe"
                        try:
                            # Try simple cmd start first
                            subprocess.Popen(f'cmd /c start {browser} "{url}"', shell=True)
                            success = True
                        except Exception:
                            # Fallback registry lookup
                            found = False
                            for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                                try:
                                    key_path = f"SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\App Paths\\{browser_exe}"
                                    with winreg.OpenKey(hive, key_path) as key:
                                        path_val, _ = winreg.QueryValueEx(key, "")
                                        subprocess.Popen([path_val, url])
                                        success = True
                                        found = True
                                        break
                                except Exception:
                                    continue
                            if not found:
                                raise Exception(f"未在系统注册表中找到 {browser} 的安装路径")
                except Exception as e:
                    error_msg = str(e)
            else:
                error_msg = "不支持的浏览器或未选择浏览器"
                
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps({"success": success, "error": error_msg}).encode('utf-8'))
            
        elif path == "/api/config":
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length)
            params = json.loads(post_data.decode('utf-8'))
            
            config_data = load_config()
            for k in config_data.keys():
                if k in params:
                    config_data[k] = params[k]
                    
            success = save_config(config_data)
            
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps({"success": success}).encode('utf-8'))
            
        elif path == "/api/verify_python":
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length)
            params = json.loads(post_data.decode('utf-8'))
            py_path = params.get("python_path", "").strip()
            
            success = False
            version_str = ""
            error_msg = ""
            resolved_path = ""
            
            if py_path:
                if not os.path.exists(py_path):
                    error_msg = f"指定的 Python 路径不存在: {py_path}"
                else:
                    resolved_path = py_path
            else:
                import sys
                resolved_path = sys.executable
                
            if not error_msg:
                try:
                    proc = subprocess.Popen([resolved_path, "--version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                    stdout, stderr = proc.communicate()
                    if proc.returncode == 0:
                        success = True
                        version_str = stdout.strip() or stderr.strip() or "Python 3.x"
                    else:
                        error_msg = f"错误代码 {proc.returncode}: {stderr.strip()}"
                except Exception as e:
                    error_msg = str(e)
                    
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps({
                "success": success,
                "version": version_str,
                "path": resolved_path,
                "error": error_msg
            }).encode('utf-8'))
            
        elif path == "/api/verify_ffmpeg":
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length)
            params = json.loads(post_data.decode('utf-8'))
            ff_path = params.get("ffmpeg_path", "").strip()
            
            success = False
            version_str = ""
            error_msg = ""
            resolved_exe = ""
            
            if ff_path:
                if os.path.isdir(ff_path):
                    exe_path = os.path.join(ff_path, "ffmpeg.exe")
                    if os.path.exists(exe_path):
                        resolved_exe = exe_path
                    else:
                        error_msg = f"指定的目录中未找到 ffmpeg.exe: {ff_path}"
                elif os.path.exists(ff_path):
                    resolved_exe = ff_path
                else:
                    if os.path.exists(ff_path + ".exe"):
                        resolved_exe = ff_path + ".exe"
                    else:
                        error_msg = f"指定的 FFmpeg 路径不存在: {ff_path}"
            else:
                resolved_exe, _ = get_ffmpeg_details("")
                
            if not error_msg:
                try:
                    proc = subprocess.Popen([resolved_exe, "-version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                    stdout, stderr = proc.communicate()
                    if proc.returncode == 0:
                        success = True
                        lines = stdout.splitlines()
                        version_str = lines[0].strip() if lines else "ffmpeg version unknown"
                    else:
                        error_msg = f"错误代码 {proc.returncode}: {stderr.strip()}"
                except Exception as e:
                    error_msg = str(e)
                    
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps({
                "success": success,
                "version": version_str,
                "path": resolved_exe,
                "error": error_msg
            }).encode('utf-8'))
            
        elif path == "/api/init_env":
            from env_init import start_init_environment
            success = start_init_environment(APP_DIR)
            
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps({"success": success}).encode('utf-8'))
            
        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Not Found")
