"""
进程 PID 管理模块
用于记录和管理启动器启动的进程 PID，避免误杀其他进程

处理的极端情况：
1. PID 残留：进程被强制关闭后 PID 文件未清空
2. PID 重用：Windows 重用已释放的 PID
   - 解决：验证进程名 + 工作目录
3. 文件损坏：PID 文件格式错误
4. 权限问题：无法读写 PID 文件
5. 并发冲突：多实例同时操作
"""
import os
import time
import subprocess
import json
from datetime import datetime


def get_pid_file_path():
    """获取 PID 文件路径"""
    if hasattr(os, 'getuid'):
        # Unix-like 系统
        pid_dir = os.path.expanduser("~/.local/share/zjt")
    else:
        # Windows 系统
        pid_dir = os.path.join(os.environ.get('LOCALAPPDATA', os.path.expanduser('~')), 'zjt')

    os.makedirs(pid_dir, exist_ok=True)
    return os.path.join(pid_dir, 'launcher_pids.json')


def get_process_info(pid):
    """
    获取进程信息（工作目录和可执行文件路径）

    Args:
        pid: 进程 ID

    Returns:
        dict: {'name': str, 'cwd': str, 'exe': str} 或 None
    """
    if pid is None or pid <= 0:
        return None

    try:
        # 使用 wmic 命令获取进程信息（注意：ProcessId 要大写 P）
        result = subprocess.run(
            'wmic process where ProcessId={} get ExecutablePath /format:csv'.format(pid),
            shell=True,
            capture_output=True,
            text=True,
            timeout=10,
            encoding='gbk',
            errors='ignore'
        )

        if result.returncode != 0:
            return None

        # 解析输出
        # 格式: Node,ExecutablePath\nDESKTOP-xxx,C:\path\to\file.exe
        lines = result.stdout.strip().split('\n')
        if len(lines) < 2:
            return None

        # 第二行可能包含机器名，需要提取实际路径
        data_line = lines[1].strip()

        # 尝试找到最后一个包含 .exe 的部分（去掉机器名前缀）
        exe_path = None
        if ',' in data_line:
            # 机器名和路径用逗号分隔，取路径部分
            parts = data_line.split(',')
            for part in parts:
                cleaned = part.strip()
                if cleaned.endswith('.exe'):
                    exe_path = cleaned
                    break
        else:
            exe_path = data_line

        if not exe_path or not os.path.isfile(exe_path):
            # 无法获取有效的可执行文件路径
            return None

        # 从可执行文件路径推断工作目录
        cwd = os.path.dirname(exe_path)

        # 获取进程名
        name = os.path.basename(exe_path)

        return {
            'name': name,
            'exe': exe_path,
            'cwd': cwd
        }

    except subprocess.TimeoutExpired:
        return None
    except Exception:
        return None


def is_process_running(pid, process_name=None, expected_cwd=None):
    """
    检查进程是否在运行

    Args:
        pid: 进程 ID
        process_name: 可选的进程名，用于验证
        expected_cwd: 可选的期望工作目录，用于验证

    Returns:
        bool: 进程是否在运行（且符合验证条件）
    """
    if pid is None or pid <= 0:
        return False

    # 获取进程信息
    proc_info = get_process_info(pid)
    if not proc_info:
        return False

    # 验证进程名
    if process_name:
        actual_name = proc_info.get('name', '').lower()
        expected_name = process_name.lower()
        # 检查进程名是否匹配（允许部分匹配）
        if expected_name not in actual_name and not actual_name.endswith(expected_name):
            return False

    # 验证工作目录（重要：避免误杀其他目录的同名进程）
    if expected_cwd:
        actual_cwd = proc_info.get('cwd', '')
        # 标准化路径（统一使用小写和正斜杠）
        actual_cwd_normalized = actual_cwd.lower().replace('\\', '/')
        expected_cwd_normalized = expected_cwd.lower().replace('\\', '/')

        # 检查进程是否在期望的目录下
        if not actual_cwd_normalized.startswith(expected_cwd_normalized):
            return False

    return True


def cleanup_dead_pids_on_startup():
    """
    启动时清理已死亡的进程 PID
    这个函数应该在进程启动时调用，清理上次异常退出残留的 PID

    Returns:
        tuple: (清理的死亡 PID 数量, 保留的活跃 PID 数量)
    """
    pid_file = get_pid_file_path()

    if not os.path.exists(pid_file):
        return 0, 0

    try:
        with open(pid_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except (json.JSONDecodeError, Exception) as e:
        # 文件损坏，清空后重建
        print(f"PID 文件损坏，重新创建: {e}")
        try:
            os.remove(pid_file)
        except Exception:
            pass
        return 0, 0

    if not isinstance(data, dict) or 'pids' not in data:
        # 文件格式错误，清空后重建
        print("PID 文件格式错误，重新创建")
        try:
            os.remove(pid_file)
        except Exception:
            pass
        return 0, 0

    alive_pids = []
    dead_pids = []

    for entry in data['pids']:
        pid = entry.get('pid')
        process_name = entry.get('name')
        cwd = entry.get('cwd')

        if is_process_running(pid, process_name, cwd):
            # 进程还在运行，保留
            alive_pids.append(entry)
        else:
            # 进程已死亡，记录以便清理
            dead_pids.append(entry)
            print(f"清理死亡进程 PID: {pid} ({process_name}) from {cwd}")

    # 更新文件，只保留活跃的 PID
    data['pids'] = alive_pids

    try:
        with open(pid_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"更新 PID 文件失败: {e}")

    return len(dead_pids), len(alive_pids)


def add_pid(pid, process_name=None, cwd=None):
    """
    添加 PID 到文件

    Args:
        pid: 进程 ID
        process_name: 进程名（用于验证，避免 PID 重用）
        cwd: 工作目录（用于验证，避免误杀其他目录的同名进程）
    """
    if pid is None or pid <= 0:
        return

    pid_file = get_pid_file_path()

    # 读取现有数据
    data = {'pids': []}
    if os.path.exists(pid_file):
        try:
            with open(pid_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except (json.JSONDecodeError, Exception):
            # 文件损坏，重新创建
            data = {'pids': []}

    # 检查 PID 是否已存在
    for entry in data['pids']:
        if entry.get('pid') == pid:
            return  # 已存在，不重复添加

    # 如果没有指定 cwd，尝试获取当前进程的工作目录
    if cwd is None:
        cwd = os.getcwd()

    # 添加新 PID
    entry = {
        'pid': pid,
        'name': process_name or 'unknown',
        'cwd': cwd,
        'timestamp': datetime.now().isoformat()
    }
    data['pids'].append(entry)

    # 写回文件
    try:
        with open(pid_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"写入 PID 文件失败: {e}")


def remove_pid(pid):
    """
    从文件移除 PID

    Args:
        pid: 进程 ID
    """
    if pid is None or pid <= 0:
        return

    pid_file = get_pid_file_path()

    if not os.path.exists(pid_file):
        return

    try:
        with open(pid_file, 'r', encoding='utf-8') as f:
            data = json.load(f)

        # 移除指定 PID
        data['pids'] = [e for e in data['pids'] if e.get('pid') != pid]

        # 如果没有 PID 了，删除文件
        if not data['pids']:
            try:
                os.remove(pid_file)
            except Exception:
                pass
        else:
            # 写回文件
            with open(pid_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
    except (json.JSONDecodeError, Exception) as e:
        print(f"更新 PID 文件失败: {e}")


def get_pids():
    """
    获取所有记录的 PID（只返回存活的有效 PID）

    Returns:
        list: PID 列表（已过滤掉死亡或无效的 PID）
    """
    pid_file = get_pid_file_path()

    if not os.path.exists(pid_file):
        return []

    pids = []
    try:
        with open(pid_file, 'r', encoding='utf-8') as f:
            data = json.load(f)

        if isinstance(data, dict) and 'pids' in data:
            for entry in data['pids']:
                pid = entry.get('pid')
                process_name = entry.get('name')
                cwd = entry.get('cwd')
                if pid and is_process_running(pid, process_name, cwd):
                    pids.append(pid)
    except (json.JSONDecodeError, Exception) as e:
        print(f"读取 PID 文件失败: {e}")

    return pids


def get_pid_entries():
    """
    获取所有记录的 PID 条目（包含完整信息）

    Returns:
        list: PID 条目列表，每个条目包含 pid, name, cwd, timestamp
    """
    pid_file = get_pid_file_path()

    if not os.path.exists(pid_file):
        return []

    entries = []
    try:
        with open(pid_file, 'r', encoding='utf-8') as f:
            data = json.load(f)

        if isinstance(data, dict) and 'pids' in data:
            entries = data['pids']
    except (json.JSONDecodeError, Exception) as e:
        print(f"读取 PID 文件失败: {e}")

    return entries


def cleanup_dead_pids():
    """
    清理已死掉的进程 PID（内部使用）

    Returns:
        list: 存活的 PID 列表
    """
    pid_file = get_pid_file_path()

    if not os.path.exists(pid_file):
        return []

    try:
        with open(pid_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except (json.JSONDecodeError, Exception):
        return []

    if not isinstance(data, dict) or 'pids' not in data:
        return []

    alive_pids = []
    dead_pids = []

    for entry in data['pids']:
        pid = entry.get('pid')
        process_name = entry.get('name')
        cwd = entry.get('cwd')
        if is_process_running(pid, process_name, cwd):
            alive_pids.append(pid)
        else:
            dead_pids.append(pid)
            remove_pid(pid)

    return alive_pids


def clear_pids():
    """
    清空 PID 文件
    """
    pid_file = get_pid_file_path()

    if os.path.exists(pid_file):
        try:
            os.remove(pid_file)
        except Exception as e:
            print(f"删除 PID 文件失败: {e}")


def check_launcher_running():
    """
    检查是否有 launcher 在运行

    Returns:
        tuple: (是否在运行, launcher PID)
    """
    entries = get_pid_entries()

    for entry in entries:
        name = entry.get('name', '').lower()
        # 检查多种可能的进程名：launcher、点我启动、python（开发环境）
        if 'launcher' in name or '点我启动' in name or name == 'python':
            pid = entry.get('pid')
            cwd = entry.get('cwd')
            if pid and is_process_running(pid, name, cwd):
                return True, pid

    return False, None


if __name__ == "__main__":
    # 测试代码
    print(f"PID 文件路径: {get_pid_file_path()}")

    # 清理死亡进程
    dead_count, alive_count = cleanup_dead_pids_on_startup()
    print(f"清理了 {dead_count} 个死亡进程，保留了 {alive_count} 个活跃进程")

    # 显示当前记录的 PID
    entries = get_pid_entries()
    print(f"\n当前记录的进程:")
    for entry in entries:
        print(f"  PID: {entry.get('pid')}, 名称: {entry.get('name')}, 目录: {entry.get('cwd')}, 时间: {entry.get('timestamp')}")
