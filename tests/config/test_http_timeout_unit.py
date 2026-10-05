"""timeout.request_timeout 从毫秒配置换算成 HTTP 客户端使用的秒。"""
from unittest.mock import MagicMock, patch

from api.clients.duomi_client import _http_timeout as duomi_http_timeout
from api.clients.vidu_client import _http_timeout as vidu_http_timeout
from config.config_util import get_dynamic_config_value, invalidate_dynamic_cache
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


def _ok_response():
    response = MagicMock()
    response.status_code = 200
    response.headers = {}
    response.json.return_value = {"ok": True}
    response.text = ""
    return response


def test_database_keeps_10000_and_http_client_receives_10_seconds():
    """已入库的 10000 原样读出，视觉驱动发给 requests 时换成 10 秒。"""
    row = MagicMock()
    row.config_value = "10000"
    row.get_typed_value.return_value = 10000

    invalidate_dynamic_cache()
    try:
        with patch("model.system_config.SystemConfigModel.get_by_key", return_value=row):
            stored = get_dynamic_config_value("timeout", "request_timeout", default=30)
        assert stored == 10000

        driver = _DummyDriver()
        driver._timeout = stored
        with patch("task.visual_drivers.base_video_driver.requests.request", return_value=_ok_response()) as request:
            driver._request(url="https://example.test/status", method="GET", json=None, headers={})
        assert request.call_args.kwargs["timeout"] == 10
    finally:
        invalidate_dynamic_cache()


def test_sync_timeout_in_seconds_is_not_divided():
    """同步接口的 300 秒不能被当成毫秒。"""
    driver = _DummyDriver()
    driver._timeout = 10000
    with patch("task.visual_drivers.base_video_driver.requests.request", return_value=_ok_response()) as request:
        driver._request(
            url="https://example.test/generate",
            method="POST",
            json={},
            headers={},
            timeout=300,
        )
    assert request.call_args.kwargs["timeout"] == 300


def test_legacy_clients_convert_database_value_before_request():
    with patch("api.clients.duomi_client.get_dynamic_config_value", return_value=10000):
        assert duomi_http_timeout() == 10
    with patch("api.clients.vidu_client.get_dynamic_config_value", return_value=10000):
        assert vidu_http_timeout() == 10
