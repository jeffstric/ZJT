"""
火山引擎（豆包语音）语音合成 2.0 工具（V3 单向流式 HTTP）

接口：POST https://openspeech.bytedance.com/api/v3/tts/unidirectional
- 鉴权 Header（新版控制台单 API Key，2026-10 实测）：
    X-Api-Key: {控制台 API Key（UUID 密钥本体）}
    X-Api-Resource-Id: seed-tts-2.0
    X-Api-Request-Id: {uuid}
- 请求体：{"req_params": {"text", "speaker", "audio_params", "speech_rate"}}
- 响应为 HTTP chunked JSON 块流（非二进制帧协议，2026-10 实测）：
    数据块 {"code": 0, "data": "<base64 mp3>"}
    字幕块 {"code": 0, "sentence": {...}}
    结束块 {"code": 20000000, "message": "OK"}
  拼接全部 data 即完整音频。

全链路 async（httpx.AsyncClient + aiter_bytes），不阻塞事件循环。
"""
import base64
import json
import logging
import os
import time
import uuid
from typing import Dict, List, Optional, Tuple

import httpx

from config.config_util import get_dynamic_config_value
from config.volcengine_tts_constants import (
    VolcengineTtsConstants,
    normalize_volcengine_tts_speed,
    speed_ratio_to_speech_rate,
)

logger = logging.getLogger(__name__)

# JSON 块流缓冲累积上限（字节）。超限说明对端返回的不是预期协议，直接失败。
_DECODE_BUFFER_LIMIT = 32 * 1024 * 1024


class TtsJsonBlockDecoder:
    """2.0 单向流式响应解析器：HTTP chunk 内为直接串联的 JSON 对象块。

    每个 chunk 未必对齐 JSON 边界：用 raw_decode 从缓冲头解析，
    剩余不完整字节保留等待下一块。
    """

    def __init__(self):
        self._buffer = ""

    def feed(self, chunk: bytes) -> List[dict]:
        """喂入一个 HTTP chunk，返回本块成功解析出的 JSON 对象列表。"""
        if not chunk:
            return []
        self._buffer += chunk.decode("utf-8", errors="replace")
        if len(self._buffer) > _DECODE_BUFFER_LIMIT:
            raise ValueError(
                f"TTS JSON 块缓冲超过 {_DECODE_BUFFER_LIMIT} 字节，响应不是预期的块流协议"
            )
        blocks: List[dict] = []
        decoder = json.JSONDecoder()
        idx = 0
        n = len(self._buffer)
        while idx < n:
            # 跳过块间空白
            while idx < n and self._buffer[idx] in " \r\n\t":
                idx += 1
            if idx >= n:
                break
            try:
                obj, end = decoder.raw_decode(self._buffer, idx)
            except json.JSONDecodeError:
                break  # 半块：等待更多数据
            if isinstance(obj, dict):
                blocks.append(obj)
            idx = end
        if idx > 0:
            self._buffer = self._buffer[idx:]
        return blocks


def get_volcengine_tts_config() -> Dict[str, str]:
    """读取火山 TTS 配置（DB 优先 YAML 兜底，支持热更换 key）。"""
    return {
        "api_key": (get_dynamic_config_value("volcengine_tts", "api_key") or "").strip(),
        "resource_id": (
            get_dynamic_config_value("volcengine_tts", "resource_id")
            or VolcengineTtsConstants.RESOURCE_ID
        ),
    }


def is_tts_configured(config: Dict[str, str]) -> bool:
    return bool(config.get("api_key"))


async def synthesize_speech(
    text: str,
    speaker: str,
    speed_ratio: float = VolcengineTtsConstants.SPEED_DEFAULT,
    encoding: str = VolcengineTtsConstants.DEFAULT_ENCODING,
    timeout: Optional[float] = None,
) -> Tuple[bool, bytes, str]:
    """调用火山语音合成 2.0 单向流式接口（async，非阻塞）。

    Args:
        text: 待合成文本（调用方负责长度校验）
        speaker: 2.0 音色 ID（如 zh_female_vv_uranus_bigtts，需在音色库白名单内）
        speed_ratio: 语速（1.0 正常，>1 更快），请求体换算为 speech_rate
        encoding: 音频格式（mp3/wav）
        timeout: 请求超时秒数（默认 VolcengineTtsConstants.TIMEOUT_SECONDS）

    Returns:
        (success, audio_bytes, message)：
        - 成功：audio_bytes 为拼接后的完整音频字节
        - 失败：audio_bytes 为空 bytes，message 为错误信息
    """
    config = get_volcengine_tts_config()
    if not is_tts_configured(config):
        return False, b"", (
            "火山语音合成未配置：请在管理后台「快速配置-多媒体-火山引擎语音合成」填写"
            "控制台 API Key（详见 docs/audio/volcengine_tts.md）"
        )

    if timeout is None:
        timeout = VolcengineTtsConstants.TIMEOUT_SECONDS

    payload = {
        "req_params": {
            "text": text,
            "speaker": speaker,
            "audio_params": {
                "format": encoding,
                "sample_rate": VolcengineTtsConstants.DEFAULT_SAMPLE_RATE,
                "bit_rate": VolcengineTtsConstants.DEFAULT_BITRATE,
            },
            "speech_rate": speed_ratio_to_speech_rate(speed_ratio),
        }
    }
    headers = {
        "X-Api-Key": config["api_key"],
        "X-Api-Resource-Id": config["resource_id"],
        "X-Api-Request-Id": str(uuid.uuid4()),
        "Content-Type": "application/json",
    }
    url = VolcengineTtsConstants.API_HOST + VolcengineTtsConstants.UNIDIRECTIONAL_PATH

    decoder = TtsJsonBlockDecoder()
    audio_parts: List[bytes] = []
    finished = False
    try:
        async with httpx.AsyncClient() as client:
            async with client.stream(
                "POST", url, json=payload, headers=headers, timeout=timeout
            ) as response:
                if response.status_code != 200:
                    error_text = (await response.aread()).decode("utf-8", errors="replace")[:500]
                    return False, b"", f"火山TTS HTTP {response.status_code}: {error_text}"

                async for chunk in response.aiter_bytes():
                    for block in decoder.feed(chunk):
                        code = block.get("code")
                        message = block.get("message") or ""
                        if code == VolcengineTtsConstants.FINISH_CODE:
                            finished = True
                            continue
                        if code not in VolcengineTtsConstants.OK_CODES:
                            return False, b"", f"火山TTS错误 code={code}: {message}"
                        data_b64 = block.get("data")
                        if data_b64:
                            try:
                                audio_parts.append(base64.b64decode(data_b64))
                            except (ValueError, TypeError) as e:
                                return False, b"", f"火山TTS音频块 base64 解码失败: {e}"
    except httpx.TimeoutException:
        return False, b"", f"火山TTS请求超时（{timeout}s），请稍后重试"
    except httpx.ConnectError:
        return False, b"", "无法连接火山TTS服务（openspeech.bytedance.com），请检查网络"
    except ValueError as e:
        return False, b"", f"火山TTS响应解析失败: {e}"
    except Exception as e:  # noqa: BLE001
        logger.exception("火山TTS调用异常")
        return False, b"", f"火山TTS调用失败: {e}"

    audio_bytes = b"".join(audio_parts)
    if not audio_bytes or not finished:
        return False, b"", "火山TTS未返回完整音频（流提前结束），请重试"
    return True, audio_bytes, "success"


def build_audio_filename(prefix: str = "tts") -> str:
    """生成本地落盘文件名：{prefix}_{yyyymmdd_HHMMSS}_{uuid8}.mp3"""
    return f"{prefix}_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}.mp3"


def resolve_result_dir() -> str:
    """本地结果目录（相对项目根的绝对路径），不存在则创建。"""
    from utils.project_path import get_project_root

    result_dir = os.path.join(get_project_root(), VolcengineTtsConstants.RESULT_SUBDIR)
    os.makedirs(result_dir, exist_ok=True)
    return result_dir
