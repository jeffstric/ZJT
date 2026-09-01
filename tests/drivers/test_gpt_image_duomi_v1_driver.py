import logging
import os
from types import SimpleNamespace

import pytest

os.environ.setdefault("comfyui_env", "prod")

from task.visual_drivers.gpt_image_duomi_v1_driver import GptImageDuomiV1Driver


def make_driver():
    driver = GptImageDuomiV1Driver.__new__(GptImageDuomiV1Driver)
    driver._base_url = "https://duomiapi.com"
    driver._token = "test-token"
    driver.logger = logging.getLogger("test_gpt_image_duomi")
    return driver


EXPECTED_SIZE_MAPPING = {
    '1k': {
        '1:1': '1024x1024',
        '3:2': '1536x1024',
        '2:3': '1024x1536',
        '16:9': '1280x720',
        '9:16': '720x1280',
    },
    '2k': {
        '1:1': '2048x2048',
        '3:2': '2048x1360',
        '2:3': '1360x2048',
        '16:9': '2048x1152',
        '9:16': '1152x2048',
    },
    '4k': {
        '1:1': '2880x2880',
        '3:2': '3520x2352',
        '2:3': '2352x3520',
        '16:9': '3840x2160',
        '9:16': '2160x3840',
    },
}


def test_map_size_exact_mapping():
    driver = make_driver()
    for image_size, ratio_map in EXPECTED_SIZE_MAPPING.items():
        for ratio, expected in ratio_map.items():
            assert driver._map_size(image_size, ratio) == expected, f"{image_size} + {ratio}"


def test_map_size_all_values_satisfy_duomi_constraints():
    """多米约束：宽高被 16 整除、单边 [16, 3840]、像素预算 [655360, 8294400]"""
    driver = make_driver()
    for image_size, ratio_map in driver.SIZE_MAPPING.items():
        for ratio, size in ratio_map.items():
            w, h = (int(v) for v in size.split('x'))
            assert w % 16 == 0 and h % 16 == 0, f"{image_size}+{ratio}={size} 未被16整除"
            assert 16 <= w <= 3840 and 16 <= h <= 3840, f"{image_size}+{ratio}={size} 单边超限"
            assert 655360 <= w * h <= 8294400, f"{image_size}+{ratio}={size} 像素预算超限"


def test_map_size_16x9_is_true_ratio_for_all_tiers():
    """16:9 / 9:16 必须出真比例，不再兼容映射到 3:2 / 2:3"""
    driver = make_driver()
    for image_size in ('1k', '2k', '4k'):
        w, h = (int(v) for v in driver._map_size(image_size, '16:9').split('x'))
        assert w / h == pytest.approx(16 / 9, abs=1e-3)
        w, h = (int(v) for v in driver._map_size(image_size, '9:16').split('x'))
        assert w / h == pytest.approx(9 / 16, abs=1e-3)


def test_map_size_uppercase_image_size_normalized():
    driver = make_driver()
    assert driver._map_size('2K', '16:9') == '2048x1152'
    assert driver._map_size('4K', '9:16') == '2160x3840'


def test_map_size_fallbacks():
    driver = make_driver()
    # 空档位默认 1k
    assert driver._map_size(None, '1:1') == '1024x1024'
    assert driver._map_size('', '1:1') == '1024x1024'
    # 未知档位回退 1k
    assert driver._map_size('8k', '16:9') == '1280x720'
    # 未知比例回退 1:1
    assert driver._map_size('2k', '21:9') == '2048x2048'


def test_build_create_request_uses_explicit_pixel_size():
    driver = make_driver()

    ai_tool = SimpleNamespace(
        prompt="a coffee shop scene",
        image_path=None,
        image_size="2k",
        ratio="16:9",
    )

    request = driver.build_create_request(ai_tool)

    assert request["url"] == "https://duomiapi.com/v1/images/generations?async=true"
    assert request["json"] == {
        "model": "gpt-image-2",
        "prompt": "a coffee shop scene",
        "size": "2048x1152",
    }
    assert request["headers"] == {
        "Content-Type": "application/json",
        "Authorization": "test-token",
    }


def test_build_create_request_default_size_when_image_size_missing():
    driver = make_driver()

    ai_tool = SimpleNamespace(
        prompt="a coffee shop scene",
        image_path=None,
        image_size=None,
        ratio="3:2",
    )

    request = driver.build_create_request(ai_tool)

    assert request["json"]["size"] == "1536x1024"
