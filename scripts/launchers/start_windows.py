# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "mysql-connector-python>=8.0.0",
#   "pyyaml>=6.0",
# ]
# ///
"""
Windows 启动脚本
用于 Windows 系统上启动和管理本地服务

功能：
1. 启动 MySQL 服务（bin/mysql）
2. 首次启动时执行 --initialize-insecure 初始化
3. 从 config_{env}.yml 读取数据库密码并设置
4. 首次初始化时导入 model/sql/baseline_with_db.sql
5. 通过 uv 启动 run_{env}.py（Web 服务 + 定时任务）
6. 服务监控和自动重启
"""
import subprocess
import os
import sys
import time
import logging
import socket
import atexit
import signal
import shutil
import yaml
import webbrowser
from pathlib import Path

import mysql.connector
from mysql.connector import Error as MysqlError

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.constant import (
    MYSQL_INITIALIZE_TIMEOUT_SECONDS,
    MYSQL_STARTUP_LOCK_TIMEOUT_SECONDS,
    RUNTIME_FILE_LOCK_POLL_SECONDS,
    UV_BUNDLED_PYTHON_REQUEST,
)

# 导入 PID 管理模块 / 一体包 binlog 配置工具
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pid_manager import (
    add_pid,
    remove_pid,
    clear_pids,
    cleanup_dead_pids_on_startup
)
from mysql_binlog_config import ensure_mysql_binlog_retention
from runtime_lock import InterProcessFileLock

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

mysql_process = None
mysql_process_owned = False
app_process = None
is_shutting_down = False
_app_config = None  # 存储应用配置，供 signal_handler 使用

# 是否由托盘启动器启动（托盘启动器会自行处理浏览器打开）
# 支持命令行参数 --tray 或环境变量 TRAY_MODE=1
tray_mode = '--tray' in sys.argv or os.environ.get('TRAY_MODE') == '1'


def wait_for_service(port, timeout=60):
    """
    等待服务可用
    
    Args:
        port: 服务端口
        timeout: 超时时间（秒）
    
    Returns:
        bool: 服务是否可用
    """
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1)
            result = sock.connect_ex(('127.0.0.1', port))
            sock.close()
            if result == 0:
                return True
        except:
            pass
        time.sleep(1)
    return False


def check_path_no_spaces(path, path_name):
    """
    检查路径中是否包含空格

    Args:
        path: 要检查的路径
        path_name: 路径名称（用于错误提示）

    Returns:
        bool: 如果路径不包含空格返回 True，否则返回 False
    """
    if ' ' in path:
        logger.error(f"路径包含空格: {path_name}")
        logger.error(f"路径: {path}")
        logger.error("请将项目移动到不含空格的路径下，例如: C:\\Projects\\comfyui_server")
        return False
    return True


def get_current_dir():
    """
    获取项目根目录，兼容打包后的路径
    """
    if getattr(sys, 'frozen', False):
        # 打包后的可执行文件，返回可执行文件所在目录的上级目录
        current_dir = os.path.dirname(sys.executable)
    else:
        # 开发环境，从脚本路径向上三级到达项目根目录
        # scripts/launchers/start_windows.py -> scripts/ -> project_root
        current_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    return current_dir


def create_config_from_example(config_file):
    """
    从 config.example.yml 创建配置文件，并更新 ffmpeg/ffprobe 路径
    Args:
        config_file: 目标配置文件路径
    Returns:
        bool: 是否成功创建
    """
    try:
        current_dir = get_current_dir()
        example_file = os.path.join(current_dir, "config.example.yml")
        
        if not os.path.exists(example_file):
            logger.error(f"模板配置文件不存在: {example_file}")
            return False
        
        logger.info(f"从 {example_file} 创建配置文件: {config_file}")
        
        with open(example_file, 'r', encoding='utf-8') as f:
            config_content = f.read()
        
        current_dir_forward_slash = current_dir.replace('\\', '/')
        
        config_content = config_content.replace(
            'ffmpeg: "bin/ffmpeg/ffmpeg"',
            f'ffmpeg: "{current_dir_forward_slash}/bin/ffmpeg/ffmpeg.exe"'
        )
        config_content = config_content.replace(
            'ffprobe: "bin/ffmpeg/ffprobe"',
            f'ffprobe: "{current_dir_forward_slash}/bin/ffmpeg/ffprobe.exe"'
        )
        
        with open(config_file, 'w', encoding='utf-8') as f:
            f.write(config_content)
        
        logger.info(f"配置文件创建成功: {config_file}")
        logger.info(f"已更新 ffmpeg 路径为: {current_dir_forward_slash}/bin/ffmpeg/ffmpeg.exe")
        logger.info(f"已更新 ffprobe 路径为: {current_dir_forward_slash}/bin/ffmpeg/ffprobe.exe")
        return True
        
    except Exception as e:
        logger.error(f"创建配置文件失败: {e}")
        return False


def load_config():
    """
    加载配置文件
    根据环境变量 comfyui_env 加载对应的配置文件
    默认使用 config_prod.yml
    如果配置文件不存在，则从 config.example.yml 自动创建
    """
    env = os.getenv("comfyui_env", "prod")
    config_file = os.path.join(get_current_dir(), f"config_{env}.yml")

    if not os.path.exists(config_file):
        logger.warning(f"配置文件不存在: {config_file}")
        logger.info("尝试从 config.example.yml 创建配置文件...")
        
        if not create_config_from_example(config_file):
            logger.error("无法创建配置文件")
            return None
        
        logger.info("配置文件已自动创建，请根据实际情况修改配置")

    try:
        with open(config_file, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
            logger.info(f"已加载配置文件: {config_file}")
            return config, config_file
    except Exception as e:
        logger.error(f"加载配置文件失败: {e}")
        return None, None


def check_and_update_ffmpeg_paths(config, config_file):
    """
    检查并更新配置文件中的 ffmpeg/ffprobe 路径
    确保路径指向当前项目目录下的正确位置
    
    Args:
        config: 配置字典
        config_file: 配置文件路径
    Returns:
        dict: 更新后的配置
    """
    try:
        current_dir = get_current_dir()
        current_dir_forward_slash = current_dir.replace('\\', '/')
        
        expected_ffmpeg = f"{current_dir_forward_slash}/bin/ffmpeg/ffmpeg.exe"
        expected_ffprobe = f"{current_dir_forward_slash}/bin/ffmpeg/ffprobe.exe"
        
        current_ffmpeg = config.get('ffmpeg', '')
        current_ffprobe = config.get('ffprobe', '')
        
        need_update = False
        
        # 检查 ffmpeg 路径
        if current_ffmpeg != expected_ffmpeg:
            logger.info(f"更新 ffmpeg 路径: {current_ffmpeg} -> {expected_ffmpeg}")
            config['ffmpeg'] = expected_ffmpeg
            need_update = True
        
        # 检查 ffprobe 路径
        if current_ffprobe != expected_ffprobe:
            logger.info(f"更新 ffprobe 路径: {current_ffprobe} -> {expected_ffprobe}")
            config['ffprobe'] = expected_ffprobe
            need_update = True
        
        # 如果有更新，写回配置文件
        if need_update:
            with open(config_file, 'w', encoding='utf-8') as f:
                yaml.dump(config, f, default_flow_style=False, allow_unicode=True)
            logger.info("配置文件已更新")
        else:
            logger.info("ffmpeg/ffprobe 路径已是最新")
        
        return config
        
    except Exception as e:
        logger.error(f"检查/更新 ffmpeg 路径失败: {e}")
        return config


def check_mysql_path():
    """
    检查 MySQL 相关路径
    Returns:
        tuple: (bool, dict|str) - (是否找到所有必需文件, 包含所有路径的字典或错误信息)
    """
    try:
        current_dir = get_current_dir()
        mysql_dir = os.path.join(current_dir, 'bin', 'mysql')

        if not os.path.exists(mysql_dir):
            return False, f"MySQL目录不存在: {mysql_dir}"

        mysql_bin_dir = os.path.join(mysql_dir, 'bin')
        if not os.path.exists(mysql_bin_dir):
            return False, f"MySQL bin目录不存在: {mysql_bin_dir}"

        mysqld_exe = os.path.join(mysql_bin_dir, 'mysqld.exe')
        if not os.path.exists(mysqld_exe):
            return False, f"mysqld.exe不存在: {mysqld_exe}"

        mysql_client = os.path.join(mysql_bin_dir, 'mysql.exe')
        if not os.path.exists(mysql_client):
            return False, f"mysql.exe不存在: {mysql_client}"

        mysql_ini = os.path.join(mysql_dir, 'my.ini')
        if not os.path.exists(mysql_ini):
            return False, f"my.ini不存在: {mysql_ini}"

        paths = {
            'mysql_dir': mysql_dir,
            'mysql_bin_dir': mysql_bin_dir,
            'mysqld_exe': mysqld_exe,
            'mysql_client': mysql_client,
            'mysql_ini': mysql_ini
        }
        return True, paths

    except Exception as e:
        return False, f"检查MySQL路径时发生错误: {e}"


def check_mysql_data_dir():
    """
    检查 MySQL 数据目录是否为空或不存在
    Returns:
        bool: 如果目录为空或不存在返回 True（需要初始化），否则返回 False
    """
    try:
        data_dir = os.path.join(get_current_dir(), 'data', 'mysql')

        if not os.path.exists(data_dir):
            os.makedirs(data_dir, exist_ok=True)
            logger.info(f"创建数据目录: {data_dir}")
            return True

        if len(os.listdir(data_dir)) == 0:
            return True

        return False
    except Exception as e:
        logger.error(f"检查MySQL数据目录时出错: {e}")
        return True


def get_mysql_port(config=None):
    """
    获取 MySQL 端口号
    优先级：config 配置文件 > my.ini > 默认 3306

    Args:
        config: 应用配置字典（可选）

    Returns:
        int: MySQL 端口号
    """
    # 优先从 config 读取
    if config and isinstance(config, dict):
        db_config = config.get('database', {})
        if isinstance(db_config, dict):
            port = db_config.get('port')
            if port is not None:
                try:
                    return int(port)
                except (TypeError, ValueError):
                    logger.warning(f"config 中 database.port 值无效: {port}")

    # 从 my.ini 读取
    try:
        current_dir = get_current_dir()
        mysql_ini = os.path.join(current_dir, 'bin', 'mysql', 'my.ini')

        if os.path.exists(mysql_ini):
            with open(mysql_ini, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line.startswith('port='):
                        try:
                            return int(line.split('=')[1])
                        except (IndexError, ValueError):
                            logger.warning(f"解析端口号失败: {line}")

        logger.info("未找到端口配置，使用默认端口3306")
    except Exception as e:
        logger.error(f"读取MySQL端口配置时出错: {e}")

    return 3306


def check_port_in_use(port):
    """
    检查指定端口是否被占用
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1)
            result = s.connect_ex(('127.0.0.1', port))
            return result == 0
    except Exception as e:
        logger.error(f"检查端口状态时发生错误: {e}")
        return False


def get_server_port(config=None):
    """Return the actual web port used by run_prod.py."""
    env_port = os.environ.get("PORT")
    if env_port is not None:
        try:
            return int(env_port)
        except (TypeError, ValueError):
            logger.warning(f"PORT 环境变量无效: {env_port}")

    server_config = config.get("server", {}) if isinstance(config, dict) else {}
    try:
        return int(server_config.get("port", 9003))
    except (TypeError, ValueError):
        return 9003


def get_mysql_startup_lock(port):
    """Serialize MySQL startup by TCP port across all local project copies."""
    if os.name == "nt":
        runtime_root = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
        lock_dir = os.path.join(runtime_root, "zjt", "locks")
    else:
        lock_dir = os.path.expanduser("~/.local/share/zjt/locks")
    return InterProcessFileLock(
        os.path.join(lock_dir, f"mysql-port-{int(port)}.lock"),
        timeout=MYSQL_STARTUP_LOCK_TIMEOUT_SECONDS,
        poll_interval=RUNTIME_FILE_LOCK_POLL_SECONDS,
    )


def _ensure_binlog_retention_on_ini(mysql_ini):
    """
    确保 my.ini 含 binlog_expire_logs_seconds（约 7 天）。

    TODO(deprecate): 存量一体包迁移用；打包固化后可删除此调用。
    仅写配置文件，不执行 SQL。
    """
    try:
        ok, msg = ensure_mysql_binlog_retention(mysql_ini)
        if ok:
            logger.info(f"MySQL binlog 保留策略: {msg}")
        else:
            logger.warning(f"MySQL binlog 保留策略未写入: {msg}")
    except Exception as e:
        logger.warning(f"MySQL binlog 保留策略处理异常（忽略）: {e}")


def update_mysql_ini_paths(config=None):
    """
    更新 my.ini 中的路径和端口为当前项目配置
    端口优先从 config 的 database.port 读取，未配置时默认 3306

    Args:
        config: 应用配置字典（可选）

    Returns:
        tuple: (bool, str) - (是否成功, 消息)
    """
    try:
        current_dir = get_current_dir()
        mysql_dir = os.path.join(current_dir, 'bin', 'mysql')
        mysql_ini = os.path.join(mysql_dir, 'my.ini')
        mysql_ini_template = os.path.join(mysql_dir, 'my.ini.template')

        # 将Windows路径转换为正斜杠格式（MySQL配置文件要求）
        basedir = mysql_dir.replace('\\', '/')
        datadir = os.path.join(current_dir, 'data', 'mysql').replace('\\', '/')

        # 从 config 获取端口，未配置时默认 3306
        port = get_mysql_port(config)

        # 如果存在模板文件，使用模板
        if os.path.exists(mysql_ini_template):
            logger.info(f"使用模板文件更新MySQL配置: {mysql_ini_template}")
            with open(mysql_ini_template, 'r', encoding='utf-8') as f:
                template_content = f.read()

            # 替换占位符
            ini_content = template_content.replace('{BASEDIR}', basedir)
            ini_content = ini_content.replace('{DATADIR}', datadir)
            ini_content = ini_content.replace('{PORT}', str(port))

            # 兜底：兼容旧模板中没有 {PORT} 占位符的情况（如 port=3306）
            updated_lines = []
            for line in ini_content.split('\n'):
                if line.strip().startswith('port='):
                    updated_lines.append(f'port={port}')
                else:
                    updated_lines.append(line)
            ini_content = '\n'.join(updated_lines)

            # 写入 my.ini
            with open(mysql_ini, 'w', encoding='utf-8') as f:
                f.write(ini_content)

            logger.info(f"MySQL配置文件已更新: basedir={basedir}, datadir={datadir}, port={port}")
            _ensure_binlog_retention_on_ini(mysql_ini)
            return True, "MySQL配置文件路径更新成功"

        # 如果没有模板文件，直接修改现有的 my.ini
        if not os.path.exists(mysql_ini):
            return False, f"MySQL配置文件不存在: {mysql_ini}"

        logger.info(f"直接修改MySQL配置文件: {mysql_ini}")
        with open(mysql_ini, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        # 更新路径和端口
        updated_lines = []
        port_updated = False
        for line in lines:
            stripped = line.strip()
            if stripped.startswith('basedir='):
                updated_lines.append(f'basedir={basedir}\n')
            elif stripped.startswith('datadir='):
                updated_lines.append(f'datadir={datadir}\n')
            elif stripped.startswith('port='):
                updated_lines.append(f'port={port}\n')
                port_updated = True
            else:
                updated_lines.append(line)

        # 如果 my.ini 中没有 port 行，在 [mysqld] 段后添加
        if not port_updated:
            new_lines = []
            for line in updated_lines:
                new_lines.append(line)
                if line.strip() == '[mysqld]':
                    new_lines.append(f'port={port}\n')
            updated_lines = new_lines

        # 写回文件
        with open(mysql_ini, 'w', encoding='utf-8') as f:
            f.writelines(updated_lines)

        logger.info(f"MySQL配置文件已更新: basedir={basedir}, datadir={datadir}, port={port}")
        _ensure_binlog_retention_on_ini(mysql_ini)
        return True, "MySQL配置文件路径更新成功"

    except Exception as e:
        logger.error(f"更新MySQL配置文件时出错: {e}")
        return False, f"更新MySQL配置文件失败: {e}"


def start_mysql_service(config=None):
    """
    启动 MySQL 服务

    Args:
        config: 应用配置字典（可选，用于读取端口配置）

    Returns:
        tuple: (bool, str, bool) - (是否成功启动, 消息, 是否是首次初始化)
    """
    global mysql_process, mysql_process_owned

    mysql_process_owned = False

    try:
        mysql_exists, mysql_paths = check_mysql_path()
        if not mysql_exists:
            return False, mysql_paths, False

        # 更新 my.ini 中的路径和端口为当前项目配置
        logger.info("正在更新MySQL配置文件...")
        success, message = update_mysql_ini_paths(config)
        if not success:
            logger.warning(f"更新MySQL配置文件失败: {message}，继续尝试启动")
        else:
            logger.info(message)

        mysqld_exe = mysql_paths['mysqld_exe']
        mysql_ini = mysql_paths['mysql_ini']

        port = get_mysql_port(config)
        is_first_init = check_mysql_data_dir()

        with get_mysql_startup_lock(port):
            # The check must happen while holding the machine-wide port lock.
            # Never attach to an arbitrary listener: this launcher only manages
            # a MySQL process that it created itself.
            if check_port_in_use(port):
                return False, f"MySQL端口 {port} 已被占用，请为当前实例配置独立的 database.port", False

            if is_first_init:
                logger.info("MySQL数据目录为空，正在初始化...")
                cmd = [mysqld_exe, f'--defaults-file={mysql_ini}', '--initialize-insecure']
                logger.info(f"正在执行初始化命令: {' '.join(cmd)}")

                process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    creationflags=subprocess.CREATE_NO_WINDOW
                )
                try:
                    stdout, stderr = process.communicate(timeout=MYSQL_INITIALIZE_TIMEOUT_SECONDS)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.communicate(timeout=10)
                    return False, "MySQL初始化超时", False
                if process.returncode != 0:
                    error_msg = stderr.decode('utf-8', errors='ignore')
                    return False, f"MySQL初始化失败，错误信息：{error_msg}", False
                logger.info("MySQL数据目录初始化成功")

            cmd = [mysqld_exe, f"--defaults-file={mysql_ini}"]
            logger.info(f"正在执行启动命令: {' '.join(cmd)}")

            mysql_process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            mysql_process_owned = True

            if mysql_process.pid:
                current_dir = get_current_dir()
                add_pid(mysql_process.pid, "mysqld.exe", current_dir)

            retry_count = 0
            max_retries = 60 if is_first_init else 30

            while retry_count < max_retries:
                # Check the owned process before accepting a listener on the
                # public port. This closes the old cross-instance race.
                if mysql_process.poll() is not None:
                    stdout, stderr = mysql_process.communicate(timeout=10)
                    mysql_process_owned = False
                    remove_pid(mysql_process.pid, project_dir=get_current_dir())
                    error_msg = stderr.decode('utf-8', errors='ignore')
                    return False, f"MySQL进程已退出，错误信息：{error_msg}", False

                if check_port_in_use(port):
                    logger.info(f"MySQL服务已启动，端口: {port}")
                    return True, "MySQL服务启动成功", is_first_init

                logger.info(f"等待MySQL启动... ({retry_count + 1}/{max_retries})")
                time.sleep(1)
                retry_count += 1

            mysql_process.terminate()
            try:
                stdout, stderr = mysql_process.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                mysql_process.kill()
                stdout, stderr = mysql_process.communicate(timeout=10)
            mysql_process_owned = False
            remove_pid(mysql_process.pid, project_dir=get_current_dir())
            error_msg = stderr.decode('utf-8', errors='ignore')
            if error_msg:
                return False, f"MySQL服务启动超时，错误信息：{error_msg}", False
            return False, "MySQL服务启动超时，无错误信息", False

    except Exception as e:
        return False, f"启动MySQL服务时发生错误: {e}", False


def init_database(config):
    """
    检查并初始化数据库
    - 首次启动时设置 root 密码
    - 导入 baseline_with_db.sql
    """
    try:
        mysql_port = get_mysql_port(config)
        target_password = config['database']['password']

        logger.info("开始尝试连接MySQL...")

        conn = None
        current_password = ""
        retry_count = 0
        max_retries = 3

        # 先尝试使用配置密码连接，如果失败再尝试空密码（首次初始化场景）
        while retry_count < max_retries:
            try:
                logger.info(f"尝试使用密码连接MySQL... (第{retry_count + 1}次)")
                conn = mysql.connector.connect(
                    host="127.0.0.1",
                    user="root",
                    password=target_password,
                    port=mysql_port,
                    connect_timeout=5,
                    use_pure=True
                )
                current_password = target_password
                logger.info("使用配置密码连接成功")
                break
            except MysqlError as e:
                logger.warning(f"使用配置密码连接失败: {e}")
                retry_count += 1
                # 最后一次重试失败时，尝试空密码（首次初始化场景）
                if retry_count >= max_retries:
                    logger.info("尝试使用空密码连接（首次初始化场景）...")
                    try:
                        conn = mysql.connector.connect(
                            host="127.0.0.1",
                            user="root",
                            password="",
                            port=mysql_port,
                            connect_timeout=5,
                            use_pure=True
                        )
                        current_password = ""
                        logger.info("使用空密码连接成功，需要设置新密码")

                        # 设置新密码
                        cursor = conn.cursor()
                        cursor.execute(f"ALTER USER 'root'@'localhost' IDENTIFIED BY '{target_password}'")
                        conn.commit()
                        cursor.close()
                        logger.info("MySQL root密码设置成功")

                        # 重新用新密码连接
                        conn.close()
                        conn = mysql.connector.connect(
                            host="127.0.0.1",
                            user="root",
                            password=target_password,
                            port=mysql_port,
                            connect_timeout=5,
                            use_pure=True
                        )
                        current_password = target_password
                        logger.info("使用新密码重新连接成功")
                    except MysqlError as empty_pass_error:
                        logger.error(f"空密码连接也失败: {empty_pass_error}")
                        return False, f"无法连接MySQL: {empty_pass_error}"
                    except Exception as e:
                        logger.error(f"空密码连接时发生未知异常: {type(e).__name__}: {e}")
                        import traceback
                        logger.error(traceback.format_exc())
                        return False, f"连接MySQL时发生未知异常: {e}"
                else:
                    time.sleep(1)
            except Exception as e:
                logger.error(f"连接MySQL时发生未知异常: {type(e).__name__}: {e}")
                import traceback
                logger.error(traceback.format_exc())
                return False, f"连接MySQL时发生未知异常: {e}"

        if conn is None:
            return False, "无法连接到MySQL服务"

        cursor = conn.cursor()

        logger.info("检查zjt数据库是否存在...")
        cursor.execute("SHOW DATABASES LIKE 'zjt'")
        database_exists = cursor.fetchone() is not None

        if not database_exists:
            logger.info("zjt数据库不存在，准备导入baseline_with_db.sql...")

            current_dir = get_current_dir()
            baseline_sql_path = os.path.join(current_dir, 'model', 'sql', 'baseline_with_db.sql')

            if not os.path.exists(baseline_sql_path):
                cursor.close()
                conn.close()
                return False, f"找不到baseline_with_db.sql文件: {baseline_sql_path}"

            mysql_exists, mysql_paths = check_mysql_path()
            if not mysql_exists:
                cursor.close()
                conn.close()
                return False, "MySQL路径检查失败"

            mysql_client = mysql_paths['mysql_client']

            logger.info(f"使用MySQL客户端程序导入: {mysql_client}")
            cmd = [
                mysql_client,
                '-uroot',
                f'-P{mysql_port}',
                f'-p{current_password}',
                '-e',
                f'source {baseline_sql_path}'
            ]
            logger.info(f"执行命令: {mysql_client} -uroot -P{mysql_port} -p*** -e 'source {baseline_sql_path}'")

            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            stdout, stderr = process.communicate()

            if process.returncode == 0:
                logger.info("数据库表初始化成功")
            else:
                error_msg = stderr.decode('utf-8', errors='ignore')
                cursor.close()
                conn.close()
                return False, f"数据库初始化失败: {error_msg}"
        else:
            logger.info("zjt数据库已存在，跳过初始化")

        cursor.close()
        conn.close()
        logger.info("数据库操作完成，连接已关闭")

        return True, "数据库初始化成功"

    except Exception as e:
        logger.error(f"初始化数据库时发生错误: {e}")
        return False, f"初始化数据库时发生错误: {e}"


def check_mysql_status(config=None):
    """
    检查 MySQL 是否正在运行
    """
    global mysql_process

    port = get_mysql_port(config)

    if not check_port_in_use(port):
        return False

    if mysql_process is not None and mysql_process.poll() is not None:
        return False

    return True


def check_app_status():
    """
    检查应用进程是否正在运行
    """
    global app_process

    if app_process is None:
        return False

    if app_process.poll() is not None:
        return False

    return True


def get_env():
    """
    获取当前环境
    """
    return os.getenv("comfyui_env", "prod")


def start_app_service(config=None):
    """
    通过 uv 启动 run_{env}.py
    Returns:
        tuple: (bool, str) - (是否成功启动, 消息)
    """
    global app_process

    try:
        env = get_env()
        current_dir = get_current_dir()
        run_script = os.path.join(current_dir, "scripts", "running", f"run_{env}.py")

        if not os.path.exists(run_script):
            return False, f"启动脚本不存在: {run_script}"

        uv_path = os.path.join(current_dir, "bin", "uv", "uv.exe")
        if not os.path.exists(uv_path):
            uv_path = shutil.which("uv")
            if uv_path is None:
                return False, "找不到 uv 可执行文件，请确保 bin\\uv\\uv.exe 存在或已安装 uv"

        server_port = get_server_port(config)
        if check_port_in_use(server_port):
            return False, f"Web端口 {server_port} 已被占用，请为当前实例配置独立的 server.port 或 PORT"

        logger.info(f"使用 uv 启动: {run_script}")
        requirements_file = os.path.join(current_dir, "requirements.txt")

        bundled_python = os.path.join(
            current_dir,
            "bin",
            "python",
            UV_BUNDLED_PYTHON_REQUEST,
            "python.exe",
        )
        if not os.path.isfile(bundled_python):
            return False, f"找不到程序包内置 Python：{bundled_python}"

        cmd = [
            uv_path,
            "run",
            "--no-python-downloads",
            "--python",
            bundled_python,
        ]
        if os.path.exists(requirements_file):
            cmd.extend(["--with-requirements", requirements_file])
            logger.info(f"使用依赖文件: {requirements_file}")
        cmd.append(run_script)

        logger.info(f"执行命令: {' '.join(cmd)}")

        # 设置环境变量
        subprocess_env = os.environ.copy()
        subprocess_env['PYTHONUTF8'] = '1'
        subprocess_env['UV_PYTHON_DOWNLOADS'] = 'never'
        subprocess_env['UV_PYTHON_INSTALL_DIR'] = os.path.join(current_dir, "bin", "python")

        app_process = subprocess.Popen(
            cmd,
            cwd=current_dir,
            stdout=sys.stdout,
            stderr=sys.stderr,
            env=subprocess_env
        )

        # 记录应用进程 PID（带进程名和工作目录）
        if app_process.pid:
            current_dir = get_current_dir()
            # Popen 的直接子进程是 uv.exe；真正的 Python 服务位于其进程树内。
            add_pid(app_process.pid, "uv.exe", current_dir)

        time.sleep(3)

        if app_process.poll() is not None:
            return False, f"应用进程启动后立即退出，退出码: {app_process.returncode}"

        return True, f"应用服务启动成功 (run_{env}.py)"

    except Exception as e:
        return False, f"启动应用服务时发生错误: {e}"


def monitor_services(config=None):
    """
    监控 MySQL 和应用服务，异常退出时自动重启

    Args:
        config: 应用配置字典（可选，传递给子函数）
    """
    global is_shutting_down

    logger.info("开始监控服务...")
    mysql_restart_count = 0
    app_restart_count = 0
    max_restarts = 5

    while not is_shutting_down:
        try:
            if not check_mysql_status(config):
                if is_shutting_down:
                    break

                mysql_restart_count += 1
                if mysql_restart_count > max_restarts:
                    logger.error(f"MySQL已重启{max_restarts}次，超过最大限制，停止监控")
                    break

                logger.warning(f"检测到MySQL服务异常，尝试重启... (第{mysql_restart_count}次)")
                success, message, _ = start_mysql_service(config)
                if success:
                    logger.info(f"MySQL服务重启成功: {message}")
                else:
                    logger.error(f"MySQL服务重启失败: {message}")
                    time.sleep(10)
            else:
                mysql_restart_count = 0

            if not check_app_status():
                if is_shutting_down:
                    break

                app_restart_count += 1
                if app_restart_count > max_restarts:
                    logger.error(f"应用服务已重启{max_restarts}次，超过最大限制，停止监控")
                    break

                logger.warning(f"检测到应用服务异常，尝试重启... (第{app_restart_count}次)")
                success, message = start_app_service(config)
                if success:
                    logger.info(f"应用服务重启成功: {message}")
                else:
                    logger.error(f"应用服务重启失败: {message}")
                    time.sleep(10)
            else:
                app_restart_count = 0

            time.sleep(5)

        except Exception as e:
            logger.error(f"监控服务时发生错误: {e}")
            time.sleep(5)


def stop_mysql_gracefully(config=None):
    """
    使用 mysqladmin shutdown 优雅停止 MySQL

    Args:
        config: 应用配置字典（可选，用于读取端口配置）
    """
    try:
        mysql_exists, mysql_paths = check_mysql_path()
        if not mysql_exists:
            return False

        current_dir = get_current_dir()
        mysql_client = mysql_paths['mysql_client']
        mysqladmin = os.path.join(mysql_paths['mysql_bin_dir'], 'mysqladmin.exe')

        if not os.path.exists(mysqladmin):
            logger.warning(f"mysqladmin 不存在: {mysqladmin}")
            return False

        if config is None:
            config, _ = load_config()
        password = config['database']['password'] if config and 'database' in config else ""
        port = get_mysql_port(config)

        cmd = [mysqladmin, '-uroot', f'-P{port}', 'shutdown']
        if password:
            cmd.insert(2, f'-p{password}')

        logger.info("使用 mysqladmin shutdown 停止 MySQL...")
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=subprocess.CREATE_NO_WINDOW
        )
        stdout, stderr = process.communicate(timeout=15)

        if process.returncode == 0:
            logger.info("MySQL 已优雅停止")
            return True
        else:
            error_msg = stderr.decode('utf-8', errors='ignore')
            logger.warning(f"mysqladmin shutdown 失败: {error_msg}")
            return False

    except subprocess.TimeoutExpired:
        logger.warning("mysqladmin shutdown 超时")
        return False
    except Exception as e:
        logger.error(f"停止 MySQL 时出错: {e}")
        return False


def cleanup(config=None):
    """
    清理函数，停止所有服务

    Args:
        config: 应用配置字典（可选，传递给 stop_mysql_gracefully）
    """
    global mysql_process, mysql_process_owned, app_process, is_shutting_down

    is_shutting_down = True
    logger.info("正在停止所有服务...")

    app_pid = app_process.pid if app_process is not None else None
    mysql_pid = mysql_process.pid if mysql_process is not None else None

    if app_process is not None:
        try:
            logger.info("正在停止应用服务...")
            app_process.terminate()
            app_process.wait(timeout=10)
            logger.info("应用服务已停止")
        except subprocess.TimeoutExpired:
            logger.warning("应用服务停止超时，强制结束")
            app_process.kill()
        except Exception as e:
            logger.error(f"停止应用服务时出错: {e}")

    if mysql_process_owned and mysql_process is not None and mysql_process.poll() is None:
        logger.info("正在停止MySQL服务...")
        if not stop_mysql_gracefully(config):
            try:
                logger.info("尝试强制终止MySQL进程...")
                mysql_process.terminate()
                mysql_process.wait(timeout=10)
                logger.info("MySQL服务已停止")
            except subprocess.TimeoutExpired:
                logger.warning("MySQL服务停止超时，强制结束")
                mysql_process.kill()
            except Exception as e:
                logger.error(f"停止MySQL服务时出错: {e}")
    elif mysql_process is not None:
        logger.info("跳过MySQL停止：当前启动器不拥有存活的MySQL进程")

    # 清理 PID 记录
    try:
        my_pid = os.getpid()
        remove_pid(my_pid, project_dir=get_current_dir())
        if app_pid:
            remove_pid(app_pid, project_dir=get_current_dir())
        if mysql_pid:
            remove_pid(mysql_pid, project_dir=get_current_dir())
    except Exception as e:
        logger.error(f"清理 PID 记录时出错: {e}")

    mysql_process_owned = False
    mysql_process = None
    app_process = None


def signal_handler(signum, frame):
    """
    信号处理函数
    """
    global _app_config
    logger.info(f"收到信号 {signum}，正在退出...")
    cleanup(_app_config)
    sys.exit(0)


def main():
    """
    主函数
    """
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # 获取当前项目目录（必须在 cleanup 之前，用于按项目过滤 PID）
    current_dir = get_current_dir()

    # Record the supervising launcher itself. stop.bat terminates this exact
    # process tree, preventing the monitor loop from restarting stopped children.
    add_pid(os.getpid(), "python.exe", current_dir)

    # 启动时清理残留的死亡进程 PID（只清理当前项目的）
    cleanup_dead_pids_on_startup(project_dir=current_dir)

    env = get_env()
    logger.info("=" * 50)
    logger.info(f"Windows 启动脚本 (环境: {env})")
    logger.info("=" * 50)

    # 检查关键路径是否包含空格
    if not check_path_no_spaces(current_dir, "项目根目录"):
        sys.exit(1)

    logger.info("路径空格检查通过")

    config, config_file = load_config()
    if config is None:
        logger.error("无法加载配置文件，退出")
        sys.exit(1)

    # 保存到全局变量，供 signal_handler 和 atexit 使用
    global _app_config
    _app_config = config
    atexit.register(lambda: cleanup(_app_config))

    # 检查并更新 ffmpeg/ffprobe 路径
    config = check_and_update_ffmpeg_paths(config, config_file)

    if 'database' not in config or 'password' not in config['database']:
        logger.error("配置文件中缺少 database.password 配置")
        sys.exit(1)

    mysql_exists, mysql_result = check_mysql_path()
    if not mysql_exists:
        logger.error(f"MySQL检查失败: {mysql_result}")
        sys.exit(1)
    logger.info("MySQL路径检查成功")

    logger.info("正在启动MySQL服务...")
    success, message, is_first_init = start_mysql_service(config)
    logger.info(message)
    if not success:
        logger.error("MySQL服务启动失败，退出")
        sys.exit(1)

    # 每次启动都检查数据库连接和密码配置
    # 确保密码设置正确，数据库存在
    logger.info("正在检查数据库连接和初始化...")
    success, message = init_database(config)
    logger.info(message)
    if not success:
        logger.error("数据库初始化失败，退出")
        sys.exit(1)

    logger.info("正在启动应用服务...")
    success, message = start_app_service(config)
    logger.info(message)
    if not success:
        logger.error("应用服务启动失败，退出")
        sys.exit(1)

    # 从配置文件读取服务器 URL 和端口号
    server_port = get_server_port(config)
    # 使用 server.port 构建浏览器 URL，避免 server.host 中端口不一致
    url = f"http://localhost:{server_port}"
    
    # 等待服务真正可用后再打开浏览器（托盘模式由托盘启动器处理）
    if not tray_mode:
        logger.info(f"等待服务就绪 (端口 {server_port})...")
        if wait_for_service(server_port, timeout=60):
            # 额外等待 1 秒确保服务完全就绪
            time.sleep(1)
            logger.info(f"服务已就绪，正在打开浏览器: {url}")
            webbrowser.open(url)
        else:
            logger.warning(f"等待服务超时，请手动访问: {url}")

    logger.info("所有服务已就绪，开始监控...")
    try:
        monitor_services(config)
    except KeyboardInterrupt:
        logger.info("收到退出信号")
    finally:
        cleanup(config)

    logger.info("Windows启动脚本退出")


if __name__ == "__main__":
    main()
