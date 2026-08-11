"""纯函数单测：时长 clamp 与分辨率→max_edge（不依赖数据库配置）。"""
import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.constant import StoryboardDigitalHumanConstants as C


def _clamp_minimax_video_duration(raw_seconds):
    """与 services.storyboard_digital_human_service.clamp_minimax_video_duration 对齐。"""
    try:
        value = float(raw_seconds) if raw_seconds is not None else float(C.DEFAULT_VIDEO_DURATION)
    except (TypeError, ValueError):
        value = float(C.DEFAULT_VIDEO_DURATION)
    if value <= 0:
        value = float(C.DEFAULT_VIDEO_DURATION)
    ceiled = int(math.ceil(value))
    if ceiled < int(C.MIN_VIDEO_DURATION):
        return int(C.MIN_VIDEO_DURATION), "floor_to_4"
    if ceiled > int(C.MAX_VIDEO_DURATION):
        return int(C.MAX_VIDEO_DURATION), "ceil_to_10"
    return ceiled, "none"


def _resolve_max_edge_from_resolution(resolution):
    raw = (str(resolution).strip() if resolution is not None else "") or C.DEFAULT_RESOLUTION
    key = raw.upper().replace(" ", "")
    edge = C.RESOLUTION_TO_MAX_EDGE.get(raw)
    if edge is None:
        edge = C.RESOLUTION_TO_MAX_EDGE.get(key)
    if edge is None:
        return C.DEFAULT_RESOLUTION, int(C.DEFAULT_MAX_EDGE)
    if key in ("480P", "720P", "1080P"):
        normalized = key
    else:
        reverse = {720: "480P", 1280: "720P", 1920: "1080P"}
        normalized = reverse.get(int(edge), C.DEFAULT_RESOLUTION)
    return normalized, int(edge)


def test_task_type_is_minimax_h3():
    assert C.TASK_TYPE == 35
    assert C.MODEL_MINIMAX_H3 == "minimax_h3"


@pytest.mark.parametrize(
    "raw,expected",
    [
        (3, (4, "floor_to_4")),
        (3.2, (4, "none")),  # ceil(3.2)=4，已在合法区间
        (4, (4, "none")),
        (7.1, (8, "none")),
        (10, (10, "none")),
        (10.1, (10, "ceil_to_10")),
        (99, (10, "ceil_to_10")),
        (None, (10, "none")),
    ],
)
def test_clamp_duration(raw, expected):
    assert _clamp_minimax_video_duration(raw) == expected


@pytest.mark.parametrize(
    "res,edge",
    [
        ("480P", 720),
        ("480p", 720),
        ("720P", 1280),
        ("720p", 1280),
        ("1080P", 1920),
        (None, 1280),
        ("4K", 1280),
    ],
)
def test_resolution_to_max_edge(res, edge):
    _label, max_edge = _resolve_max_edge_from_resolution(res)
    assert max_edge == edge
