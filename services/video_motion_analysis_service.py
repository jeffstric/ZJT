# -*- coding: utf-8 -*-
"""剧本提取的运动信号分析服务（消费方：services/video_script_extract_service.py）。

对输入视频按低分辨率灰度帧序列做**程序化运动分析**，产出「逐镜头运动信号表」
注入剧本提取的 user prompt，让分镜的表演/运镜/光线描述从"模型猜"变为"实测"
（用户反馈对标：WB 的动作捕捉优势正来自帧间差/亮度/位移这类确定性测量）：

- 帧间差（相邻帧平均绝对灰度差）：每镜均值 + 全片排名 + 镜内峰值时刻
  → 区分「静止/微动/大幅动作」，并把动作定位到具体时间点（如"镜尾才闭眼"）
- 亮度均值/斜率：每镜均值 + 全片排名 → 光线色调线索（修正"偏暖/冷调"类硬错误）
- 镜头首尾帧行列投影互相关：净位移（dx/dy）→ 识别摇镜方向与幅度
- 相邻镜头首帧对比：低于阈值标注「疑似平行镜头」（同构图呼应/轴线保持）

实现约束：
- 纯 numpy 数值计算（无 cv2 依赖）；rawvideo 经 pipe 输出，无临时文件；
- 总帧数封顶 MOTION_MAX_FRAMES，长视频自动降 fps；
- 任何失败由调用方降级为空表（不阻塞剧本提取主链路）。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from config.constant import VideoScriptExtractConstants as C
from services.video_frame_extract_service import (
    FrameExtractError,
    _run_bin,
    get_ffmpeg_path,
)
from utils.time_label import format_time_label_precise

logger = logging.getLogger(__name__)


def compute_motion_sample_fps(duration: float) -> float:
    """有效采样 fps：默认 MOTION_SAMPLE_FPS；总帧数超上限时长视频自动降 fps。"""
    total = max(0.0, float(duration))
    fps = float(C.MOTION_SAMPLE_FPS)
    if total > 0 and total * fps > C.MOTION_MAX_FRAMES:
        fps = max(1.0, C.MOTION_MAX_FRAMES / total)
    return fps


async def extract_motion_frames(video_path: str, fps: float) -> Tuple[np.ndarray, float]:
    """ffmpeg 抽低分辨率灰度帧序列（rawvideo pipe，无临时文件）。

    返回 (frames, fps)：frames 形状 (N, H, W) uint8，帧 i 的时间戳 = i / fps。
    """
    width = int(C.MOTION_FRAME_WIDTH)
    height = int(C.MOTION_FRAME_HEIGHT)
    frame_size = width * height
    cmd = [
        get_ffmpeg_path(),
        "-an", "-sn", "-dn",
        "-i", video_path,
        "-vf", f"fps={float(fps):.4f},scale={width}:{height},format=gray",
        "-f", "rawvideo", "-pix_fmt", "gray",
        "pipe:1",
    ]
    returncode, stdout, stderr = await _run_bin(cmd, C.MOTION_ANALYSIS_TIMEOUT)
    if returncode != 0:
        detail = stderr.decode(errors="replace")[-300:]
        raise FrameExtractError(f"运动抽帧失败 exit {returncode}: {detail}")
    count = len(stdout) // frame_size
    if count <= 0:
        raise FrameExtractError("运动抽帧未得到任何帧，视频可能无法解码")
    frames = np.frombuffer(stdout[: count * frame_size], dtype=np.uint8).reshape(
        count, height, width,
    )
    return frames, float(fps)


def _frame_abs_diffs(frames: np.ndarray) -> np.ndarray:
    """相邻帧平均绝对灰度差；diffs[i] 对应 frame[i]→frame[i+1]（时间记在后帧）。

    分块计算避免 int16 中间数组一次性占双倍内存（1500 帧 × 72 × 128）。
    """
    total = len(frames) - 1
    diffs = np.empty(max(total, 0), dtype=np.float64)
    step = 256
    for start in range(0, total, step):
        end = min(start + step, total)
        block = (
            frames[start + 1: end + 1].astype(np.int16)
            - frames[start: end].astype(np.int16)
        )
        diffs[start: end] = np.abs(block).mean(axis=(1, 2))
    return diffs


def _lag_shift(prev_proj: np.ndarray, cur_proj: np.ndarray, max_lag: int) -> int:
    """1D 投影互相关：返回 lag 使 cur ≈ shift(prev, lag)。

    正 lag = cur 的内容相对 prev 向大索引方向平移（行投影 → 内容下移，
    列投影 → 内容右移）。相关性用标准差归一化（[-1,1]）：平坦投影（纯色/
    均匀画面无结构）不具可测性，归一化峰值低于阈值时一律判无位移，
    避免全零点积下 best_score=-inf 被搜索边界 lag 污染成假位移。
    """
    n = len(prev_proj)
    a = prev_proj.astype(np.float64)
    b = cur_proj.astype(np.float64)
    denom = float(a.std() * b.std())
    if denom < 1e-6:
        return 0
    a -= float(a.mean())
    b -= float(b.mean())
    best_lag, best_score = 0, float("-inf")
    for lag in range(-int(max_lag), int(max_lag) + 1):
        if lag >= 0:
            m = n - lag
        else:
            m = n + lag
        if m < 4:
            continue
        if lag >= 0:
            raw = float(np.dot(a[:m], b[lag:]))
        else:
            raw = float(np.dot(a[-lag:], b[:m]))
        score = raw / (m * denom)
        if score > best_score:
            best_score, best_lag = score, lag
    if best_score < 0.5:
        return 0
    return best_lag


def _frame_shift(first: np.ndarray, last: np.ndarray) -> Tuple[int, int]:
    """镜头首尾帧净位移 (dx, dy)（px，采样分辨率基准）。

    dy>0 = 画面内容下移（相机上摇）；dx>0 = 画面内容右移（相机左摇）。
    """
    height, width = first.shape
    max_lag = max(2, min(int(C.MOTION_SHIFT_MAX_LAG_PX), height - 4, width - 4))
    dy = _lag_shift(first.mean(axis=1), last.mean(axis=1), max_lag)
    dx = _lag_shift(first.mean(axis=0), last.mean(axis=0), max_lag)
    return int(dx), int(dy)


def _build_shot_boundaries(scene_points: List[float], duration: float) -> List[float]:
    """切点 → 镜头边界 [0, c1, c2, ..., duration]（界外点丢弃，近距点合并）。"""
    end = max(0.0, float(duration))
    internal = sorted({
        min(max(float(p), 0.05), end - 0.05)
        for p in (scene_points or [])
        if 0.05 < float(p) < end - 0.05
    })
    merged: List[float] = []
    for p in internal:
        if not merged or p - merged[-1] >= 0.1:
            merged.append(p)
    return [0.0] + merged + [end]


def summarize_motion_signals(
    frame_times: np.ndarray,
    frames: np.ndarray,
    scene_points: List[float],
    duration: float,
) -> List[Dict[str, Any]]:
    """逐镜头运动信号汇总（纯函数，单测以合成帧覆盖）。

    转场尖峰剔除：切点 ± MOTION_CUT_GUARD_SECONDS 内、以及跨越切点的帧间差
    一律不计入镜内统计（快速剪辑视频的转场帧会污染均值与峰值）。
    """
    boundaries = _build_shot_boundaries(scene_points, duration)
    if len(boundaries) < 2 or len(frames) == 0:
        return []
    guard = float(C.MOTION_CUT_GUARD_SECONDS)
    diffs = _frame_abs_diffs(frames)
    lumas = frames.mean(axis=(1, 2), dtype=np.float64)

    shots: List[Dict[str, Any]] = []
    kept_all: List[float] = []
    for k in range(len(boundaries) - 1):
        start, end = boundaries[k], boundaries[k + 1]
        if k == len(boundaries) - 2:
            mask = (frame_times >= start) & (frame_times <= end)
        else:
            mask = (frame_times >= start) & (frame_times < end)
        idx = np.nonzero(mask)[0]
        shot_frames = frames[idx]
        shot_lumas = lumas[idx]
        # 镜内帧间差：后帧仍在本镜内、且时间不在任何切点保护带内
        kept: List[Tuple[float, float]] = []  # (diff, 时间)
        for j in idx:
            if j == 0:
                continue
            t = float(frame_times[j])
            if not (start <= t <= end):
                continue
            if any(abs(t - b) < guard for b in boundaries):
                continue
            kept.append((float(diffs[j - 1]), t))
        kept_all.extend(d for d, _t in kept)
        shots.append({
            "index": k + 1,
            "start": float(start),
            "end": float(end),
            "frames": shot_frames,
            "shot_lumas": shot_lumas,
            "kept": kept,
        })

    valid = [s for s in shots if len(s["shot_lumas"]) > 0]
    diff_order = sorted(
        (s for s in shots if s["kept"] is not None and len(s["kept"]) > 0),
        key=lambda s: sum(d for d, _t in s["kept"]) / len(s["kept"]),
    )
    diff_rank = {id(s): r + 1 for r, s in enumerate(diff_order)}
    luma_order = sorted(valid, key=lambda s: float(s["shot_lumas"].mean()), reverse=True)
    luma_rank = {id(s): r + 1 for r, s in enumerate(luma_order)}
    median_diff = float(np.median(kept_all)) if kept_all else 0.0
    peak_floor = max(2.0, 1.5 * median_diff)
    lookback = int(C.MOTION_PARALLEL_LOOKBACK)
    threshold = float(C.MOTION_PARALLEL_DIFF_THRESHOLD)

    signals: List[Dict[str, Any]] = []
    for pos, s in enumerate(shots):
        shot_dur = max(s["end"] - s["start"], 1e-6)
        kept = s["kept"]
        if kept:
            peak_diff, peak_time = max(kept, key=lambda item: item[0])
            mean_diff = sum(d for d, _t in kept) / len(kept)
        else:
            peak_diff, peak_time, mean_diff = None, None, None
        lumas_k = s["shot_lumas"]
        if len(lumas_k) >= 2:
            slope = float((lumas_k[-1] - lumas_k[0]) / shot_dur)
        else:
            slope = 0.0
        shift: Optional[Dict[str, int]] = None
        if len(s["frames"]) >= 2:
            dx, dy = _frame_shift(s["frames"][0], s["frames"][-1])
            if max(abs(dx), abs(dy)) >= int(C.MOTION_SHIFT_REPORT_PX):
                shift = {"dx": dx, "dy": dy}
        similar_to: Optional[int] = None
        if len(s["frames"]) > 0:
            mine = s["frames"][0]
            best = threshold
            for prev in shots[max(0, pos - lookback): pos]:
                if len(prev["frames"]) == 0:
                    continue
                d = float(np.abs(
                    mine.astype(np.int16) - prev["frames"][0].astype(np.int16)
                ).mean())
                if d < best:
                    best, similar_to = d, prev["index"]
        signals.append({
            "index": s["index"],
            "start": s["start"],
            "end": s["end"],
            "mean_diff": mean_diff,
            "diff_rank": diff_rank.get(id(s)),
            "diff_shot_total": len(diff_order),
            "peak_time": peak_time,
            "peak_diff": peak_diff,
            "peak_notable": bool(peak_diff is not None and peak_diff >= peak_floor),
            "luma_mean": float(lumas_k.mean()) if len(lumas_k) else 0.0,
            "luma_rank": luma_rank.get(id(s)),
            "luma_shot_total": len(luma_order),
            "luma_slope_per_sec": slope,
            "shift": shift,
            "similar_to": similar_to,
        })
    return signals


def _describe_shift(shift: Optional[Dict[str, int]]) -> str:
    """位移 → 人类可读运镜提示（语义：内容下移=相机上摇，内容右移=相机左摇）。"""
    if not shift:
        return "位移 无（固定机位）"
    thr = int(C.MOTION_SHIFT_REPORT_PX)
    parts: List[str] = []
    dy, dx = int(shift.get("dy", 0)), int(shift.get("dx", 0))
    if dy >= thr:
        parts.append(f"内容下移{dy}px（相机上摇）")
    elif dy <= -thr:
        parts.append(f"内容上移{-dy}px（相机下摇）")
    if dx >= thr:
        parts.append(f"内容右移{dx}px（相机左摇）")
    elif dx <= -thr:
        parts.append(f"内容左移{-dx}px（相机右摇）")
    return "位移：" + ("＋".join(parts) if parts else "无（固定机位）")


def format_motion_signal_lines(signals: List[Dict[str, Any]]) -> List[str]:
    """信号 → 每镜一行的文本表（注入 user prompt；空输入返回空列表）。"""
    lines: List[str] = []
    for s in signals or []:
        span = (
            f"镜{s['index']}（{format_time_label_precise(s['start'])}"
            f"-{format_time_label_precise(s['end'])}）"
        )
        if s.get("mean_diff") is None:
            diff_part = "帧间差 无数据（镜内无有效帧）"
        else:
            rank = s.get("diff_rank")
            total = s.get("diff_shot_total") or 1
            if total <= 1 or rank is None:
                tag = ""
            elif rank == 1:
                tag = "，全片最静"
            elif rank == total:
                tag = "，全片动作最强"
            else:
                tag = "，运动中等"
            diff_part = f"帧间差 {s['mean_diff']:.2f}{tag}"
        luma_rank = s.get("luma_rank")
        luma_total = s.get("luma_shot_total") or 1
        if luma_total <= 1 or luma_rank is None:
            luma_tag = ""
        elif luma_rank == 1:
            luma_tag = "，全片最亮"
        elif luma_rank == luma_total:
            luma_tag = "，全片最暗"
        else:
            luma_tag = "，亮度中等"
        slope = float(s.get("luma_slope_per_sec") or 0.0)
        slope_part = ""
        if abs(slope) >= 0.5:
            slope_part = f"，{'渐亮' if slope > 0 else '渐暗'}{abs(slope):.1f}/秒"
        luma_part = f"亮度 {float(s.get('luma_mean') or 0.0):.1f}{luma_tag}{slope_part}"
        if s.get("peak_time") is not None and s.get("peak_notable"):
            peak_note = "（镜中动作）"
            peak_time = float(s["peak_time"])
            if peak_time >= float(s["end"]) - 0.3:
                peak_note = "（镜尾动作，随后切镜）"
            elif peak_time <= float(s["start"]) + 0.3:
                peak_note = "（镜首动作）"
            peak_part = f"峰值 {format_time_label_precise(peak_time)}{peak_note}"
        else:
            peak_part = "峰值 无（无显著动作突增）"
        parts = [span, diff_part, luma_part, _describe_shift(s.get("shift")), peak_part]
        if s.get("similar_to"):
            parts.append(f"与镜{s['similar_to']}构图高度相似（疑似平行镜头）")
        lines.append("｜".join(parts))
    return lines


async def analyze_motion_signals(
    video_path: str,
    scene_points: List[float],
    duration: float,
) -> List[Dict[str, Any]]:
    """完整分析入口：采样计划 → ffmpeg 抽帧 → 逐镜头信号汇总。

    ffmpeg 失败（FrameExtractError）向上抛出，由调用方降级为空表；
    外层另 asyncio.wait_for 包整体超时（双保险，遵守超时红线）。
    """
    if not video_path or duration is None or float(duration) <= 0:
        return []
    fps = compute_motion_sample_fps(float(duration))
    frames, fps = await extract_motion_frames(video_path, fps)
    frame_times = np.arange(len(frames), dtype=np.float64) / fps
    signals = summarize_motion_signals(frame_times, frames, scene_points, float(duration))
    logger.info(
        "[motion-analysis] video=%s duration=%.1fs fps=%.2f frames=%d shots=%d",
        video_path, float(duration), fps, len(frames), len(signals),
    )
    return signals
