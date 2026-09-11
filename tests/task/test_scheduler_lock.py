"""
调度器文件锁回归测试（修复：批量启动/重启导致多实例同时持锁，生产曾积累 31 个调度器进程）

关键语义：
  - 锁文件用 'a' 模式打开（不截断持有者记录），排他性完全由 flock/msvcrt 文件锁承担；
  - flock 随持有进程死亡由内核自动释放 → "死持有者"场景重试即可获取，无需删除重建锁文件；
  - 持有者存活时第二次获取必须诚实失败。
"""
import os
import subprocess
import sys
import time

import pytest

from task.scheduler import (
    _acquire_scheduler_lock,
    _is_lock_holder_alive,
    _release_scheduler_lock,
)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BS = chr(92)  # 反斜杠（构造原始字符串路径用）


def _make_temp_dir(prefix):
    import tempfile
    return tempfile.mkdtemp(prefix=prefix)


@pytest.fixture
def lock_file():
    d = _make_temp_dir("scheduler_lock_test_")
    path = os.path.join(d, "scheduler.lock")
    yield path
    import shutil
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def lock_file2():
    d = _make_temp_dir("scheduler_lock_test2_")
    path = os.path.join(d, "scheduler.lock2")
    yield path
    import shutil
    shutil.rmtree(d, ignore_errors=True)


def _read_lock_pid(path):
    with open(path, encoding="utf-8") as f:
        content = f.read().strip()
    return int(content) if content.isdigit() else None


def test_acquire_success_records_pid(lock_file):
    assert _acquire_scheduler_lock(lock_file=lock_file) is True
    assert _read_lock_pid(lock_file) == os.getpid()
    _release_scheduler_lock()


@pytest.mark.skipif(sys.platform == "win32", reason="msvcrt 允许同进程重复加锁，与 flock 语义不同")
def test_second_acquire_fails_while_held(lock_file):
    # Linux flock：同进程经由新 fd 的 flock 同样会被拒绝（按 open file description 排他）
    assert _acquire_scheduler_lock(lock_file=lock_file) is True
    assert _acquire_scheduler_lock(lock_file=lock_file) is False
    _release_scheduler_lock()


def test_release_then_reacquire(lock_file):
    assert _acquire_scheduler_lock(lock_file=lock_file) is True
    _release_scheduler_lock()
    assert _acquire_scheduler_lock(lock_file=lock_file) is True
    _release_scheduler_lock()


def test_dead_holder_allows_acquire(lock_file):
    """锁文件中的 pid 已死亡：flock 应自动可获取（死持有者场景）"""
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    with open(lock_file, "w", encoding="utf-8") as f:
        f.write(str(p.pid))
    # 注意：Windows 上 os.kill(pid,0) 与 pid 复用语义不同，这里只验证核心行为：
    # 死持有者（无人持有 flock）→ 获取成功
    assert _acquire_scheduler_lock(lock_file=lock_file) is True
    _release_scheduler_lock()


def _write_helper(path, lock_path, extra=""):
    q = chr(39)
    lines = [
        'import sys, time',
        'sys.path.insert(0, r"@ROOT@")',
        'from task.scheduler import _acquire_scheduler_lock',
        'ok = _acquire_scheduler_lock(lock_file=r"@LOCK@")',
        "print('OK' if ok else 'FAIL', flush=True)",
    ]
    if extra:
        lines.append(extra)
    code = chr(10).join(lines)
    code = code.replace('@ROOT@', PROJECT_ROOT.replace(BS, BS + BS)).replace('@LOCK@', lock_path.replace(BS, BS + BS))
    with open(path, 'w', encoding='utf-8') as f:
        f.write(code)


def test_live_holder_blocks_acquire(lock_file, lock_file2):
    """存活进程持有 flock 时：新的获取必须诚实失败"""
    helper_path = os.path.join(_make_temp_dir("lock_helper_"), "lock_helper.py")
    _write_helper(helper_path, lock_file2, extra='time.sleep(8)')
    holder = subprocess.Popen(
        [sys.executable, helper_path],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
    )
    try:
        line = holder.stdout.readline().strip()
        assert line == 'OK', '持有者子进程获取失败: ' + line
        assert _is_lock_holder_alive(lock_file2) is True
        assert _acquire_scheduler_lock(lock_file=lock_file2) is False
    finally:
        holder.kill()
        holder.wait()


def test_concurrent_acquirers_exactly_one_wins(lock_file):
    """回归：批量同时启动只允许一个实例获得锁（修复 31 进程重复的根因）"""
    helper_path = os.path.join(_make_temp_dir("lock_helper_"), "lock_helper.py")
    _write_helper(helper_path, lock_file)
    procs = [
        subprocess.Popen([sys.executable, helper_path],
                         stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        for _ in range(4)
    ]
    outs = [p.communicate(timeout=60)[0].strip() for p in procs]
    wins = [o for o in outs if o == 'OK']
    assert len(wins) == 1, '应恰好 1 个成功: ' + repr(outs)


def test_lock_holder_alive_detection(lock_file):
    """_is_lock_holder_alive：活 PID → True；死 PID / 非法内容 → False"""
    with open(lock_file, "w", encoding="utf-8") as f:
        f.write("not-a-pid")
    assert _is_lock_holder_alive(lock_file) is False

    with open(lock_file, "w", encoding="utf-8") as f:
        f.write(str(os.getpid()))
    assert _is_lock_holder_alive(lock_file) is True

    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    with open(lock_file, "w", encoding="utf-8") as f:
        f.write(str(p.pid))
    assert _is_lock_holder_alive(lock_file) is False


@pytest.mark.skipif(not hasattr(os, "fork"), reason="fork 仅 POSIX 平台可用")
def test_forked_child_does_not_hold_lock_after_parent_death(lock_file, lock_file2):
    """回归：调度器 fork 的 worker 子进程不得继承锁 fd。

    主进程被强杀后，锁必须立即可被新实例获取（at_fork 阻断继承生效）。
    修复前：worker 继承 open file description，主进程死后锁仍被持有，
    新调度器永远无法启动，只能人工清理。
    """
    helper_path = os.path.join(_make_temp_dir("lock_helper_fork_"), "lock_helper_fork.py")
    fork_extra = "\n".join([
        "import os",
        "c = os.fork()",
        "if c == 0:",
        "    time.sleep(15)",
        "    os._exit(0)",
        "time.sleep(15)",
    ])
    _write_helper(helper_path, lock_file2, extra=fork_extra)
    holder = subprocess.Popen(
        [sys.executable, helper_path],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
    )
    try:
        line = holder.stdout.readline().strip()
        assert line == 'OK', '持有者子进程获取失败: ' + line
        time.sleep(0.5)  # 等 fork 出 worker
        holder.kill()
        holder.wait()
        time.sleep(0.3)  # 等内核回收
        # worker 仍存活（15s sleep），但不应再持有锁
        assert _acquire_scheduler_lock(lock_file=lock_file2) is True, \
            'worker 继承了锁 fd，主进程死后锁未释放（at_fork 阻断未生效）'
        _release_scheduler_lock()
    finally:
        # 清理孤儿 worker（15s sleep 自然退出前的兜底）
        subprocess.run(["pkill", "-f", "lock_helper_fork.py"], capture_output=True)
