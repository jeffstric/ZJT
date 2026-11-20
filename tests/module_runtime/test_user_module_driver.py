"""UserModuleMediaDriver 驱动协议测试。

通过 fake UserModuleService / ModuleJobsModel 注入验证：
- submit_task 的参数映射（prompt/inputs/parameters/幂等键）与错误翻译
- check_status 的 module_job 状态翻译与结果 URL 提取
"""

from types import SimpleNamespace

import pytest

from task.user_module_driver import UserModuleMediaDriver


def _make_ai_tool(**overrides):
    base = dict(
        id=7,
        user_id=42,
        prompt="一只猫在弹钢琴",
        image_path="https://cdn.example.com/first.jpg",
        reference_images='["https://cdn.example.com/ref.jpg"]',
        duration=5,
        ratio="16:9",
        image_size=None,
        extra_config='{"resolution": "720p"}',
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _make_driver(operation="text_to_video"):
    return UserModuleMediaDriver(
        module_id="huimeng.grok_video",
        operation=operation,
        task_id=34,
        impl_name=f"user_module:huimeng.grok_video:{operation}",
    )


class _FakeService:
    def __init__(self, job_id="job-123", error=None):
        self.job_id = job_id
        self.error = error
        self.created = []
        self.dispatched = []

    async def create_media_job(self, **kwargs):
        if self.error:
            raise self.error
        self.created.append(kwargs)
        return SimpleNamespace(job_id=self.job_id)

    async def dispatch_job(self, job_id):
        self.dispatched.append(job_id)


def _patch_service(monkeypatch, service):
    import services.user_module_service as svc

    monkeypatch.setattr(svc, "get_user_module_service", lambda: service)


def _patch_cdn_upload(monkeypatch, mapper):
    """替换 CDN 图床上传：mapper 收到 URL 列表，返回对应转换结果。

    通过 sys.modules 注入 fake 模块实现，避免加载真实的
    utils.image_upload_utils（其顶层依赖 aiohttp，测试环境未必安装）。
    """
    import sys
    import types

    calls = []

    async def _fake_upload(urls, config, project_root=None):
        calls.append(list(urls))
        return mapper(urls)

    fake_module = types.ModuleType("utils.image_upload_utils")
    fake_module.upload_local_images_to_cdn = _fake_upload
    monkeypatch.setitem(sys.modules, "utils.image_upload_utils", fake_module)
    return calls


# --------------------------------------------------------------------------- #
# submit_task
# --------------------------------------------------------------------------- #

def test_submit_maps_ai_tool_to_media_request(monkeypatch):
    import asyncio

    fake = _FakeService()
    _patch_service(monkeypatch, fake)
    _patch_cdn_upload(monkeypatch, lambda urls: urls)

    result = asyncio.run(_make_driver().submit_task(_make_ai_tool()))

    assert result == {"success": True, "project_id": "job-123"}
    assert fake.dispatched == ["job-123"]
    (request,) = fake.created
    assert request["module_id"] == "huimeng.grok_video"
    assert request["operation"] == "text_to_video"
    assert request["media_kind"] == "video"
    assert request["prompt"] == "一只猫在弹钢琴"
    assert request["idempotency_key"] == "aitool-7"
    # image_path 与参考图均为 http URL，进入 inputs
    input_urls = [item["url"] for item in request["inputs"]]
    assert "https://cdn.example.com/first.jpg" in input_urls
    assert "https://cdn.example.com/ref.jpg" in input_urls
    # 标量参数与 extra_config 进入 parameters
    assert request["parameters"]["duration"] == 5
    assert request["parameters"]["ratio"] == "16:9"
    # 分辨率规范化：核心存储键 video_resolution → 模块契约键 resolution
    assert request["parameters"]["resolution"] == "720p"


def test_submit_maps_media_urls_to_compat_parameters(monkeypatch):
    """兼容映射：按图片模式把引用 URL 冗余写入通用参数名，供只读参数的模块使用。"""

    import asyncio

    _patch_cdn_upload(monkeypatch, lambda urls: urls)

    fake = _FakeService()
    _patch_service(monkeypatch, fake)

    # 首尾帧模式（默认）：单图作为首帧
    asyncio.run(_make_driver("image_to_video").submit_task(_make_ai_tool()))
    (request,) = fake.created
    assert request["parameters"]["first_frame_image"] == "https://cdn.example.com/first.jpg"
    assert request["parameters"]["reference_images"] == ["https://cdn.example.com/ref.jpg"]
    assert "image_url" not in request["parameters"]

    # 图片编辑：单图映射为 image_url
    fake2 = _FakeService(job_id="job-456")
    _patch_service(monkeypatch, fake2)
    asyncio.run(_make_driver("image_edit").submit_task(_make_ai_tool(reference_images=None)))
    (request2,) = fake2.created
    assert request2["parameters"]["image_url"] == "https://cdn.example.com/first.jpg"


def test_submit_skips_non_http_media_references(monkeypatch):
    import asyncio

    fake = _FakeService()
    _patch_service(monkeypatch, fake)

    result = asyncio.run(
        _make_driver().submit_task(
            _make_ai_tool(image_path="/upload/local/path.jpg", reference_images=None)
        )
    )

    assert result["success"] is True
    (request,) = fake.created
    assert request["inputs"] == []


def test_submit_uploads_local_urls_to_cdn(monkeypatch):
    """本地/局域网 URL 必须上传图床转为公网 URL 后再传给模块。"""
    import asyncio

    fake = _FakeService(job_id="job-cdn")
    _patch_service(monkeypatch, fake)
    _patch_cdn_upload(
        monkeypatch,
        lambda urls: ["https://cdn.example.com/uploaded.png" for _ in urls],
    )

    result = asyncio.run(
        _make_driver("image_to_video").submit_task(
            _make_ai_tool(
                image_path="http://localhost:19003/upload/image_to_video/1/x.png",
                reference_images=None,
            )
        )
    )

    assert result["success"] is True
    (request,) = fake.created
    assert request["inputs"][0]["url"] == "https://cdn.example.com/uploaded.png"
    assert (
        request["parameters"]["first_frame_image"]
        == "https://cdn.example.com/uploaded.png"
    )


def test_submit_cdn_failure_falls_back_to_original_urls(monkeypatch):
    import asyncio

    fake = _FakeService(job_id="job-cdn-fail")
    _patch_service(monkeypatch, fake)
    _patch_cdn_upload(
        monkeypatch,
        lambda urls: (_ for _ in ()).throw(RuntimeError("cdn down")),
    )

    result = asyncio.run(
        _make_driver().submit_task(
            _make_ai_tool(image_path="http://localhost:19003/upload/a.png")
        )
    )

    assert result["success"] is True
    (request,) = fake.created
    assert request["inputs"][0]["url"] == "http://localhost:19003/upload/a.png"


def test_submit_publicizes_direct_slot_for_image_edit(monkeypatch):
    """回归：image_edit 场景 direct 与 first 是同一张局域网图，参数键不得残留内网地址。

    真实事故 runninghub.qweniamgeeidtv2（aitool-1129）：inputs 已公网化但
    parameters.image_url 仍是 http://192.168.x.x，供应商模块按合同优先读参数键，
    局域网地址透传给 RunningHub 导致其拉图失败、任务失败。
    """
    import asyncio

    fake = _FakeService(job_id="job-lan-leak")
    _patch_service(monkeypatch, fake)
    lan_url = "http://192.168.10.101:9003/upload/temp/20260826/upload_x.png"
    cdn_url = "http://cdn.example.com/2026-08-26/upload_x.png"
    _patch_cdn_upload(monkeypatch, lambda urls: [cdn_url for _ in urls])

    result = asyncio.run(
        _make_driver("image_edit").submit_task(
            _make_ai_tool(image_path=lan_url, reference_images=None)
        )
    )

    assert result["success"] is True
    (request,) = fake.created
    assert request["inputs"][0]["url"] == cdn_url
    assert request["parameters"]["image_url"] == cdn_url
    assert "192.168." not in str(request["parameters"])
    assert "192.168." not in str(request["inputs"])


def test_submit_remaps_private_urls_in_extra_config(monkeypatch):
    """extra_config 重复携带的局域网媒体 URL 也要按映射替换为公网 URL。"""
    import asyncio

    fake = _FakeService(job_id="job-extra-remap")
    _patch_service(monkeypatch, fake)
    lan_url = "http://192.168.10.101:9003/upload/temp/20260826/upload_y.png"
    cdn_url = "http://cdn.example.com/2026-08-26/upload_y.png"
    _patch_cdn_upload(monkeypatch, lambda urls: [cdn_url for _ in urls])

    result = asyncio.run(
        _make_driver("image_edit").submit_task(
            _make_ai_tool(
                image_path=lan_url,
                reference_images=None,
                extra_config='{"source_image": "%s"}' % lan_url,
            )
        )
    )

    assert result["success"] is True
    (request,) = fake.created
    assert request["parameters"]["source_image"] == cdn_url
    assert "192.168." not in str(request["parameters"])


def test_submit_normalizes_video_resolution_key(monkeypatch):
    """核心存储键 video_resolution 规范化为模块契约键 resolution。"""
    import asyncio

    fake = _FakeService(job_id="job-res")
    _patch_service(monkeypatch, fake)
    _patch_cdn_upload(monkeypatch, lambda urls: urls)

    asyncio.run(
        _make_driver("image_to_video").submit_task(
            _make_ai_tool(extra_config='{"video_resolution": "2K", "image_mode": "first_last_frame"}')
        )
    )
    (request,) = fake.created
    assert request["parameters"]["resolution"] == "2K"
    assert "video_resolution" not in request["parameters"]


def test_submit_translates_service_error_without_retry_for_unavailable(monkeypatch):
    import asyncio

    from services.user_module_service import UserModuleServiceError

    fake = _FakeService(error=UserModuleServiceError("MODULE_UNAVAILABLE", "模块不可用"))
    _patch_service(monkeypatch, fake)

    result = asyncio.run(_make_driver().submit_task(_make_ai_tool()))

    assert result["success"] is False
    assert result["error_type"] == "USER"
    assert result["retry"] is True


def test_submit_rejects_incomplete_binding(monkeypatch):
    import asyncio

    result = asyncio.run(UserModuleMediaDriver().submit_task(_make_ai_tool()))
    assert result["success"] is False
    assert result["error_type"] == "SYSTEM"
    assert result["retry"] is False


# --------------------------------------------------------------------------- #
# check_status
# --------------------------------------------------------------------------- #

def _patch_job(monkeypatch, job):
    import model.user_modules as models

    monkeypatch.setattr(models.ModuleJobsModel, "get", staticmethod(lambda _id: job))


def test_check_status_translates_running_states(monkeypatch):
    for status in ("queued", "submitted", "running"):
        _patch_job(monkeypatch, SimpleNamespace(status=status, result=None, error=None))
        assert _make_driver().check_status("job-1") == {"status": "RUNNING"}


def test_check_status_success_extracts_output_url(monkeypatch):
    _patch_job(
        monkeypatch,
        SimpleNamespace(
            status="succeeded",
            result={"outputs": [{"url": "https://cdn.example.com/out.mp4"}]},
            error=None,
        ),
    )
    result = _make_driver().check_status("job-1")
    assert result["status"] == "SUCCESS"
    assert result["result_url"] == "https://cdn.example.com/out.mp4"


def test_check_status_success_without_url_fails(monkeypatch):
    _patch_job(monkeypatch, SimpleNamespace(status="succeeded", result={"outputs": []}, error=None))
    assert _make_driver().check_status("job-1")["status"] == "FAILED"


def test_check_status_failed_uses_driver_error_message(monkeypatch):
    _patch_job(
        monkeypatch,
        SimpleNamespace(status="failed", result=None, error={"code": "E_UPSTREAM", "message": "供应商拒绝"}),
    )
    result = _make_driver().check_status("job-1")
    assert result["status"] == "FAILED"
    assert result["error"] == "供应商拒绝"
    assert result["error_type"] == "USER"


def test_check_status_missing_job_fails(monkeypatch):
    _patch_job(monkeypatch, None)
    assert _make_driver().check_status("job-1")["status"] == "FAILED"


def test_submit_aliases_ratio_to_aspect_ratio(monkeypatch):
    """比例冗余键：核心 ratio 简式值同时以 aspect_ratio 下发，且不覆盖 extra_config 显式值。"""
    import asyncio

    fake = _FakeService(job_id="job-ratio")
    _patch_service(monkeypatch, fake)
    _patch_cdn_upload(monkeypatch, lambda urls: urls)

    asyncio.run(
        _make_driver("image_to_video").submit_task(
            _make_ai_tool(extra_config='{"image_mode": "first_last_frame"}')
        )
    )
    (request,) = fake.created
    assert request["parameters"]["ratio"] == "16:9"
    assert request["parameters"]["aspect_ratio"] == "16:9"

    fake2 = _FakeService(job_id="job-ratio-2")
    _patch_service(monkeypatch, fake2)
    asyncio.run(
        _make_driver("image_to_video").submit_task(
            _make_ai_tool(extra_config='{"image_mode": "first_last_frame", "aspect_ratio": "9:16 (Portrait Widescreen)"}')
        )
    )
    (request2,) = fake2.created
    assert request2["parameters"]["aspect_ratio"] == "9:16 (Portrait Widescreen)"


def test_submit_normalizes_image_size_to_resolution(monkeypatch):
    """文生图链路：ai_tools.image_size 档位规范化为模块契约键 resolution（原键保留）。"""
    import asyncio

    fake = _FakeService(job_id="job-size")
    _patch_service(monkeypatch, fake)
    _patch_cdn_upload(monkeypatch, lambda urls: urls)

    asyncio.run(
        _make_driver("image_edit").submit_task(
            _make_ai_tool(image_size="1K", extra_config="{}")
        )
    )
    (request,) = fake.created
    assert request["parameters"]["image_size"] == "1K"
    assert request["parameters"]["resolution"] == "1K"


def test_submit_resolution_prefers_video_resolution_over_image_size(monkeypatch):
    """视频分辨率选择优先于 image_size，避免两个来源同时存在时取错。"""
    import asyncio

    fake = _FakeService(job_id="job-prio")
    _patch_service(monkeypatch, fake)
    _patch_cdn_upload(monkeypatch, lambda urls: urls)

    asyncio.run(
        _make_driver("image_to_video").submit_task(
            _make_ai_tool(
                image_size="1K",
                extra_config='{"video_resolution": "2K", "image_mode": "first_last_frame"}',
            )
        )
    )
    (request,) = fake.created
    assert request["parameters"]["resolution"] == "2K"
