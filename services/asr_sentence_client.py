"""
SenseVoice ASR 句级转写客户端（l3 内网服务）。

供故事板整片导出的 smart 字幕使用：把单条对白 wav 转成句级时间轴
[{start, end, text}]（秒，相对该音频起点），字幕按句显示而非整条分页。

同步实现（urllib），仅允许在导出后台线程（asyncio.to_thread / 工作线程）中调用，
禁止在事件循环内直接调用。任何失败（配置关闭、网络、超时、解析）都返回 []，
由调用方回退为整条对白分页字幕，绝不阻塞/中断导出。
"""
from __future__ import annotations

import json
import logging
import os
import uuid
from typing import Any, Dict, List, Optional
from urllib.request import Request, urlopen

from config.config_util import get_config_value
from config.constant import StoryboardAsrConstants

logger = logging.getLogger(__name__)


def is_asr_enabled() -> bool:
    """opt-in：未配置 asr 段的环境默认关闭（避免对不可达内网地址逐条等
    30s 连接超时拖慢导出，以及用户音频被默认外发到未知地址）。"""
    try:
        enabled = get_config_value("asr", "enabled", default=False)
        return bool(enabled)
    except Exception:
        return False


def get_asr_api_url() -> str:
    try:
        url = str(get_config_value("asr", "api_url", default="") or "").strip()
        return url or StoryboardAsrConstants.DEFAULT_API_URL
    except Exception:
        return StoryboardAsrConstants.DEFAULT_API_URL


def transcribe_sentences(
    wav_path: str,
    *,
    timeout: Optional[float] = None,
    lang: str = "auto",
) -> List[Dict[str, Any]]:
    """
    调 ASR 服务 /api/v1/asr_sentences，返回句级时间轴。

    Args:
        wav_path: 本地音频路径（wav/mp3 等常见格式均可）。
        timeout: 单条请求超时秒数，缺省用 StoryboardAsrConstants.SENTENCES_TIMEOUT_SECONDS。
        lang: 语言 auto/zh/en...

    Returns:
        [{"start": float, "end": float, "text": str}, ...]（start/end 秒，升序）。
        服务不可用/失败/结果为空时返回 []。
    """
    if not wav_path or not os.path.isfile(wav_path):
        return []
    if not is_asr_enabled():
        return []
    api_url = get_asr_api_url()
    if not api_url:
        return []
    url = api_url.rstrip("/") + "/api/v1/asr_sentences"
    if timeout is None:
        timeout = StoryboardAsrConstants.SENTENCES_TIMEOUT_SECONDS

    boundary = "----sbAsrBoundary" + uuid.uuid4().hex
    try:
        with open(wav_path, "rb") as f:
            audio_bytes = f.read()
    except OSError as e:
        logger.warning("asr_sentences read file fail %s: %s", wav_path, e)
        return []
    if not audio_bytes:
        return []

    body = b"".join([
        f"--{boundary}\r\n".encode("utf-8"),
        b'Content-Disposition: form-data; name="lang"\r\n\r\n',
        f"{lang}\r\n".encode("utf-8"),
        f"--{boundary}\r\n".encode("utf-8"),
        (
            'Content-Disposition: form-data; name="file"; filename="audio.wav"\r\n'
            "Content-Type: application/octet-stream\r\n\r\n"
        ).encode("utf-8"),
        audio_bytes,
        f"\r\n--{boundary}--\r\n".encode("utf-8"),
    ])
    headers = {
        "Content-Type": f"multipart/form-data; boundary={boundary}",
        "Content-Length": str(len(body)),
    }

    try:
        req = Request(url, data=body, headers=headers, method="POST")
        with urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8", errors="replace"))
    except Exception as e:
        logger.warning("asr_sentences request fail %s: %s", url, e)
        return []

    result = payload.get("result") if isinstance(payload, dict) else None
    if not isinstance(result, list) or len(result) < StoryboardAsrConstants.SENTENCES_MIN_COUNT:
        return []

    sents: List[Dict[str, Any]] = []
    for item in result:
        if not isinstance(item, dict):
            continue
        try:
            start = float(item.get("start"))
            end = float(item.get("end"))
        except (TypeError, ValueError):
            continue
        text = str(item.get("text") or "").strip()
        if end <= start:
            continue
        sents.append({"start": start, "end": end, "text": text})
    sents.sort(key=lambda s: s["start"])
    return sents
