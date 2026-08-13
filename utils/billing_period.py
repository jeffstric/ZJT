"""
峰谷计费时段判断工具（北京时间，UTC+8）

用途：LLM 异步扣费时，根据 token_log.created_at（调用发生时间）判断高峰/空闲时段，
从而在 vendor_model 表中选择对应的 time_period 计费档位。

设计要点：
- 中国无夏令时，固定 UTC+8，用 datetime.timezone(timedelta(hours=8)) 纯计算，
  不依赖系统时区库 / tzdata，跨 Windows/Linux/macOS 行为一致。
- 与项目现有约定一致（如 checkin_service 依赖 DB=北京时间）：
  token_log.created_at 为 MySQL CURRENT_TIMESTAMP，视为北京时间 naive datetime。
- 提供 aware→北京时间 naive 的归一化，兼容传入带 tzinfo 的时间。
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Union

from config.constant import PeakValleyBillingConstants as PVB

# 北京时间（固定 UTC+8，不依赖系统时区 / tzdata 包）
BJT = timezone(timedelta(hours=8))

# 支持的入参类型：datetime 或 ISO 字符串
DateTimeLike = Union[datetime, str, None]


def to_bjt_naive(dt: DateTimeLike) -> datetime:
    """将入参归一化为「北京时间 naive datetime」。

    - None / 无法解析：返回当前北京时间，保证扣费不中断（fail-safe）。
    - naive datetime：视为北京时间，原样返回。
    - aware datetime：转换到 BJT 后去掉 tzinfo。
    - str：按常见格式尝试解析，失败则回退当前北京时间。
    """
    if dt is None:
        return datetime.now(BJT).replace(tzinfo=None)

    if isinstance(dt, str):
        parsed = _parse_str(dt)
        if parsed is None:
            return datetime.now(BJT).replace(tzinfo=None)
        dt = parsed

    if not isinstance(dt, datetime):
        return datetime.now(BJT).replace(tzinfo=None)

    if dt.tzinfo is not None:
        return dt.astimezone(BJT).replace(tzinfo=None)
    return dt


def _parse_str(s: str) -> datetime | None:
    """尝试按常见格式解析字符串为 datetime，失败返回 None。"""
    text = s.strip()
    # 处理带时区后缀 'Z' / '+08:00' 的情况
    candidates = (
        '%Y-%m-%d %H:%M:%S',
        '%Y-%m-%d %H:%M:%S.%f',
        '%Y-%m-%dT%H:%M:%S',
        '%Y-%m-%dT%H:%M:%S.%f',
    )
    normalized = text.replace('Z', '+00:00')
    for fmt in candidates:
        try:
            # fromisoformat 能处理带偏移的 ISO 串（含上面 normalized 的 +HH:MM）
            if 'T' in text or '+' in text[10:] or normalized != text:
                try:
                    return datetime.fromisoformat(normalized)
                except ValueError:
                    pass
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def get_billing_period(dt: DateTimeLike) -> str:
    """判断 dt 所属计费时段。

    Args:
        dt: datetime / ISO 字符串 / None。视为北京时间（naive）或自动转换（aware）。

    Returns:
        PeakValleyBillingConstants.PERIOD_PEAK ('peak') 或
        PeakValleyBillingConstants.PERIOD_OFF_PEAK ('off_peak')

    任何异常都不会抛出：解析失败回退「当前时间」，确保扣费链路不中断。
    """
    try:
        bjt = to_bjt_naive(dt)
        hour = bjt.hour
        for start, end in PVB.PEAK_TIME_RANGES:
            if start <= hour < end:
                return PVB.PERIOD_PEAK
        return PVB.PERIOD_OFF_PEAK
    except Exception:
        # 极端情况下按当前时间兜底（默认大概率空闲时段）
        hour = datetime.now(BJT).hour
        for start, end in PVB.PEAK_TIME_RANGES:
            if start <= hour < end:
                return PVB.PERIOD_PEAK
        return PVB.PERIOD_OFF_PEAK


def now_period() -> str:
    """返回当前北京时间所属计费时段（调试/展示用）。"""
    return get_billing_period(None)
