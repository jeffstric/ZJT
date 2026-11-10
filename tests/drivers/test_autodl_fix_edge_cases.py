"""上线前边界对抗测试：钩子异常输入、修饰符合并鲁棒性、5xx 边界、payload 异常值。"""
from unittest.mock import MagicMock, patch
from types import SimpleNamespace

import pytest
import requests

from task.visual_drivers.minimax_h3_autodl_v1_driver import (
    MinimaxH3AutodlV1Driver,
    MinimaxH3FirstLastAutodlV1Driver,
    MinimaxH3ReferenceAutodlV1Driver,
)

MODULE = "task.visual_drivers.minimax_h3_autodl_v1_driver"


def make_driver(cls=MinimaxH3ReferenceAutodlV1Driver, workflow_id="minimax_h3_zm_u24", driver_type=37):
    driver = cls.__new__(cls)
    driver._workflow_id = workflow_id
    driver._base_url = "https://autodl.art"
    driver._api_key = "test-token"
    driver._timeout = 30
    driver._config = {}
    driver._test_mode_enabled = False
    driver._mock_video_url = None
    driver.logger = MagicMock()
    return driver


def make_tool(**overrides):
    base = {
        "id": 1, "type": 37, "image_path": None, "image_path_2": None,
        "reference_images": '["a.png"]', "audio_path": None, "video_path": None,
        "prompt": "p", "duration": 5, "ratio": "9:16", "extra_config": '{"image_mode": "multi_reference"}',
        "message": None,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def make_first_last_tool(**overrides):
    base = {
        "id": 2, "type": 34, "image_path": "first.png,last.png", "reference_images": None,
        "audio_path": None, "video_path": None, "prompt": "p", "duration": 5,
        "ratio": "9:16", "extra_config": '{"image_mode": "first_last_frame"}', "message": None,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


# ==================== 钩子异常输入（不得抛异常，按兼容处理） ====================

class TestHookRobustInput:
    """畸形 extra_config 由 parse_image_mode 回退，钩子仍按素材判断；其它异常继续抛出。"""

    def setup_method(self):
        self.ref_driver = make_driver()
        self.fl_driver = make_driver(MinimaxH3FirstLastAutodlV1Driver, "minimax_h3_lightx2v", 34)

    def test_extra_config_none(self):
        tool = make_tool(extra_config=None)
        assert self.ref_driver.validate_input_compatibility(tool) == (True, None)
        assert self.fl_driver.validate_input_compatibility(
            make_first_last_tool(extra_config=None))[0] is True  # 双图兼容

    def test_extra_config_empty_string(self):
        tool = make_first_last_tool(extra_config="", image_path="f.png,l.png")
        ok, _ = self.fl_driver.validate_input_compatibility(tool)
        assert ok is True  # 默认 first_last_frame 模式，双图兼容

    def test_extra_config_invalid_json(self):
        tool = make_first_last_tool(extra_config="{broken json", image_path="f.png,l.png")
        ok, _ = self.fl_driver.validate_input_compatibility(tool)
        assert ok is True

    def test_extra_config_non_dict_json(self):
        tool = make_first_last_tool(extra_config='["array"]', image_path="f.png,l.png")
        ok, _ = self.fl_driver.validate_input_compatibility(tool)
        assert ok is True  # 回退首尾帧模式后仍能读到双图

    def test_extra_config_non_dict_json_single_frame_incompatible(self):
        """数组 JSON 不能在看首尾帧之前被当成兼容，否则单首帧会被切到 AutoDL。"""
        tool = make_first_last_tool(extra_config='["array"]', image_path="only_first.png")
        ok, reason = self.fl_driver.validate_input_compatibility(tool)
        assert ok is False
        assert "尾帧" in reason

    def test_extra_config_json_null_single_frame_incompatible(self):
        tool = make_first_last_tool(extra_config="null", image_path="only_first.png")
        ok, reason = self.fl_driver.validate_input_compatibility(tool)
        assert ok is False
        assert "尾帧" in reason

    def test_extra_config_list_object_single_frame_incompatible(self):
        tool = make_first_last_tool(extra_config=["array"], image_path="only_first.png")
        ok, reason = self.fl_driver.validate_input_compatibility(tool)
        assert ok is False
        assert "尾帧" in reason

    def test_hook_does_not_treat_unexpected_error_as_compatible(self):
        with patch.object(self.fl_driver, "get_all_images_by_mode", side_effect=RuntimeError("boom")):
            with pytest.raises(RuntimeError):
                self.fl_driver.validate_input_compatibility(make_first_last_tool())
        with patch.object(self.ref_driver, "get_video_path", side_effect=RuntimeError("boom")):
            with pytest.raises(RuntimeError):
                self.ref_driver.validate_input_compatibility(make_tool(video_path="a.mp4"))

    def test_reference_images_invalid_json_not_break_hook(self):
        """非法 reference_images JSON：get_reference_images 返回 []，首尾帧判定不受影响"""
        tool = make_first_last_tool(reference_images="{bad", image_path="f.png")
        ok, reason = self.fl_driver.validate_input_compatibility(tool)
        assert ok is False  # 单首帧仍判不兼容
        assert "尾帧" in reason

    def test_video_path_empty_string_compatible(self):
        assert self.ref_driver.validate_input_compatibility(make_tool(video_path=""))[0] is True

    def test_video_path_whitespace_compatible(self):
        assert self.ref_driver.validate_input_compatibility(make_tool(video_path="  "))[0] is True

    def test_video_path_multiple_comma_separated_incompatible(self):
        ok, reason = self.ref_driver.validate_input_compatibility(make_tool(video_path="a.mp4,b.mp4"))
        assert ok is False and "参考视频" in reason

    def test_first_last_with_ref_mode_single_frame_incompatible(self):
        """first_last_with_ref 模式同样走首尾帧解析，单帧不兼容"""
        tool = make_first_last_tool(extra_config='{"image_mode": "first_last_with_ref"}', image_path="f.png")
        ok, reason = self.fl_driver.validate_input_compatibility(tool)
        assert ok is False and "尾帧" in reason

    def test_trailing_comma_in_image_path(self):
        """image_path 尾随逗号：get_first_last_frames 拆出空段，仍视为单首帧"""
        tool = make_first_last_tool(image_path="f.png,")
        ok, _ = self.fl_driver.validate_input_compatibility(tool)
        assert ok is False  # 保守判不兼容（无有效尾帧），宁缺勿错切


# ==================== 5xx / 4xx 边界 ====================

class TestCheckStatusHttpBoundaries:

    def _driver_with_status(self, status_code):
        driver = make_driver()
        driver._send_alert = MagicMock()
        resp = MagicMock(status_code=status_code)
        driver._request = MagicMock(side_effect=requests.exceptions.HTTPError(response=resp))
        return driver

    def test_500_exact_boundary_running(self):
        assert self._driver_with_status(500).check_status("t")["status"] == "RUNNING"

    def test_599_exact_boundary_running(self):
        assert self._driver_with_status(599).check_status("t")["status"] == "RUNNING"

    def test_600_not_5xx_fails(self):
        assert self._driver_with_status(600).check_status("t")["status"] == "FAILED"

    def test_400_fails(self):
        assert self._driver_with_status(400).check_status("t")["status"] == "FAILED"

    def test_401_fails(self):
        assert self._driver_with_status(401).check_status("t")["status"] == "FAILED"

    def test_status_code_none_fails(self):
        """response 无 status_code（mock/畸形）：不进 5xx 分支，走 SYSTEM FAILED"""
        driver = make_driver()
        driver._send_alert = MagicMock()
        resp = MagicMock(status_code=None)
        driver._request = MagicMock(side_effect=requests.exceptions.HTTPError(response=resp))
        assert driver.check_status("t")["status"] == "FAILED"


# ==================== payload 异常值 ====================

class TestBuildPayloadEdgeCases:

    def test_ratio_none_defaults_portrait(self):
        driver = make_driver()
        payload = driver._build_base_payload(make_tool(ratio=None), {}, "p")
        assert payload["resolution"] == "768p竖"

    def test_ratio_empty_string_defaults_portrait(self):
        driver = make_driver()
        payload = driver._build_base_payload(make_tool(ratio=""), {}, "p")
        assert payload["resolution"] == "768p竖"

    def test_ratio_unknown_falls_back_portrait(self):
        driver = make_driver()
        payload = driver._build_base_payload(make_tool(ratio="7:5"), {}, "p")
        assert payload["resolution"] == "768p竖"  # 未知比例按竖兜底

    def test_ratio_string_whitespace(self):
        driver = make_driver()
        payload = driver._build_base_payload(make_tool(ratio=" 16:9 "), {}, "p")
        assert payload["resolution"] == "768p竖"  # 带空格非精确匹配 → 竖兜底（与 RunningHub 口径一致地保守）

    def test_duration_string_numeric(self):
        driver = make_driver()
        payload = driver._build_base_payload(make_tool(duration="8"), {}, "p")
        assert payload["duration"] == 8

    def test_duration_garbage_string_defaults_5(self):
        driver = make_driver()
        payload = driver._build_base_payload(make_tool(duration="abc"), {}, "p")
        assert payload["duration"] == 5


# ==================== 基类默认钩子（107 个既有驱动不受影响） ====================

def test_base_driver_default_hook_always_compatible():
    """未覆写钩子的既有驱动默认全兼容——用 RunningHub 标准版实例验证（无 __init__ 依赖）"""
    from task.visual_drivers.minimax_h3_runninghub_v1_driver import MinimaxH3RunninghubV1Driver
    driver = MinimaxH3RunninghubV1Driver.__new__(MinimaxH3RunninghubV1Driver)
    assert driver.validate_input_compatibility(make_tool()) == (True, None)
    assert driver.validate_input_compatibility(make_tool(video_path="v.mp4")) == (True, None)
    assert driver.validate_input_compatibility(make_first_last_tool(image_path="f.png")) == (True, None)


# ==================== 提交链路回归（兼容钩子不影响正常提交） ====================

def test_normal_submit_path_untouched_by_hook():
    """正常提交不调用钩子：单首帧任务直接提交仍走原 USER 错误（带尾帧提示）"""
    driver = make_driver(MinimaxH3FirstLastAutodlV1Driver, "minimax_h3_lightx2v", 34)
    result = driver.build_create_request(make_first_last_tool(image_path="first.png"))
    assert result["success"] is False
    assert "尾帧" in result["error"]


def test_non_dict_extra_config_both_frames_submit_does_not_raise():
    """数组 extra_config 回退后，双帧提交能读到首尾帧，不再 AttributeError。"""
    driver = make_driver(MinimaxH3FirstLastAutodlV1Driver, "minimax_h3_lightx2v", 34)

    def _fake(path, *args, **kwargs):
        name = str(path).rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
        return True, f"https://cdn.example/{name}", None

    with patch(f"{MODULE}.compress_and_upload_image_sync", side_effect=_fake):
        request = driver.build_create_request(
            make_first_last_tool(extra_config='["array"]', image_path="f.png,l.png")
        )
    assert "success" not in request
    assert request["json"]["first_frame"] == "https://cdn.example/f.png"
    assert request["json"]["last_frame"] == "https://cdn.example/l.png"
