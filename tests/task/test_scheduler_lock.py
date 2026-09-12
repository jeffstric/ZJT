"""
调度器文件锁回归测试（修复：批量启动/重启导致多实例同时持锁，生产曾积累 31 个调度器进程）

关键语义：
  - 锁文件用 'a' 模式打开（不截断持有者记录），排他性完全由 flock/msvcrt 文件锁承担；
  - flock 随持有进程死亡由内核自动释放 → "死持有者"场景重试即可获取，无需删除重建锁文件；
  - 持有者存活时第二次获取必须诚实失败。
"""
import os
import signal
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


# ---------------------------------------------------------------------------
# 补充场景：锁文件完整性、陈旧残留自愈、强杀/优雅重启交接、防孤儿看门狗
# ---------------------------------------------------------------------------

def _write_helper_raw(path, code):
    with open(path, 'w', encoding='utf-8') as f:
        f.write(code)


def _sigterm_release_helper_code(lock_path):
    """持有者 helper：拿锁后驻留，收到 SIGTERM 时优雅释放锁再退出（模拟正常重启）"""
    return "\n".join([
        "import sys, time, signal",
        "sys.path.insert(0, r'%s')" % PROJECT_ROOT.replace(BS, BS + BS),
        "from task.scheduler import _acquire_scheduler_lock, _release_scheduler_lock",
        "ok = _acquire_scheduler_lock(lock_file=r'%s')" % lock_path.replace(BS, BS + BS),
        "print('OK' if ok else 'FAIL', flush=True)",
        "def _term(signum, frame):",
        "    _release_scheduler_lock()",
        "    print('RELEASED', flush=True)",
        "    sys.exit(0)",
        "signal.signal(signal.SIGTERM, _term)",
        "time.sleep(15)",
    ])


def _retrying_helper_code(lock_path):
    """等待者 helper：循环重试获取锁，直到成功或超时"""
    return "\n".join([
        "import sys, time",
        "sys.path.insert(0, r'%s')" % PROJECT_ROOT.replace(BS, BS + BS),
        "from task.scheduler import _acquire_scheduler_lock",
        "deadline = time.time() + 10",
        "ok = False",
        "while time.time() < deadline:",
        "    if _acquire_scheduler_lock(lock_file=r'%s'):" % lock_path.replace(BS, BS + BS),
        "        ok = True",
        "        break",
        "    time.sleep(0.2)",
        "print('OK' if ok else 'FAIL', flush=True)",
    ])


def test_refused_acquire_preserves_lock_file(lock_file, lock_file2):
    """回归（生产事故核心）：获取被拒时，持有者的锁文件内容与 inode 必须原样保留。

    旧实现 'w' 截断清空内容 + 失败后删除重建（换 inode），正是 31 个调度器
    同时"持锁"的根因。
    """
    helper_path = os.path.join(_make_temp_dir("lock_helper_"), "lock_helper.py")
    _write_helper(helper_path, lock_file2, extra='time.sleep(8)')
    holder = subprocess.Popen(
        [sys.executable, helper_path],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
    )
    try:
        line = holder.stdout.readline().strip()
        assert line == 'OK', '持有者子进程获取失败: ' + line
        holder_pid = _read_lock_pid(lock_file2)
        inode_before = os.stat(lock_file2).st_ino

        assert _acquire_scheduler_lock(lock_file=lock_file2) is False

        assert os.stat(lock_file2).st_ino == inode_before, '锁文件被删除重建（inode 变化）'
        assert _read_lock_pid(lock_file2) == holder_pid, '持有者 PID 记录被破坏'
    finally:
        holder.kill()
        holder.wait()


@pytest.mark.parametrize("stale_content_mode", ["empty", "garbage", "dead_pid"])
def test_acquire_overrides_stale_lock_file_contents(lock_file, stale_content_mode):
    """陈旧/异常残留的锁文件不应阻止启动：空文件、垃圾内容、死 PID 均可直接获取并覆盖。

    旧实现把空文件误判为"残留死锁"进而强抢；新实现下这些场景第一次 flock 即成功。
    """
    if stale_content_mode == "dead_pid":
        p = subprocess.Popen([sys.executable, "-c", "pass"])
        p.wait()
        content = str(p.pid)
    elif stale_content_mode == "empty":
        content = ""
    else:
        content = "garbage-not-a-pid"
    with open(lock_file, "w", encoding="utf-8") as f:
        f.write(content)

    assert _acquire_scheduler_lock(lock_file=lock_file) is True
    assert _read_lock_pid(lock_file) == os.getpid()
    _release_scheduler_lock()


def test_kill9_holder_then_immediate_acquire(lock_file):
    """强杀场景：持有者被 kill -9 后，新实例必须立即获取锁（无需任何人工清理）"""
    helper_path = os.path.join(_make_temp_dir("lock_helper_"), "lock_helper.py")
    _write_helper(helper_path, lock_file, extra='time.sleep(8)')
    holder = subprocess.Popen(
        [sys.executable, helper_path],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
    )
    try:
        line = holder.stdout.readline().strip()
        assert line == 'OK', '持有者子进程获取失败: ' + line
        holder.kill()  # SIGKILL
        holder.wait()
        time.sleep(0.3)  # 等内核回收锁
        assert _acquire_scheduler_lock(lock_file=lock_file) is True, \
            '强杀持有者后锁未释放，重启无法自愈'
        _release_scheduler_lock()
    finally:
        if holder.poll() is None:
            holder.kill()
            holder.wait()


@pytest.mark.skipif(sys.platform == "win32", reason="Windows 上 send_signal(SIGTERM) 走 TerminateProcess，Python 信号 handler 不执行，无法验证优雅释放路径")
def test_graceful_terminated_holder_then_next_acquires(lock_file):
    """正常重启场景：持有者收到 SIGTERM 优雅释放后，新实例立即获取成功"""
    helper_path = os.path.join(_make_temp_dir("lock_helper_"), "lock_helper_sigterm.py")
    _write_helper_raw(helper_path, _sigterm_release_helper_code(lock_file))
    holder = subprocess.Popen(
        [sys.executable, helper_path],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
    )
    try:
        line = holder.stdout.readline().strip()
        assert line == 'OK', '持有者子进程获取失败: ' + line
        holder.send_signal(signal.SIGTERM)
        assert holder.stdout.readline().strip() == 'RELEASED', '持有者未优雅释放'
        holder.wait(timeout=5)
        assert _acquire_scheduler_lock(lock_file=lock_file) is True
        _release_scheduler_lock()
    finally:
        if holder.poll() is None:
            holder.kill()
            holder.wait()


@pytest.mark.skipif(sys.platform == "win32", reason="Windows 上 send_signal(SIGTERM) 走 TerminateProcess，Python 信号 handler 不执行，无法验证优雅释放路径")
def test_waiter_acquires_after_holder_releases(lock_file):
    """交接场景：等待者循环重试期间被持续拒绝；持有者一释放即无缝接手"""
    holder_path = os.path.join(_make_temp_dir("lock_helper_"), "lock_helper_sigterm.py")
    _write_helper_raw(holder_path, _sigterm_release_helper_code(lock_file))
    holder = subprocess.Popen(
        [sys.executable, holder_path],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
    )
    try:
        line = holder.stdout.readline().strip()
        assert line == 'OK', '持有者子进程获取失败: ' + line
        # 必须等持有者拿锁成功后再启动等待者，避免两者竞争初始锁
        waiter_path = os.path.join(_make_temp_dir("lock_helper_"), "lock_helper_waiter.py")
        _write_helper_raw(waiter_path, _retrying_helper_code(lock_file))
        waiter = subprocess.Popen(
            [sys.executable, waiter_path],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
        )
        time.sleep(0.6)  # 让等待者先经历若干次被拒
        holder.send_signal(signal.SIGTERM)
        assert holder.stdout.readline().strip() == 'RELEASED'
        holder.wait(timeout=5)
        # 等待者应在重试窗口内拿到锁
        assert waiter.stdout.readline().strip() == 'OK', '持有者释放后等待者未能接手'
        waiter.wait(timeout=5)
    finally:
        for p in (holder, waiter):
            if p.poll() is None:
                p.kill()
                p.wait()


def test_parent_process_dead_detection():
    """防孤儿看门狗：真实父 PID → 存活；假 PID → 已死亡"""
    from task.scheduler import parent_process_dead
    assert parent_process_dead(os.getppid()) is False
    assert parent_process_dead(os.getppid() + 1000000) is True


@pytest.mark.skipif(sys.platform != "win32", reason="仅 Windows 可验证 _win_process_alive 的句柄未回收路径")
def test_win_process_alive_false_for_exited_child_with_open_handle():
    """子进程已退出、但父进程仍持有其句柄（Popen.wait() 后对象未销毁）时，
    OpenProcess 照样成功——旧实现（OpenProcess 成功即存活）在此误判为活，
    会把看门狗和锁探活一起卡死在"永远等不到死"。

    新实现必须经 GetExitCodeProcess == STILL_ACTIVE 判真死。
    本用例是守护该修复的唯一真实路径：PID 不存在或句柄已回收的场景
    旧实现也能通过，无法暴露回归。
    """
    from task.scheduler import _win_process_alive

    proc = subprocess.Popen([sys.executable, "-c", "import sys; sys.exit(0)"])
    try:
        proc.wait()
        # proc 对象保持引用：其 _handle 仍打开，模拟"已退出但句柄未回收"
        assert proc.returncode == 0
        assert _win_process_alive(proc.pid) is False
    finally:
        proc.poll()
