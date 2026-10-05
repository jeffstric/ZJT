"""timeout.request_timeout 从毫秒配置换算成 HTTP 客户端使用的秒。"""
from unittest.mock import MagicMock, patch

from config.constant import coerce_http_timeout_seconds
from task.visual_drivers.base_video_driver import BaseVideoDriver


class _DummyDriver(BaseVideoDriver):
    def __init__(self):
        self.driver_name = "dummy"
        self.logger = MagicMock()
        self._timeout = 10000

    def submit_task(self, ai_tool):
        return {}

    def check_status(self, project_id):
        return {}

    def build_create_request(self, ai_tool):
        return {}

    def build_check_query(self, project_id):
        return {}


def test_legacy_millisecond_config_becomes_ten_seconds():
    assert coerce_http_timeout_seconds(10000) == 10
    assert coerce_http_timeout_seconds("10000") == 10


def test_values_already_in_seconds_stay_unchanged():
    assert coerce_http_timeout_seconds(10) == 10
    assert coerce_http_timeout_seconds(30) == 30
    assert coerce_http_timeout_seconds(300) == 300
    assert coerce_http_timeout_seconds(600) == 600


def test_missing_or_invalid_value_uses_default():
    assert coerce_http_timeout_seconds(None) == 30
    assert coerce_http_timeout_seconds(0) == 30
    assert coerce_http_timeout_seconds(-1) == 30
    assert coerce_http_timeout_seconds("bad", default=15) == 15


def test_video_driver_request_passes_seconds_to_requests():
    driver = _DummyDriver()
    response = MagicMock()
    response.status_code = 200
    response.headers = {}
    response.json.return_value = {"ok": True}
    response.text = ""

    with patch("task.visual_drivers.base_video_driver.requests.request", return_value=response) as request:
        driver._request(url="https://example.test/status", method="GET", json=None, headers={})

    assert request.call_args.kwargs["timeout"] == 10
