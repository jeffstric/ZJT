"""
故事板整片导出：字幕折行、时间轴分页、ASS 生成与 ffmpeg 硬烧滤镜。

与 storyboard_export_service 解耦：只消费带 text/duration 的 plan 结构，不反向依赖导出实现细节。
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from typing import Any, List, Optional, Protocol, Sequence

from config.constant import StoryboardSubtitleConstants

logger = logging.getLogger(__name__)


@dataclass
class SubtitleCue:
    """一条 ASS Dialogue 事件（可能是长对白分页后的一页）。"""
    start: float
    end: float
    text: str  # 可含 ASS \\N 换行


class _AudioLike(Protocol):
    text: str
    duration: Optional[float]
    file: str
    url: str


class _SceneLike(Protocol):
    duration: float
    audios: Sequence[_AudioLike]


class _PlanLike(Protocol):
    scenes: Sequence[_SceneLike]


# ---------------------------------------------------------------------------
# 文本规范化 / 折行 / 分页
# ---------------------------------------------------------------------------

_PUNCT_BREAK = set("，。！？；、,.!?;:：…—-\n\r\t ")


def normalize_subtitle_text(text: str) -> str:
    if not text:
        return ""
    s = str(text).replace("\r\n", "\n").replace("\r", "\n")
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def estimate_max_chars_per_line(width: int, font_size: int) -> int:
    """按分辨率与字号估算每行最大字符数（中文按一字一宽）。"""
    usable = max(1, int(width * StoryboardSubtitleConstants.MAX_WIDTH_RATIO))
    char_w = max(1.0, font_size * StoryboardSubtitleConstants.CHAR_WIDTH_RATIO)
    n = int(usable / char_w)
    return max(StoryboardSubtitleConstants.MIN_CHARS_PER_LINE, n)


def resolve_font_size(height: int) -> int:
    raw = int(round(height / StoryboardSubtitleConstants.FONT_SIZE_DIVISOR))
    return max(
        StoryboardSubtitleConstants.FONT_SIZE_MIN,
        min(StoryboardSubtitleConstants.FONT_SIZE_MAX, raw),
    )


def wrap_subtitle_lines(text: str, max_chars: int) -> List[str]:
    """按标点优先、再按字数硬切，折成多行（不含分页）。"""
    text = normalize_subtitle_text(text)
    if not text:
        return []
    max_chars = max(StoryboardSubtitleConstants.MIN_CHARS_PER_LINE, int(max_chars))

    # 先按显式换行拆段
    paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
    lines: List[str] = []
    for para in paragraphs:
        lines.extend(_wrap_paragraph(para, max_chars))
    return lines


def _wrap_paragraph(para: str, max_chars: int) -> List[str]:
    if len(para) <= max_chars:
        return [para]

    lines: List[str] = []
    buf = ""
    i = 0
    n = len(para)
    while i < n:
        ch = para[i]
        buf += ch
        i += 1
        if len(buf) < max_chars:
            continue
        # 在 buf 内找最近可断点
        break_at = -1
        for j in range(len(buf) - 1, max(0, len(buf) - max_chars // 3) - 1, -1):
            if buf[j] in _PUNCT_BREAK:
                break_at = j + 1
                break
        if break_at <= 0:
            break_at = len(buf)
        line = buf[:break_at].strip()
        rest = buf[break_at:]
        if line:
            lines.append(line)
        buf = rest
    if buf.strip():
        lines.append(buf.strip())
    return lines


def paginate_lines(lines: List[str], max_lines: int) -> List[List[str]]:
    """将行列表切成多页，每页最多 max_lines 行。"""
    if not lines:
        return []
    max_lines = max(1, int(max_lines))
    pages: List[List[str]] = []
    for i in range(0, len(lines), max_lines):
        pages.append(lines[i : i + max_lines])
    return pages


def ellipsize_line(line: str, max_chars: int) -> str:
    line = (line or "").strip()
    if len(line) <= max_chars:
        return line
    if max_chars <= 1:
        return "…"
    return line[: max_chars - 1].rstrip() + "…"


def fit_pages_to_duration(
    pages: List[List[str]],
    avail: float,
    *,
    min_page: float,
    max_chars: int,
) -> List[List[str]]:
    """
    根据可用时长限制页数；装不下则截断最后一页并加省略号。
    """
    if not pages:
        return []
    avail = max(0.0, float(avail))
    min_page = max(0.1, float(min_page))
    if avail < 1e-6:
        # 无时长：只留一页并省略
        first = pages[0][:]
        if len(pages) > 1 or (first and len("".join(first)) > max_chars * 2):
            if first:
                first[-1] = ellipsize_line(first[-1], max_chars)
        return [first]

    max_pages = max(1, int(avail // min_page))
    if len(pages) <= max_pages:
        return pages

    kept = pages[:max_pages]
    # 还有后续页被丢掉 → 末页加省略
    if kept and kept[-1]:
        kept[-1] = kept[-1][:]
        kept[-1][-1] = ellipsize_line(kept[-1][-1], max_chars)
    return kept


def allocate_page_durations(
    pages: List[List[str]],
    avail: float,
    *,
    min_page: float,
) -> List[float]:
    """字数加权分配各页时长，尽量满足 min_page。"""
    n = len(pages)
    if n == 0:
        return []
    avail = max(0.0, float(avail))
    if n == 1:
        return [avail]

    weights = [max(1, sum(len(line) for line in p)) for p in pages]
    total_w = sum(weights) or n
    raw = [avail * w / total_w for w in weights]

    # 抬升过短页（从较长页挪）
    min_page = min(min_page, avail / n) if avail > 0 else 0.0
    for _ in range(n * 2):
        short_idx = [i for i, d in enumerate(raw) if d + 1e-9 < min_page]
        if not short_idx:
            break
        need = sum(min_page - raw[i] for i in short_idx)
        long_idx = [i for i, d in enumerate(raw) if d > min_page + 1e-9]
        if not long_idx:
            break
        pool = sum(raw[i] - min_page for i in long_idx)
        if pool <= 1e-9:
            break
        for i in short_idx:
            take = min_page - raw[i]
            raw[i] = min_page
        # 按超出比例从 long 扣
        for i in long_idx:
            excess = raw[i] - min_page
            raw[i] = min_page + excess * max(0.0, (pool - need)) / pool

    # 归一到 avail
    s = sum(raw) or 1.0
    raw = [d * avail / s for d in raw]
    return raw


def lines_to_ass_text(lines: List[str]) -> str:
    escaped = [_escape_ass(line) for line in lines if line is not None]
    return r"\N".join(escaped)


def _escape_ass(text: str) -> str:
    s = str(text or "")
    s = s.replace("\\", r"\\")
    s = s.replace("{", r"\{").replace("}", r"\}")
    s = s.replace("\n", r"\N")
    return s


# ---------------------------------------------------------------------------
# Cue 构建
# ---------------------------------------------------------------------------

def build_subtitle_cues(
    plan: _PlanLike,
    *,
    width: int,
    height: int,
    max_lines: Optional[int] = None,
    min_page_duration: Optional[float] = None,
) -> List[SubtitleCue]:
    """
    从导出 plan 生成全局时间轴字幕 cues。
    仅处理有 text 的对白；时长用 audio.duration，缺省 DEFAULT_CUE_DURATION。
    """
    max_lines = max_lines or StoryboardSubtitleConstants.MAX_LINES
    min_page = (
        min_page_duration
        if min_page_duration is not None
        else StoryboardSubtitleConstants.MIN_PAGE_DURATION_SECONDS
    )
    font_size = resolve_font_size(height)
    max_chars = estimate_max_chars_per_line(width, font_size)

    cues: List[SubtitleCue] = []
    t_global = 0.0
    fallback_span = 2.0

    for scene in plan.scenes or []:
        span = float(getattr(scene, "duration", 0) or 0) or fallback_span
        if span <= 0:
            span = fallback_span
        t_local = 0.0

        for audio in getattr(scene, "audios", None) or []:
            text = normalize_subtitle_text(getattr(audio, "text", None) or "")
            if not text:
                # 无文本仍推进时间（与音轨对齐）
                dur = _audio_dur(audio, span - t_local)
                t_local += dur
                if t_local >= span - 1e-9:
                    break
                continue

            remaining = max(0.0, span - t_local)
            if remaining <= 1e-6:
                break
            dur = min(_audio_dur(audio, remaining), remaining)
            if dur <= 1e-6:
                break

            window_start = t_global + t_local
            window_end = t_global + t_local + dur

            lines = wrap_subtitle_lines(text, max_chars)
            pages = paginate_lines(lines, max_lines)
            pages = fit_pages_to_duration(
                pages, dur, min_page=min_page, max_chars=max_chars
            )
            if not pages:
                t_local += dur
                continue

            durations = allocate_page_durations(pages, dur, min_page=min_page)
            t = window_start
            for page, pd in zip(pages, durations):
                pe = min(window_end, t + max(pd, 0.05))
                body = lines_to_ass_text(page)
                if body and pe > t + 1e-3:
                    cues.append(SubtitleCue(start=t, end=pe, text=body))
                t = pe

            t_local += dur
            if t_local >= span - 1e-9:
                break

        t_global += span

    return cues


def _audio_dur(audio: Any, fallback: float) -> float:
    d = getattr(audio, "duration", None)
    try:
        if d is not None and float(d) > 0:
            return float(d)
    except (TypeError, ValueError):
        pass
    # 尝试本地文件探测由 export 侧填好 duration；此处仅 fallback
    fb = float(fallback) if fallback and fallback > 0 else StoryboardSubtitleConstants.DEFAULT_CUE_DURATION_SECONDS
    return max(0.05, fb)


# ---------------------------------------------------------------------------
# ASS 写出
# ---------------------------------------------------------------------------

def format_ass_time(seconds: float) -> str:
    """ASS 时间 H:MM:SS.cc"""
    if seconds < 0:
        seconds = 0.0
    cs = int(round(seconds * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def resolve_builtin_font() -> tuple[Optional[str], Optional[str]]:
    """
    返回内置 CJK 字体的 (family_name, 绝对路径)。

    优先使用随项目分发的思源黑体（Noto Sans SC），避免：
    - 宿主机未安装中文字体（瘦客户机 / Docker / Windows Server Core）
    - Windows 下 ffmpeg fontconfig 无法把 family 名解析到系统字体（libass 渲染成豆腐块/蚂蚁文）

    内置字体缺失时返回 (None, None)，由调用方回退到系统字体探测。
    """
    from utils.project_path import get_project_root

    font_path = os.path.join(
        get_project_root(),
        StoryboardSubtitleConstants.BUILTIN_FONT_SUBDIR,
        StoryboardSubtitleConstants.BUILTIN_FONT_FILENAME,
    )
    if os.path.isfile(font_path):
        return StoryboardSubtitleConstants.BUILTIN_FONT_FAMILY, font_path
    logger.warning("内置 CJK 字体缺失，回退系统字体探测: %s", font_path)
    return None, None


def resolve_cjk_font_name() -> str:
    """返回 ASS Style 用的字体名（尽量选系统常见中文字体）。"""
    candidates = [
        # (path, ass font name)
        (r"C:\Windows\Fonts\msyh.ttc", "Microsoft YaHei"),
        (r"C:\Windows\Fonts\msyhbd.ttc", "Microsoft YaHei"),
        (r"C:\Windows\Fonts\simhei.ttf", "SimHei"),
        (r"C:\Windows\Fonts\simsun.ttc", "SimSun"),
        ("/System/Library/Fonts/PingFang.ttc", "PingFang SC"),
        ("/System/Library/Fonts/STHeiti Light.ttc", "Heiti SC"),
        ("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", "Noto Sans CJK SC"),
        ("/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc", "Noto Sans CJK SC"),
        ("/usr/share/fonts/truetype/wqy/wqy-microhei.ttc", "WenQuanYi Micro Hei"),
    ]
    for path, name in candidates:
        if os.path.isfile(path):
            return name
    logger.warning("未找到常见中文字体，ASS 使用 sans-serif")
    return "sans-serif"


def write_ass_file(
    cues: List[SubtitleCue],
    path: str,
    width: int,
    height: int,
    *,
    font_name: Optional[str] = None,
) -> str:
    """写入 ASS 文件，返回 path。"""
    if not font_name:
        # 内置字体优先，缺失时回退系统字体探测
        builtin_family, _ = resolve_builtin_font()
        font_name = builtin_family or resolve_cjk_font_name()
    font_size = resolve_font_size(height)
    margin_l = max(8, int(width * StoryboardSubtitleConstants.SIDE_MARGIN_RATIO))
    margin_r = margin_l
    margin_v = max(12, int(height * StoryboardSubtitleConstants.BOTTOM_MARGIN_RATIO))

    # Style: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour,
    # Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow,
    # Alignment, MarginL, MarginR, MarginV, Encoding
    style = (
        f"Style: Default,{font_name},{font_size},"
        f"&H00FFFFFF,&H000000FF,&H00000000,&H80000000,"
        f"0,0,0,0,100,100,0,0,1,2,1,2,"
        f"{margin_l},{margin_r},{margin_v},1"
    )

    lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {int(width)}",
        f"PlayResY: {int(height)}",
        "WrapStyle: 0",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding",
        style,
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    for cue in cues:
        if cue.end <= cue.start or not (cue.text or "").strip():
            continue
        lines.append(
            f"Dialogue: 0,{format_ass_time(cue.start)},{format_ass_time(cue.end)},"
            f"Default,,0,0,0,,{cue.text}"
        )

    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    # UTF-8 BOM 有助于部分 Windows 环境识别
    with open(path, "w", encoding="utf-8-sig", newline="\n") as f:
        f.write("\n".join(lines) + "\n")
    return path


def ffmpeg_subtitles_filter_arg(
    ass_basename: str = "subtitles.ass",
    fonts_subdir: Optional[str] = None,
) -> str:
    """
    在 work_dir 为 cwd 时使用的 -vf 参数。
    仅用相对文件名，避免 Windows 盘符冒号破坏滤镜语法。

    :param fonts_subdir: work_dir 下的字体子目录（相对路径），传入后会追加 ``:fontsdir=``。
        让 libass 从该目录加载字体，规避宿主机 fontconfig 解析失败导致中文渲染为豆腐块。
    """
    # 转义：\\ 与 :
    name = ass_basename.replace("\\", "/").replace(":", r"\:").replace("'", r"\'")
    arg = f"subtitles={name}"
    if fonts_subdir:
        # fontsdir 用相对路径（work_dir 下子目录），避免 Windows 盘符冒号
        fonts_dir = fonts_subdir.replace("\\", "/").replace(":", r"\:").replace("'", r"\'")
        arg += f":fontsdir={fonts_dir}"
    return arg
