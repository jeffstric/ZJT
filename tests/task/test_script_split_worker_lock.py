"""script split worker 文件锁的回归测试。

背景：_acquire_worker_lock 曾把探活判断写反（_is_stale_lock True=持有者已死，
却在 True 分支"诚实退出"）——持有者已死不重试、持有者活着反重试；且
PermissionError（进程存在但无权限）被误判为已死。现已复用 scheduler 的
_is_lock_holder_alive 单一实现。本组测试守护分支方向不再抄反。
"""

import fcntl
import os
import sys

import pytest

from scripts.running import run_script_split_worker as worker

# 用大 index 避免与真实运行中的 worker 锁（0..N-1）冲突
TEST_INDEX = 999


@pytest.fixture
def clean_lock_state():
    """隔离 worker 模块的全局锁状态，测试后清理锁文件。"""
    worker._lock_fd = None
    worker._LOCK_FILE = None
    lock_path = os.path.join(
        worker.project_root, f"script_split_worker_{TEST_INDEX}.lock"
    )
    yield lock_path
    if worker._lock_fd is not None:
        try:
            worker._lock_fd.close()
        except Exception:
            pass
        worker._lock_fd = None
    if os.path.exists(lock_path):
        os.remove(lock_path)


@pytest.mark.skipif(sys.platform == "win32", reason="依赖 fcntl，Windows 走 msvcrt 分支")
def test_lock_held_by_alive_process_returns_false(clean_lock_state, caplog):
    """持有者存活（pid=当前进程，flock 被另一 fd 持有）→ 诚实退出。"""
    lock_path = clean_lock_state
    with open(lock_path, "a") as holder:
        holder.write(str(os.getpid()))
        holder.flush()
        fcntl.flock(holder.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        with caplog.at_level("ERROR", logger=worker.__name__):
            assert worker._acquire_worker_lock(TEST_INDEX) is False
    assert "already running" in caplog.text


@pytest.mark.skipif(sys.platform == "win32", reason="依赖 fcntl，Windows 走 msvcrt 分支")
def test_lock_held_by_dead_pid_takes_retry_branch(clean_lock_state, caplog):
    """持有者已死（pid 不存在，flock 被另一 fd 持有）→ 走"重试"分支而非退出。

    回归守护：修复前语义写反，此场景会走 "already running"（已死却不重试）。
    """
    lock_path = clean_lock_state
    # 找一个确定不存在的 pid：进程号上限默认约 4M，取超大值
    dead_pid = 4194304
    with open(lock_path, "a") as holder:
        holder.write(str(dead_pid))
        holder.flush()
        fcntl.flock(holder.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        with caplog.at_level("INFO", logger=worker.__name__):
            # holder 仍持锁：重试一次也失败，最终 False——但必须走的是 retry 分支
            assert worker._acquire_worker_lock(TEST_INDEX) is False
    assert "retrying" in caplog.text
    assert "already running" not in caplog.text


@pytest.mark.skipif(sys.platform == "win32", reason="依赖 fcntl，Windows 走 msvcrt 分支")
def test_lock_free_acquires_and_releases(clean_lock_state):
    """无人持锁 → 成功获取；释放后他人可再获取。"""
    assert worker._acquire_worker_lock(TEST_INDEX) is True
    assert worker._lock_fd is not None

    # 已持有：另一 fd 再 flock 必失败（排他性生效）
    with open(worker._LOCK_FILE, "a") as rival:
        with pytest.raises(OSError):
            fcntl.flock(rival.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    worker._release_worker_lock()
    assert worker._lock_fd is None

    # 释放后他人可获取
    with open(worker._LOCK_FILE, "a") as rival:
        fcntl.flock(rival.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
