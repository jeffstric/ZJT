"""
智剧通启动器 - 系统托盘启动器
打包命令: pyinstaller --onefile --noconsole --name "点我启动" --icon=files/logo.ico launcher.py

功能：
- 在系统托盘显示启动状态图标
- 通过气泡提示显示启动进度
- 服务就绪后自动打开浏览器
- 右键菜单支持：打开浏览器、查看日志、退出
"""
import os
import sys
import subprocess
import threading
import time
import socket
import webbrowser
import ctypes

# 导入 PID 管理模块
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pid_manager import (
    add_pid,
    remove_pid,
    clear_pids,
    cleanup_dead_pids_on_startup,
    check_launcher_running
)

# 顶层导入 pystray 和 PIL，让 PyInstaller 认为它们是必需模块
import pystray
from PIL import Image, ImageDraw, ImageFont

# 单实例检测（使用 Windows 命名互斥锁）
MUTEX_NAME = "Global\\ZhiJuTong_Launcher_Mutex"
mutex_handle = None


def check_single_instance():
    """检查是否已有实例在运行"""
    global mutex_handle

    try:
        # 先检查是否有 launcher 进程真的在运行（通过 PID 文件和进程检测）
        is_running, running_pid = check_launcher_running()

        # 创建命名互斥锁
        mutex_handle = ctypes.windll.kernel32.CreateMutexW(None, False, MUTEX_NAME)
        last_error = ctypes.windll.kernel32.GetLastError()

        # ERROR_ALREADY_EXISTS = 183
        if last_error == 183:
            # 互斥锁已存在，但需要验证进程是否真的在运行
            if is_running:
                # 进程真的在运行，显示提示并退出
                ctypes.windll.user32.MessageBoxW(
                    0,
                    "智剧通已在运行中，请查看系统托盘图标。",
                    "提示",
                    0x40  # MB_ICONINFORMATION
                )
                return False
            else:
                # 互斥锁存在但进程不存在，说明是残留锁，允许继续运行
                return True
        return True
    except Exception as e:
        # 如果互斥锁检测失败，允许继续运行
        return True


# 检查托盘依赖是否可用
HAS_TRAY_DEPS = True
IMPORT_ERROR = None


class TrayLauncher:
    """托盘启动器"""
    
    # 状态常量
    STATUS_STARTING = "starting"
    STATUS_READY = "ready"
    STATUS_ERROR = "error"
    STATUS_STOPPING = "stopping"
    
    # 状态对应的颜色
    STATUS_COLORS = {
        STATUS_STARTING: "#FFA500",  # 橙色
        STATUS_READY: "#00FF00",     # 绿色
        STATUS_ERROR: "#FF0000",     # 红色
        STATUS_STOPPING: "#808080",  # 灰色
    }
    
    # 状态对应的提示文字
    STATUS_TEXTS = {
        STATUS_STARTING: "智剧通 - 启动中...",
        STATUS_READY: "智剧通 - 服务运行中",
        STATUS_ERROR: "智剧通 - 启动失败",
        STATUS_STOPPING: "智剧通 - 正在停止...",
    }
    
    def __init__(self):
        self.status = self.STATUS_STARTING
        self.status_message = "正在初始化..."
        self.icon = None
        self.process = None
        self.server_port = 9003
        self.server_url = f"http://localhost:{self.server_port}"
        self.should_stop = False
        self.current_dir = self._get_current_dir()

        # 启动时清理残留的死亡进程 PID
        cleanup_dead_pids_on_startup()

        # 记录 launcher 自身的 PID（带进程名和工作目录）
        launcher_name = "点我启动.exe" if getattr(sys, 'frozen', False) else "python"
        add_pid(os.getpid(), launcher_name, self.current_dir)
        
    def _get_current_dir(self):
        """获取当前脚本所在目录"""
        if getattr(sys, 'frozen', False):
            # 打包环境下，返回项目根目录而不是可执行文件目录
            # 假设可执行文件在项目根目录
            return os.path.dirname(sys.executable)
        else:
            # 开发环境下，返回项目根目录
            return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    
    def _load_icon_file(self):
        """尝试加载图标文件"""
        icon_paths = [
            os.path.join(self.current_dir, "files", "logo.ico"),
            os.path.join(self.current_dir, "icon.ico"),
            os.path.join(self.current_dir, "logo.ico"),
        ]
        
        for path in icon_paths:
            if os.path.exists(path):
                try:
                    return Image.open(path)
                except:
                    pass
        return None
    
    def _create_icon_image(self, color="#FFA500"):
        """创建托盘图标图像"""
        # 优先使用图标文件
        if not hasattr(self, '_base_icon'):
            self._base_icon = self._load_icon_file()
        
        if self._base_icon:
            return self._base_icon.copy()
        
        # 如果没有图标文件，生成简单图标
        size = 64
        image = Image.new('RGBA', (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        
        # 绘制圆形背景
        margin = 4
        draw.ellipse(
            [margin, margin, size - margin, size - margin],
            fill=color
        )
        
        # 绘制 "Z" 字母（智剧通的首字母）
        try:
            font = ImageFont.truetype("arial.ttf", 32)
        except:
            font = ImageFont.load_default()
        
        text = "Z"
        bbox = draw.textbbox((0, 0), text, font=font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        x = (size - text_width) // 2
        y = (size - text_height) // 2 - 4
        draw.text((x, y), text, fill="white", font=font)
        
        return image
    
    def _update_icon(self):
        """更新托盘图标"""
        if self.icon:
            color = self.STATUS_COLORS.get(self.status, "#FFA500")
            self.icon.icon = self._create_icon_image(color)
            self.icon.title = self.STATUS_TEXTS.get(self.status, "智剧通")
            # 更新菜单内容以刷新状态消息
            try:
                self.icon.update_menu()
            except Exception as e:
                pass
    
    def _notify(self, title, message):
        """显示气泡通知"""
        if self.icon:
            try:
                self.icon.notify(message, title)
            except Exception as e:
                pass
    
    def _check_port_available(self, port, timeout=1):
        """检查端口是否可访问"""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            result = sock.connect_ex(('127.0.0.1', port))
            sock.close()
            return result == 0
        except:
            return False
    
    def _wait_for_service(self, port, timeout=120):
        """等待服务可用"""
        start_time = time.time()
        while time.time() - start_time < timeout:
            if self.should_stop:
                return False
            if self._check_port_available(port):
                return True
            time.sleep(1)
        return False
    
    def _read_config_url(self):
        """从配置文件读取服务器 URL 和端口号"""
        try:
            import yaml
            env = os.environ.get('comfyui_env', 'prod')
            config_file = os.path.join(self.current_dir, f"config_{env}.yml")

            if not os.path.exists(config_file):
                config_file = os.path.join(self.current_dir, "config.example.yml")

            if os.path.exists(config_file):
                with open(config_file, 'r', encoding='utf-8') as f:
                    config = yaml.safe_load(f)
                    server_config = config.get('server', {})
                    # 优先使用 server.host，如果没有则用 host 和 port 组合
                    server_url = server_config.get('host')
                    if server_url:
                        # 确保 server_url 以 http:// 或 https:// 开头
                        if not server_url.startswith(('http://', 'https://')):
                            server_url = f"http://{server_url}"
                    else:
                        # 回退到使用 localhost + port
                        port = server_config.get('port', 9003)
                        server_url = f"http://localhost:{port}"
                    port = server_config.get('port', 9003)
                    return server_url, port
        except Exception:
            pass
        return "http://localhost:9003", 9003
    
    def _start_service(self):
        """启动服务的线程"""
        try:
            self.server_url, self.server_port = self._read_config_url()

            self.status_message = "正在启动服务..."
            self._notify("智剧通", "正在启动服务，请稍候...")
            
            start_script = os.path.join(self.current_dir, "start.bat")
            
            if not os.path.exists(start_script):
                self.status = self.STATUS_ERROR
                self.status_message = "找不到启动脚本"
                self._update_icon()
                self._notify("启动失败", f"找不到启动脚本:\n{start_script}")
                return
            
            # 启动进程（隐藏窗口）
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE
            
            # 设置环境变量告诉 start_windows.py 不要打开浏览器（由托盘启动器负责）
            env = os.environ.copy()
            env['TRAY_MODE'] = '1'
            
            self.process = subprocess.Popen(
                ["cmd", "/c", start_script],
                cwd=self.current_dir,
                startupinfo=startupinfo,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding='utf-8',
                errors='replace',
                creationflags=subprocess.CREATE_NO_WINDOW,
                env=env
            )

            # 记录启动的进程 PID（带进程名和工作目录）
            if self.process and self.process.pid:
                add_pid(self.process.pid, "cmd.exe", self.current_dir)

            # 启动日志读取线程
            log_thread = threading.Thread(target=self._read_process_output, daemon=True)
            log_thread.start()
            
            # 等待服务可用
            self.status_message = f"等待服务就绪 (端口 {self.server_port})..."
            
            if self._wait_for_service(self.server_port, timeout=180):
                time.sleep(2)

                self.status = self.STATUS_READY
                self.status_message = "服务已就绪"
                self._update_icon()
                self._notify("启动成功", f"服务已就绪\n{self.server_url}")

                webbrowser.open(self.server_url)
            else:
                if not self.should_stop:
                    self.status = self.STATUS_ERROR
                    self.status_message = "服务启动超时"
                    self._update_icon()
                    self._notify("启动失败", "服务启动超时，请检查日志")
            
        except Exception as e:
            self.status = self.STATUS_ERROR
            self.status_message = f"启动失败: {e}"
            self._update_icon()
            self._notify("启动失败", str(e))
    
    def _read_process_output(self):
        """读取进程输出（用于日志）"""
        if self.process and self.process.stdout:
            try:
                for line in self.process.stdout:
                    pass
            except Exception:
                pass
    
    def _open_browser(self, icon=None, item=None):
        """打开浏览器"""
        webbrowser.open(self.server_url)
    
    def _show_logs(self, icon=None, item=None):
        """打开日志目录"""
        logs_dir = os.path.join(self.current_dir, "logs")
        if os.path.exists(logs_dir):
            os.startfile(logs_dir)
        else:
            os.startfile(self.current_dir)
    
    def _stop_service(self, icon=None, item=None):
        """停止服务"""
        self.should_stop = True
        self.status = self.STATUS_STOPPING
        self.status_message = "正在停止服务..."
        self._update_icon()

        # 执行 stop.bat 来优雅地停止服务（等待完成）
        stop_script = os.path.join(self.current_dir, "stop.bat")
        if os.path.exists(stop_script):
            try:
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = subprocess.SW_HIDE

                subprocess.run(
                    ["cmd", "/c", stop_script],
                    cwd=self.current_dir,
                    startupinfo=startupinfo,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                    timeout=30
                )
            except subprocess.TimeoutExpired:
                pass
            except Exception:
                pass

        # 使用 /T 参数终止进程树（包括所有子进程）
        if self.process:
            try:
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(self.process.pid)],
                    capture_output=True,
                    timeout=10
                )
            except Exception:
                pass

        # 清理 PID 记录
        try:
            my_pid = os.getpid()
            remove_pid(my_pid)
            if self.process and self.process.pid:
                remove_pid(self.process.pid)
        except Exception:
            pass

        if self.icon:
            # 先隐藏托盘图标
            try:
                self.icon.visible = False
            except Exception:
                pass

            # 停止托盘图标（这会退出 icon.run() 事件循环）
            try:
                self.icon.stop()
            except Exception:
                pass

            # 确保程序完全退出
            sys.exit(0)
    
    def _create_menu(self):
        """创建右键菜单"""
        return pystray.Menu(
            pystray.MenuItem(
                lambda item: self.status_message,
                None,
                enabled=False
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("打开浏览器", self._open_browser),
            pystray.MenuItem("查看日志", self._show_logs),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("退出", self._stop_service),
        )
    
    def run(self):
        """运行托盘启动器"""
        image = self._create_icon_image(self.STATUS_COLORS[self.STATUS_STARTING])
        
        self.icon = pystray.Icon(
            "智剧通",
            image,
            "智剧通 - 启动中...",
            menu=self._create_menu()
        )
        
        service_thread = threading.Thread(target=self._start_service, daemon=True)
        service_thread.start()
        
        self.icon.run()


def show_error(message):
    """显示错误对话框"""
    ctypes.windll.user32.MessageBoxW(0, message, "错误", 0x10)


def check_non_ascii_in_path():
    """检查路径是否包含非ASCII字符（包括中文、日文、韩文等）"""
    import re
    
    current_path = os.getcwd()
    
    # 检查路径中是否包含非ASCII字符（超出ASCII 0-127范围的字符）
    non_ascii_pattern = re.compile(r'[^\x00-\x7F]')
    if non_ascii_pattern.search(current_path):
        error_msg = (
            f"路径兼容性检查失败\n\n"
            f"当前路径：{current_path}\n\n"
            f"问题原因：\n"
            f"• 检测到路径包含非英文字符（可能包括中文、日文、韩文等）\n"
            f"• MySQL 配置文件在 Windows 系统下对非英文字符路径存在编码兼容性问题\n"
            f"• 可能导致配置文件读取失败，数据库无法正常启动\n\n"
            f"解决方案：\n"
            f"请将整个程序文件夹移动到纯英文路径下，例如：\n"
            f"• C:\\ZhiJuTong\\\n"
            f"• D:\\Programs\\ZhiJuTong\\\n"
            f"• C:\\ComfyUI\\\n"
            f"• D:\\Tools\\ComfyUI\\\n\n"
            f"移动后重新运行程序即可。"
        )
        show_error(error_msg)
        return False
    
    return True


def fallback_vbs_launch():
    """回退到 VBS 静默启动"""
    if getattr(sys, 'frozen', False):
        # 打包环境下，可执行文件应该在根目录
        current_dir = os.path.dirname(sys.executable)
    else:
        # 开发环境下，获取项目根目录
        current_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    
    vbs_path = os.path.join(current_dir, "scripts", "tools", "start_silent.vbs")
    
    if os.path.exists(vbs_path):
        subprocess.Popen(["wscript", vbs_path], cwd=current_dir)
        return True
    return False


def main():
    """主函数"""
    # 检查路径是否包含非ASCII字符
    if not check_non_ascii_in_path():
        sys.exit(1)
    
    # 单实例检测
    if not check_single_instance():
        sys.exit(0)
    
    try:
        if HAS_TRAY_DEPS:
            # 使用托盘启动器
            launcher = TrayLauncher()
            launcher.run()
        else:
            # 依赖不存在，回退到 VBS 启动
            if not fallback_vbs_launch():
                error_msg = f"缺少依赖 pystray/Pillow\n导入错误: {IMPORT_ERROR}\n\n且找不到 start_silent.vbs"
                show_error(error_msg)
                sys.exit(1)
    except Exception as e:
        # 捕获异常并显示错误
        import traceback
        error_msg = f"启动失败:\n{e}\n\n{traceback.format_exc()}"
        show_error(error_msg)
        
        # 同时写入日志文件
        try:
            if getattr(sys, 'frozen', False):
                log_dir = os.path.dirname(sys.executable)
            else:
                # 开发环境下，获取项目根目录
                log_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            log_file = os.path.join(log_dir, "launcher_error.log")
            with open(log_file, 'w', encoding='utf-8') as f:
                f.write(error_msg)
        except:
            pass
        
        sys.exit(1)


if __name__ == "__main__":
    main()
