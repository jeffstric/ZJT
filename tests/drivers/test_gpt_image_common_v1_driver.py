import logging
import os
from types import SimpleNamespace

os.environ.setdefault("comfyui_env", "prod")

from task.visual_drivers.gpt_image_common_v1_driver import GptImageCommonV1Driver


def make_driver():
    driver = GptImageCommonV1Driver.__new__(GptImageCommonV1Driver)
    driver._base_url = "https://yunwu.ai"
    driver._api_key = "test-key"
    driver.logger = logging.getLogger("test_gpt_image_common")
    return driver


def test_build_edit_request_uses_yunwu_gpt_image_2_form_fields():
    driver = make_driver()
    driver._prepare_image_file = lambda path: (b"image-bytes", f"{path}.png", "image/png")

    ai_tool = SimpleNamespace(
        prompt="merge these images",
        image_path="first, second",
        image_size="4k",
        ratio="16:9",
        extra_config={
            "quality": "high",
            "background": "transparent",
            "moderation": "low",
            "mask": "mask",
            "n": 2,
        },
    )

    request = driver.build_edit_request(ai_tool)

    assert request["url"] == "https://yunwu.ai/v1/images/edits"
    assert [field for field, _ in request["files"]] == ["image[]", "image[]", "mask"]
    assert request["data"] == {
        "prompt": "merge these images",
        "model": "gpt-image-2",
        "n": "2",
        "size": "3840x2160",
        "quality": "high",
        "background": "transparent",
        "moderation": "low",
    }
    assert request["headers"] == {
        "Accept": "application/json",
        "Authorization": "Bearer test-key",
    }


def test_extract_image_from_yunwu_object_data_response():
    driver = make_driver()

    image = driver._extract_image_from_response({
        "created": 0,
        "background": "transparent",
        "data": {
            "b64_json": "abc123",
        },
        "output_format": "png",
        "quality": "high",
        "size": "1024x1536",
    })

    assert image == "data:image/png;base64,abc123"
