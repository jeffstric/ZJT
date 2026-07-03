import logging
import os
import signal
import time


logger = logging.getLogger(__name__)


def terminate_worker_process(pid: int, grace_seconds: float = 2.0) -> bool:
    if not pid or pid <= 0:
        return False

    try:
        if os.name == "nt":
            import subprocess

            result = subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                capture_output=True,
                text=True,
                timeout=max(grace_seconds, 1.0) + 3.0,
            )
            if result.returncode != 0:
                logger.warning("taskkill failed for pid=%s stderr=%s", pid, result.stderr)
                return False
            return True

        os.kill(pid, signal.SIGTERM)
        deadline = time.time() + grace_seconds
        while time.time() < deadline:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return True
            time.sleep(0.05)

        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            return True
        return True
    except ProcessLookupError:
        return True
    except Exception as exc:
        logger.error("Failed to terminate worker process pid=%s: %s", pid, exc)
        return False
