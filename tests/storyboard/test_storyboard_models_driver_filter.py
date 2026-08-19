"""分镜模型列表按驱动可用性过滤。"""
from task.visual_drivers.driver_factory import VideoDriverFactory


def test_missing_status_is_available():
    assert VideoDriverFactory.is_task_available(26, None) is True
    assert VideoDriverFactory.is_task_available(26, {}) is True
    assert VideoDriverFactory.is_task_available(26, {"20": {"available": False}}) is True


def test_explicit_unavailable_is_hidden():
    assert VideoDriverFactory.is_task_available(20, {"20": {"available": False}}) is False
    assert VideoDriverFactory.is_task_available("20", {"20": {"available": False}}) is False


def test_explicit_available_is_kept():
    assert VideoDriverFactory.is_task_available(22, {"22": {"available": True, "missing_configs": []}}) is True
