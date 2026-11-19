# -*- coding: utf-8 -*-
"""时间轴「导出成品视频」服务（web/video_workflow.html 时间轴 → ffmpeg 烧录 mp4）。

与 services/storyboard_export_service.py 同纪律：
- 本模块函数均为同步函数，API 层必须用 asyncio.to_thread 调用，禁止在事件循环内直接跑 ffmpeg；
- ffmpeg/ffprobe 路径经 config `bin.ffmpeg`/`bin.ffprobe` + resolve_bin_path 解析。

合成模型（三遍式，与前端时间轴预览语义一致，见 docs/timeline_v2_multitrack_and_trash.md）：
  1) 时间线按所有片段边界切分成连续小节 → 每小节独立渲染**无声视频**
     （黑场 / 单段裁剪定格补满 / 多段 overlay）→ concat 拼接；
  2) 全局音频混音：视频内嵌音轨（ffprobe 探测存在才纳入）+ 独立音频轨片段，
     atrim → adelay 到时间轴绝对位置 → 统一 44100Hz/立体声 → amix(normalize=0)
     → atrim 钳制到全片长；
  3) mux 视频与音轨（-c:v copy，零重编码损耗）。

  【关键教训】绝不在同一 ffmpeg 命令里交叉引用同一输入的视频流与音频流
  （视频链 + 同 -i 的 [i:a] trim 起点超前视频需求）——ffmpeg 滤镜调度会死锁，
  实测表现为视频流 0 帧/时长截断。因此音频一律走独立的全局混音命令。
"""

import json
import logging
import os
import shutil
import subprocess
import threading
import uuid
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from config.config_util import get_config_value, resolve_bin_path
from config.constant import TimelineVideoExportConstants
from utils.project_path import get_upload_dir, get_project_root

logger = logging.getLogger(__name__)

# job 状态：pending|downloading|rendering|uploading|completed|failed
_export_jobs: Dict[str, dict] = {}
_export_job_lock = threading.Lock()


def _ffmpeg_path() -> str:
    raw = get_config_value("bin", "ffmpeg", default="ffmpeg")
    return resolve_bin_path(raw, get_project_root())


def _ffprobe_path() -> str:
    raw = get_config_value("bin", "ffprobe", default="ffprobe")
    return resolve_bin_path(raw, get_project_root())


def _run_cmd(cmd: List[str], timeout: float) -> None:
    """同步执行 ffmpeg 命令（调用方必须已在线程中）。超时/非零统一抛 RuntimeError。"""
    logger.debug("run: %s", " ".join(cmd))
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
        )
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"视频合成超时({timeout}s)，请缩短时间轴或分批导出") from e
    except FileNotFoundError as e:
        raise RuntimeError(f"找不到可执行文件: {cmd[0]}") from e
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "")[-800:]
        raise RuntimeError(f"视频合成失败 returncode={proc.returncode}: {err}")


def _probe_has_audio(path: str) -> bool:
    """ffprobe 探测文件是否存在音频轨（无音轨的输入在 filter_complex 里引用 [i:a] 会直接报错）。"""
    cmd = [
        _ffprobe_path(),
        "-v", "quiet",
        "-select_streams", "a",
        "-show_entries", "stream=index",
        "-of", "csv=p=0",
        path,
    ]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True,
            timeout=30, encoding="utf-8", errors="replace",
        )
        return proc.returncode == 0 and bool(proc.stdout.strip())
    except Exception as e:
        logger.warning("ffprobe 音轨探测失败 %s: %s", path, e)
        return False


_src_duration_cache: Dict[str, Optional[float]] = {}


def _probe_src_duration(path: str) -> Optional[float]:
    """ffprobe 探测源文件总时长（按路径缓存）。探测失败返回 None（不钳制）。"""
    if path in _src_duration_cache:
        return _src_duration_cache[path]
    cmd = [
        _ffprobe_path(),
        "-v", "quiet",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        path,
    ]
    dur = None
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True,
            timeout=30, encoding="utf-8", errors="replace",
        )
        if proc.returncode == 0 and proc.stdout.strip():
            dur = float(proc.stdout.strip())
    except Exception as e:
        logger.warning("ffprobe 源时长探测失败 %s: %s", path, e)
    _src_duration_cache[path] = dur
    return dur


def _seg_text(parts: List[str]) -> str:
    return ";\n".join(parts)


def _normalize_segments(items) -> List[dict]:
    """把前端片段条目规整成统一 segment 结构。

    裁剪区间按源实际时长钳制（前端 duration 可能与真实时长有偏差，与剪映草稿
    导出的 ffprobe 真实时长口径一致）；裁剪起点已超源尾的段整体丢弃（该区间黑场）。
    """
    segments = []
    for item in items or []:
        clip = item.get('clip') or {}
        file_path = item.get('file_path')
        if not file_path or not os.path.isfile(file_path):
            continue
        ts = float(clip.get('timeline_start') or 0)
        ss = max(0.0, float(clip.get('startTime') or 0))
        se = float(clip.get('endTime') or clip.get('duration') or 0)
        src_dur = _probe_src_duration(file_path)
        if src_dur is not None and src_dur > 0:
            se = min(se, src_dur)
        if se - ss < 0.05 or (src_dur is not None and ss >= src_dur - 0.05):
            continue
        segments.append({
            'file_path': file_path,
            'ss': ss,                      # 源内裁剪起点
            'se': se,                      # 源内裁剪终点（已按源时长钳制）
            'start': max(0.0, ts),         # 时间轴绝对位置
            'end': max(0.0, ts) + (se - ss),
            'track': int(clip.get('track') or 0),
            'name': clip.get('name') or '',
        })
    return segments


def _v_filter_chain(src_off: float, src_end: float, width: int, height: int,
                    rel_dur: float, label: str) -> str:
    """视频段小节内滤镜链：源内裁剪 → 归零 → 等比铺满 → fps/format → tpad 定格补满小节。"""
    consts = TimelineVideoExportConstants
    return (
        f"trim=start={src_off:.3f}:end={src_end:.3f},setpts=PTS-STARTPTS,"
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,"
        f"fps={consts.OUTPUT_FPS},format=yuv420p,"
        f"tpad=stop_mode=clone:stop_duration={rel_dur:.3f}[{label}]"
    )


def _render_section_video_file(
    out_path: str, rel_dur: float, width: int, height: int,
    video_segs: List[dict], t0: float,
) -> None:
    """渲染单个小节的**无声视频**（黑场 / 单段裁剪定格补满 / 多段 overlay）。

    小节切分保证：video_segs 里的每个段都完整覆盖小节 [t0, t0+rel_dur)。
    音频走全局独立混音（见 _render_audio_track），绝不在同一命令里交叉引用
    视频输入的内嵌音轨——同一 -i 的视频链 + 音频 trim 起点超前组合会让 ffmpeg
    滤镜调度死锁（实测：视频 0-2s + 同输入音轨 atrim 3s+ → 视频流 0 帧）。
    """
    consts = TimelineVideoExportConstants

    cmd: List[str] = [_ffmpeg_path(), "-y", "-v", "error"]
    parts: List[str] = []

    if not video_segs:
        cmd += ["-f", "lavfi", "-i",
                f"color=c=black:s={width}x{height}:r={consts.OUTPUT_FPS}:d={rel_dur:.3f}"]
        v_map = ["-map", "0:v"]
    elif len(video_segs) == 1:
        seg = video_segs[0]
        cmd += ["-i", seg['file_path']]
        src_off = seg['ss'] + (t0 - seg['start'])
        parts.append("[0:v]" + _v_filter_chain(src_off, src_off + rel_dur,
                                               width, height, rel_dur, "v"))
        v_map = ["-map", "[v]"]
    else:
        # 多段重叠：低轨先叠=下层，高轨后叠覆盖（与预览一致）
        segs = sorted(video_segs, key=lambda s: (s['track'], s['start']))
        for i, seg in enumerate(segs):
            cmd += ["-i", seg['file_path']]
            src_off = seg['ss'] + (t0 - seg['start'])
            parts.append(f"[{i}:v]" + _v_filter_chain(src_off, src_off + rel_dur,
                                                      width, height, rel_dur, f"v{i}"))
        canvas_idx = len(segs)
        cmd += ["-f", "lavfi", "-i",
                f"color=c=black:s={width}x{height}:r={consts.OUTPUT_FPS}:d={rel_dur:.3f}"]
        current = f"[{canvas_idx}:v]"
        for i in range(len(segs)):
            out_label = "vout" if i == len(segs) - 1 else f"ov{i}"
            parts.append(f"{current}[v{i}]overlay=eof_action=pass[{out_label}]")
            current = f"[{out_label}]"
        v_map = ["-map", "[vout]"]

    cmd += (["-filter_complex", _seg_text(parts)] if parts else []) + v_map
    cmd += [
        "-t", f"{rel_dur:.3f}", "-an",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        out_path,
    ]
    _run_cmd(cmd, consts.FFMPEG_TIMEOUT_SECONDS)


def _render_audio_track(
    audio_sources: List[Tuple[str, float, float, float]],
    total: float, out_path: str,
) -> None:
    """全局混音：把各音频源裁剪+延迟到时间轴绝对位置后 amix 成整条音轨。

    audio_sources 元素 (file_path, src_off, src_end, abs_start)。
    每个源文件独立 -i 且只引用其音频流（不与视频链交叉），规避调度死锁。
    全无音频源时输出 total 时长静音。
    """
    consts = TimelineVideoExportConstants
    sr = consts.AUDIO_SAMPLE_RATE

    cmd: List[str] = [_ffmpeg_path(), "-y", "-v", "error"]
    parts: List[str] = []
    labels: List[str] = []
    for k, (file_path, src_off, src_end, abs_start) in enumerate(audio_sources):
        cmd += ["-i", file_path]
        delay_ms = int(round(abs_start * 1000))
        parts.append(
            f"[{k}:a]atrim=start={src_off:.3f}:end={src_end:.3f},asetpts=PTS-STARTPTS,"
            f"aresample={sr},pan=stereo|c0=c0|c1=c1,"
            f"adelay={delay_ms}|{delay_ms},apad[a{k}]"
        )
        labels.append(f"[a{k}]")

    if labels:
        parts.append(
            f"{''.join(labels)}amix=inputs={len(labels)}:normalize=0,"
            f"atrim=end={total:.3f},asetpts=PTS-STARTPTS[aout]"
        )
        cmd += ["-filter_complex", _seg_text(parts), "-map", "[aout]"]
    else:
        cmd += ["-f", "lavfi", "-i", f"anullsrc=r={sr}:cl=stereo", "-t", f"{total:.3f}"]
    cmd += [
        "-c:a", "aac", "-b:a", consts.AUDIO_BITRATE,
        "-ar", str(sr), "-ac", str(consts.AUDIO_CHANNELS),
        out_path,
    ]
    _run_cmd(cmd, consts.FFMPEG_TIMEOUT_SECONDS)


def render_timeline_video(
    video_clips: List[dict],
    audio_clips: List[dict],
    work_dir: str,
    width: int,
    height: int,
) -> str:
    """把时间轴片段渲染成成品 mp4（同步函数，API 层必须 asyncio.to_thread 调用）。

    video_clips/audio_clips 元素为下载产物条目 {'file_path': str, 'clip': dict}，
    clip 含 timeline_start/startTime/endTime/name 等字段（前端 collectTimelineExportClips 产出）。
    返回输出 mp4 本地路径。
    """
    consts = TimelineVideoExportConstants

    video_segments = _normalize_segments(video_clips)
    if not video_segments:
        raise RuntimeError("时间轴上没有可用的视频片段")
    audio_segments = _normalize_segments(audio_clips)
    for seg in video_segments:
        seg['has_audio'] = _probe_has_audio(seg['file_path'])

    if len(video_segments) + len(audio_segments) > consts.MAX_CLIPS:
        raise RuntimeError(f"片段总数超过上限({consts.MAX_CLIPS})，请精简时间轴后导出")

    total = round(max(seg['end'] for seg in video_segments) + 0.05, 3)

    os.makedirs(work_dir, exist_ok=True)
    seg_dir = os.path.join(work_dir, "segments")
    os.makedirs(seg_dir, exist_ok=True)
    out_path = os.path.join(
        work_dir,
        f"timeline_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}.mp4",
    )
    try:
        # ---- Pass 1：小节无声视频 ----
        bounds = {0.0, total}
        for seg in video_segments + audio_segments:
            bounds.add(round(seg['start'], 3))
            bounds.add(round(seg['end'], 3))
        cuts = sorted(b for b in bounds if 0 <= b < total)
        sections = [(cuts[i], cuts[i + 1]) for i in range(len(cuts) - 1)
                    if cuts[i + 1] - cuts[i] > 0.01]
        if not sections:
            sections = [(0.0, total)]

        seg_files: List[str] = []
        for idx, (t0, t1) in enumerate(sections):
            rel_dur = round(t1 - t0, 3)
            out_seg = os.path.join(seg_dir, f"seg_{idx:04d}.mp4")
            active_v = [s for s in video_segments
                        if s['start'] < t1 - 0.005 and s['end'] > t0 + 0.005]
            try:
                _render_section_video_file(out_seg, rel_dur, width, height, active_v, t0)
            except RuntimeError as e:
                raise RuntimeError(
                    f"小节[{t0:.2f}s~{t1:.2f}s]视频渲染失败: {e}（视频段={[s['name'] for s in active_v]}）"
                ) from e
            seg_files.append(out_seg)

        silent_path = os.path.join(seg_dir, "silent.mp4")
        list_path = os.path.join(seg_dir, "concat_list.txt")
        # concat demuxer 的 file 条目相对路径是相对 list 文件所在目录解析的，必须写绝对路径
        with open(list_path, "w", encoding="utf-8", newline="\n") as f:
            for p in seg_files:
                abs_p = os.path.abspath(p).replace("\\", "/").replace("'", "'\\''")
                f.write("file '" + abs_p + "'\n")
        _run_cmd([
            _ffmpeg_path(), "-y", "-v", "error",
            "-f", "concat", "-safe", "0", "-i", list_path,
            "-c", "copy", silent_path,
        ], consts.FFMPEG_TIMEOUT_SECONDS)

        # ---- Pass 2：全局音频混音（内嵌音轨 + 独立音频段，钳制到全片长）----
        audio_sources: List[Tuple[str, float, float, float]] = []
        for seg in video_segments:
            if not seg.get('has_audio'):
                continue
            overlap_start = max(seg['start'], 0)
            overlap_end = min(seg['end'], total)
            if overlap_end - overlap_start > 0.01:
                src_off = seg['ss'] + (overlap_start - seg['start'])
                src_end = src_off + (overlap_end - overlap_start)
                audio_sources.append((seg['file_path'], src_off, src_end, overlap_start))
        for seg in audio_segments:
            overlap_start = max(seg['start'], 0)
            overlap_end = min(seg['end'], total)
            if overlap_end - overlap_start > 0.01:
                src_off = seg['ss'] + (overlap_start - seg['start'])
                src_end = src_off + (overlap_end - overlap_start)
                audio_sources.append((seg['file_path'], src_off, src_end, overlap_start))

        audio_path = os.path.join(seg_dir, "audio.m4a")
        try:
            _render_audio_track(audio_sources, total, audio_path)
        except RuntimeError as e:
            raise RuntimeError(f"音频混音失败: {e}") from e

        # ---- Pass 3：mux（视频 copy，音轨已是目标规格 copy）----
        _run_cmd([
            _ffmpeg_path(), "-y", "-v", "error",
            "-i", silent_path, "-i", audio_path,
            "-map", "0:v", "-map", "1:a",
            "-c:v", "copy", "-c:a", "copy",
            "-movflags", "+faststart",
            "-t", f"{total:.3f}",
            out_path,
        ], consts.FFMPEG_TIMEOUT_SECONDS)
    finally:
        shutil.rmtree(seg_dir, ignore_errors=True)

    if not os.path.isfile(out_path) or os.path.getsize(out_path) < 1024:
        raise RuntimeError("合成产物异常（文件缺失或过小），请重试")
    return out_path


# ---------------- 导出 job 基建（内存 dict + JSON 落盘，仿 storyboard_export_service） ----------------

def _job_path(job_id: str) -> str:
    d = os.path.join(get_upload_dir(), TimelineVideoExportConstants.JOBS_SUBDIR)
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, f"{job_id}.json")


def save_job(job: dict) -> None:
    job_id = job["job_id"]
    with _export_job_lock:
        _export_jobs[job_id] = job
    try:
        with open(_job_path(job_id), "w", encoding="utf-8") as f:
            json.dump(job, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning("save timeline export job file fail: %s", e)


def get_timeline_export_job(job_id: str) -> Optional[dict]:
    with _export_job_lock:
        if job_id in _export_jobs:
            return dict(_export_jobs[job_id])
    path = _job_path(job_id)
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None
    return None


def create_timeline_export_job(user_id: int, workflow_name: str = "") -> dict:
    job = {
        "job_id": uuid.uuid4().hex,
        "user_id": user_id,
        "workflow_name": workflow_name,
        "status": "pending",  # pending|downloading|rendering|uploading|completed|failed
        "progress": 0,
        "download_url": None,
        "filename": None,
        "error": None,
        "create_at": datetime.now().isoformat(),
        "update_at": datetime.now().isoformat(),
    }
    save_job(job)
    return job


def update_timeline_export_job(job_id: str, **kwargs) -> Optional[dict]:
    job = get_timeline_export_job(job_id)
    if not job:
        return None
    job.update(kwargs)
    job["update_at"] = datetime.now().isoformat()
    save_job(job)
    return job


def cleanup_job_tmp_dir(job_id: str) -> None:
    """清理 job 的素材下载临时目录（渲染完成后调用）。"""
    d = os.path.join(get_upload_dir(), TimelineVideoExportConstants.WORK_SUBDIR, "tmp", job_id)
    try:
        if os.path.isdir(d):
            shutil.rmtree(d, ignore_errors=True)
    except Exception as e:
        logger.warning("cleanup tmp dir fail job=%s: %s", job_id, e)
