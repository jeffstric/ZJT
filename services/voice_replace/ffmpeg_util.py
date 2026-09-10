"""ffmpeg 抽音 / 切片 / 变速 / 拼接 / 混流。全部 asyncio + 显式超时。"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import List, Optional, Sequence

from config.config_util import get_config_value, resolve_bin_path
from config.constant import VoiceReplaceConstants as C
from utils.project_path import get_project_root

logger = logging.getLogger(__name__)


class FfmpegError(Exception):
    """ffmpeg/ffprobe 失败或超时。"""


def get_ffmpeg_path() -> str:
    try:
        raw = get_config_value("bin", "ffmpeg", default="ffmpeg")
        return resolve_bin_path(raw, get_project_root())
    except Exception as exc:
        logger.warning("[voice-replace] ffmpeg path fallback: %s", exc)
        return "ffmpeg"


def get_ffprobe_path() -> str:
    try:
        raw = get_config_value("bin", "ffprobe", default="ffprobe")
        return resolve_bin_path(raw, get_project_root())
    except Exception as exc:
        logger.warning("[voice-replace] ffprobe path fallback: %s", exc)
        return "ffprobe"


async def run_ffmpeg(args: Sequence[str], timeout: Optional[float] = None) -> None:
    timeout = float(timeout if timeout is not None else C.FFMPEG_TIMEOUT)
    cmd = [get_ffmpeg_path(), *args]
    logger.info("[voice-replace][ffmpeg] %s", " ".join(cmd[:8]))
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        _stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError as exc:
        proc.kill()
        await proc.wait()
        raise FfmpegError(f"ffmpeg timeout {timeout}s") from exc
    if proc.returncode != 0:
        err = (stderr or b"").decode(errors="replace")[-1000:]
        raise FfmpegError(f"ffmpeg exit {proc.returncode}: {err}")


async def probe_duration(path: str, timeout: Optional[float] = None) -> float:
    timeout = float(timeout if timeout is not None else C.FFMPEG_TIMEOUT)
    cmd = [
        get_ffprobe_path(),
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        path,
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError as exc:
        proc.kill()
        await proc.wait()
        raise FfmpegError(f"ffprobe timeout {timeout}s") from exc
    if proc.returncode != 0:
        err = (stderr or b"").decode(errors="replace")[-500:]
        raise FfmpegError(f"ffprobe exit {proc.returncode}: {err}")
    text = (stdout or b"").decode().strip()
    try:
        return float(text)
    except ValueError as exc:
        raise FfmpegError(f"ffprobe duration invalid: {text!r}") from exc


def _pcm_args() -> List[str]:
    return [
        "-ac", str(C.AUDIO_CHANNELS),
        "-ar", str(C.AUDIO_SAMPLE_RATE),
        "-c:a", "pcm_s16le",
    ]


async def probe_sample_rate(path: str, timeout: Optional[float] = None) -> int:
    timeout = float(timeout if timeout is not None else C.FFMPEG_TIMEOUT)
    cmd = [
        get_ffprobe_path(),
        "-v", "error",
        "-select_streams", "a:0",
        "-show_entries", "stream=sample_rate",
        "-of", "default=noprint_wrappers=1:nokey=1",
        path,
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError as exc:
        proc.kill()
        await proc.wait()
        raise FfmpegError(f"ffprobe timeout {timeout}s") from exc
    if proc.returncode != 0:
        err = (stderr or b"").decode(errors="replace")[-500:]
        raise FfmpegError(f"ffprobe exit {proc.returncode}: {err}")
    text = (stdout or b"").decode().strip().splitlines()[0] if stdout else ""
    try:
        return int(float(text))
    except ValueError as exc:
        raise FfmpegError(f"ffprobe sample_rate invalid: {text!r}") from exc


async def normalize_wav(src_wav: str, dest_wav: str) -> None:
    """统一成 44100Hz / 单声道 / PCM s16le，避免 concat 把 22050 当 44100 倍速播放。"""
    await run_ffmpeg(
        [
            "-y", "-i", src_wav,
            "-filter:a", f"aresample={C.AUDIO_SAMPLE_RATE}",
            *_pcm_args(),
            dest_wav,
        ]
    )
    if not os.path.isfile(dest_wav) or os.path.getsize(dest_wav) == 0:
        raise FfmpegError("normalize produced empty audio")


async def extract_audio(video_path: str, wav_path: str) -> None:
    video_dur = await probe_duration(video_path)
    await run_ffmpeg(
        [
            "-y", "-i", video_path,
            "-vn",
            "-af", f"apad=whole_dur={video_dur:.6f}",
            "-t", f"{video_dur:.6f}",
            *_pcm_args(),
            wav_path,
        ]
    )
    if not os.path.isfile(wav_path) or os.path.getsize(wav_path) == 0:
        raise FfmpegError("extracted audio is empty (video may have no audio track)")


async def slice_audio(src_wav: str, dest_wav: str, start: float, end: float) -> None:
    dur = max(0.0, float(end) - float(start))
    if dur <= 0:
        raise FfmpegError("slice duration must be > 0")
    await run_ffmpeg(
        [
            "-y", "-i", src_wav,
            "-ss", f"{start:.3f}",
            "-t", f"{dur:.3f}",
            *_pcm_args(),
            dest_wav,
        ]
    )


def atempo_filter(ratio: float) -> str:
    """ffmpeg atempo 仅接受 0.5–2.0，超出则串联。"""
    if ratio <= 0:
        raise FfmpegError(f"invalid atempo ratio {ratio}")
    parts: List[str] = []
    r = float(ratio)
    while r > 2.0 + 1e-6:
        parts.append("atempo=2.0")
        r /= 2.0
    while r < 0.5 - 1e-6:
        parts.append("atempo=0.5")
        r /= 0.5
    parts.append(f"atempo={r:.6f}")
    return ",".join(parts)


async def stretch_to_duration(src_wav: str, dest_wav: str, target_seconds: float) -> None:
    actual = await probe_duration(src_wav)
    if actual <= 0 or target_seconds <= 0:
        raise FfmpegError("cannot stretch empty audio")
    ratio = actual / target_seconds
    filters = [f"aresample={C.AUDIO_SAMPLE_RATE}"]
    if abs(ratio - 1.0) >= 0.02:
        filters.append(atempo_filter(ratio))
    await run_ffmpeg(
        [
            "-y", "-i", src_wav,
            "-filter:a", ",".join(filters),
            *_pcm_args(),
            dest_wav,
        ]
    )


async def concat_wavs(paths: Sequence[str], dest_wav: str) -> None:
    if not paths:
        raise FfmpegError("no wavs to concat")
    list_path = dest_wav + ".concat.txt"
    norms: List[str] = []
    try:
        for i, src in enumerate(paths):
            norm = f"{dest_wav}.n{i}.wav"
            await normalize_wav(src, norm)
            norms.append(norm)
        with open(list_path, "w", encoding="utf-8") as fh:
            for p in norms:
                escaped = os.path.abspath(p).replace("'", "'\\''")
                fh.write(f"file '{escaped}'\n")
        await run_ffmpeg(
            [
                "-y", "-f", "concat", "-safe", "0",
                "-i", list_path,
                *_pcm_args(),
                dest_wav,
            ]
        )
    finally:
        if os.path.exists(list_path):
            os.remove(list_path)
        for p in norms:
            if os.path.exists(p):
                os.remove(p)


async def mix_wavs(
    vocal_path: str,
    instrumental_path: str,
    dest_wav: str,
    vocal_gain: float = 1.0,
    instrumental_gain: float = 1.0,
) -> None:
    """人声 + 环境声/伴奏叠加。normalize=0 避免 amix 默认除以输入路数把音量砍半。"""
    sr = C.AUDIO_SAMPLE_RATE
    await run_ffmpeg(
        [
            "-y",
            "-i", vocal_path,
            "-i", instrumental_path,
            "-filter_complex",
            (
                f"[0:a]aresample={sr},aformat=channel_layouts=mono,volume={vocal_gain}[v];"
                f"[1:a]aresample={sr},aformat=channel_layouts=mono,volume={instrumental_gain}[i];"
                "[v][i]amix=inputs=2:duration=longest:dropout_transition=0:normalize=0[a]"
            ),
            "-map", "[a]",
            *_pcm_args(),
            dest_wav,
        ]
    )
    if not os.path.isfile(dest_wav) or os.path.getsize(dest_wav) == 0:
        raise FfmpegError("mix produced empty audio")


async def mux_video_audio(video_path: str, audio_path: str, dest_mp4: str) -> None:
    video_dur = await probe_duration(video_path)
    await run_ffmpeg(
        [
            "-y",
            "-i", video_path,
            "-i", audio_path,
            "-filter_complex",
            (
                f"[1:a]aresample={C.AUDIO_SAMPLE_RATE},"
                f"aformat=channel_layouts=mono,"
                f"apad=whole_dur={video_dur:.6f}[a]"
            ),
            "-map", "0:v:0",
            "-map", "[a]",
            "-c:v", "copy",
            "-c:a", "aac",
            "-b:a", "192k",
            "-t", f"{video_dur:.6f}",
            "-movflags", "+faststart",
            dest_mp4,
        ]
    )
    if not os.path.isfile(dest_mp4) or os.path.getsize(dest_mp4) == 0:
        raise FfmpegError("mux produced empty video")
