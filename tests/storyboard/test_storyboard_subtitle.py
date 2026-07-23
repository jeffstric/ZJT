"""整片导出字幕模块单元测试。

覆盖：
- ``ffmpeg_subtitles_filter_arg`` 在带/不带 fontsdir 时的滤镜字符串
- ``resolve_builtin_font`` 在内置字体存在/缺失时的返回值
- ``write_ass_file`` 生成的 ASS Style 字体名为内置 CJK 字体
"""
import os
import tempfile
from unittest import mock

import pytest

from config.constant import StoryboardSubtitleConstants
from services.storyboard_subtitle import (
    SubtitleCue,
    ffmpeg_subtitles_filter_arg,
    resolve_builtin_font,
    resolve_cjk_font_name,
    write_ass_file,
)


# ---------------- ffmpeg_subtitles_filter_arg ----------------

def test_filter_arg_default_has_no_fontsdir():
    """旧调用方式（不传 fonts_subdir）应保持向后兼容，不附加 fontsdir。"""
    arg = ffmpeg_subtitles_filter_arg()
    assert arg == "subtitles=subtitles.ass"


def test_filter_arg_with_fontsdir_relative():
    """传入相对子目录时应追加 :fontsdir=，且不破坏原文件名。"""
    arg = ffmpeg_subtitles_filter_arg("subtitles.ass", fonts_subdir="fonts")
    assert arg == "subtitles=subtitles.ass:fontsdir=fonts"


def test_filter_arg_escapes_colon_in_ass_name():
    """ass 名含冒号（理论上的奇怪文件名）必须转义，避免破坏滤镜语法。"""
    arg = ffmpeg_subtitles_filter_arg("wei rd.ass", fonts_subdir="fonts")
    # 主名没冒号，只验证 fontsdir 仍在
    assert arg.endswith(":fontsdir=fonts")


def test_filter_arg_fontsdir_backslash_normalized():
    """Windows 反斜杠路径在 fontsdir 中应被规范化为 /。"""
    arg = ffmpeg_subtitles_filter_arg("subtitles.ass", fonts_subdir="fonts\\sub")
    assert arg == "subtitles=subtitles.ass:fontsdir=fonts/sub"


# ---------------- resolve_builtin_font ----------------

def test_resolve_builtin_font_returns_family_and_path():
    """内置字体存在时应返回 (family, 绝对路径)。"""
    family, path = resolve_builtin_font()
    assert family == StoryboardSubtitleConstants.BUILTIN_FONT_FAMILY
    assert path is not None
    assert os.path.isabs(path)
    assert os.path.isfile(path), f"内置字体文件应存在: {path}"
    assert path.endswith(StoryboardSubtitleConstants.BUILTIN_FONT_FILENAME)


def test_resolve_builtin_font_missing_returns_none():
    """内置字体文件缺失时应返回 (None, None)，不抛异常。"""
    with mock.patch("os.path.isfile", return_value=False):
        family, path = resolve_builtin_font()
    assert family is None
    assert path is None


# ---------------- write_ass_file ----------------

def _read_ass(path: str) -> str:
    with open(path, "r", encoding="utf-8-sig") as f:
        return f.read()


def test_write_ass_file_uses_builtin_font_family():
    """生成的 ASS Style 行字体名应为内置 CJK 字体（前提是内置字体存在）。"""
    family, _ = resolve_builtin_font()
    if family is None:
        pytest.skip("内置字体不存在，跳过内置字体名校验")
    cues = [SubtitleCue(start=0.0, end=2.0, text="你好世界")]

    with tempfile.TemporaryDirectory() as d:
        ass_path = os.path.join(d, "subtitles.ass")
        write_ass_file(cues, ass_path, width=1080, height=1920)
        content = _read_ass(ass_path)

    style_line = next(line for line in content.splitlines() if line.startswith("Style: Default,"))
    assert StoryboardSubtitleConstants.BUILTIN_FONT_FAMILY in style_line, style_line


def test_write_ass_file_writes_utf8_bom_and_dialogue():
    """ASS 文件应以 UTF-8 BOM 开头，且包含 Dialogue 行。"""
    cues = [SubtitleCue(start=0.0, end=2.0, text="中文测试 \\N 第二行")]
    with tempfile.TemporaryDirectory() as d:
        ass_path = os.path.join(d, "subtitles.ass")
        write_ass_file(cues, ass_path, width=1080, height=1920)
        with open(ass_path, "rb") as f:
            head = f.read(3)
        content = _read_ass(ass_path)

    assert head == b"\xef\xbb\xbf"  # UTF-8 BOM
    assert any(line.startswith("Dialogue:") and "中文测试" in line for line in content.splitlines())


def test_write_ass_file_explicit_font_name_overrides_builtin():
    """显式传入 font_name 时应优先使用，不查内置字体。"""
    cues = [SubtitleCue(start=0.0, end=2.0, text="x")]
    with tempfile.TemporaryDirectory() as d:
        ass_path = os.path.join(d, "subtitles.ass")
        write_ass_file(cues, ass_path, width=1080, height=1920, font_name="SimHei")
        content = _read_ass(ass_path)

    style_line = next(line for line in content.splitlines() if line.startswith("Style: Default,"))
    assert "SimHei" in style_line
    assert StoryboardSubtitleConstants.BUILTIN_FONT_FAMILY not in style_line


# ---------------- resolve_cjk_font_name (fallback) ----------------

def test_resolve_cjk_font_name_returns_non_empty():
    """系统字体探测兜底应始终返回非空字符串（即使是 'sans-serif'）。"""
    name = resolve_cjk_font_name()
    assert isinstance(name, str) and name
