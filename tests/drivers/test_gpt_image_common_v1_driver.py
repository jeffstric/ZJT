import logging
import os
from types import SimpleNamespace

import pytest

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
        "model": "gpt-image-2-c",
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
    assert request["request_context"] == {
        "mode": "edit",
        "ratio": "16:9",
        "image_size": "4k",
        "mapped_size": "3840x2160",
        "image_count": 2,
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


def test_build_edit_request_logs_portrait_size_context_without_rewriting_image():
    driver = make_driver()
    driver._prepare_image_file = lambda path: (b"image-bytes", "input.png", "image/png")

    ai_tool = SimpleNamespace(
        prompt="make this portrait",
        image_path="input.png",
        image_size="1K",
        ratio="9:16",
        extra_config={},
    )

    request = driver.build_edit_request(ai_tool)

    assert request["data"]["size"] == "864x1536"
    assert request["request_context"] == {
        "mode": "edit",
        "ratio": "9:16",
        "image_size": "1K",
        "mapped_size": "864x1536",
        "image_count": 1,
    }
    assert request["files"] == [("image", ("input.png", b"image-bytes", "image/png"))]


def test_map_size_1k_widescreen_and_portrait_use_true_ratio():
    """1k 档位 16:9 / 9:16 映射为真比例自定义尺寸，2:3 / 3:2 保持预设尺寸。"""
    driver = make_driver()

    assert driver._map_size("1k", "9:16") == "864x1536"
    assert driver._map_size("1k", "16:9") == "1536x864"
    assert driver._map_size("1k", "2:3") == "1024x1536"
    assert driver._map_size("1k", "3:2") == "1536x1024"


def test_resolve_local_path_maps_upload_web_relative_path(tmp_path, monkeypatch):
    """`/upload/...` Web 相对路径（前端场景参考图常见形态）映射到项目根目录。"""
    import task.visual_drivers.gpt_image_common_v1_driver as driver_module

    rel = os.path.join("upload", "location", "pic", "scene.png")
    abs_path = tmp_path / rel
    abs_path.parent.mkdir(parents=True)
    abs_path.write_bytes(b"png-bytes")
    monkeypatch.setattr(driver_module, "get_project_root", lambda: str(tmp_path))

    driver = make_driver()
    resolved = driver._resolve_local_path("/upload/location/pic/scene.png")
    assert os.path.normpath(resolved) == os.path.normpath(str(abs_path))


def test_resolve_local_path_keeps_existing_absolute_path(tmp_path, monkeypatch):
    """字面路径存在时不重映射，避免误伤真实绝对路径。"""
    import task.visual_drivers.gpt_image_common_v1_driver as driver_module

    real_file = tmp_path / "real.png"
    real_file.write_bytes(b"real")
    # 即使 /upload/ 下有同名文件，也不应重映射
    rel = tmp_path / "upload" / "real.png"
    rel.parent.mkdir(parents=True)
    rel.write_bytes(b"other")
    monkeypatch.setattr(driver_module, "get_project_root", lambda: str(tmp_path))

    driver = make_driver()
    assert driver._resolve_local_path(str(real_file)) == str(real_file)


def test_resolve_local_path_returns_original_when_unresolvable(tmp_path, monkeypatch):
    """字面路径与映射候选都不存在时原样返回（保留 FileNotFoundError 语义）。"""
    import task.visual_drivers.gpt_image_common_v1_driver as driver_module

    monkeypatch.setattr(driver_module, "get_project_root", lambda: str(tmp_path))

    driver = make_driver()
    missing = "/upload/location/pic/not_exist_xxx.png"
    assert driver._resolve_local_path(missing) == missing


@pytest.mark.parametrize(
    "malicious_path",
    [
        "/upload/../pyproject.toml",
        "/upload/%2e%2e/pyproject.toml",
        r"/upload/..\pyproject.toml",
    ],
)
def test_resolve_local_path_rejects_upload_traversal(malicious_path):
    driver = make_driver()
    with pytest.raises(ValueError, match="非法的上传路径"):
        driver._resolve_local_path(malicious_path)


def test_prepare_image_file_reads_upload_web_relative_path(tmp_path, monkeypatch):
    """回归：/upload/ Web 相对路径不再 FileNotFoundError。"""
    import task.visual_drivers.gpt_image_common_v1_driver as driver_module

    rel = os.path.join("upload", "location", "pic", "scene.png")
    abs_path = tmp_path / rel
    abs_path.parent.mkdir(parents=True)
    abs_path.write_bytes(b"png-bytes")
    monkeypatch.setattr(driver_module, "get_project_root", lambda: str(tmp_path))

    driver = make_driver()
    content, filename, mime_type = driver._prepare_image_file("/upload/location/pic/scene.png")
    assert content == b"png-bytes"
    assert filename == "scene.png"
    assert mime_type == "image/png"


def _make_submit_driver():
    """构造可调用 submit_task 的驱动：跳过真实请求构建，只留 _request 桩。"""
    driver = make_driver()
    driver._timeout = 30
    driver._send_alert = lambda **kwargs: None
    driver.build_create_request = lambda ai_tool: {"url": "https://yunwu.ai/v1/images/generations", "method": "POST"}
    return driver


def _http_error_with_body(body):
    import requests

    err = requests.exceptions.HTTPError("403 Client Error: Forbidden for url: https://yunwu.ai")
    err.response_body = body
    return err


def test_submit_task_http_error_surfaces_quota_message():
    """HTTP 4xx 响应体中的业务错误（如额度不足）不再被"服务异常"掩盖。"""
    driver = _make_submit_driver()
    driver._request = lambda **kwargs: (_ for _ in ()).throw(_http_error_with_body({
        "error": {"message": "user quota is not enough", "type": "new_api_error", "code": "local:insufficient_quota"}
    }))

    ai_tool = SimpleNamespace(id=1, prompt="test", image_path="", ratio="1:1", image_size="1k", extra_config={})
    result = driver.submit_task(ai_tool)

    assert result["success"] is False
    assert result["error_type"] == "USER"
    assert "user quota is not enough" in result["error"]


def test_submit_task_http_error_surfaces_moderation_friendly_message():
    """HTTP 4xx 响应体命中内容审核特征时返回中文友好文案。"""
    driver = _make_submit_driver()
    driver._request = lambda **kwargs: (_ for _ in ()).throw(_http_error_with_body({
        "error": {"message": "Your request was rejected by the safety system", "type": "invalid_request_error", "code": "moderation_blocked"}
    }))

    ai_tool = SimpleNamespace(id=1, prompt="test", image_path="", ratio="1:1", image_size="1k", extra_config={})
    result = driver.submit_task(ai_tool)

    assert result["success"] is False
    assert result["error_type"] == "USER"
    assert result["error"].startswith("内容审核未通过")


def test_submit_task_http_error_without_body_keeps_generic_system_error():
    """异常未携带响应体时保持原有 SYSTEM 兜底行为。"""
    import requests

    driver = _make_submit_driver()
    driver._request = lambda **kwargs: (_ for _ in ()).throw(
        requests.exceptions.HTTPError("500 Server Error")
    )

    ai_tool = SimpleNamespace(id=1, prompt="test", image_path="", ratio="1:1", image_size="1k", extra_config={})
    result = driver.submit_task(ai_tool)

    assert result["success"] is False
    assert result["error_type"] == "SYSTEM"
    assert result["error"] == "服务异常，请联系技术支持"
