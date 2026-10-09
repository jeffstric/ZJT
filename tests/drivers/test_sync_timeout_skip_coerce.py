"""sync_request_timeout 来源的驱动超时跳过毫秒启发式（#8）。

coerce_http_timeout_seconds 的 "≥1000 按毫秒除 1000" 只对 timeout.request_timeout
（毫秒语义）正确；timeout.sync_request_timeout 是纯秒语义且 gpt_image 会 ×2 放大，
运营按文档把秒配大（如 500，×2=1000）会被误压成 1 秒，驱动所有同步请求必超时。
修复：四个 sync_request_timeout 驱动设 _skip_timeout_coerce=True，
base_video_driver._make_request 对其跳过换算。
"""
import logging
from unittest.mock import patch

import pytest

from task.visual_drivers.base_video_driver import BaseVideoDriver

os_env = None


class _StubDriver(BaseVideoDriver):
    """桩掉抽象方法，只测 _make_request 的超时处理"""

    def build_check_query(self, *a, **k):
        return {}

    def build_create_request(self, *a, **k):
        return {}

    def check_status(self, *a, **k):
        return {}

    def submit_task(self, *a, **k):
        return {}


def _make_base_driver(skip_coerce=False, timeout=None):
    """绕过重量级 __init__，只构造 _make_request 依赖的属性"""
    driver = _StubDriver.__new__(_StubDriver)
    driver.logger = logging.getLogger("test_sync_timeout")
    driver.driver_name = "test_driver"
    if timeout is not None:
        driver._timeout = timeout
    if skip_coerce:
        driver._skip_timeout_coerce = True
    return driver


class _FakeResponse:
    status_code = 200
    text = "{}"
    headers = {}

    def json(self):
        return {}

    def raise_for_status(self):
        return None


def _captured_timeout(mock_request):
    return mock_request.call_args.kwargs["timeout"]


def test_sync_driver_timeout_not_divided_by_1000():
    """sync_request_timeout=500 ×2=1000 秒：跳过换算，原样传给 requests"""
    driver = _make_base_driver(skip_coerce=True, timeout=1000)
    with patch("requests.request", return_value=_FakeResponse()) as mock_req:
        driver._request("https://example.com/api")
    assert _captured_timeout(mock_req) == 1000


def test_sync_driver_large_seconds_preserved():
    driver = _make_base_driver(skip_coerce=True, timeout=1200)
    with patch("requests.request", return_value=_FakeResponse()) as mock_req:
        driver._request("https://example.com/api")
    assert _captured_timeout(mock_req) == 1200


def test_regular_driver_still_coerces_millisecond_values():
    """request_timeout 来源（默认驱动）回归：10000 毫秒仍换算成 10 秒"""
    driver = _make_base_driver(timeout=10000)
    with patch("requests.request", return_value=_FakeResponse()) as mock_req:
        driver._request("https://example.com/api")
    assert _captured_timeout(mock_req) == 10.0


def test_regular_driver_small_seconds_unchanged():
    driver = _make_base_driver(timeout=30)
    with patch("requests.request", return_value=_FakeResponse()) as mock_req:
        driver._request("https://example.com/api")
    assert _captured_timeout(mock_req) == 30


def test_four_sync_drivers_carry_the_flag():
    """四个 sync_request_timeout 驱动实例属性必须带跳过标志（防后续新增驱动漏设）"""
    from task.visual_drivers import (
        gpt_image_common_v1_driver,
        gemini_image_preview_common_v1_driver,
        seedream_volcengine_v1_driver,
        seedream_volcengine_oversea_v1_driver,
    )

    for mod in (
        gpt_image_common_v1_driver,
        gemini_image_preview_common_v1_driver,
        seedream_volcengine_v1_driver,
        seedream_volcengine_oversea_v1_driver,
    ):
        source = open(mod.__file__, encoding="utf-8").read()
        assert "_skip_timeout_coerce = True" in source, mod.__name__
        assert "sync_request_timeout" in source, mod.__name__
