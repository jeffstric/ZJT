# -*- coding: utf-8 -*-
"""时间标签格式化共享函数（剧本提取与运动信号分析共用，避免服务间循环导入）。

- format_time_label：整秒精度（展示层：meta/报错文案）。
- format_time_label_precise：0.1 秒精度（分镜边界对齐镜头切换点、运动信号峰值时刻）。
"""
from __future__ import annotations


def format_time_label(seconds: float) -> str:
    total = max(0, int(round(float(seconds))))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours:d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def format_time_label_precise(seconds: float) -> str:
    """0.1 秒精度时间标签（MM:SS.d），供分镜边界对齐镜头切换点。

    整秒精度会让模型只能估出「00:00-00:03」级粗区间；此版本保留一位小数
    （ASR/切换点本身是浮点秒），且按 0.1s 取整后再进位，避免 59.96s 显示成 00:60.0。
    """
    tenths_total = max(0, int(round(float(seconds) * 10)))
    hours, remainder = divmod(tenths_total, 36000)
    minutes, remainder = divmod(remainder, 600)
    secs, tenths = divmod(remainder, 10)
    if hours:
        return f"{hours:d}:{minutes:02d}:{secs:02d}.{tenths:d}"
    return f"{minutes:02d}:{secs:02d}.{tenths:d}"
