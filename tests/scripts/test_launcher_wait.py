#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""scripts/launchers/launcher.py 的等待状态机与服务身份验证测试"""
import json
import sys
import threading
import time
import unittest

sys.path.insert(0, __import__("pathlib").Path(__file__).resolve().parents[2].as_posix())

# launcher 顶层 import pystray/PIL/ctypes.windll，非 Windows 环境不可导入
launcher = None
if sys.platform == "win32":
    from scripts.launchers import launcher as launcher_mod
    launcher = launcher_mod


@unittest.skipUnless(sys.platform == "win32", "launcher 仅支持 Windows")
class TestWaitForService(unittest.TestCase):
    """wait_for_service 四分支 + 慢启动提醒"""

    def _run(self, health, poll, stop, on_tick=None, slow=0.05, hard=0.2, interval=0.01):
        return launcher.wait_for_service(
            health_check_fn=health,
            proc_poll_fn=poll,
            should_stop_fn=stop,
            on_tick=on_tick,
            slow_warning=slow,
            hard_timeout=hard,
            poll_interval=interval,
        )

    def test_ready(self):
        result = self._run(lambda: True, lambda: None, lambda: False)
        self.assertEqual(result, "ready")

    def test_exited_takes_priority_over_health(self):
        """进程已死时即使端口/健康检查"可达"也必须返回 exited（防端口占用造成假 ready）"""
        result = self._run(lambda: True, lambda: 1, lambda: False)
        self.assertEqual(result, "exited")

    def test_stopped(self):
        result = self._run(lambda: False, lambda: None, lambda: True)
        self.assertEqual(result, "stopped")

    def test_hard_timeout(self):
        start = time.time()
        result = self._run(lambda: False, lambda: None, lambda: False)
        self.assertEqual(result, "timeout")
        self.assertGreaterEqual(time.time() - start, 0.2)

    def test_slow_warning_fires_once_and_keeps_waiting(self):
        """到达慢启动阈值只提醒一次，且不置失败、继续等待直至 ready"""
        slow_events = []

        def on_tick(elapsed, slow_fired):
            if slow_fired:
                slow_events.append(elapsed)

        state = {"checks": 0}

        def health():
            state["checks"] += 1
            return state["checks"] >= 10  # 约 0.1s 后就绪，晚于 slow=0.05

        result = self._run(health, lambda: None, lambda: False, on_tick=on_tick,
                           slow=0.03, hard=5, interval=0.01)
        self.assertEqual(result, "ready")
        self.assertEqual(len(slow_events), 1)


@unittest.skipUnless(sys.platform == "win32", "launcher 仅支持 Windows")
class TestCheckServiceIdentity(unittest.TestCase):
    """_check_service_identity：区分智剧通服务 / 其他程序 / 端口空闲"""

    @classmethod
    def setUpClass(cls):
        from http.server import BaseHTTPRequestHandler, HTTPServer

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                body = json.dumps(self.server.payload).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        cls.Handler = Handler
        cls.HTTPServer = HTTPServer
        cls.servers = []

    @classmethod
    def tearDownClass(cls):
        for srv in cls.servers:
            srv.shutdown()
            srv.server_close()

    def _start_server(self, payload):
        srv = self.HTTPServer(("127.0.0.1", 0), self.Handler)
        srv.payload = payload
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.servers.append(srv)
        return srv.server_address[1]

    def _tray(self):
        # __new__ 跳过 __init__ 的 PID 管理等副作用；方法只依赖 _check_port_available
        return launcher.TrayLauncher.__new__(launcher.TrayLauncher)

    def test_zjt_service_identified(self):
        port = self._start_server({"code": 0, "data": {"app": "ZJT", "status": "ok"}})
        self.assertTrue(self._tray()._check_service_identity(port))

    def test_other_app_rejected(self):
        port = self._start_server({"code": 0, "data": {"app": "something-else"}})
        self.assertFalse(self._tray()._check_service_identity(port))

    def test_closed_port_rejected(self):
        import socket
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        sock.close()
        self.assertFalse(self._tray()._check_service_identity(port))


if __name__ == "__main__":
    unittest.main()
