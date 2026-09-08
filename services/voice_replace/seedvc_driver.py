"""Seed-VC V2 Gradio API driver。"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any, Optional
from urllib.parse import urljoin, urlparse, urlunparse

import httpx

from config.config_util import get_config_value
from config.constant import VoiceReplaceConstants as C
from services.voice_replace.ffmpeg_util import normalize_wav

logger = logging.getLogger(__name__)

_convert_lock = asyncio.Lock()


class SeedVcError(Exception):
    """Seed-VC 调用失败。"""


def get_seedvc_base_url() -> str:
    env = os.environ.get("SEEDVC_URL") or os.environ.get("VOICE_REPLACE_SEEDVC_URL")
    if env:
        return str(env).rstrip("/")
    try:
        yaml_url = get_config_value("voice_replace", "seedvc_base_url", default=None)
    except Exception as exc:
        logger.warning("[voice-replace][vc] yaml seedvc_base_url unavailable: %s", exc)
        yaml_url = None
    if yaml_url:
        return str(yaml_url).rstrip("/")
    return C.SEEDVC_BASE_URL.rstrip("/")


def parse_gradio_sse(text: str) -> Any:
    stripped = (text or "").strip()
    if stripped.startswith("{") or stripped.startswith("["):
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            pass
    last = None
    for line in text.splitlines():
        raw = line.strip()
        if not raw.startswith("data:"):
            continue
        payload = raw[5:].strip()
        if not payload or payload == "[DONE]":
            continue
        try:
            last = json.loads(payload)
        except json.JSONDecodeError:
            continue
    return last


def _file_data(server_path: str, orig_name: str) -> dict:
    return {
        "path": server_path,
        "orig_name": orig_name,
        "meta": {"_type": "gradio.FileData"},
    }


def extract_gradio_audio(payload: Any) -> Optional[dict]:
    """从 Gradio complete 事件里取出非流式 wav（第二个 output）。"""
    data = payload
    if isinstance(payload, dict):
        inner = payload.get("output", payload)
        if isinstance(inner, dict) and "data" in inner:
            data = inner.get("data")
        elif "data" in payload:
            data = payload.get("data")
    if isinstance(data, list):
        # 优先非流式 wav（网页「audio」口），不要拿 streaming m3u8/mp3
        for item in reversed(data):
            if isinstance(item, dict) and item.get("is_stream"):
                continue
            if isinstance(item, dict) and (item.get("path") or item.get("url")):
                return item
            if isinstance(item, str) and item and not item.endswith(".m3u8"):
                return {"path": item}
    if isinstance(data, dict) and (data.get("path") or data.get("url")):
        return data
    return None


def rewrite_loopback_url(url: str, base_url: str) -> str:
    parsed = urlparse(url)
    if parsed.hostname in ("127.0.0.1", "localhost"):
        base = urlparse(base_url)
        return urlunparse(
            (base.scheme, base.netloc, parsed.path, parsed.params, parsed.query, parsed.fragment)
        )
    return url


class SeedVcDriver:
    def __init__(
        self,
        base_url: Optional[str] = None,
        timeout: Optional[float] = None,
        client: Optional[httpx.AsyncClient] = None,
    ):
        self.base_url = (base_url or get_seedvc_base_url()).rstrip("/")
        read_timeout = float(timeout if timeout is not None else C.SEEDVC_TIMEOUT)
        self.timeout = httpx.Timeout(read_timeout, connect=float(C.HTTP_CONNECT_TIMEOUT))
        self._client = client

    async def convert(
        self,
        source_wav: str,
        reference_wav: str,
        dest_wav: str,
    ) -> str:
        async with _convert_lock:
            return await self._convert_unlocked(source_wav, reference_wav, dest_wav)

    async def _convert_unlocked(self, source_wav: str, reference_wav: str, dest_wav: str) -> str:
        if self._client is not None:
            return await self._convert_with(self._client, source_wav, reference_wav, dest_wav)
        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
            return await self._convert_with(client, source_wav, reference_wav, dest_wav)

    async def _convert_with(
        self,
        client: httpx.AsyncClient,
        source_wav: str,
        reference_wav: str,
        dest_wav: str,
    ) -> str:
        logger.info("[voice-replace][vc] convert source=%s ref=%s", source_wav, reference_wav)
        src_id = await self._upload(client, source_wav)
        ref_id = await self._upload(client, reference_wav)
        body = {
            "data": [
                _file_data(src_id, os.path.basename(source_wav)),
                _file_data(ref_id, os.path.basename(reference_wav)),
                int(C.SEEDVC_STEPS),
                float(C.SEEDVC_LENGTH),
                float(C.SEEDVC_CLARITY),
                float(C.SEEDVC_SIMILARITY),
                float(C.SEEDVC_TOP_P),
                float(C.SEEDVC_TEMPERATURE),
                float(C.SEEDVC_REPETITION),
                False,
                False,
            ]
        }
        try:
            posted = await client.post(
                f"{self.base_url}{C.SEEDVC_PREDICT_PATH}",
                json=body,
            )
            posted.raise_for_status()
            event_id = posted.json().get("event_id")
            if not event_id:
                raise SeedVcError(f"seed-vc missing event_id: {posted.text[:300]}")
            stream = await client.get(
                f"{self.base_url}{C.SEEDVC_PREDICT_PATH}/{event_id}",
            )
            stream.raise_for_status()
        except httpx.TimeoutException as exc:
            raise SeedVcError(f"seed-vc timeout after {self.timeout.read}s") from exc
        except httpx.HTTPStatusError as exc:
            raise SeedVcError(f"seed-vc http {exc.response.status_code}") from exc
        except httpx.HTTPError as exc:
            raise SeedVcError(f"seed-vc request failed: {exc}") from exc
        payload = parse_gradio_sse(stream.text)
        audio = extract_gradio_audio(payload)
        if not audio:
            raise SeedVcError("seed-vc response has no audio")
        raw_path = dest_wav + ".dl.wav"
        await self._download_result(client, audio, raw_path)
        try:
            await normalize_wav(raw_path, dest_wav)
        finally:
            if os.path.exists(raw_path):
                os.remove(raw_path)
        if not os.path.isfile(dest_wav) or os.path.getsize(dest_wav) == 0:
            raise SeedVcError("seed-vc downloaded empty audio")
        return dest_wav

    async def _upload(self, client: httpx.AsyncClient, path: str) -> str:
        with open(path, "rb") as fh:
            resp = await client.post(
                f"{self.base_url}/gradio_api/upload",
                files={"files": (os.path.basename(path), fh, "audio/wav")},
            )
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, list) and data:
            item = data[0]
            if isinstance(item, str):
                return item
            if isinstance(item, dict):
                return item.get("path") or item.get("name") or ""
        if isinstance(data, str):
            return data
        raise SeedVcError(f"unexpected upload response: {data!r}")

    async def _download_result(self, client: httpx.AsyncClient, audio: dict, dest_wav: str) -> None:
        url = audio.get("url") or ""
        path = audio.get("path") or ""
        if url:
            url = rewrite_loopback_url(url, self.base_url)
        elif path:
            url = urljoin(self.base_url + "/", f"gradio_api/file={path}")
        else:
            raise SeedVcError("seed-vc audio missing path/url")
        resp = await client.get(url)
        resp.raise_for_status()
        os.makedirs(os.path.dirname(dest_wav) or ".", exist_ok=True)
        with open(dest_wav, "wb") as fh:
            fh.write(resp.content)
