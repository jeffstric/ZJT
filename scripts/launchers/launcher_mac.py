"""
智剧通启动器 - Mac 系统托盘启动器
打包命令: pyinstaller --onefile --noconsole --name "智剧通启动器" --icon=files/logo.png launcher_mac.py

功能：
- 在菜单栏显示启动状态图标
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
import fcntl

# 单实例检测（使用文件锁）
LOCK_FILE = None
LOCK_FD = None


def check_single_instance():
    """检查是否已有实例在运行（使用文件锁）"""
    global LOCK_FD, LOCK_FILE

    try:
        # 获取项目根目录
        current_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        lock_file = os.path.join(current_dir, ".launcher_lock")

        LOCK_FILE = lock_file
        LOCK_FD = open(lock_file, 'w')

        try:
            fcntl.flock(LOCK_FD, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except IOError:
            # 文件已被锁定，说明有实例在运行
            LOCK_FD.close()
            return False
    except Exception as e:
        print(f"单实例检测失败: {e}，允许继续运行")
        return True


def show_running_alert():
    """显示已在运行的提示"""
    try:
        # Mac 使用 osascript 显示对话框
        script = '''
        tell application "System Events"
            activate
        end tell

        tell application "Finder"
            display dialog "智剧通已在运行中，请查看菜单栏图标。" buttons {"确定"} default button "确定" with icon note
        end tell
        '''
        subprocess.run(['osascript', '-e', script], check=False)
    except Exception as e:
        print(f"显示提示失败: {e}")


# 检查并导入依赖
HAS_TRAY_DEPS = False
IMPORT_ERROR = None

try:
    import pystray
    from PIL import Image, ImageDraw, ImageFont
    HAS_TRAY_DEPS = True
except ImportError as e:
    IMPORT_ERROR = str(e)


class TrayLauncher:
    """Mac 托盘启动器"""

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
        self.should_stop = False
        self.current_dir = self._get_current_dir()

    def _get_current_dir(self):
        """获取当前脚本所在目录"""
        if getattr(sys, 'frozen', False):
            return os.path.dirname(sys.executable)
        return os.path.dirname(os.path.abspath(__file__))

    def _load_icon_file(self):
        """尝试加载图标文件"""
        icon_paths = [
            os.path.join(self.current_dir, "files", "logo.png"),
            os.path.join(self.current_dir, "logo.png"),
            os.path.join(self.current_dir, "icon.png"),
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
            # Mac 上尝试常见的中文字体
            font_paths = [
                "/System/Library/Fonts/PingFang.ttc",
                "/System/Library/Fonts/STHeiti Light.ttc",
                "/System/Library/Fonts/Helvetica.ttc",
            ]
            font = None
            for font_path in font_paths:
                if os.path.exists(font_path):
                    try:
                        font = ImageFont.truetype(font_path, 32)
                        break
                    except:
                        pass

            if font is None:
                font = ImageFont.load_default()
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

    def _notify(self, title, message):
        """显示气泡通知"""
        if self.icon:
            try:
                self.icon.notify(message, title)
            except Exception as e:
                print(f"通知失败: {e}")

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

    def _read_config_port(self):
        """从配置文件读取端口号"""
        try:
            import yaml
            env = os.environ.get('comfyui_env', 'prod')
            config_file = os.path.join(self.current_dir, f"config_{env}.yml")

            if not os.path.exists(config_file):
                config_file = os.path.join(self.current_dir, "config.example.yml")

            if os.path.exists(config_file):
                with open(config_file, 'r', encoding='utf-8') as f:
                    config = yaml.safe_load(f)
                    return config.get('server', {}).get('port', 9003)
        except Exception as e:
            print(f"读取配置失败: {e}")
        return 9003

    def _start_service(self):
        """启动服务的线程"""
        try:
            self.server_port = self._read_config_port()

            self.status_message = "正在启动服务..."
            self._notify("智剧通", "正在启动服务，请稍候...")

            start_script = os.path.join(self.current_dir, "start.command")

            if not os.path.exists(start_script):
                self.status = self.STATUS_ERROR
                self.status_message = "找不到启动脚本"
                self._update_icon()
                self._notify("启动失败", f"找不到启动脚本:\n{start_script}")
                return

            # 启动进程
            # 设置环境变量告诉 start_mac.py 不要打开浏览器（由托盘启动器负责）
            env = os.environ.copy()
            env['TRAY_MODE'] = '1'

            # Mac: 使用 nohup 在后台运行，重定向输出到 /dev/null
            self.process = subprocess.Popen(
                ["bash", start_script],
                cwd=self.current_dir,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=env
            )

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
                self._notify("启动成功", f"服务已就绪\nhttp://localhost:{self.server_port}")

                webbrowser.open(f"http://localhost:{self.server_port}")
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
        # Mac 启动脚本通过 bash 运行，输出已被重定向
        # 这里主要用于监控状态变化
        pass

    def _open_browser(self, icon=None, item=None):
        """打开浏览器"""
        webbrowser.open(f"http://localhost:{self.server_port}")

    def _show_logs(self, icon=None, item=None):
        """打开日志目录"""
        logs_dir = os.path.join(self.current_dir, "logs")
        if os.path.exists(logs_dir):
            # Mac 使用 open 命令打开文件夹
            subprocess.run(["open", logs_dir], check=False)
        else:
            subprocess.run(["open", self.current_dir], check=False)

    def _stop_service(self, icon=None, item=None):
        """停止服务"""
        self.should_stop = True
        self.status = self.STATUS_STOPPING
        self.status_message = "正在停止服务..."
        self._update_icon()

        # 执行 stop.command 来优雅地停止服务（等待完成）
        stop_script = os.path.join(self.current_dir, "stop.command")
        if os.path.exists(stop_script):
            try:
                # 等待 stop.command 执行完成
                subprocess.run(
                    ["bash", stop_script],
                    cwd=self.current_dir,
                    timeout=30
                )
            except subprocess.TimeoutExpired:
                print("stop.command 执行超时")
            except Exception as e:
                print(f"执行 stop.command 失败: {e}")

        # 使用 pkill 终止进程
        if self.process:
            try:
                # 终止 start_command 相关的 bash 进程
                subprocess.run(
                    ["pkill", "-9", "-f", "start.command"],
                    capture_output=True,
                    timeout=5
                )
            except Exception as e:
                print(f"停止进程失败: {e}")

        if self.icon:
            self.icon.stop()

    def _create_menu(self):
        """创建右键菜单"""
        return pystray.Menu(
            pystray.MenuItem(
                lambda text: self.status_message,
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
    try:
        # 转义特殊字符，防止 osascript 语法错误
        safe_message = message.replace('\\', '\\\\').replace('"', '\\"').replace('\n', ' ')
        # 限制消息长度，避免对话框过大
        if len(safe_message) > 500:
            safe_message = safe_message[:500] + "..."
        script = f'''
        tell application "System Events"
            activate
        end tell

        tell application "Finder"
            display dialog "{safe_message}" buttons {{"确定"}} default button "确定" with icon stop
        end tell
        '''
        subprocess.run(['osascript', '-e', script], check=False)
    except Exception as e:
        print(f"显示错误失败: {e}")


def main():
    """主函数"""
    # 单实例检测
    if not check_single_instance():
        show_running_alert()
        sys.exit(0)

    try:
        if HAS_TRAY_DEPS:
            # 使用托盘启动器
            launcher = TrayLauncher()
            launcher.run()
        else:
            # 依赖不存在
            error_msg = f"缺少依赖 pystray/Pillow\n导入错误: {IMPORT_ERROR}"
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
                # 获取项目根目录
                log_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            log_file = os.path.join(log_dir, "launcher_error.log")
            with open(log_file, 'w', encoding='utf-8') as f:
                f.write(error_msg)
        except:
            pass

        sys.exit(1)
    finally:
        # 清理锁文件
        if LOCK_FD is not None:
            try:
                fcntl.flock(LOCK_FD, fcntl.LOCK_UN)
                LOCK_FD.close()
            except:
                pass
        if LOCK_FILE and os.path.exists(LOCK_FILE):
            try:
                os.remove(LOCK_FILE)
            except:
                pass


if __name__ == "__main__":
    main()
