"""
生成次数偏好注入测试（Agent 模式「生成次数」支持）

背景：Agent 模式下用户在界面选择「生成次数 ×N」后，count 随 image_preferences /
video_preferences 下发并持久化到世界偏好；MCP 工具执行时应按「已由系统注入」
语义用偏好覆盖 LLM 传参（与 ratio / duration 的处理一致），不依赖 LLM 听话。

本文件验证注入函数这一环：偏好覆盖、越界/非法回退、图片工具集成（edit_image
无参路径）、工具 schema 描述已收敛为系统注入语义。
"""
import os

os.environ.setdefault("comfyui_env", "unit")
from config import config_util  # noqa: E402

config_util._config_cache["config_unit.yml"] = {
    "database": {
        "host": "localhost",
        "port": 3306,
        "user": "root",
        "password": "",
        "database": "unit",
    },
    "server": {},
    "file_storage": {},
}

from script_writer_core.mcp_tool import (  # noqa: E402
    _resolve_generation_count_from_prefs,
)


def test_pref_count_overrides_argument():
    assert _resolve_generation_count_from_prefs('u', 'w', 1, user_prefs={'count': 2}) == 2


def test_pref_count_string_value_is_parsed():
    assert _resolve_generation_count_from_prefs('u', 'w', 1, user_prefs={'count': '3'}) == 3


def test_missing_pref_keeps_argument():
    assert _resolve_generation_count_from_prefs('u', 'w', 1, user_prefs={}) == 1


def test_none_pref_keeps_argument():
    assert _resolve_generation_count_from_prefs('u', 'w', 2, user_prefs={'count': None}) == 2


def test_out_of_range_pref_keeps_argument():
    assert _resolve_generation_count_from_prefs('u', 'w', 1, user_prefs={'count': 9}) == 1
    assert _resolve_generation_count_from_prefs('u', 'w', 1, user_prefs={'count': 0}) == 1


def test_non_numeric_pref_keeps_argument():
    assert _resolve_generation_count_from_prefs('u', 'w', 1, user_prefs={'count': 'auto'}) == 1


def test_no_prefs_dict_reads_via_getter(monkeypatch):
    """不传 user_prefs 时应走 _get_image_preferences 读世界偏好。"""
    import script_writer_core.mcp_tool as mcp_tool

    monkeypatch.setattr(
        mcp_tool, '_get_image_preferences', lambda uid, wid: {'count': 4}
    )
    assert mcp_tool._resolve_generation_count_from_prefs('u', 'w', 1) == 4
