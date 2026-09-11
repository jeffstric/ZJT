"""SenseVoice ASR driver：httpx 异步调用分段接口。"""
from __future__ import annotations

from typing import List, Optional, Protocol, Union
import logging
import os
from pathlib import Path
from urllib.parse import urlparse

import httpx

from config.config_util import get_config_value
from config.constant import VoiceReplaceConstants as C
from services.voice_replace.aligner import AsrSegment

logger = logging.getLogger(__name__)

AudioInput = Union[str, bytes, os.PathLike]


class SenseVoiceAsrError(Exception):
    """远程 ASR 失败（超时、HTTP、协议）。"""


class AsrDriver(Protocol):
    async def transcribe_segments(
        self,
        audio: AudioInput,
        *,
        language: str = "auto",
        filename: Optional[str] = None,
    ) -> List[AsrSegment]:
        ...


def get_asr_base_url() -> str:
    env = os.environ.get("SENSEVOICE_ASR_URL") or os.environ.get("VOICE_REPLACE_ASR_URL")
    if env:
        return str(env).rstrip("/")
    try:
        yaml_url = get_config_value("voice_replace", "asr_base_url", default=None)
    except Exception as exc:
        logger.warning("[voice-replace][asr] yaml asr_base_url unavailable: %s", exc)
        yaml_url = None
    if yaml_url:
        return str(yaml_url).rstrip("/")
    return C.ASR_BASE_URL.rstrip("/")


def _guess_filename(audio: AudioInput, filename: Optional[str]) -> str:
    if filename:
        return filename
    if isinstance(audio, bytes):
        return "audio.wav"
    name = Path(str(audio)).name
    return name or "audio.wav"


def _content_type(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    return {
        ".wav": "audio/wav",
        ".mp3": "audio/mpeg",
        ".m4a": "audio/mp4",
        ".aac": "audio/aac",
        ".ogg": "audio/ogg",
        ".flac": "audio/flac",
        ".mp4": "audio/mp4",
        ".webm": "audio/webm",
    }.get(ext, "application/octet-stream")


def parse_asr_segments_payload(payload: object) -> List[AsrSegment]:
    if not isinstance(payload, dict):
        raise SenseVoiceAsrError("asr response is not an object")
    items = payload.get("result")
    if items is None:
        raise SenseVoiceAsrError("asr response missing result")
    if not isinstance(items, list):
        raise SenseVoiceAsrError("asr result is not a list")
    segments: List[AsrSegment] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            start = float(item.get("start") if item.get("start") is not None else 0)
            end = float(item.get("end") if item.get("end") is not None else 0)
        except (TypeError, ValueError) as exc:
            raise SenseVoiceAsrError(f"invalid asr timestamps: {item!r}") from exc
        text = (item.get("text") or item.get("raw_text") or "").strip()
        if end < start:
            end = start
        if end <= start and not text:
            continue
        segments.append(AsrSegment(start=start, end=end, text=text))
    return segments


class SenseVoiceAsrDriver:
    """POST {base}/api/v1/asr_segments ，返回 aligner 用的 AsrSegment 列表。"""

    def __init__(
        self,
        base_url: Optional[str] = None,
        timeout: Optional[float] = None,
        client: Optional[httpx.AsyncClient] = None,
    ):
        self.base_url = (base_url or get_asr_base_url()).rstrip("/")
        read_timeout = float(timeout if timeout is not None else C.ASR_TIMEOUT)
        self.timeout = httpx.Timeout(
            read_timeout,
            connect=float(C.HTTP_CONNECT_TIMEOUT),
        )
        self._client = client
        self._segments_url = f"{self.base_url}{C.ASR_SEGMENTS_PATH}"

    async def transcribe_segments(
        self,
        audio: AudioInput,
        *,
        language: str = "auto",
        filename: Optional[str] = None,
    ) -> List[AsrSegment]:
        name = _guess_filename(audio, filename)
        file_bytes, name = await self._load_audio(audio, name)
        if not file_bytes:
            raise SenseVoiceAsrError("empty audio")
        logger.info(
            "[voice-replace][asr] POST %s bytes=%s lang=%s",
            self._segments_url,
            len(file_bytes),
            language,
        )
        files = {"file": (name, file_bytes, _content_type(name))}
        data = {"lang": language or "auto"}
        try:
            if self._client is not None:
                response = await self._client.post(
                    self._segments_url,
                    files=files,
                    data=data,
                    timeout=self.timeout,
                )
            else:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    response = await client.post(
                        self._segments_url,
                        files=files,
                        data=data,
                    )
            response.raise_for_status()
            payload = response.json()
        except httpx.TimeoutException as exc:
            raise SenseVoiceAsrError(f"asr timeout after {self.timeout.read}s") from exc
        except httpx.HTTPStatusError as exc:
            body = ""
            try:
                body = exc.response.text[:300]
            except Exception:
                body = ""
            raise SenseVoiceAsrError(
                f"asr http {exc.response.status_code}: {body}"
            ) from exc
        except httpx.HTTPError as exc:
            raise SenseVoiceAsrError(f"asr request failed: {exc}") from exc
        except ValueError as exc:
            raise SenseVoiceAsrError("asr response is not json") from exc
        segments = parse_asr_segments_payload(payload)
        logger.info("[voice-replace][asr] segments=%s", len(segments))
        return segments

    async def health(self) -> bool:
        url = f"{self.base_url}/health"
        try:
            if self._client is not None:
                response = await self._client.get(url, timeout=self.timeout)
            else:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    response = await client.get(url)
            if response.status_code != 200:
                return False
            data = response.json()
            return bool(data.get("ok"))
        except (httpx.HTTPError, ValueError):
            return False

    async def _load_audio(self, audio: AudioInput, filename: str) -> tuple:
        if isinstance(audio, bytes):
            return audio, filename
        path_or_url = os.fspath(audio)
        parsed = urlparse(path_or_url)
        if parsed.scheme in ("http", "https"):
            return await self._download(path_or_url), _guess_filename(path_or_url, filename)
        path = Path(path_or_url)
        if not path.is_file():
            raise SenseVoiceAsrError(f"audio file not found: {path_or_url}")
        return path.read_bytes(), filename or path.name

    async def _download(self, url: str) -> bytes:
        try:
            if self._client is not None:
                response = await self._client.get(url, timeout=self.timeout)
            else:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    response = await client.get(url)
            response.raise_for_status()
            data = response.content
        except httpx.TimeoutException as exc:
            raise SenseVoiceAsrError(f"audio download timeout: {url}") from exc
        except httpx.HTTPError as exc:
            raise SenseVoiceAsrError(f"audio download failed: {exc}") from exc
        if not data:
            raise SenseVoiceAsrError("downloaded audio is empty")
        return data


def get_asr_driver() -> SenseVoiceAsrDriver:
    return SenseVoiceAsrDriver()
