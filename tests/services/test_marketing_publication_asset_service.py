import json
from pathlib import Path
from types import SimpleNamespace


def _seed_config_cache(monkeypatch):
    monkeypatch.setenv("comfyui_env", "unit")
    import config.config_util as config_util

    config_util._config_cache["config_unit.yml"] = {
        "database": {
            "host": "127.0.0.1",
            "port": 3306,
            "user": "unit",
            "password": "unit",
            "database": "unit",
        }
    }


def test_promote_assets_copies_cache_files_and_rewrites_snapshot(tmp_path, monkeypatch):
    _seed_config_cache(monkeypatch)
    from services.marketing_publication_asset_service import MarketingPublicationAssetService

    root = tmp_path
    cache_file = root / "upload" / "cache" / "2026-06-24" / "result.png"
    ref_file = root / "upload" / "temp" / "20260624" / "ref.png"
    cache_file.parent.mkdir(parents=True)
    ref_file.parent.mkdir(parents=True)
    cache_file.write_bytes(b"result-bytes")
    ref_file.write_bytes(b"ref-bytes")

    created_mappings = []

    def fake_create(**kwargs):
        created_mappings.append(kwargs)
        return len(created_mappings)

    monkeypatch.setattr(
        "services.marketing_publication_asset_service.MediaFileMappingModel.create",
        fake_create,
    )

    ai_tool = SimpleNamespace(
        id=91,
        user_id=7,
        prompt="make a bright poster",
        result_url="/upload/cache/2026-06-24/result.png",
        image_path="/upload/temp/20260624/ref.png",
        reference_images=json.dumps(["/upload/temp/20260624/ref.png"]),
        audio_path=None,
        video_path=None,
        type=12,
        ratio="9:16",
        duration=None,
        image_size="2K",
        extra_config=json.dumps({"image_mode": "first_last_frame", "model_key": "seedream_5"}),
        implementation=3,
    )

    promoted = MarketingPublicationAssetService.promote_assets(ai_tool, 123, root_dir=root)

    result_path = root / promoted["result_url"].lstrip("/")
    ref_path = root / "upload" / "marketing_publications" / "123" / "reference_1.png"

    assert promoted["result_url"] == "/upload/marketing_publications/123/result.png"
    assert promoted["cover_url"] == "/upload/marketing_publications/123/result.png"
    assert promoted["reference_images"] == ["/upload/marketing_publications/123/reference_1.png"]
    assert result_path.read_bytes() == b"result-bytes"
    assert ref_path.read_bytes() == b"ref-bytes"
    assert promoted["params_snapshot"]["prompt"] == "make a bright poster"
    assert promoted["params_snapshot"]["media"][0]["serverUrl"] == promoted["reference_images"][0]
    assert promoted["params_snapshot"]["reference_images"] == promoted["reference_images"]
    assert {m["policy_code"] for m in created_mappings} == {"never_expire"}


def test_text_to_image_snapshot_does_not_use_result_as_remix_media(tmp_path, monkeypatch):
    _seed_config_cache(monkeypatch)
    from services.marketing_publication_asset_service import MarketingPublicationAssetService

    root = tmp_path
    cache_file = root / "upload" / "cache" / "2026-06-25" / "text2image.png"
    cache_file.parent.mkdir(parents=True)
    cache_file.write_bytes(b"result-bytes")

    monkeypatch.setattr(
        "services.marketing_publication_asset_service.MediaFileMappingModel.create",
        lambda **kwargs: 1,
    )
    monkeypatch.setattr(
        "services.marketing_publication_asset_service.MarketingPublicationAssetService._get_task_config",
        lambda task_id: SimpleNamespace(category="text_to_image", key="seedream_5", name="Seedream 5.0"),
    )

    ai_tool = SimpleNamespace(
        id=93,
        user_id=7,
        prompt="make a puppy portrait",
        result_url="/upload/cache/2026-06-25/text2image.png",
        image_path=None,
        reference_images=None,
        audio_path=None,
        video_path=None,
        type=16,
        ratio="9:16",
        duration=None,
        image_size="2K",
        extra_config=None,
        implementation=3,
    )

    promoted = MarketingPublicationAssetService.promote_assets(ai_tool, 125, root_dir=root)

    assert promoted["params_snapshot"]["prompt"] == "make a puppy portrait"
    assert promoted["params_snapshot"]["result_url"] == promoted["result_url"]
    assert "media" not in promoted["params_snapshot"]
    assert "reference_images" not in promoted["params_snapshot"]


def test_promote_assets_copies_absolute_local_upload_url_without_http_download(tmp_path, monkeypatch):
    _seed_config_cache(monkeypatch)
    from services.marketing_publication_asset_service import MarketingPublicationAssetService

    root = tmp_path
    upload_file = root / "upload" / "temp" / "20260625" / "upload_20260625_104009_160fa219.png"
    upload_file.parent.mkdir(parents=True)
    upload_file.write_bytes(b"uploaded-reference")
    result_file = root / "upload" / "cache" / "2026-06-25" / "result.png"
    result_file.parent.mkdir(parents=True)
    result_file.write_bytes(b"result-bytes")

    monkeypatch.setattr(
        "services.marketing_publication_asset_service.MediaFileMappingModel.create",
        lambda **kwargs: 1,
    )
    monkeypatch.setattr(
        "services.marketing_publication_asset_service.urllib.request.urlopen",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not download local upload URL")),
    )

    ai_tool = SimpleNamespace(
        id=94,
        user_id=7,
        prompt="edit with uploaded reference",
        result_url="/upload/cache/2026-06-25/result.png",
        image_path="http://localhost:11000/upload/temp/20260625/upload_20260625_104009_160fa219.png",
        reference_images=None,
        audio_path=None,
        video_path=None,
        type=12,
        ratio="1:1",
        duration=None,
        image_size=None,
        extra_config=None,
        implementation=3,
    )

    promoted = MarketingPublicationAssetService.promote_assets(ai_tool, 126, root_dir=root)

    ref_path = root / "upload" / "marketing_publications" / "126" / "reference_1.png"
    assert ref_path.read_bytes() == b"uploaded-reference"
    assert promoted["reference_images"] == ["/upload/marketing_publications/126/reference_1.png"]


def test_text_to_video_snapshot_does_not_use_result_as_remix_media(tmp_path, monkeypatch):
    _seed_config_cache(monkeypatch)
    from services.marketing_publication_asset_service import MarketingPublicationAssetService

    root = tmp_path
    result_file = root / "upload" / "cache" / "2026-06-25" / "text2video.mp4"
    result_file.parent.mkdir(parents=True)
    result_file.write_bytes(b"video-result")

    monkeypatch.setattr(
        "services.marketing_publication_asset_service.MediaFileMappingModel.create",
        lambda **kwargs: 1,
    )
    monkeypatch.setattr(
        "services.marketing_publication_asset_service.MarketingPublicationAssetService._get_task_config",
        lambda task_id: SimpleNamespace(category="text_to_video", key="seedance_1", name="Seedance 1.0"),
    )

    ai_tool = SimpleNamespace(
        id=95,
        user_id=7,
        prompt="make a product video",
        result_url="/upload/cache/2026-06-25/text2video.mp4",
        image_path=None,
        reference_images=None,
        audio_path=None,
        video_path=None,
        type=22,
        ratio="16:9",
        duration=5,
        image_size=None,
        extra_config=None,
        implementation=3,
    )

    promoted = MarketingPublicationAssetService.promote_assets(ai_tool, 127, root_dir=root)

    assert promoted["params_snapshot"]["mode"] == "video"
    assert promoted["params_snapshot"]["media_type"] == "video"
    assert promoted["params_snapshot"]["result_url"] == promoted["result_url"]
    assert "media" not in promoted["params_snapshot"]
    assert "video_urls" not in promoted["params_snapshot"]
    assert "reference_images" not in promoted["params_snapshot"]


def test_image_and_video_references_are_included_for_video_remix(tmp_path, monkeypatch):
    _seed_config_cache(monkeypatch)
    from services.marketing_publication_asset_service import MarketingPublicationAssetService

    root = tmp_path
    result_file = root / "upload" / "cache" / "2026-06-25" / "result.mp4"
    image_ref = root / "upload" / "temp" / "20260625" / "first.png"
    video_ref = root / "upload" / "temp" / "20260625" / "ref.mp4"
    for path, payload in [(result_file, b"video-result"), (image_ref, b"image-ref"), (video_ref, b"video-ref")]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)

    monkeypatch.setattr(
        "services.marketing_publication_asset_service.MediaFileMappingModel.create",
        lambda **kwargs: 1,
    )
    monkeypatch.setattr(
        "services.marketing_publication_asset_service.MarketingPublicationAssetService._get_task_config",
        lambda task_id: SimpleNamespace(category="image_to_video", key="seedance_1", name="Seedance 1.0"),
    )

    ai_tool = SimpleNamespace(
        id=96,
        user_id=7,
        prompt="animate the product",
        result_url="/upload/cache/2026-06-25/result.mp4",
        image_path="/upload/temp/20260625/first.png",
        reference_images=None,
        audio_path=None,
        video_path="/upload/temp/20260625/ref.mp4",
        type=23,
        ratio="16:9",
        duration=5,
        image_size=None,
        extra_config=None,
        implementation=3,
    )

    promoted = MarketingPublicationAssetService.promote_assets(ai_tool, 128, root_dir=root)

    assert promoted["reference_images"] == ["/upload/marketing_publications/128/reference_1.png"]
    assert promoted["video_urls"] == ["/upload/marketing_publications/128/video_1.mp4"]
    assert promoted["params_snapshot"]["media"] == [
        {
            "type": "image",
            "serverUrl": "/upload/marketing_publications/128/reference_1.png",
            "thumbnailUrl": "/upload/marketing_publications/128/reference_1.png",
        },
        {
            "type": "video",
            "serverUrl": "/upload/marketing_publications/128/video_1.mp4",
            "thumbnailUrl": "/upload/marketing_publications/128/video_1.mp4",
        },
    ]


def test_promote_assets_fails_when_source_file_is_missing(tmp_path, monkeypatch):
    _seed_config_cache(monkeypatch)
    from services.marketing_publication_asset_service import PublicationAssetError
    from services.marketing_publication_asset_service import MarketingPublicationAssetService

    ai_tool = SimpleNamespace(
        id=92,
        user_id=7,
        prompt="expired file",
        result_url="/upload/cache/2026-06-24/missing.png",
        image_path=None,
        reference_images=None,
        audio_path=None,
        video_path=None,
        type=12,
        ratio="1:1",
        duration=None,
        image_size=None,
        extra_config=None,
        implementation=3,
    )

    try:
        MarketingPublicationAssetService.promote_assets(ai_tool, 124, root_dir=tmp_path)
    except PublicationAssetError as exc:
        assert "missing" in str(exc).lower() or "not found" in str(exc).lower()
    else:
        raise AssertionError("Expected PublicationAssetError for missing source file")


def _enable_cdn(monkeypatch):
    """在单元测试配置中开启 CDN，并返回可继续写入的 server 配置字典。"""
    import config.config_util as config_util

    server_cfg = config_util._config_cache.setdefault(
        "config_unit.yml", {}
    ).setdefault("server", {})
    server_cfg["auto_upload_to_cdn"] = True
    return server_cfg


def test_promote_assets_triggers_cdn_upload_for_each_promoted_asset(tmp_path, monkeypatch):
    _seed_config_cache(monkeypatch)
    from services.marketing_publication_asset_service import MarketingPublicationAssetService

    root = tmp_path
    cache_file = root / "upload" / "cache" / "2026-06-24" / "result.png"
    ref_file = root / "upload" / "temp" / "20260624" / "ref.png"
    for path in (cache_file, ref_file):
        path.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_bytes(b"result-bytes")
    ref_file.write_bytes(b"ref-bytes")

    monkeypatch.setattr(
        "services.marketing_publication_asset_service.MediaFileMappingModel.create",
        lambda **kwargs: 1000 + len(kwargs),  # 返回伪 mapping_id
    )

    triggered = []

    def fake_trigger(mapping_id, local_path):
        triggered.append((mapping_id, local_path))

    monkeypatch.setattr(
        "services.marketing_publication_asset_service.MarketingPublicationAssetService._trigger_cdn_upload",
        fake_trigger,
    )

    ai_tool = SimpleNamespace(
        id=97,
        user_id=7,
        prompt="cdn promote",
        result_url="/upload/cache/2026-06-24/result.png",
        image_path="/upload/temp/20260624/ref.png",
        reference_images=json.dumps(["/upload/temp/20260624/ref.png"]),
        audio_path=None,
        video_path=None,
        type=12,
        ratio="1:1",
        duration=None,
        image_size=None,
        extra_config=None,
        implementation=3,
    )

    MarketingPublicationAssetService.promote_assets(ai_tool, 130, root_dir=root)

    # result 与 reference 各应触发一次，且使用去掉前导 / 的本地路径
    promoted_paths = {entry[1] for entry in triggered}
    assert "upload/marketing_publications/130/result.png" in promoted_paths
    assert "upload/marketing_publications/130/reference_1.png" in promoted_paths
    assert len(triggered) == 2


def test_trigger_cdn_upload_skips_when_cdn_disabled(tmp_path, monkeypatch):
    _seed_config_cache(monkeypatch)
    import utils.cdn_util as cdn_util
    from services.marketing_publication_asset_service import MarketingPublicationAssetService

    # 配置中未设置 auto_upload_to_cdn（默认 False）
    util_calls = []
    monkeypatch.setattr(cdn_util.CDNUtil, "trigger_cdn_upload", lambda *a, **k: util_calls.append(a))

    MarketingPublicationAssetService._trigger_cdn_upload(42, "upload/marketing_publications/130/result.png")

    assert util_calls == []  # 未启用 CDN，不应调用上传


def test_trigger_cdn_upload_invokes_util_when_enabled(tmp_path, monkeypatch):
    _seed_config_cache(monkeypatch)
    _enable_cdn(monkeypatch)
    import threading
    import utils.cdn_util as cdn_util
    from services.marketing_publication_asset_service import MarketingPublicationAssetService

    util_calls = []
    monkeypatch.setattr(cdn_util.CDNUtil, "trigger_cdn_upload", lambda *a, **k: util_calls.append(a))

    # 用同步执行的 FakeThread 替换 threading.Thread，避免线程竞态，保证断言确定性
    class _FakeThread:
        def __init__(self, target, args, **kwargs):
            self._target = target
            self._args = args

        def start(self):
            self._target(*self._args)

    monkeypatch.setattr(threading, "Thread", _FakeThread)

    MarketingPublicationAssetService._trigger_cdn_upload(77, "upload/marketing_publications/130/result.png")

    assert util_calls == [(77, "upload/marketing_publications/130/result.png")]
