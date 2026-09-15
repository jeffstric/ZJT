"""
上传媒体文件安全校验单元测试

覆盖扩展名白名单 / 危险扩展显式拒绝 / 魔数校验（防伪造扩展名的存储型 XSS）/
分块大小上限（防超大文件打满磁盘，超限半成品清理）。不连数据库。
"""
import io
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest
from starlette.datastructures import UploadFile

from config.constant import MediaUploadSafetyConstants
from utils.media_upload import (
    UploadValidationError,
    max_upload_size_for_ext,
    resolve_media_extension,
    save_upload_chunked,
)


def _upload(content: bytes, filename: str) -> UploadFile:
    return UploadFile(file=io.BytesIO(content), filename=filename)


PNG_BYTES = b'\x89PNG\r\n\x1a\n' + b'\x00' * 64
JPEG_BYTES = b'\xff\xd8\xff\xe0' + b'\x00' * 64
MP4_BYTES = b'\x00\x00\x00\x20ftypisom' + b'\x00' * 64
WEBP_BYTES = b'RIFF\x24\x00\x00\x00WEBPVP8 ' + b'\x00' * 64
WAV_BYTES = b'RIFF\x24\x08\x00\x00WAVEfmt ' + b'\x00' * 64
MP3_ID3_BYTES = b'ID3\x04\x00\x00\x00\x00\x00\x00' + b'\x00' * 64
MP3_FRAME_BYTES = b'\xff\xfb\x90\x00' + b'\x00' * 64
HTML_BYTES = b'<!DOCTYPE html><html><script>alert(1)</script></html>'


# ============ resolve_media_extension ============

class TestResolveMediaExtension:
    @pytest.mark.parametrize("filename,expected", [
        ("photo.PNG", ".png"),
        ("a.Jpg", ".jpg"),
        ("b.jpeg", ".jpeg"),
        ("c.webp", ".webp"),
        ("d.gif", ".gif"),
        ("e.bmp", ".bmp"),
        ("v.mp4", ".mp4"),
        ("v.mov", ".mov"),
        ("v.webm", ".webm"),
        ("v.avi", ".avi"),
        ("v.mkv", ".mkv"),
        ("a.mp3", ".mp3"),
        ("a.wav", ".wav"),
        ("a.m4a", ".m4a"),
        ("a.aac", ".aac"),
        ("a.ogg", ".ogg"),
        ("a.flac", ".flac"),
        ("/path/to/x.png", ".png"),   # 带路径分隔符时只取最后一段扩展名
    ])
    def test_allowed_extensions(self, filename, expected):
        assert resolve_media_extension(filename) == expected

    @pytest.mark.parametrize("filename", [
        "poc.html", "poc.htm", "evil.svg", "a.xhtml", "b.xml", "c.js", "d.mjs", "e.css",
    ])
    def test_blocked_extensions_rejected(self, filename):
        with pytest.raises(UploadValidationError, match="不允许上传"):
            resolve_media_extension(filename)

    @pytest.mark.parametrize("filename", [
        "payload.html.png",   # 双扩展名：真实扩展名 .png 走白名单，内容由魔数校验兜底
    ])
    def test_double_extension_uses_final_ext(self, filename):
        # 双扩展名最终以 .png 结尾，允许进入魔数校验（内容由魔数把关）
        assert resolve_media_extension(filename) == ".png"

    @pytest.mark.parametrize("filename", ["shell.php", "doc.pdf", "video.exe", "sub", ""])
    def test_unknown_extensions_rejected(self, filename):
        with pytest.raises(UploadValidationError):
            resolve_media_extension(filename)

    def test_none_filename_rejected(self):
        with pytest.raises(UploadValidationError, match="缺少扩展名"):
            resolve_media_extension(None)

    def test_error_is_value_error_subclass(self):
        # 端点层用 except UploadValidationError 映射 400，须是 ValueError 子类
        assert issubclass(UploadValidationError, ValueError)


# ============ max_upload_size_for_ext ============

class TestMaxUploadSizeForExt:
    def test_size_tiers(self):
        assert max_upload_size_for_ext(".png") == MediaUploadSafetyConstants.MAX_IMAGE_SIZE
        assert max_upload_size_for_ext(".mp4") == MediaUploadSafetyConstants.MAX_VIDEO_SIZE
        assert max_upload_size_for_ext(".mp3") == MediaUploadSafetyConstants.MAX_AUDIO_SIZE


# ============ save_upload_chunked ============

class TestSaveUploadChunked:
    def _save(self, tmp_path, content, filename):
        target = os.path.join(tmp_path, "out" + os.path.splitext(filename)[1])
        upload = _upload(content, filename)
        size = save_upload_chunked(upload, target, os.path.splitext(filename)[1].lower())
        return target, size

    @pytest.mark.parametrize("filename,content", [
        ("a.png", PNG_BYTES),
        ("a.jpg", JPEG_BYTES),
        ("a.mp4", MP4_BYTES),
        ("a.webp", WEBP_BYTES),
        ("a.wav", WAV_BYTES),
        ("a.mp3", MP3_ID3_BYTES),
        ("a.mp3", MP3_FRAME_BYTES),
    ])
    def test_valid_files_saved(self, tmp_path, filename, content):
        target, size = self._save(tmp_path, content, filename)
        assert os.path.exists(target)
        assert size == len(content)
        with open(target, "rb") as f:
            assert f.read() == content

    def test_forged_extension_rejected(self, tmp_path):
        # 核心攻击场景：poc.html 改名 poc.png（Content-Type 也可伪造为 image/png）
        target = os.path.join(tmp_path, "out.png")
        with pytest.raises(UploadValidationError, match="魔数校验失败"):
            save_upload_chunked(_upload(HTML_BYTES, "poc.png"), target, ".png")
        assert not os.path.exists(target), "校验失败时不得留下半成品文件"

    def test_empty_head_rejected(self, tmp_path):
        target = os.path.join(tmp_path, "out.png")
        with pytest.raises(UploadValidationError):
            save_upload_chunked(_upload(b"", "a.png"), target, ".png")
        assert not os.path.exists(target)

    def test_oversize_rejected_and_cleaned(self, tmp_path, monkeypatch):
        # 缩小图片上限到 1 字节，构造跨块内容触发超限中断
        monkeypatch.setattr(MediaUploadSafetyConstants, "MAX_IMAGE_SIZE", 1)
        target = os.path.join(tmp_path, "out.png")
        with pytest.raises(UploadValidationError, match="超过限制"):
            save_upload_chunked(_upload(PNG_BYTES, "a.png"), target, ".png")
        assert not os.path.exists(target), "超限时必须清理半成品文件"

    def test_multichunk_write(self, tmp_path, monkeypatch):
        # 跨多个 chunk 的正常文件完整落盘（块大小缩到 8 字节）
        monkeypatch.setattr(MediaUploadSafetyConstants, "CHUNK_SIZE", 8)
        content = PNG_BYTES + os.urandom(100)
        target, size = self._save(tmp_path, content, "a.png")
        assert size == len(content)
        with open(target, "rb") as f:
            assert f.read() == content
