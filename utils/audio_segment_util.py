# -*- coding: utf-8 -*-
"""音频分段工具：按静音（标点停顿）切分长音频为 H3 数字人分段素材。

供 script_writer_core（营销数字人 confirm 切分）与 task/visual_drivers
（H3 分段 driver OOM 降档重切）共同使用，故放在 utils 中立位置。

切点规则：段数 = ceil(总长/max_seg)；每个均分目标点在 ±target_window 秒窗口内
取最近的静音中点（TTS 标点停顿），窗口内无静音时放宽到该段内任意静音中点，
仍无则硬切均分点（兜底，可能出现词中切，概率低）。每段对齐到整数秒
（截断或尾部补静音），供 H3 duration 整数节点使用。
"""
import math
import os
import re
import subprocess
import sys
from typing import Any, Dict, List

from utils.project_path import get_project_root


def _get_ffmpeg_bin() -> str:
    """定位 ffmpeg：优先项目内置 bin/ffmpeg（不依赖环境配置），回退 PATH。"""
    bundled = os.path.join(get_project_root(), 'bin', 'ffmpeg',
                           'ffmpeg.exe' if sys.platform == 'win32' else 'ffmpeg')
    if os.path.isfile(bundled):
        return bundled
    return 'ffmpeg'


def _detect_silence_midpoints(audio_path: str, noise_db: str = '-32dB',
                              min_duration: str = '0.18') -> List[float]:
    """用 ffmpeg silencedetect 返回静音区间中点列表（秒）。

    参数比默认更灵敏（-32dB / 0.18s），以捕捉 TTS 标点停顿；
    识别失败返回空列表，由调用方硬切兜底。
    """
    try:
        r = subprocess.run(
            [_get_ffmpeg_bin(), '-hide_banner', '-i', audio_path,
             '-af', f'silencedetect=noise={noise_db}:d={min_duration}', '-f', 'null', '-'],
            capture_output=True, text=True, timeout=60)
        starts = [float(m) for m in re.findall(r'silence_start:\s*([\d.]+)', r.stderr)]
        ends = [float(m) for m in re.findall(r'silence_end:\s*([\d.]+)', r.stderr)]
        return [(s + e) / 2 for s, e in zip(starts, ends)]
    except Exception:
        return []


def split_audio_into_segments(audio_path: str, total_seconds: float, out_dir: str,
                              max_seg: int = 15, min_seg: int = 4) -> Dict[str, Any]:
    """把驱动音频切成 N 段（每段 ≤ max_seg 且 ≥ min_seg）并各自对齐到整数秒。

    段数 = ceil(total/max_seg)；每个均分目标点在 ±3.5s 窗口内取最近的静音中点
    （标点停顿处），窗口内无静音时放宽到相邻切点约束内的任意静音中点，
    仍无则硬切均分点。每段 ffmpeg 截断/apad 对齐到整数秒。

    Returns:
        {"segments": [{"path": wav, "duration": int}], "cuts": [float], "total": float}
    """
    total_seconds = float(total_seconds)
    seg_count = max(1, int(math.ceil(total_seconds / max_seg)))
    silences = _detect_silence_midpoints(audio_path)

    cuts: List[float] = []
    prev = 0.0
    for i in range(1, seg_count):
        target = total_seconds * i / seg_count
        remaining_segs = seg_count - i
        # 窗口下限必须含 total - max_seg*remaining：否则前面段切晚会导致
        # 后续段切片超过 max_seg，而 H3 按 duration(=ceil 段长) 输出会把
        # 超长部分的语音截断（表现为片尾残句/变调怪声）
        win_lo = max(prev + min_seg, target - 3.5,
                     total_seconds - max_seg * remaining_segs)
        win_hi = min(prev + max_seg, total_seconds - min_seg * remaining_segs,
                     target + 3.5)
        if win_lo > win_hi:
            break  # 剩余时长不足再切，合并进末段
        # 优先窗口内静音；否则放宽到 (prev, total-min_seg*remaining) 内任意静音
        candidates = [m for m in silences if win_lo <= m <= win_hi]
        if not candidates:
            loose_lo, loose_hi = prev + 0.5, total_seconds - min_seg * remaining_segs
            candidates = [m for m in silences if loose_lo <= m <= loose_hi]
        if candidates:
            # 放宽后可能偏离均分点较远：仍取离目标最近者，并夹回硬约束窗口
            cut = min(candidates, key=lambda m: abs(m - target))
            cut = min(max(cut, win_lo), win_hi)
        else:
            cut = min(max(win_lo, target), win_hi)
        cuts.append(round(cut, 3))
        prev = cut

    bounds = [0.0] + cuts + [total_seconds]
    os.makedirs(out_dir, exist_ok=True)
    ffmpeg = _get_ffmpeg_bin()
    segments = []
    for idx in range(len(bounds) - 1):
        start, end = bounds[idx], bounds[idx + 1]
        seg_len = end - start
        seg_dur = max(min_seg, min(max_seg, int(math.ceil(seg_len))))
        raw = os.path.join(out_dir, f'seg_{idx + 1}_raw.wav')
        final = os.path.join(out_dir, f'seg_{idx + 1}.wav')
        trim = ['-ss', f'{start:.3f}'] if start > 0 else []
        subprocess.run([ffmpeg, '-y', '-loglevel', 'error', *trim, '-i', audio_path,
                        '-t', f'{seg_len:.3f}', '-ar', '44100', '-ac', '2', raw],
                       check=True, capture_output=True, timeout=120)
        if seg_len < seg_dur:
            # 不足整数秒：尾部补静音（无声收尾人物静止，自然）
            subprocess.run([ffmpeg, '-y', '-loglevel', 'error', '-i', raw,
                            '-af', f'apad=whole_dur={seg_dur}', final],
                           check=True, capture_output=True, timeout=120)
        else:
            # 超出整数秒：截断到整数秒（切点在静音内，截的是停顿）
            subprocess.run([ffmpeg, '-y', '-loglevel', 'error', '-i', raw,
                            '-t', str(seg_dur), '-c', 'copy', final],
                           check=True, capture_output=True, timeout=120)
        if os.path.isfile(raw):
            os.remove(raw)
        segments.append({"path": final, "duration": seg_dur})
    return {"segments": segments, "cuts": cuts, "total": round(total_seconds, 3)}
