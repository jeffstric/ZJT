#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""scripts/tools/install_python.ps1 的 Windows 条件测试。

核心断言（对应托盘链路 P0 问题）：
- 下载进程按 PID 精确管理：成功路径不傻等、超时路径只杀本次下载进程
- 长期存活的外层进程（模拟托盘常驻的 uv.exe）不受任何影响
"""
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PS1 = ROOT / "scripts" / "tools" / "install_python.ps1"
UV = ROOT / "bin" / "uv" / "uv.exe"
SYSTEM32 = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"


def run_ps1(*args, env_extra=None, timeout=120):
    cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(PS1)]
    cmd += [str(a) for a in args]
    env = dict(os.environ)
    if env_extra:
        env.update(env_extra)
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env)


@unittest.skipUnless(sys.platform == "win32", "Windows only")
class TestPs1Syntax(unittest.TestCase):
    def test_ps1_parses(self):
        cmd = [
            "powershell", "-NoProfile", "-Command",
            f"$errs=$null; [void][System.Management.Automation.PSParser]::Tokenize("
            f"(Get-Content -Raw -LiteralPath '{PS1}'), [ref]$errs); "
            "if ($errs.Count -gt 0) { $errs | ForEach-Object { Write-Host $_.Message }; exit 1 }",
        ]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


@unittest.skipUnless(sys.platform == "win32", "Windows only")
@unittest.skipUnless(UV.exists(), "bundled uv not found")
class TestInstallPythonPs1(unittest.TestCase):
    def setUp(self):
        # 长存进程：模拟托盘链路常驻的外层 uv.exe，ps1 在任何路径下都不得触碰它
        self.outer = subprocess.Popen(
            [str(SYSTEM32 / "ping.exe"), "-n", "120", "127.0.0.1"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        self.log_dir = tempfile.mkdtemp(prefix="zjt_ps1_test_")

    def tearDown(self):
        if self.outer.poll() is None:
            self.outer.kill()
            self.outer.wait()
        shutil.rmtree(self.log_dir, ignore_errors=True)

    def _silent_server(self):
        """接受连接但永不响应的本地服务，让 uv 确定性地挂起（uv 允许 localhost 走 http）"""
        srv = socket.socket()
        srv.bind(("127.0.0.1", 0))
        srv.listen(5)

        def _serve():
            try:
                while True:
                    conn, _ = srv.accept()
                    try:
                        conn.recv(4096)
                        time.sleep(60)
                    finally:
                        conn.close()
            except OSError:
                pass

        threading.Thread(target=_serve, daemon=True).start()
        self.addCleanup(srv.close)
        return f"http://127.0.0.1:{srv.getsockname()[1]}/mirror"

    def _read_log(self, path):
        with open(path, encoding="utf-8-sig") as f:
            return f.read()

    def test_short_circuit_when_already_installed(self):
        """已安装时前置短路：不进入下载流程、快速返回、不碰外层进程"""
        local_python = ROOT / "bin" / "python"
        if not list(local_python.glob("cpython-3.10*-windows-x86_64-none")):
            self.skipTest("本机 bin/python 无托管 Python，无法验证短路路径")
        log = os.path.join(self.log_dir, "short_circuit.log")
        start = time.time()
        r = run_ps1("-UvCmd", UV, "-LogFile", log,
                    env_extra={"UV_PYTHON_INSTALL_DIR": str(local_python)})
        self.assertLess(time.time() - start, 30)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        content = self._read_log(log)
        self.assertIn("short-circuit", content)
        self.assertNotIn("Trying mirror", content)
        self.assertIsNone(self.outer.poll())

    def test_timeout_kills_only_download_pid(self):
        """超时：只 taskkill 本次下载进程树，外层长存进程存活"""
        log = os.path.join(self.log_dir, "timeout.log")
        url = self._silent_server()
        start = time.time()
        r = run_ps1("-UvCmd", UV, "-LogFile", log,
                    "-MirrorUrlOverride", url, "-TimeoutOverrideSec", "2",
                    env_extra={"UV_PYTHON_INSTALL_DIR": os.path.join(self.log_dir, "py"),
                               "UV_PYTHON_PREFERENCE": "only-managed"},
                    timeout=90)
        elapsed = time.time() - start
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertLess(elapsed, 30, "超时被拉长，疑似计时失效")
        content = self._read_log(log)
        m = re.search(r"killing pid (\d+)", content)
        self.assertIsNotNone(m, "未触发按 PID 终止: " + content)
        pid = m.group(1)
        out = subprocess.run([str(SYSTEM32 / "tasklist.exe"), "/FI", f"PID eq {pid}"],
                             capture_output=True, text=True).stdout
        self.assertNotIn(pid, out, "下载进程未被终止")
        self.assertIsNone(self.outer.poll(), "外层长存进程被误杀")

    def test_no_fallback_single_attempt(self):
        """NoFallback：只试一个镜像即失败返回"""
        log = os.path.join(self.log_dir, "nofallback.log")
        r = run_ps1("-UvCmd", UV, "-LogFile", log,
                    "-Request", "cpython-9.99-windows-x86_64-none",
                    "-StartMirrorIdx", "4", "-NoFallback",
                    env_extra={"UV_PYTHON_INSTALL_DIR": os.path.join(self.log_dir, "py")},
                    timeout=90)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        content = self._read_log(log)
        self.assertEqual(content.count("Trying mirror"), 1, content)
        self.assertIsNone(self.outer.poll())


if __name__ == "__main__":
    unittest.main()
