import os
import re
import time
import urllib.parse
import hashlib
import threading
import subprocess
from functools import reduce
from logger import add_log

def get_ffmpeg_details(custom_path):
    local_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if custom_path and custom_path.strip():
        # Check if it is a directory
        if os.path.isdir(custom_path):
            exe = os.path.join(custom_path, "ffmpeg.exe")
            if os.path.exists(exe):
                return exe, custom_path
            return "ffmpeg", custom_path
        # Check if it's the executable itself
        elif os.path.exists(custom_path):
            exe = custom_path
            if not exe.lower().endswith(".exe"):
                exe += ".exe"
            return exe, os.path.dirname(custom_path)
            
    # Fallback to local root or ffmpeg_env files
    env_ffmpeg = os.path.join(local_dir, "ffmpeg_env", "ffmpeg.exe")
    if os.path.exists(env_ffmpeg):
        return env_ffmpeg, os.path.dirname(env_ffmpeg)
        
    local_ffmpeg = os.path.join(local_dir, "ffmpeg.exe")
    if os.path.exists(local_ffmpeg):
        return local_ffmpeg, local_dir
        
    return "ffmpeg", None

# ==========================================
# Bilibili WBI Signature Algorithm
# ==========================================
MIXIN_KEY_ENC_TAB = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35,
    27, 43, 5, 49, 33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13,
    37, 48, 7, 16, 24, 55, 40, 61, 26, 17, 0, 1, 60, 51, 30, 4,
    22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11, 36, 20, 34, 44, 52
]

def get_mixin_key(orig: str):
    """Generate mixin key for WBI signature"""
    return reduce(lambda s, i: s + orig[i], MIXIN_KEY_ENC_TAB, '')[:32]

def enc_wbi(params: dict, img_key: str, sub_key: str):
    """Sign params with WBI"""
    mixin_key = get_mixin_key(img_key + sub_key)
    curr_time = round(time.time())
    params['wts'] = curr_time
    params = dict(sorted(params.items()))
    # Filter special chars
    params = {k: ''.join(filter(lambda chr: chr not in "!'()*", str(v))) for k, v in params.items()}
    query = urllib.parse.urlencode(params)
    wbi_sign = hashlib.md5((query + mixin_key).encode()).hexdigest()
    params['w_rid'] = wbi_sign
    return params

# ==========================================
# Downloader Core Engine Class
# ==========================================
class DownloaderEngine:
    def __init__(self):
        import requests
        self.http_session = requests.Session()
        self.http_session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://www.bilibili.com"
        })
        self.wbi_keys = None
        self.wbi_keys_expiry = 0
        self.download_in_progress = False
        self.active_task = ""
        
        # Task control states
        self.cancel_requested = False
        self.download_paused = False
        self.pause_event = threading.Event()
        self.pause_event.set()
        self.current_process = None

    def log_msg(self, message):
        add_log(message)

    def _prepare_raw_cookie_file(self, raw_cookie, domain, filename):
        if not raw_cookie:
            return None
        try:
            filepath = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs", filename)
            lines = ["# Netscape HTTP Cookie File\n"]
            cookie_str = raw_cookie.strip()
            if cookie_str.lower().startswith("cookie:"):
                cookie_str = cookie_str[7:].strip()
            parts = cookie_str.split(";")
            for part in parts:
                part = part.strip()
                if not part or "=" not in part:
                    continue
                name, val = part.split("=", 1)
                name = name.strip()
                val = val.strip()
                lines.append(f"{domain}\tTRUE\t/\tTRUE\t2000000000\t{name}\t{val}\n")
            os.makedirs(os.path.dirname(filepath), exist_ok=True)
            with open(filepath, "w", encoding="utf-8") as f:
                f.writelines(lines)
            return filepath
        except Exception as e:
            self.log_msg(f"⚠️ 解析与保存原始 Cookie 发生异常: {str(e)}")
            return None

    def _suspend_process(self, pid):
        try:
            import ctypes
            handle = ctypes.windll.kernel32.OpenProcess(0x0800, False, pid)
            if handle:
                ctypes.windll.ntdll.NtSuspendProcess(handle)
                ctypes.windll.kernel32.CloseHandle(handle)
                self.log_msg("⏸️ 【下载暂停】已暂停后台下载进程。")
        except Exception as e:
            self.log_msg(f"⚠️ 暂停进程失败: {str(e)}")

    def _resume_process(self, pid):
        try:
            import ctypes
            handle = ctypes.windll.kernel32.OpenProcess(0x0800, False, pid)
            if handle:
                ctypes.windll.ntdll.NtResumeProcess(handle)
                ctypes.windll.kernel32.CloseHandle(handle)
                self.log_msg("▶️ 【下载恢复】已恢复后台下载进程。")
        except Exception as e:
            self.log_msg(f"⚠️ 恢复进程失败: {str(e)}")

    def pause_task(self):
        if not self.download_in_progress:
            return
        if not self.download_paused:
            self.download_paused = True
            self.pause_event.clear()
            if self.current_process and self.current_process.poll() is None:
                self._suspend_process(self.current_process.pid)
            else:
                self.log_msg("⏸️ 【下载暂停】下载任务已暂停。")

    def resume_task(self):
        if not self.download_in_progress:
            return
        if self.download_paused:
            self.download_paused = False
            self.pause_event.set()
            if self.current_process and self.current_process.poll() is None:
                self._resume_process(self.current_process.pid)
            else:
                self.log_msg("▶️ 【下载恢复】下载任务已恢复。")

    def cancel_task(self):
        if not self.download_in_progress:
            return
        self.cancel_requested = True
        self.log_msg("🛑 【下载终止】正在请求终止当前下载任务...")
        
        # If paused, resume it so it can check cancel state and exit
        if self.download_paused:
            self.resume_task()
            
        if self.current_process and self.current_process.poll() is None:
            try:
                self.current_process.terminate()
                self.log_msg("🛑 【下载终止】已终止后台下载进程。")
            except Exception as e:
                self.log_msg(f"⚠️ 终止进程失败: {str(e)}")

    def get_wbi_img_keys(self):
        """Fetch img_key and sub_key from Bilibili for WBI signatures"""
        now = time.time()
        if self.wbi_keys and now < self.wbi_keys_expiry:
            return self.wbi_keys
            
        try:
            resp = self.http_session.get("https://api.bilibili.com/x/web-interface/nav", timeout=10)
            resp.raise_for_status()
            res_json = resp.json()
            if 'data' in res_json and 'wbi_img' in res_json['data']:
                wbi_img = res_json['data']['wbi_img']
                img_key = wbi_img['img_url'].split('/')[-1].split('.')[0]
                sub_key = wbi_img['sub_url'].split('/')[-1].split('.')[0]
                self.wbi_keys = (img_key, sub_key)
                self.wbi_keys_expiry = now + 86400  # cache 1 day
                return self.wbi_keys
        except Exception as e:
            self.log_msg(f"【WBI获取失败】未能获取B站签名密钥: {str(e)}")
        # Return fallback keys in case of failure
        return ("701a93c140c04a07858f3e2aa03fe0ae", "143003027cd440f3b4d6e41943c22974")

    def search_bilibili_api(self, keyword, proxy=None):
        if proxy:
            self.http_session.proxies = {"http": proxy, "https": proxy}
        else:
            self.http_session.proxies = {}
        img_key, sub_key = self.get_wbi_img_keys()
        params = {
            "search_type": "video",
            "keyword": keyword,
            "page": 1,
            "order": "totalrank",
            "tids": 0,
            "duration": 0
        }
        signed_params = enc_wbi(params, img_key, sub_key)
        url = "https://api.bilibili.com/x/web-interface/wbi/search/type"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://search.bilibili.com/all?keyword=" + urllib.parse.quote(keyword)
        }
        if not self.http_session.cookies:
            try: self.http_session.get("https://www.bilibili.com/", timeout=5)
            except: pass
            
        resp = self.http_session.get(url, params=signed_params, headers=headers, timeout=10)
        resp.raise_for_status()
        res_data = resp.json()
        if res_data.get('code') != 0:
            self.log_msg(f"【B站接口返回错误】代码 {res_data.get('code')}: {res_data.get('message')}")
            return []
            
        results = []
        data = res_data.get('data', {})
        if 'result' in data and isinstance(data['result'], list):
            for item in data['result']:
                title = re.sub(r'<[^>]+>', '', item.get('title', ''))
                bvid = item.get('bvid', '')
                author = item.get('author', '')
                duration = item.get('duration', '')
                link = f"https://www.bilibili.com/video/{bvid}"
                item_type = "分P/单视频" if ":" in duration else "视频"
                results.append({"title": title, "author": author, "type": item_type, "link": link})
        return results

    def search_netease_api(self, keyword, proxy=None):
        if proxy:
            self.http_session.proxies = {"http": proxy, "https": proxy}
        else:
            self.http_session.proxies = {}
        url = "http://music.163.com/api/search/get/web"
        params = {"s": keyword, "type": 1, "limit": 15, "offset": 0}
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "http://music.163.com/"
        }
        resp = self.http_session.get(url, params=params, headers=headers, timeout=10)
        resp.raise_for_status()
        res_data = resp.json()
        results = []
        if res_data.get('code') == 200 and 'result' in res_data:
            songs = res_data['result'].get('songs', [])
            for song in songs:
                title = song.get('name', '')
                artists = [art.get('name', '') for art in song.get('artists', [])]
                author = ", ".join(artists)
                song_id = song.get('id', '')
                link = f"https://music.163.com/#/song?id={song_id}"
                results.append({"title": title, "author": author, "type": "网易云歌曲", "link": link})
    def search_youtube(self, keyword, max_results=15, proxy=None):
        results = []
        temp_yt_search = None
        try:
            import json
            import subprocess
            
            query = f"ytsearch{max_results}:{keyword}"
            cmd = [
                "python", "-m", "yt_dlp",
                "--flat-playlist",
                "--dump-json",
                "--ignore-errors",
                "--no-warnings",
            ]
            if proxy:
                cmd.extend(["--proxy", proxy])
            
            # Prioritize raw YouTube cookie string
            from web_server import load_config
            raw_yt = load_config().get("cookie_yt_raw", "")
            if raw_yt:
                temp_yt_search = self._prepare_raw_cookie_file(raw_yt, ".youtube.com", "temp_yt_search.txt")
                if temp_yt_search:
                    cmd.extend(["--cookies", temp_yt_search])
            cmd.append(query)
            
            startupinfo = None
            if os.name == 'nt':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding='utf-8',
                errors='ignore',
                startupinfo=startupinfo
            )
            
            stdout, stderr = proc.communicate()
            
            for line in stdout.splitlines():
                if not line.strip():
                    continue
                try:
                    video_info = json.loads(line)
                    title = video_info.get("title", "")
                    url = video_info.get("url") or f"https://www.youtube.com/watch?v={video_info.get('id')}"
                    uploader = video_info.get("uploader") or video_info.get("channel", "Unknown")
                    results.append({
                        "title": title,
                        "author": uploader,
                        "type": "YouTube 视频",
                        "link": url
                    })
                except Exception as json_err:
                    pass
        except Exception as e:
            self.log_msg(f"【YouTube搜索失败】发生异常: {str(e)}")
        finally:
            if temp_yt_search and os.path.exists(temp_yt_search):
                try: os.remove(temp_yt_search)
                except: pass
            
        return results

    def download_bilibili_native(self, bvid, save_dir, format_sel, delay_max=10.0, proxy=None, ffmpeg_path=None, overwrite_existing=True):
        self.log_msg("开始调用 B站 自研极速接口进行下载与转换...")
        if proxy:
            self.http_session.proxies = {"http": proxy, "https": proxy}
        else:
            self.http_session.proxies = {}
        self.log_msg(f"【自定义下载】正在解析 B站视频 {bvid}...")
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/120.0.0.0',
            'Referer': 'https://www.bilibili.com/'
        }
        try:
            qn_value = 64
            # First prioritize raw Bilibili cookie string
            from web_server import load_config
            raw_bili = load_config().get("cookie_bili_raw", "")
            if raw_bili:
                try:
                    cookie_str = raw_bili.strip()
                    if cookie_str.lower().startswith("cookie:"):
                        cookie_str = cookie_str[7:].strip()
                    import http.cookies
                    simple_cookie = http.cookies.SimpleCookie()
                    simple_cookie.load(cookie_str)
                    for key, morsel in simple_cookie.items():
                        self.http_session.cookies.set(key, morsel.value, domain=".bilibili.com", path="/")
                    self.log_msg("🔑 【登录凭证】已成功加载粘贴的 B站 Cookie 凭证，为您申请最高音质流！")
                    qn_value = 116
                except Exception as err:
                    self.log_msg(f"⚠️ 【登录警告】解析粘贴的 B站 Cookie 失败: {str(err)}")
                    qn_value = 64
            else:
                self.log_msg("ℹ 【下载提示】当前为免登录游客模式，音质受限为标准品质。如需高音质，请在配置参数中粘贴您的 B站 Cookie 凭证。")

            view_url = f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}"
            resp = self.http_session.get(view_url, headers=headers, timeout=10)
            resp.raise_for_status()
            view_data = resp.json()
            if view_data.get("code") != 0:
                self.log_msg(f"❌ B站视频信息获取失败: {view_data.get('message')}")
                return False
                
            title = view_data["data"]["title"]
            clean_title = "".join(c for c in title if c not in r'\/:*?"<>|').strip()
            pages = view_data["data"].get("pages", [])
            
            self.log_msg(f"🎬 视频标题: {title}")
            self.log_msg(f"📦 共检测到 {len(pages)} 个分P任务。")
            
            img_key, sub_key = self.get_wbi_img_keys()
            target_dir = save_dir
            if len(pages) > 1:
                target_dir = os.path.join(save_dir, clean_title)
                os.makedirs(target_dir, exist_ok=True)
                
            for idx, p in enumerate(pages):
                if self.cancel_requested:
                    self.log_msg("🛑 【下载终止】用户已终止任务。正在退出列表下载...")
                    break
                    
                page_num = p["page"]
                cid = p["cid"]
                part_title = p["part"]
                clean_part_title = "".join(c for c in part_title if c not in r'\/:*?"<>|').strip()
                
                if len(pages) > 1:
                    filename = f"{page_num:02d} - {clean_part_title}"
                else:
                    filename = clean_title
                    
                audio_format = "mp3"
                if "FLAC" in format_sel:
                    audio_format = "flac"
                elif "M4A" in format_sel:
                    audio_format = "m4a"
                target_file = os.path.join(target_dir, f"{filename}.{audio_format}")
                if not overwrite_existing and os.path.exists(target_file):
                    self.log_msg(f"  ✨ [已存在] {filename}.{audio_format} 已存在，跳过下载。")
                    continue
                    
                if idx > 0:
                    import random
                    sleep_time = random.uniform(5.0, delay_max)
                    self.log_msg(f"⏱️ 防风控策略：等待 {sleep_time:.1f} 秒...")
                    
                    # Wait in small increments to remain responsive to cancel/pause
                    waited = 0
                    while waited < sleep_time:
                        self.pause_event.wait()
                        if self.cancel_requested:
                            break
                        time.sleep(0.5)
                        waited += 0.5
                        
                    if self.cancel_requested:
                        self.log_msg("🛑 【下载终止】用户已终止任务。正在退出...")
                        break
                    
                self.log_msg(f"🚀 [正在下载 {page_num}/{len(pages)}] {part_title}")
                temp_file = os.path.join(target_dir, f"temp_{bvid}_{cid}.m4s")
                try:
                    playurl_raw = "https://api.bilibili.com/x/player/wbi/playurl"
                    params = {
                        'bvid': bvid,
                        'cid': cid,
                        'qn': qn_value,
                        'fnval': 16,
                        'fnver': 0,
                        'fourk': 1
                    }
                    signed_params = enc_wbi(params, img_key, sub_key)
                    
                    self.pause_event.wait()
                    if self.cancel_requested:
                        raise Exception("Task cancelled by user")
                        
                    play_resp = self.http_session.get(playurl_raw, params=signed_params, headers=headers, timeout=10)
                    play_resp.raise_for_status()
                    play_data = play_resp.json()
                    
                    if play_data.get("code") != 0:
                        self.log_msg(f"  ⚠️ 分P {page_num} 链接获取失败: {play_data.get('message')}，已跳过。")
                        continue
                        
                    dash_data = play_data.get("data", {}).get("dash", {})
                    audio_list = dash_data.get("audio", [])
                    if not audio_list:
                        self.log_msg("  ⚠️ 未找到音频流，已跳过。")
                        continue
                        
                    best_audio = audio_list[0]
                    audio_url = best_audio.get("base_url") or best_audio.get("backup_url", [None])[0]
                    if not audio_url:
                        self.log_msg("  ⚠️ 音频 URL 为空，已跳过。")
                        continue
                        
                    dl_headers = {
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                        'Referer': f'https://www.bilibili.com/video/{bvid}/',
                        'Range': 'bytes=0-'
                    }
                    
                    download_success = False
                    for attempt in range(3):
                        if self.cancel_requested:
                            break
                        if os.path.exists(temp_file):
                            try: os.remove(temp_file)
                            except: pass
                        try:
                            if attempt > 0:
                                self.log_msg(f"  🔄 正在重试下载 (第 {attempt+1}/3 次尝试)...")
                            
                            with self.http_session.get(audio_url, headers=dl_headers, stream=True, timeout=30) as dl_resp:
                                dl_resp.raise_for_status()
                                total_size = int(dl_resp.headers.get('content-length', 0))
                                downloaded = 0
                                
                                with open(temp_file, "wb") as f:
                                    for chunk in dl_resp.iter_content(chunk_size=32768):
                                        self.pause_event.wait()
                                        if self.cancel_requested:
                                            break
                                        if chunk:
                                            f.write(chunk)
                                            downloaded += len(chunk)
                                            if total_size > 0:
                                                percent = downloaded * 100 / total_size
                                                if downloaded % (1024 * 1024) < 32768 or percent >= 100:
                                                    self.log_msg(f"   [下载进度] {percent:.1f}% ({downloaded / (1024*1024):.2f}MB / {total_size / (1024*1024):.2f}MB)")
                                                    
                            if self.cancel_requested:
                                raise Exception("Task cancelled by user")
                            download_success = True
                            break
                        except Exception as e_dl:
                            if self.cancel_requested:
                                raise e_dl
                            self.log_msg(f"  ⚠️ 尝试 {attempt+1}/3 失败: {str(e_dl)}")
                            time.sleep(2)
                            
                    if self.cancel_requested:
                        raise Exception("Task cancelled by user")
                        
                    if not download_success:
                        self.log_msg(f"  ❌ 歌曲 {part_title} 经历 3 次尝试均下载失败，跳过此曲。")
                        continue
                        
                    audio_format = "mp3"
                    if "FLAC" in format_sel:
                        audio_format = "flac"
                    elif "M4A" in format_sel:
                        audio_format = "m4a"
                        
                    target_file = os.path.join(target_dir, f"{filename}.{audio_format}")
                    if os.path.exists(target_file):
                        try: os.remove(target_file)
                        except: pass
                        
                    ffmpeg_exe, _ = get_ffmpeg_details(ffmpeg_path)
                    if audio_format == "mp3":
                        cmd = [ffmpeg_exe, "-y", "-i", temp_file, "-vn", "-ar", "44100", "-ac", "2", "-b:a", "320k", target_file]
                    elif audio_format == "flac":
                        cmd = [ffmpeg_exe, "-y", "-i", temp_file, "-vn", target_file]
                    else:
                        cmd = [ffmpeg_exe, "-y", "-i", temp_file, "-vn", "-acodec", "copy", target_file]
                        
                    self.pause_event.wait()
                    if self.cancel_requested:
                        raise Exception("Task cancelled by user")
                        
                    self.current_process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                    stdout, stderr = self.current_process.communicate()
                    returncode = self.current_process.returncode
                    self.current_process = None
                    
                    if os.path.exists(temp_file):
                        try: os.remove(temp_file)
                        except: pass
                        
                    if returncode == 0:
                        self.log_msg(f"  ✨ [转换完成] 成功保存为 {filename}.{audio_format}")
                    else:
                        if self.cancel_requested:
                            raise Exception("Task cancelled by user")
                        self.log_msg(f"  ❌ FFmpeg 转换失败: {stderr.decode('utf-8', errors='ignore')}")
                except Exception as e_page:
                    if self.cancel_requested:
                        self.log_msg("🛑 【下载终止】任务已中止，正在清理临时文件并退出...")
                    else:
                        self.log_msg(f"  ⚠️ 处理此分P {part_title} 时发生未知错误: {str(e_page)}，已自动跳过。")
                    if os.path.exists(temp_file):
                        try: os.remove(temp_file)
                        except: pass
                    if self.cancel_requested:
                        break
                    continue
                    
            self.log_msg("🎉 【任务成功】自定义解析下载完成！")
            return True
            
        except Exception as e:
            self.log_msg(f"【任务异常】自定义解析出错: {str(e)}")
            return False

    def run_download_thread(self, link, save_dir, format_sel, delay_max=10.0, proxy=None, ffmpeg_path=None, overwrite_existing=True):
        self.download_in_progress = True
        self.active_task = link
        self.cancel_requested = False
        self.download_paused = False
        self.pause_event.set()
        self.current_process = None
        
        # Load raw cookies and prepare temp cookie files
        from web_server import load_config
        config = load_config()
        raw_bili = config.get("cookie_bili_raw", "")
        raw_yt = config.get("cookie_yt_raw", "")
        
        self.cookie_file_bili = self._prepare_raw_cookie_file(raw_bili, ".bilibili.com", "temp_bili_cookies.txt")
        self.cookie_file_yt = self._prepare_raw_cookie_file(raw_yt, ".youtube.com", "temp_yt_cookies.txt")
        
        try:
            bv_match = re.search(r"BV[a-zA-Z0-9]{10}", link)
            if bv_match:
                bvid = bv_match.group(0)
                self.download_bilibili_native(bvid, save_dir, format_sel, delay_max=delay_max, proxy=proxy, ffmpeg_path=ffmpeg_path, overwrite_existing=overwrite_existing)
                return
                
            audio_format = "mp3"
            audio_quality = "320K"
            if "FLAC" in format_sel:
                audio_format = "flac"
                audio_quality = "0"
            elif "M4A" in format_sel:
                audio_format = "m4a"
                audio_quality = "128K"
                
            out_template = os.path.join(save_dir, "%(title)s.%(ext)s")
            if "playlist" in link.lower() or "video/BV" in link or "/p/" in link or "?p=" in link:
                out_template = os.path.join(save_dir, "%(playlist_title,title)s", "%(playlist_index&{:02d} - |)s%(title)s.%(ext)s")
                
            cmd = [
                "python", "-m", "yt_dlp",
                "--ignore-errors",
                "--sleep-interval", "5",
                "--max-sleep-interval", str(delay_max),
                "--no-mtime",
                "--extract-audio",
                "--audio-format", audio_format,
                "--audio-quality", audio_quality,
                "--user-agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "--add-header", "Referer:https://www.bilibili.com/",
                "-o", out_template,
                link
            ]
            
            if overwrite_existing:
                cmd.insert(-1, "--force-overwrites")
            else:
                cmd.insert(-1, "--no-overwrites")
            
            # Prioritize raw cookie files if they exist
            is_yt_link = "youtube.com" in link or "youtu.be" in link
            if is_yt_link:
                if hasattr(self, "cookie_file_yt") and self.cookie_file_yt:
                    cmd.insert(-1, "--cookies")
                    cmd.insert(-1, self.cookie_file_yt)
            else:
                if hasattr(self, "cookie_file_bili") and self.cookie_file_bili:
                    cmd.insert(-1, "--cookies")
                    cmd.insert(-1, self.cookie_file_bili)
                
            if proxy:
                cmd.insert(-1, "--proxy")
                cmd.insert(-1, proxy)
                
            _, ffmpeg_dir = get_ffmpeg_details(ffmpeg_path)
            if ffmpeg_dir:
                cmd.insert(-1, "--ffmpeg-location")
                cmd.insert(-1, ffmpeg_dir)
            
            self.log_msg(f"【执行命令】: {' '.join(cmd)}")
            self.log_msg("正在调起 yt-dlp 与 ffmpeg 进行下载与转码，请稍候...")
            
            if self.cancel_requested:
                raise Exception("Task cancelled by user")
                
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                shell=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1
            )
            self.current_process = process
            
            while True:
                if self.cancel_requested:
                    self.log_msg("🛑 【下载终止】用户已终止任务。正在关闭进程...")
                    try:
                        process.terminate()
                    except:
                        pass
                    break
                    
                line = process.stdout.readline()
                if not line:
                    break
                line_str = line.strip()
                if line_str:
                    if "[download]" in line_str and "%" in line_str:
                        self.log_msg(f" [下载进度] {line_str}")
                    elif "[ExtractAudio]" in line_str:
                        self.log_msg(f" [提取音频] {line_str}")
                    elif "[ffmpeg]" in line_str:
                        self.log_msg(f" [音频转码] {line_str}")
                    elif "ERROR:" in line_str or "error" in line_str.lower():
                        self.log_msg(f" ⚠️ [错误信息] {line_str}")
                    elif "[info]" in line_str:
                        self.log_msg(f" [媒体信息] {line_str}")
                    else:
                        if not any(x in line_str for x in ["frag", "ETA", "has already been downloaded"]):
                            self.log_msg(f" > {line_str}")
                            
            process.wait()
            if self.cancel_requested:
                self.log_msg("🛑 【下载终止】处理进程被用户手动终止退出。")
            elif process.returncode == 0:
                self.log_msg("🎉 【任务成功】所有选中音视频提取转换完毕！")
            else:
                self.log_msg(f"❌ 【任务失败】处理进程退出，代码 {process.returncode}")
                if "bilibili" in link.lower() or "b23.tv" in link.lower():
                    self.log_msg("💡 【B站下载贴心提示】如果日志中出现大量的 412 错误，说明您的 IP 触发了下载限制。请尝试在“Cookie来源”中选择您已登录 B站的浏览器。若提示数据库锁定，请在点击下载前暂时关闭该浏览器。")
        except Exception as e:
            if self.cancel_requested:
                self.log_msg("🛑 【下载终止】任务已中止，退出运行。")
            else:
                self.log_msg(f"【任务异常】出现错误: {str(e)}")
        finally:
            self.download_in_progress = False
            self.active_task = ""
            self.cancel_requested = False
            self.download_paused = False
            self.pause_event.set()
            self.current_process = None
            # Clean up temp cookie files
            for attr in ["cookie_file_bili", "cookie_file_yt"]:
                if hasattr(self, attr):
                    fpath = getattr(self, attr)
                    if fpath and os.path.exists(fpath):
                        try: os.remove(fpath)
                        except: pass
                    setattr(self, attr, None)

# Global shared instance of downloader
engine = DownloaderEngine()
