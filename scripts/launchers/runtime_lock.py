"""Cross-platform inter-process file locks used by launcher scripts."""

from __future__ import annotations

import os
import time
from pathlib import Path


class InterProcessFileLock:
    """A small standard-library-only exclusive file lock with a hard timeout."""

    def __init__(self, path, *, timeout: float, poll_interval: float):
        self.path = Path(path)
        self.timeout = float(timeout)
        self.poll_interval = float(poll_interval)
        self._file = None

    def acquire(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._file = self.path.open("a+b")
        self._file.seek(0, os.SEEK_END)
        if self._file.tell() == 0:
            self._file.write(b"0")
            self._file.flush()

        deadline = time.monotonic() + self.timeout
        while True:
            try:
                self._lock_once()
                return self
            except (BlockingIOError, OSError):
                if time.monotonic() >= deadline:
                    self._file.close()
                    self._file = None
                    raise TimeoutError(f"Timed out acquiring runtime lock: {self.path}")
                time.sleep(self.poll_interval)

    def _lock_once(self):
        self._file.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(self._file.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(self._file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    def release(self):
        if self._file is None:
            return
        try:
            self._file.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self._file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(self._file.fileno(), fcntl.LOCK_UN)
        finally:
            self._file.close()
            self._file = None

    def __enter__(self):
        return self.acquire()

    def __exit__(self, exc_type, exc_value, traceback):
        self.release()
        return False
