"""UVR driver：httpx 异步调用人声/伴奏分离。"""
from __future__ import annotations

import io
import logging
import os
import zipfile
from typing import Optional, Tuple

import httpx

from config.config_util import get_config_value
from config.constant import VoiceReplaceConstants as C

logger = logging.getLogger(__name__)


class UvrError(Exception):
    """远程 UVR 失败（超时、HTTP、协议）。"""


def get_uvr_base_url() -> str:
    env = os.environ.get("UVR_URL") or os.environ.get("VOICE_REPLACE_UVR_URL")
    if env:
        return str(env).rstrip("/")
    try:
        yaml_url = get_config_value("voice_replace", "uvr_base_url", default=None)
    except Exception as exc:
        logger.warning("[voice-replace][uvr] yaml uvr_base_url unavailable: %s", exc)
        yaml_url = None
    if yaml_url:
        return str(yaml_url).rstrip("/")
    return C.UVR_BASE_URL.rstrip("/")


def parse_uvr_zip(payload: bytes, vocals_dest: str, instrumental_dest: str) -> Tuple[str, Optional[str]]:
    if not payload:
        raise UvrError("uvr zip is empty")
    try:
        zf = zipfile.ZipFile(io.BytesIO(payload))
    except zipfile.BadZipFile as exc:
        raise UvrError("uvr response is not a zip") from exc
    names = zf.namelist()
    vocals_name = next((n for n in names if os.path.basename(n).lower() == "vocals.wav"), None)
    inst_name = next((n for n in names if os.path.basename(n).lower() == "instrumental.wav"), None)
    if not vocals_name:
        raise UvrError(f"uvr zip missing vocals.wav: {names}")
    os.makedirs(os.path.dirname(vocals_dest) or ".", exist_ok=True)
    with zf.open(vocals_name) as src, open(vocals_dest, "wb") as dest:
        dest.write(src.read())
    if not os.path.isfile(vocals_dest) or os.path.getsize(vocals_dest) == 0:
        raise UvrError("uvr vocals is empty")
    if not inst_name:
        return vocals_dest, None
    os.makedirs(os.path.dirname(instrumental_dest) or ".", exist_ok=True)
    with zf.open(inst_name) as src, open(instrumental_dest, "wb") as dest:
        dest.write(src.read())
    if not os.path.isfile(instrumental_dest) or os.path.getsize(instrumental_dest) == 0:
        return vocals_dest, None
    return vocals_dest, instrumental_dest


class UvrDriver:
    """POST {base}/api/v1/uvr ，写出 vocals.wav / instrumental.wav。"""

    def __init__(
        self,
        base_url: Optional[str] = None,
        timeout: Optional[float] = None,
        client: Optional[httpx.AsyncClient] = None,
    ):
        self.base_url = (base_url or get_uvr_base_url()).rstrip("/")
        read_timeout = float(timeout if timeout is not None else C.UVR_TIMEOUT)
        self.timeout = httpx.Timeout(
            read_timeout,
            connect=float(C.HTTP_CONNECT_TIMEOUT),
        )
        self._client = client
        self._url = f"{self.base_url}{C.UVR_SEPARATE_PATH}"

    async def separate(
        self,
        source_wav: str,
        vocals_dest: str,
        instrumental_dest: str,
    ) -> Tuple[str, Optional[str]]:
        if not os.path.isfile(source_wav):
            raise UvrError(f"audio file not found: {source_wav}")
        logger.info("[voice-replace][uvr] POST %s src=%s", self._url, source_wav)
        with open(source_wav, "rb") as fh:
            files = {"file": (os.path.basename(source_wav), fh.read(), "audio/wav")}
        try:
            if self._client is not None:
                response = await self._client.post(self._url, files=files, timeout=self.timeout)
            else:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    response = await client.post(self._url, files=files)
            response.raise_for_status()
            payload = response.content
        except httpx.TimeoutException as exc:
            raise UvrError(f"uvr timeout after {self.timeout.read}s") from exc
        except httpx.HTTPStatusError as exc:
            body = ""
            try:
                body = exc.response.text[:300]
            except Exception:
                body = ""
            raise UvrError(f"uvr http {exc.response.status_code}: {body}") from exc
        except httpx.HTTPError as exc:
            raise UvrError(f"uvr request failed: {exc}") from exc
        vocals, instrumental = parse_uvr_zip(payload, vocals_dest, instrumental_dest)
        logger.info(
            "[voice-replace][uvr] vocals=%s instrumental=%s",
            vocals,
            instrumental,
        )
        return vocals, instrumental

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


def get_uvr_driver() -> UvrDriver:
    return UvrDriver()
