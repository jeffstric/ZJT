"""
上传媒体文件安全校验单元测试

覆盖扩展名白名单 / 危险扩展显式拒绝 / 魔数校验（防伪造扩展名的存储型 XSS）/
分块大小上限（防超大文件打满磁盘，超限半成品清理）。不连数据库。
"""
import io
import os
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest
from PIL import Image
from starlette.datastructures import UploadFile

from config.constant import MediaUploadSafetyConstants
from utils.media_upload import (
    UploadValidationError,
    check_media_magic,
    convert_tiff_file_to_png,
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
# TIFF 头两种字节序：II（小端）与 MM（大端）
TIFF_LE_BYTES = b'II*\x00' + b'\x00' * 64
TIFF_BE_BYTES = b'MM\x00*' + b'\x00' * 64


# ============ resolve_media_extension ============

class TestResolveMediaExtension:
    @pytest.mark.parametrize("filename,expected", [
        ("photo.PNG", ".png"),
        ("a.Jpg", ".jpg"),
        ("b.jpeg", ".jpeg"),
        ("c.webp", ".webp"),
        ("d.gif", ".gif"),
        ("e.bmp", ".bmp"),
        ("scan.tif", ".tif"),
        ("scan.TIFF", ".tiff"),
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


# ============ TIFF：白名单放行 + 落盘归一化为 PNG ============

def _make_tiff(path, mode="RGB", size=(8, 6), frames=1):
    """用 PIL 生成真实 TIFF 测试文件（覆盖 RGB/CMYK/16bit/多帧）。"""
    first = Image.new(mode, size, (128, 64, 32) if mode == "RGB" else 0)
    if frames > 1:
        extras = [Image.new(mode, size, 200)] * (frames - 1)
        first.save(path, format="TIFF", save_all=True, append_images=extras)
    else:
        first.save(path, format="TIFF")
    return path


class TestTiffUpload:
    @pytest.mark.parametrize("filename,content", [
        ("a.tif", TIFF_LE_BYTES),
        ("a.tiff", TIFF_LE_BYTES),
        ("a.tif", TIFF_BE_BYTES),   # 大端字节序魔数
    ])
    def test_valid_tiff_magic_saved(self, tmp_path, filename, content):
        target, size = self._save_tiff(tmp_path, content, filename)
        assert os.path.exists(target)
        assert size == len(content)

    def _save_tiff(self, tmp_path, content, filename):
        target = os.path.join(tmp_path, "out" + os.path.splitext(filename)[1])
        upload = _upload(content, filename)
        size = save_upload_chunked(upload, target, os.path.splitext(filename)[1].lower())
        return target, size

    def test_forged_tiff_rejected(self, tmp_path):
        # poc.html 改名 poc.tif：魔数校验拒绝且不留半成品
        target = os.path.join(tmp_path, "out.tif")
        with pytest.raises(UploadValidationError, match="魔数校验失败"):
            save_upload_chunked(_upload(HTML_BYTES, "poc.tif"), target, ".tif")
        assert not os.path.exists(target)

    def test_tiff_image_size_tier(self):
        # tif 沿用图片档 10MB 上限（未单独放宽）
        assert max_upload_size_for_ext(".tif") == MediaUploadSafetyConstants.MAX_IMAGE_SIZE
        assert max_upload_size_for_ext(".tiff") == MediaUploadSafetyConstants.MAX_IMAGE_SIZE


class TestConvertTiffToPng:
    def _converted(self, tmp_path, name, **kwargs):
        src = _make_tiff(os.path.join(tmp_path, name), **kwargs)
        return src, convert_tiff_file_to_png(src)

    def test_rgb_tiff_converted(self, tmp_path):
        src, dst = self._converted(tmp_path, "a.tif")
        assert dst.endswith(".png") and dst != src
        assert not os.path.exists(src), "原 tif 必须删除，upload 目录不得残留 tif"
        with Image.open(dst) as img:
            assert img.format == "PNG"
            assert img.size == (8, 6)
            assert img.mode in ("RGB", "RGBA")

    def test_cmyk_tiff_converted_to_rgb(self, tmp_path):
        src, dst = self._converted(tmp_path, "cmyk.tif", mode="CMYK")
        with Image.open(dst) as img:
            assert img.mode in ("RGB", "RGBA")

    def test_multiframe_tiff_takes_first_frame(self, tmp_path):
        src, dst = self._converted(tmp_path, "multi.tif", frames=3)
        with Image.open(dst) as img:
            assert getattr(img, "n_frames", 1) == 1, "多帧 TIFF 只保留第一帧"

    def test_corrupted_tiff_rejected_and_cleaned(self, tmp_path):
        # 魔数合法但内容损坏：转码失败时原 tif 与半成品一并清理
        src = os.path.join(tmp_path, "bad.tif")
        with open(src, "wb") as f:
            f.write(TIFF_LE_BYTES + b"\x00" * 200)
        with pytest.raises(UploadValidationError, match="解码失败"):
            convert_tiff_file_to_png(src)
        assert not os.path.exists(src), "转码失败时原 tif 必须清理"
        assert not os.path.exists(os.path.splitext(src)[0] + ".png")

    def test_save_then_convert_full_flow(self, tmp_path):
        # 端点真实链路：save_upload_chunked 落盘 → 转 png → 原扩展名文件消失
        buf = io.BytesIO()
        Image.new("RGB", (10, 10), (1, 2, 3)).save(buf, format="TIFF")
        content = buf.getvalue()
        target = os.path.join(tmp_path, "upload_x.tif")
        save_upload_chunked(_upload(content, "x.tif"), target, ".tif")
        dst = convert_tiff_file_to_png(target)
        assert os.path.exists(dst) and not os.path.exists(target)


# ============ check_media_magic ============

class TestCheckMediaMagic:
    """check_media_magic：供已持有文件内容的调用方复用的魔数校验。"""

    @pytest.mark.parametrize("ext,head", [
        (".png", PNG_BYTES[:32]),
        (".jpg", JPEG_BYTES[:32]),
        (".webp", WEBP_BYTES[:32]),
        (".mp4", MP4_BYTES[:32]),
        (".mp3", MP3_ID3_BYTES[:32]),
        (".tif", TIFF_LE_BYTES[:32]),
        (".tiff", TIFF_BE_BYTES[:32]),
    ])
    def test_matching_magic_accepted(self, ext, head):
        assert check_media_magic(ext, head) is True

    @pytest.mark.parametrize("ext", [".png", ".jpg", ".gif", ".webp"])
    def test_html_bytes_rejected(self, ext):
        # 伪造扩展名的 HTML 载荷（存储型 XSS）：魔数不符一律拒绝
        assert check_media_magic(ext, HTML_BYTES[:32]) is False

    def test_empty_head_rejected(self):
        assert check_media_magic(".png", b"") is False

    def test_unknown_ext_rejected(self):
        # 无对应魔数表的扩展名直接拒绝（防御未知格式混入）
        assert check_media_magic(".xyz", PNG_BYTES[:32]) is False


# ============ _validate_image_size 收口守卫 ============

class TestValidateImageSizeChokePoint:
    """AST 源码守卫：characters/locations/props 参考图 12 处落盘点的唯一校验
    入口 server.py::_validate_image_size 必须包含扩展名白名单 + 魔数校验，
    防止后续重构时退回仅大小校验（.html/.svg 落盘即同域存储型 XSS）。
    """

    def _validate_image_size_calls(self):
        tree = ast.parse((ROOT / "server.py").read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "_validate_image_size":
                return {
                    n.func.id if isinstance(n.func, ast.Name) else getattr(n.func, "attr", "")
                    for n in ast.walk(node)
                    if isinstance(n, ast.Call)
                }
        raise AssertionError("server.py 中未找到 _validate_image_size 函数")

    def test_choke_point_keeps_whitelist_and_magic(self):
        calls = self._validate_image_size_calls()
        assert "resolve_media_extension" in calls, "必须保留扩展名白名单校验"
        assert "check_media_magic" in calls, "必须保留魔数校验"
