"""speed_to_duration_factor 纯函数单元测试。

覆盖语速 → IndexTTS-2.5 duration_factor（时长因子，>1 变慢）的换算与兜底：
- 正常换算：duration_factor = 1/speed
- 越界夹取：结果恒在 [0.5, 2.0]
- 非法值兜底：非数值/≤0 → 1.0
"""
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from utils.index_tts_util import speed_to_duration_factor


def test_normal_speed_converts_to_inverse():
    """语速 1.5（快）→ 因子 0.6667（变快）；0.5（慢）→ 2.0（变慢）；1.0 → 1.0。"""
    assert speed_to_duration_factor(1.0) == 1.0
    assert speed_to_duration_factor(1.5) == 0.6667
    assert speed_to_duration_factor(0.5) == 2.0
    assert speed_to_duration_factor(2.0) == 0.5


def test_out_of_range_speed_clamped_to_api_limits():
    """越界语速换算后夹取到接口上限 [0.5, 2.0]。"""
    assert speed_to_duration_factor(0.1) == 2.0   # 1/0.1=10 → 夹到 2.0
    assert speed_to_duration_factor(10) == 0.5    # 1/10=0.1 → 夹到 0.5
    assert speed_to_duration_factor(0.5) == 2.0   # 边界值本身合法


def test_invalid_speed_falls_back_to_normal():
    """非法语速兜底：None/字符串/≤0/NaN → 按 1.0 处理。"""
    assert speed_to_duration_factor(None) == 1.0
    assert speed_to_duration_factor("abc") == 1.0
    assert speed_to_duration_factor(0) == 1.0
    assert speed_to_duration_factor(-1.5) == 1.0
    assert speed_to_duration_factor(float("nan")) == 1.0
