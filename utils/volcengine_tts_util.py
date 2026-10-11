"""
火山引擎（豆包语音）大模型语音合成工具（V3 单向流式 HTTP）

接口：POST https://openspeech.bytedance.com/api/v3/tts/unidirectional
- 鉴权 Header：X-Api-App-Key / X-Api-Access-Key / X-Api-Resource-Id
  （豆包语音控制台凭证，配置段 volcengine_tts.app_key / access_key，
   与方舟 volcengine.api_key 不是同一套体系）
- 请求体一次性携带全部文本，响应为 HTTP chunked 流式音频帧，
  每帧 = 4 字节协议头 + JSON payload（音频 base64 在 data 字段），
  收到 is_last=true 的帧后结束，拼接全部 data 即完整音频。

全链路 async（httpx.AsyncClient + aiter_bytes），不阻塞事件循环。
帧解析集中在 V3ChunkDecoder，独立可单测；若火山实际帧格式与官方文档
存在出入（社区示例存在"尾部 4 字节 payload_size"变体），解析器同时
兼容两种布局，仅需调整这一个类。
"""
import base64
import gzip
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
)

logger = logging.getLogger(__name__)

# 兼容的"成功"业务码：官方 v3 以 0 为成功；历史/社区示例存在 2000（v1 沿用）
_V3_OK_CODES = (0, 2000)

# 单次合成的帧缓冲累积上限（字节）。正常一段音频帧 payload 远小于此值，
# 超限说明对端返回的不是预期协议，直接失败避免内存放大。
_DECODE_BUFFER_LIMIT = 32 * 1024 * 1024


class V3ChunkDecoder:
    """火山 V3 chunked 音频帧解析器（带缓冲，兼容两种帧布局）。

    布局 A（官方文档）：4 字节头 + 可选 2 字节 sequence + payload(JSON/gzip)
        byte0: (protocol_version << 4) | message_type
        byte1: (message_type_specific_flags << 4)，bit0=1 表示头后带 2 字节 sequence
        byte2: (serialization << 4) | compression  （serialization: 0=raw 1=JSON；
               compression: 0=none 1=gzip）
        byte3: reserved
    布局 B（社区变体）：4 字节头 + payload + 尾部 4 字节 payload_size（大端）

    HTTP chunk 未必恰好一帧一块：解析失败的字节保留在缓冲区等待下一块；
    由于 payload 无显式长度字段，JSON 解析成功即认为消耗整个缓冲
    （服务端按消息边界 flush，与官方 demo 假设一致）。
    """

    def __init__(self):
        self._buffer = bytearray()

    def feed(self, chunk: bytes) -> List[Tuple[int, Optional[dict]]]:
        """喂入一个 HTTP chunk，返回本块成功解析出的 (msg_type, payload) 列表。"""
        if not chunk:
            return []
        self._buffer.extend(chunk)
        if len(self._buffer) > _DECODE_BUFFER_LIMIT:
            raise ValueError(
                f"V3 帧缓冲超过 {_DECODE_BUFFER_LIMIT} 字节，响应不是预期的流式音频协议"
            )
        return self._drain()

    def _drain(self) -> List[Tuple[int, Optional[dict]]]:
        messages: List[Tuple[int, Optional[dict]]] = []
        # 每轮尝试从缓冲头解析一条消息；布局 A/B 的 JSON 成功即整块消费
        while len(self._buffer) >= 4:
            msg_type, payload, consumed, ok = self._try_parse_one(bytes(self._buffer))
            if not ok:
                break  # 半帧：保留缓冲等待下一块
            del self._buffer[:consumed]
            messages.append((msg_type, payload))
            if consumed == 0:
                break  # 防御：避免零消费死循环
        return messages

    def _try_parse_one(self, data: bytes) -> Tuple[int, Optional[dict], int, bool]:
        """尝试把缓冲头部解析为一条消息。

        Returns:
            (msg_type, payload_dict_or_None, consumed_bytes, ok)
            ok=False 表示数据不完整，应等待更多字节。
        """
        msg_type = data[0] & 0x0F
        flags = (data[1] >> 4) & 0x0F
        serialization = (data[2] >> 4) & 0x0F
        compression = data[2] & 0x0F

        payload_start = 4 + (2 if (flags & 0x01) else 0)
        if len(data) < payload_start:
            return msg_type, None, 0, False

        body = data[payload_start:]

        # 布局 B：尾部 4 字节 payload_size（大端）。仅当总长精确吻合时采用，
        # 避免与布局 A 的裸 JSON 产生歧义。
        if len(body) >= 4:
            tail_size = int.from_bytes(body[-4:], "big")
            if 0 < tail_size <= len(body) - 4 and len(body) == tail_size + 4:
                parsed = self._parse_payload(body[:tail_size], serialization, compression)
                if parsed is not None:
                    return msg_type, parsed, len(data), True

        # 布局 A：余下全部为 payload
        parsed = self._parse_payload(body, serialization, compression)
        if parsed is not None:
            return msg_type, parsed, len(data), True

        return msg_type, None, 0, False

    @staticmethod
    def _parse_payload(body: bytes, serialization: int, compression: int) -> Optional[dict]:
        """解压并反序列化 payload；失败返回 None（可能是半帧，等更多数据）。"""
        if compression == 0x01:
            try:
                body = gzip.decompress(body)
            except OSError:
                return None
        try:
            parsed = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None
        return parsed if isinstance(parsed, dict) else None


def get_volcengine_tts_config() -> Dict[str, str]:
    """读取火山 TTS 配置（DB 优先 YAML 兜底，支持热更换 key）。

    新版控制台（console.volcengine.com/speech/new）为单 API Key 鉴权（X-Api-Key）；
    旧版 App ID + Access Token 双头保留兼容。
    """
    return {
        "api_key": (get_dynamic_config_value("volcengine_tts", "api_key") or "").strip(),
        "app_key": (get_dynamic_config_value("volcengine_tts", "app_key") or "").strip(),
        "access_key": (get_dynamic_config_value("volcengine_tts", "access_key") or "").strip(),
        "resource_id": (
            get_dynamic_config_value("volcengine_tts", "resource_id")
            or VolcengineTtsConstants.RESOURCE_ID
        ),
    }


def _is_tts_configured(config: Dict[str, str]) -> bool:
    if config["api_key"]:
        return True
    return bool(config["app_key"] and config["access_key"])


def _build_auth_headers(config: Dict[str, str]) -> Dict[str, str]:
    """新版单 API Key 优先；否则回退旧版 App ID + Access Token 双头。"""
    if config["api_key"]:
        return {
            "X-Api-Key": config["api_key"],
            "X-Api-Resource-Id": config["resource_id"],
            "Content-Type": "application/json",
        }
    return {
        "X-Api-App-Key": config["app_key"],
        "X-Api-Access-Key": config["access_key"],
        "X-Api-Resource-Id": config["resource_id"],
        "Content-Type": "application/json",
    }


async def synthesize_speech(
    text: str,
    voice_type: str,
    speed_ratio: float = VolcengineTtsConstants.SPEED_DEFAULT,
    encoding: str = VolcengineTtsConstants.DEFAULT_ENCODING,
    timeout: Optional[float] = None,
) -> Tuple[bool, bytes, str]:
    """调用火山 V3 单向流式接口合成音频（async，非阻塞）。

    Args:
        text: 待合成文本（调用方负责长度校验）
        voice_type: 火山音色 ID（如 BV700_streaming，需在音色库白名单内）
        speed_ratio: 语速（归一化到 0.5~2.0）
        encoding: 音频格式（mp3/wav）
        timeout: 请求超时秒数（默认 VolcengineTtsConstants.TIMEOUT_SECONDS）

    Returns:
        (success, audio_bytes, message)：
        - 成功：audio_bytes 为拼接后的完整音频字节
        - 失败：audio_bytes 为空 bytes，message 为错误信息
    """
    config = get_volcengine_tts_config()
    if not _is_tts_configured(config):
        return False, b"", (
            "火山语音合成未配置：请在管理后台「快速配置-多媒体-火山引擎语音合成」填写"
            "控制台 API Key（详见 docs/audio/volcengine_tts.md）"
        )

    if timeout is None:
        timeout = VolcengineTtsConstants.TIMEOUT_SECONDS
    speed = normalize_volcengine_tts_speed(speed_ratio)

    payload = {
        "user": {"uid": "perseids-tts"},
        "operation": "submit",
        "reqid": str(uuid.uuid4()),
        "text": text,
        "voice_type": voice_type,
        "encoding": encoding,
        "speed_ratio": speed,
        "audio_params": {
            "format": encoding,
            "sample_rate": VolcengineTtsConstants.DEFAULT_SAMPLE_RATE,
            "bitrate": VolcengineTtsConstants.DEFAULT_BITRATE,
        },
    }
    headers = _build_auth_headers(config)
    url = VolcengineTtsConstants.API_HOST + VolcengineTtsConstants.UNIDIRECTIONAL_PATH

    decoder = V3ChunkDecoder()
    audio_parts: List[bytes] = []
    is_last = False
    try:
        async with httpx.AsyncClient() as client:
            async with client.stream(
                "POST", url, json=payload, headers=headers, timeout=timeout
            ) as response:
                if response.status_code != 200:
                    error_text = (await response.aread()).decode("utf-8", errors="replace")[:500]
                    return False, b"", f"火山TTS HTTP {response.status_code}: {error_text}"

                async for chunk in response.aiter_bytes():
                    for msg_type, message in decoder.feed(chunk):
                        if msg_type == VolcengineTtsConstants.MSG_TYPE_ERROR_RESPONSE:
                            return False, b"", _format_error(message)
                        code = message.get("code")
                        if code is not None and code not in _V3_OK_CODES:
                            return False, b"", _format_error(message)
                        data_b64 = message.get("data")
                        if data_b64:
                            try:
                                audio_parts.append(base64.b64decode(data_b64))
                            except (ValueError, TypeError) as e:
                                return False, b"", f"火山TTS音频帧 base64 解码失败: {e}"
                        if message.get("is_last"):
                            is_last = True
    except httpx.TimeoutException:
        return False, b"", f"火山TTS请求超时（{timeout}s），请稍后重试"
    except httpx.ConnectError:
        return False, b"", "无法连接火山TTS服务（openspeech.bytedance.com），请检查网络"
    except ValueError as e:
        # V3ChunkDecoder 缓冲超限等协议异常
        return False, b"", f"火山TTS响应解析失败: {e}"
    except Exception as e:  # noqa: BLE001
        logger.exception("火山TTS调用异常")
        return False, b"", f"火山TTS调用失败: {e}"

    audio_bytes = b"".join(audio_parts)
    if not audio_bytes or not is_last:
        return False, b"", "火山TTS未返回完整音频（流提前结束），请重试"
    return True, audio_bytes, "success"


def _format_error(message: Optional[dict]) -> str:
    if not message:
        return "火山TTS返回未知错误"
    code = message.get("code", "unknown")
    desc = message.get("message") or message.get("error") or ""
    return f"火山TTS错误 code={code}: {desc}"


def build_audio_filename(prefix: str = "tts") -> str:
    """生成本地落盘文件名：{prefix}_{yyyymmdd_HHMMSS}_{uuid8}.mp3"""
    return f"{prefix}_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}.mp3"


def resolve_result_dir() -> str:
    """本地结果目录（相对项目根的绝对路径），不存在则创建。"""
    from utils.project_path import get_project_root

    result_dir = os.path.join(get_project_root(), VolcengineTtsConstants.RESULT_SUBDIR)
    os.makedirs(result_dir, exist_ok=True)
    return result_dir
