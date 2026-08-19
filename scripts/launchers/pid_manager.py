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
import shutil
from datetime import datetime


def get_pid_file_path(project_dir=None):
    """获取按项目目录隔离的 PID 文件路径。"""
    project_root = os.path.abspath(project_dir or os.getcwd())
    pid_dir = os.path.join(project_root, 'data', 'runtime')
    os.makedirs(pid_dir, exist_ok=True)
    return os.path.join(pid_dir, 'launcher_pids.json')


def _process_info_from_executable(exe_path):
    if not exe_path or not os.path.isfile(exe_path):
        return None
    return {
        'name': os.path.basename(exe_path),
        'exe': exe_path,
        # Windows does not expose another process's cwd through CIM. Executables
        # shipped inside the project are sufficient for the existing scoped-prefix
        # safety check; processes outside the project remain ineligible for killing.
        'cwd': os.path.dirname(exe_path),
    }


def _get_process_info_with_wmic(pid):
    """Query legacy Windows installations where WMIC is still available."""
    wmic = shutil.which('wmic')
    if not wmic:
        return None
    result = subprocess.run(
        [wmic, 'process', 'where', f'ProcessId={pid}', 'get', 'ExecutablePath', '/format:csv'],
        capture_output=True,
        text=True,
        timeout=10,
        encoding='gbk',
        errors='ignore',
        check=False,
    )
    if result.returncode != 0:
        return None
    for line in result.stdout.splitlines():
        data_line = line.strip()
        if not data_line or data_line.lower().startswith('node,'):
            continue
        candidates = data_line.split(',') if ',' in data_line else [data_line]
        for candidate in candidates:
            info = _process_info_from_executable(candidate.strip())
            if info:
                return info
    return None


def _get_process_info_with_powershell(pid):
    """Query modern Windows versions where WMIC is no longer installed."""
    powershell = shutil.which('powershell') or shutil.which('powershell.exe')
    if not powershell:
        return None
    command = (
        "$OutputEncoding=[Console]::OutputEncoding=[Text.UTF8Encoding]::new();"
        f"$p=Get-CimInstance Win32_Process -Filter \"ProcessId = {int(pid)}\";"
        "if($p){$p.ExecutablePath}"
    )
    result = subprocess.run(
        [powershell, '-NoProfile', '-NonInteractive', '-Command', command],
        capture_output=True,
        text=True,
        timeout=10,
        encoding='utf-8',
        errors='ignore',
        check=False,
    )
    if result.returncode != 0:
        return None
    return _process_info_from_executable(result.stdout.strip())


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
        return _get_process_info_with_wmic(pid) or _get_process_info_with_powershell(pid)

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


def _normalize_path(path):
    """
    标准化路径，用于跨平台比较

    Args:
        path: 原始路径字符串

    Returns:
        str: 标准化后的路径（小写、正斜杠、无末尾斜杠）
    """
    if not path:
        return ''
    return path.lower().replace('\\', '/').rstrip('/')


def _is_same_project(path_a, path_b):
    """
    判断两个路径是否指向同一个项目目录

    Args:
        path_a: 路径 A
        path_b: 路径 B

    Returns:
        bool: 是否为同一项目目录
    """
    if not path_a or not path_b:
        return False
    return _normalize_path(path_a) == _normalize_path(path_b)


def cleanup_dead_pids_on_startup(project_dir=None):
    """
    启动时清理已死亡的进程 PID
    这个函数应该在进程启动时调用，清理上次异常退出残留的 PID

    Args:
        project_dir: 当前项目目录，传入后只清理属于当前项目的 PID，
                     避免误操作其他项目的进程记录

    Returns:
        tuple: (清理的死亡 PID 数量, 保留的活跃 PID 数量)
    """
    pid_file = get_pid_file_path(project_dir)

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

        # 按项目目录过滤：只处理属于当前项目的 PID 条目
        # 避免因共享 PID 文件而误操作其他项目的进程记录
        if project_dir and cwd:
            if not _is_same_project(cwd, project_dir):
                # 属于其他项目的条目，跳过不做处理
                alive_pids.append(entry)
                continue

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

    pid_file = get_pid_file_path(cwd)

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


def remove_pid(pid, project_dir=None):
    """
    从文件移除 PID

    Args:
        pid: 进程 ID
    """
    if pid is None or pid <= 0:
        return

    pid_file = get_pid_file_path(project_dir)

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


def get_pids(project_dir=None):
    """
    获取所有记录的 PID（只返回存活的有效 PID）

    Returns:
        list: PID 列表（已过滤掉死亡或无效的 PID）
    """
    pid_file = get_pid_file_path(project_dir)

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


def get_pid_entries(project_dir=None):
    """
    获取所有记录的 PID 条目（包含完整信息）

    Args:
        project_dir: 项目目录，传入后只返回属于当前项目的条目

    Returns:
        list: PID 条目列表，每个条目包含 pid, name, cwd, timestamp
    """
    pid_file = get_pid_file_path(project_dir)

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

    # 按项目目录过滤
    if project_dir:
        entries = [
            e for e in entries
            if e.get('cwd') and _is_same_project(e['cwd'], project_dir)
        ]

    return entries


def cleanup_dead_pids(project_dir=None):
    """
    清理已死掉的进程 PID（内部使用）

    Args:
        project_dir: 项目目录，传入后只清理属于当前项目的 PID

    Returns:
        list: 存活的 PID 列表
    """
    pid_file = get_pid_file_path(project_dir)

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

        # 按项目目录过滤
        if project_dir and cwd:
            if not _is_same_project(cwd, project_dir):
                alive_pids.append(pid)
                continue

        if is_process_running(pid, process_name, cwd):
            alive_pids.append(pid)
        else:
            dead_pids.append(pid)
            remove_pid(pid, project_dir=project_dir or cwd)

    return alive_pids


def clear_pids(project_dir=None):
    """
    清空 PID 记录

    Args:
        project_dir: 项目目录，传入后只清除属于当前项目的 PID 条目，
                     不传入则清空整个 PID 文件（旧行为）
    """
    pid_file = get_pid_file_path(project_dir)

    if not os.path.exists(pid_file):
        return

    # 如果指定了项目目录，只移除属于当前项目的条目
    if project_dir:
        try:
            with open(pid_file, 'r', encoding='utf-8') as f:
                data = json.load(f)

            if isinstance(data, dict) and 'pids' in data:
                data['pids'] = [
                    e for e in data['pids']
                    if not (e.get('cwd') and _is_same_project(e['cwd'], project_dir))
                ]

                if not data['pids']:
                    try:
                        os.remove(pid_file)
                    except Exception:
                        pass
                else:
                    with open(pid_file, 'w', encoding='utf-8') as f:
                        json.dump(data, f, indent=2, ensure_ascii=False)
        except (json.JSONDecodeError, Exception) as e:
            print(f"按项目清理 PID 文件失败: {e}")
        return

    # 未指定项目目录，清空整个文件
    try:
        os.remove(pid_file)
    except Exception as e:
        print(f"删除 PID 文件失败: {e}")


def check_launcher_running(project_dir=None):
    """
    检查是否有 launcher 在运行

    Args:
        project_dir: 项目目录，传入后只检查属于当前项目的 launcher

    Returns:
        tuple: (是否在运行, launcher PID)
    """
    entries = get_pid_entries(project_dir=project_dir)

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
    print(f"PID 文件路径: {get_pid_file_path(os.getcwd())}")

    # 使用当前工作目录作为项目目录进行过滤
    current_project = os.getcwd()
    print(f"当前项目目录: {current_project}")

    # 清理死亡进程（只处理当前项目的 PID）
    dead_count, alive_count = cleanup_dead_pids_on_startup(project_dir=current_project)
    print(f"清理了 {dead_count} 个死亡进程，保留了 {alive_count} 个活跃进程")

    # 显示当前记录的 PID
    entries = get_pid_entries(project_dir=current_project)
    print(f"\n当前项目的进程:")
    for entry in entries:
        print(f"  PID: {entry.get('pid')}, 名称: {entry.get('name')}, 目录: {entry.get('cwd')}, 时间: {entry.get('timestamp')}")
