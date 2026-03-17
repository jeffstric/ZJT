# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "mysql-connector-python>=8.0.0",
#   "pyyaml>=6.0",
# ]
# ///
"""
Mac 启动脚本
用于 macOS 系统上启动和管理本地服务

功能：
1. 启动 MySQL 服务（bin/mysql）
2. 首次启动时执行 --initialize-insecure 初始化
3. 从 config_{env}.yml 读取数据库密码并设置
4. 首次初始化时导入 model/sql/baseline.sql
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
import platform

import mysql.connector
from mysql.connector import Error as MysqlError

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

mysql_process = None
app_process = None
is_shutting_down = False

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


def get_current_dir():
    """
    获取项目根目录，兼容打包后的路径
    """
    if getattr(sys, 'frozen', False):
        # 打包后的可执行文件，返回可执行文件所在目录的上级目录
        current_dir = os.path.dirname(sys.executable)
    else:
        # 开发环境，从脚本路径向上三级到达项目根目录
        # scripts/launchers/start_mac.py -> scripts/ -> project_root
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

        # Mac 使用无 .exe 后缀的路径，更新为绝对路径
        # 替换 Windows 路径（如果有）
        config_content = config_content.replace(
            'ffmpeg: "bin/ffmpeg/ffmpeg.exe"',
            f'ffmpeg: "{current_dir}/bin/ffmpeg/ffmpeg"'
        )
        config_content = config_content.replace(
            'ffprobe: "bin/ffmpeg/ffprobe.exe"',
            f'ffprobe: "{current_dir}/bin/ffmpeg/ffprobe"'
        )
        # 替换相对路径（Mac/Linux 默认）
        config_content = config_content.replace(
            'ffmpeg: "bin/ffmpeg/ffmpeg"',
            f'ffmpeg: "{current_dir}/bin/ffmpeg/ffmpeg"'
        )
        config_content = config_content.replace(
            'ffprobe: "bin/ffmpeg/ffprobe"',
            f'ffprobe: "{current_dir}/bin/ffmpeg/ffprobe"'
        )

        with open(config_file, 'w', encoding='utf-8') as f:
            f.write(config_content)

        logger.info(f"配置文件创建成功: {config_file}")
        logger.info(f"已更新 ffmpeg 路径为: {current_dir}/bin/ffmpeg/ffmpeg")
        logger.info(f"已更新 ffprobe 路径为: {current_dir}/bin/ffmpeg/ffprobe")
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

        expected_ffmpeg = f"{current_dir}/bin/ffmpeg/ffmpeg"
        expected_ffprobe = f"{current_dir}/bin/ffmpeg/ffprobe"

        # ffmpeg/ffprobe 在 bin: 下面
        bin_config = config.get('bin', {})
        current_ffmpeg = bin_config.get('ffmpeg', '')
        current_ffprobe = bin_config.get('ffprobe', '')

        need_update = False

        # 检查 ffmpeg 路径
        if current_ffmpeg != expected_ffmpeg:
            logger.info(f"更新 ffmpeg 路径: {current_ffmpeg} -> {expected_ffmpeg}")
            if 'bin' not in config:
                config['bin'] = {}
            config['bin']['ffmpeg'] = expected_ffmpeg
            need_update = True

        # 检查 ffprobe 路径
        if current_ffprobe != expected_ffprobe:
            logger.info(f"更新 ffprobe 路径: {current_ffprobe} -> {expected_ffprobe}")
            if 'bin' not in config:
                config['bin'] = {}
            config['bin']['ffprobe'] = expected_ffprobe
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
    如果 my.cnf 不存在,则从模板自动创建
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

        mysqld_exe = os.path.join(mysql_bin_dir, 'mysqld')
        if not os.path.exists(mysqld_exe):
            return False, f"mysqld不存在: {mysqld_exe}"

        mysql_client = os.path.join(mysql_bin_dir, 'mysql')
        if not os.path.exists(mysql_client):
            return False, f"mysql不存在: {mysql_client}"

        mysql_cnf = os.path.join(mysql_dir, 'my.cnf')
        mysql_cnf_template = os.path.join(mysql_dir, 'my.cnf.template')

        if not os.path.exists(mysql_cnf):
            logger.warning(f"my.cnf不存在: {mysql_cnf}")

            if os.path.exists(mysql_cnf_template):
                logger.info(f"从模板创建 my.cnf: {mysql_cnf_template}")
                basedir = mysql_dir
                datadir = os.path.join(current_dir, 'data', 'mysql')

                with open(mysql_cnf_template, 'r', encoding='utf-8') as f:
                    template_content = f.read()

                cnf_content = template_content.replace('{BASEDIR}', basedir)
                cnf_content = cnf_content.replace('{DATADIR}', datadir)

                with open(mysql_cnf, 'w', encoding='utf-8') as f:
                    f.write(cnf_content)

                logger.info(f"my.cnf 创建成功: basedir={basedir}, datadir={datadir}")
            else:
                return False, f"my.cnf 和 my.cnf.template 都不存在: {mysql_cnf}"

        paths = {
            'mysql_dir': mysql_dir,
            'mysql_bin_dir': mysql_bin_dir,
            'mysqld_exe': mysqld_exe,
            'mysql_client': mysql_client,
            'mysql_cnf': mysql_cnf
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


def get_mysql_port():
    """
    从 MySQL 配置文件中获取端口号
    Returns:
        int: MySQL 端口号，默认为 3306
    """
    try:
        current_dir = get_current_dir()
        mysql_cnf = os.path.join(current_dir, 'bin', 'mysql', 'my.cnf')

        if not os.path.exists(mysql_cnf):
            logger.warning(f"MySQL配置文件不存在: {mysql_cnf}，使用默认端口3306")
            return 3306

        with open(mysql_cnf, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line.startswith('port='):
                    try:
                        return int(line.split('=')[1])
                    except (IndexError, ValueError):
                        logger.warning(f"解析端口号失败: {line}")
                        return 3306

        logger.info("未在配置文件中找到端口配置，使用默认端口3306")
        return 3306
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


def update_mysql_cnf_paths():
    """
    更新 my.cnf 中的路径为当前项目路径
    Returns:
        tuple: (bool, str) - (是否成功, 消息)
    """
    try:
        current_dir = get_current_dir()
        mysql_dir = os.path.join(current_dir, 'bin', 'mysql')
        mysql_cnf = os.path.join(mysql_dir, 'my.cnf')
        mysql_cnf_template = os.path.join(mysql_dir, 'my.cnf.template')

        basedir = mysql_dir
        datadir = os.path.join(current_dir, 'data', 'mysql')

        # 如果存在模板文件，使用模板
        if os.path.exists(mysql_cnf_template):
            logger.info(f"使用模板文件更新MySQL配置: {mysql_cnf_template}")
            with open(mysql_cnf_template, 'r', encoding='utf-8') as f:
                template_content = f.read()

            # 替换占位符
            cnf_content = template_content.replace('{BASEDIR}', basedir)
            cnf_content = cnf_content.replace('{DATADIR}', datadir)

            # 写入 my.cnf
            with open(mysql_cnf, 'w', encoding='utf-8') as f:
                f.write(cnf_content)

            logger.info(f"MySQL配置文件已更新: basedir={basedir}, datadir={datadir}")
            return True, "MySQL配置文件路径更新成功"

        # 如果没有模板文件，直接修改现有的 my.cnf
        if not os.path.exists(mysql_cnf):
            return False, f"MySQL配置文件不存在: {mysql_cnf}"

        logger.info(f"直接修改MySQL配置文件: {mysql_cnf}")
        with open(mysql_cnf, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        # 更新路径
        updated_lines = []
        for line in lines:
            if line.strip().startswith('basedir='):
                updated_lines.append(f'basedir={basedir}\n')
            elif line.strip().startswith('datadir='):
                updated_lines.append(f'datadir={datadir}\n')
            else:
                updated_lines.append(line)

        # 写回文件
        with open(mysql_cnf, 'w', encoding='utf-8') as f:
            f.writelines(updated_lines)

        logger.info(f"MySQL配置文件已更新: basedir={basedir}, datadir={datadir}")
        return True, "MySQL配置文件路径更新成功"

    except Exception as e:
        logger.error(f"更新MySQL配置文件时出错: {e}")
        return False, f"更新MySQL配置文件失败: {e}"


def start_mysql_service():
    """
    启动 MySQL 服务
    Returns:
        tuple: (bool, str, bool) - (是否成功启动, 消息, 是否是首次初始化)
    """
    global mysql_process

    try:
        mysql_exists, mysql_paths = check_mysql_path()
        if not mysql_exists:
            return False, mysql_paths, False

        # 更新 my.cnf 中的路径为当前项目路径
        logger.info("正在更新MySQL配置文件路径...")
        success, message = update_mysql_cnf_paths()
        if not success:
            logger.warning(f"更新MySQL配置文件路径失败: {message}，继续尝试启动")
        else:
            logger.info(message)

        mysqld_exe = mysql_paths['mysqld_exe']
        mysql_cnf = mysql_paths['mysql_cnf']

        port = get_mysql_port()
        is_first_init = check_mysql_data_dir()

        if check_port_in_use(port):
            logger.info(f"MySQL服务已经在端口 {port} 运行")
            return True, "MySQL服务已经在运行", False

        if is_first_init:
            logger.info("MySQL数据目录为空，正在初始化...")
            cmd = [mysqld_exe, f'--defaults-file={mysql_cnf}', '--initialize-insecure']
            logger.info(f"正在执行初始化命令: {' '.join(cmd)}")

            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )

            stdout, stderr = process.communicate()
            if process.returncode != 0:
                error_msg = stderr.decode('utf-8', errors='ignore')
                return False, f"MySQL初始化失败，错误信息：{error_msg}", False
            logger.info("MySQL数据目录初始化成功")

        cmd = [mysqld_exe, f"--defaults-file={mysql_cnf}"]
        logger.info(f"正在执行启动命令: {' '.join(cmd)}")

        mysql_process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )

        retry_count = 0
        max_retries = 60 if is_first_init else 30

        while retry_count < max_retries:
            if check_port_in_use(port):
                logger.info(f"MySQL服务已启动，端口: {port}")
                return True, "MySQL服务启动成功", is_first_init

            if mysql_process.poll() is not None:
                stdout, stderr = mysql_process.communicate()
                error_msg = stderr.decode('utf-8', errors='ignore')
                return False, f"MySQL进程已退出，错误信息：{error_msg}", False

            logger.info(f"等待MySQL启动... ({retry_count + 1}/{max_retries})")
            time.sleep(1)
            retry_count += 1

        stdout, stderr = mysql_process.communicate()
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
    - 导入 baseline.sql
    """
    try:
        mysql_port = get_mysql_port()
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
            logger.info("zjt数据库不存在，准备导入baseline.sql...")

            current_dir = get_current_dir()
            baseline_sql_path = os.path.join(current_dir, 'model', 'sql', 'baseline.sql')

            if not os.path.exists(baseline_sql_path):
                cursor.close()
                conn.close()
                return False, f"找不到baseline.sql文件: {baseline_sql_path}"

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
                stderr=subprocess.PIPE
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


def check_mysql_status():
    """
    检查 MySQL 是否正在运行
    """
    global mysql_process

    port = get_mysql_port()

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


def start_app_service():
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

        uv_path = os.path.join(current_dir, "bin", "uv", "uv")
        if not os.path.exists(uv_path):
            uv_path = shutil.which("uv")
            if uv_path is None:
                return False, "找不到 uv 可执行文件，请确保 bin/uv/uv 存在或已安装 uv"

        logger.info(f"使用 uv 启动: {run_script}")
        requirements_file = os.path.join(current_dir, "requirements.txt")

        # Mac 有多种架构(x86_64/arm64)，让 uv 自动选择合适的 Python 版本
        cmd = [uv_path, "run", "--python", "3.10"]
        if os.path.exists(requirements_file):
            cmd.extend(["--with-requirements", requirements_file])
            logger.info(f"使用依赖文件: {requirements_file}")
        cmd.append(run_script)

        logger.info(f"执行命令: {' '.join(cmd)}")

        # 设置环境变量
        subprocess_env = os.environ.copy()
        subprocess_env['PYTHONUTF8'] = '1'
        # 设置 uv 镜像源，加速大陆地区下载
        subprocess_env['UV_PYTHON_INSTALL_MIRROR'] = 'https://ghfast.top/https://github.com/indygreg/python-build-standalone/releases/download'
        subprocess_env['UV_INDEX_URL'] = 'https://mirrors.aliyun.com/pypi/simple/'

        app_process = subprocess.Popen(
            cmd,
            cwd=current_dir,
            stdout=sys.stdout,
            stderr=sys.stderr,
            env=subprocess_env
        )

        time.sleep(3)

        if app_process.poll() is not None:
            return False, f"应用进程启动后立即退出，退出码: {app_process.returncode}"

        return True, f"应用服务启动成功 (run_{env}.py)"

    except Exception as e:
        return False, f"启动应用服务时发生错误: {e}"


def monitor_services():
    """
    监控 MySQL 和应用服务，异常退出时自动重启
    """
    global is_shutting_down

    logger.info("开始监控服务...")
    mysql_restart_count = 0
    app_restart_count = 0
    max_restarts = 5

    while not is_shutting_down:
        try:
            if not check_mysql_status():
                if is_shutting_down:
                    break

                mysql_restart_count += 1
                if mysql_restart_count > max_restarts:
                    logger.error(f"MySQL已重启{max_restarts}次，超过最大限制，停止监控")
                    break

                logger.warning(f"检测到MySQL服务异常，尝试重启... (第{mysql_restart_count}次)")
                success, message, _ = start_mysql_service()
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
                success, message = start_app_service()
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


def stop_mysql_gracefully():
    """
    使用 mysqladmin shutdown 优雅停止 MySQL
    """
    try:
        mysql_exists, mysql_paths = check_mysql_path()
        if not mysql_exists:
            return False

        current_dir = get_current_dir()
        mysql_client = mysql_paths['mysql_client']
        mysqladmin = os.path.join(mysql_paths['mysql_bin_dir'], 'mysqladmin')

        if not os.path.exists(mysqladmin):
            logger.warning(f"mysqladmin 不存在: {mysqladmin}")
            return False

        config, _ = load_config()
        password = config['database']['password'] if config and 'database' in config else ""
        port = get_mysql_port()

        cmd = [mysqladmin, '-uroot', f'-P{port}', 'shutdown']
        if password:
            cmd.insert(2, f'-p{password}')

        logger.info("使用 mysqladmin shutdown 停止 MySQL...")
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
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


def cleanup():
    """
    清理函数，停止所有服务
    """
    global mysql_process, app_process, is_shutting_down

    is_shutting_down = True
    logger.info("正在停止所有服务...")

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

    if mysql_process is not None:
        logger.info("正在停止MySQL服务...")
        if not stop_mysql_gracefully():
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


def signal_handler(signum, frame):
    """
    信号处理函数
    """
    logger.info(f"收到信号 {signum}，正在退出...")
    cleanup()
    sys.exit(0)


def main():
    """
    主函数
    """
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    # Mac 关闭终端窗口时会发送 SIGHUP，需要捕获并清理子进程
    signal.signal(signal.SIGHUP, signal_handler)
    atexit.register(cleanup)

    env = get_env()
    logger.info("=" * 50)
    logger.info(f"Mac 启动脚本 (环境: {env})")
    logger.info("=" * 50)

    config, config_file = load_config()
    if config is None:
        logger.error("无法加载配置文件，退出")
        sys.exit(1)

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
    success, message, is_first_init = start_mysql_service()
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
    success, message = start_app_service()
    logger.info(message)
    if not success:
        logger.error("应用服务启动失败，退出")
        sys.exit(1)

    # 从配置文件读取端口号
    server_port = config.get('server', {}).get('port', 9003)
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
        monitor_services()
    except KeyboardInterrupt:
        logger.info("收到退出信号")
    finally:
        cleanup()

    logger.info("Mac启动脚本退出")


if __name__ == "__main__":
    main()
