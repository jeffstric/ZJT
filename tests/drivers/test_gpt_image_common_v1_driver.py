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

    assert request["data"]["size"] == "1024x1536"
    assert request["request_context"] == {
        "mode": "edit",
        "ratio": "9:16",
        "image_size": "1K",
        "mapped_size": "1024x1536",
        "image_count": 1,
    }
    assert request["files"] == [("image", ("input.png", b"image-bytes", "image/png"))]


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
