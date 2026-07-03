import os
import sys
import shutil
import urllib.request
import zipfile
import subprocess
import threading
from logger import add_log

INIT_IN_PROGRESS = False
INIT_LOCK = threading.Lock()

def download_file(url, filepath, label="文件"):
    add_log(f"📥 正在下载 {label}...")
    add_log(f"   来源: {url}")
    
    try:
        import ssl
        ctx = ssl._create_unverified_context()
        req = urllib.request.Request(
            url, 
            headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
        )
        with urllib.request.urlopen(req, context=ctx, timeout=60) as response, open(filepath, 'wb') as out_file:
            meta = response.info()
            file_size = int(meta.get("Content-Length", 0))
            downloaded = 0
            block_size = 1024 * 1024 # 1MB
            
            while True:
                buffer = response.read(block_size)
                if not buffer:
                    break
                downloaded += len(buffer)
                out_file.write(buffer)
                if file_size > 0:
                    percent = downloaded * 100 / file_size
                    if downloaded % (5 * block_size) < block_size or percent >= 100:
                        add_log(f"   [下载进度] {percent:.1f}% ({downloaded / (1024*1024):.1f}MB / {file_size / (1024*1024):.1f}MB)")
                else:
                    if downloaded % (5 * block_size) < block_size:
                        add_log(f"   [已下载] {downloaded / (1024*1024):.1f}MB")
        add_log(f"✅ {label} 下载完成！")
        return True
    except Exception as e:
        add_log(f"❌ 下载 {label} 失败: {str(e)}")
        return False

def run_init_task(app_dir):
    global INIT_IN_PROGRESS
    
    try:
        add_log("=" * 50)
        add_log("🚀 【环境初始化】一键部署开始...")
        add_log(f"   工作根目录: {app_dir}")
        
        # 1. FFmpeg Installation
        ffmpeg_dir = os.path.join(app_dir, "ffmpeg_env")
        ffmpeg_exe = os.path.join(ffmpeg_dir, "ffmpeg.exe")
        ffprobe_exe = os.path.join(ffmpeg_dir, "ffprobe.exe")
        
        if os.path.exists(ffmpeg_exe) and os.path.exists(ffprobe_exe):
            add_log("ℹ️ 【环境初始化】本地已检测到 FFmpeg 与 ffprobe 环境，跳过下载。")
        else:
            add_log("📦 【环境初始化】步骤 1/4: 下载并部署 FFmpeg 转码工具...")
            os.makedirs(ffmpeg_dir, exist_ok=True)
            
            ffmpeg_url = "https://registry.npmmirror.com/-/binary/ffmpeg-static/b6.1.1/ffmpeg-win32-x64"
            ffprobe_url = "https://registry.npmmirror.com/-/binary/ffmpeg-static/b6.1.1/ffprobe-win32-x64"
            
            success_ffmpeg = False
            if not os.path.exists(ffmpeg_exe):
                success_ffmpeg = download_file(ffmpeg_url, ffmpeg_exe, "FFmpeg 主转码组件 (ffmpeg.exe)")
            else:
                success_ffmpeg = True
                add_log("ℹ️ 【环境初始化】本地已存在 ffmpeg.exe，跳过下载。")
                
            success_ffprobe = False
            if not os.path.exists(ffprobe_exe):
                success_ffprobe = download_file(ffprobe_url, ffprobe_exe, "FFmpeg 视频元数据组件 (ffprobe.exe)")
            else:
                success_ffprobe = True
                add_log("ℹ️ 【环境初始化】本地已存在 ffprobe.exe，跳过下载。")
                
            if success_ffmpeg and success_ffprobe:
                add_log("✅ FFmpeg 与 ffprobe 核心转码组件部署成功！")
            else:
                add_log("❌ FFmpeg/ffprobe 部分组件部署失败。")
                
        # 2. Python Portable Environment Installation
        py_dir = os.path.join(app_dir, "python_env")
        py_exe = os.path.join(py_dir, "python.exe")
        
        if os.path.exists(py_exe):
            add_log("ℹ️ 【环境初始化】本地已检测到便携式 Python 环境，跳过部署。")
            add_log("📦 【环境初始化】步骤 2/4: 升级便携式 Python 内部依赖包...")
            try:
                add_log("📥 正在使用清华大学镜像源安装/升级 requests 与 yt-dlp...")
                proc = subprocess.Popen(
                    [py_exe, "-m", "pip", "install", "--upgrade", "requests", "yt-dlp", "-i", "https://pypi.tuna.tsinghua.edu.cn/simple"],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
                )
                stdout, stderr = proc.communicate()
                if proc.returncode == 0:
                    add_log("✅ 依赖升级成功！")
                else:
                    add_log(f"⚠️ 依赖升级遇到警告: {stderr.strip()}")
            except Exception as pip_err:
                add_log(f"⚠️ 执行依赖维护失败: {str(pip_err)}")
        else:
            add_log("📦 【环境初始化】步骤 2/4: 下载并部署便携式 Python 3.10...")
            os.makedirs(py_dir, exist_ok=True)
            zip_path = os.path.join(app_dir, "python_temp.zip")
            
            url = "https://npmmirror.com/mirrors/python/3.10.11/python-3.10.11-embed-amd64.zip"
            success = download_file(url, zip_path, "Python 嵌入版压缩包")
            if success:
                add_log("📦 正在解压 Python 运行时环境...")
                try:
                    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                        zip_ref.extractall(py_dir)
                    add_log("✅ Python 环境解压完成！")
                    
                    add_log("📦 【环境初始化】步骤 3/4: 配置 Python 系统包加载规则...")
                    pth_file = os.path.join(py_dir, "python310._pth")
                    if os.path.exists(pth_file):
                        with open(pth_file, "r") as f:
                            lines = f.readlines()
                        new_lines = []
                        for line in lines:
                            if line.strip() == "#import site":
                                new_lines.append("import site\n")
                            else:
                                new_lines.append(line)
                        if "import site\n" not in new_lines:
                            new_lines.append("import site\n")
                        with open(pth_file, "w") as f:
                            f.writelines(new_lines)
                        add_log("✅ python310._pth 配置修改成功！")
                    
                    add_log("📦 正在拉取 pip 包管理器安装程序...")
                    pip_url = "https://cdn.jsdelivr.net/gh/pypa/get-pip@main/public/get-pip.py"
                    get_pip_path = os.path.join(py_dir, "get-pip.py")
                    if download_file(pip_url, get_pip_path, "get-pip.py 引导包"):
                        add_log("📦 正在本地安装 pip 管理器...")
                        p = subprocess.Popen([py_exe, get_pip_path, "--no-warn-script-location"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                        stdout, stderr = p.communicate()
                        if os.path.exists(get_pip_path):
                            os.remove(get_pip_path)
                            
                        if p.returncode == 0:
                            add_log("✅ pip 包管理器安装成功！")
                            add_log("📦 【环境初始化】步骤 4/4: 下载并配置下载器核心依赖包...")
                            p2 = subprocess.Popen(
                                [py_exe, "-m", "pip", "install", "requests", "yt-dlp", "-i", "https://pypi.tuna.tsinghua.edu.cn/simple"],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
                            )
                            stdout, stderr = p2.communicate()
                            if p2.returncode == 0:
                                add_log("✅ 下载器依赖 requests 和 yt-dlp 安装成功！")
                            else:
                                add_log(f"❌ 安装依赖包失败: {stderr.strip()}")
                        else:
                            add_log(f"❌ 安装 pip 失败: {stderr.strip()}")
                except Exception as zip_err:
                    add_log(f"❌ 部署 Python 失败: {str(zip_err)}")
                finally:
                    if os.path.exists(zip_path):
                        os.remove(zip_path)
            else:
                add_log("❌ Python 环境部署失败。")
                
        add_log("=" * 50)
        add_log("✨ 【环境初始化】一键部署全部完成！")
        add_log("💡 提示：如果您之前使用的是全局系统 Python，现在可以关闭当前服务，双击“双击启动音乐下载器.bat”重新启动，系统将完美自动识别并切入新部署的绿色便携式环境运行！")
        add_log("=" * 50)
        
    except Exception as fatal_err:
        add_log(f"❌ 【环境初始化】遇到严重错误: {str(fatal_err)}")
    finally:
        with INIT_LOCK:
            INIT_IN_PROGRESS = False

def start_init_environment(app_dir):
    global INIT_IN_PROGRESS
    with INIT_LOCK:
        if INIT_IN_PROGRESS:
            add_log("⚠️ 【环境初始化】已有初始化部署任务正在后台运行中，请勿重复点击！")
            return False
        INIT_IN_PROGRESS = True
        
    threading.Thread(target=run_init_task, args=(app_dir,), daemon=True).start()
    return True
