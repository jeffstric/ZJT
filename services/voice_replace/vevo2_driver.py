"""Vevo2（Amphion style-preserved VC）HTTP driver。

服务端契约：multipart POST /api/v1/convert
（source/reference 两个文件字段），返回 zip（内含 converted.wav）。
"""
from __future__ import annotations

import asyncio
import io
import logging
import os
import zipfile
from typing import Optional

import httpx

from config.config_util import get_config_value
from config.constant import VoiceReplaceConstants as C
from services.voice_replace.ffmpeg_util import normalize_wav

logger = logging.getLogger(__name__)

_convert_lock = asyncio.Lock()


class Vevo2Error(Exception):
    """Vevo2 调用失败。"""


def get_vevo2_base_url() -> str:
    env = os.environ.get("VEVO2_URL") or os.environ.get("VOICE_REPLACE_VEVO2_URL")
    if env:
        return str(env).rstrip("/")
    try:
        yaml_url = get_config_value("voice_replace", "vevo2_base_url", default=None)
    except Exception as exc:
        logger.warning("[voice-replace][vc] yaml vevo2_base_url unavailable: %s", exc)
        yaml_url = None
    if yaml_url:
        return str(yaml_url).rstrip("/")
    return C.VEVO2_BASE_URL.rstrip("/")


def extract_converted_wav(zip_bytes: bytes, dest_wav: str) -> str:
    """从结果 zip 里取出 converted.wav 写到 dest_wav。"""
    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            names = zf.namelist()
            target = next(
                (n for n in names if os.path.basename(n) == "converted.wav"), None
            )
            if not target:
                raise Vevo2Error(f"vevo2 zip has no converted.wav: {names}")
            payload = zf.read(target)
    except zipfile.BadZipFile as exc:
        raise Vevo2Error(f"vevo2 response is not a zip: {zip_bytes[:120]!r}") from exc
    os.makedirs(os.path.dirname(dest_wav) or ".", exist_ok=True)
    with open(dest_wav, "wb") as fh:
        fh.write(payload)
    return dest_wav


class Vevo2Driver:
    def __init__(
        self,
        base_url: Optional[str] = None,
        timeout: Optional[float] = None,
        client: Optional[httpx.AsyncClient] = None,
        flow_matching_steps: Optional[int] = None,
    ):
        self.base_url = (base_url or get_vevo2_base_url()).rstrip("/")
        read_timeout = float(timeout if timeout is not None else C.VEVO2_TIMEOUT)
        self.timeout = httpx.Timeout(read_timeout, connect=float(C.HTTP_CONNECT_TIMEOUT))
        self._client = client
        self.flow_matching_steps = int(
            flow_matching_steps if flow_matching_steps is not None else C.VEVO2_FM_STEPS
        )

    async def convert(
        self,
        source_wav: str,
        reference_wav: str,
        dest_wav: str,
    ) -> str:
        async with _convert_lock:
            if self._client is not None:
                return await self._convert_with(
                    self._client, source_wav, reference_wav, dest_wav
                )
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                return await self._convert_with(
                    client, source_wav, reference_wav, dest_wav
                )

    async def _convert_with(
        self,
        client: httpx.AsyncClient,
        source_wav: str,
        reference_wav: str,
        dest_wav: str,
    ) -> str:
        logger.info("[voice-replace][vc] vevo2 convert source=%s ref=%s", source_wav, reference_wav)
        try:
            with open(source_wav, "rb") as src_fh, open(reference_wav, "rb") as ref_fh:
                resp = await client.post(
                    f"{self.base_url}{C.VEVO2_CONVERT_PATH}",
                    files={
                        "source": (os.path.basename(source_wav), src_fh, "audio/wav"),
                        "reference": (os.path.basename(reference_wav), ref_fh, "audio/wav"),
                    },
                    data={
                        "use_pitch_shift": "false",
                        "flow_matching_steps": str(self.flow_matching_steps),
                    },
                )
        except httpx.TimeoutException as exc:
            raise Vevo2Error(f"vevo2 timeout after {self.timeout.read}s") from exc
        except httpx.HTTPError as exc:
            raise Vevo2Error(f"vevo2 request failed: {exc}") from exc
        if resp.status_code != 200:
            raise Vevo2Error(f"vevo2 http {resp.status_code}: {resp.text[:300]}")
        raw_path = dest_wav + ".raw.wav"
        extract_converted_wav(resp.content, raw_path)
        try:
            await normalize_wav(raw_path, dest_wav)
        finally:
            if os.path.exists(raw_path):
                os.remove(raw_path)
        if not os.path.isfile(dest_wav) or os.path.getsize(dest_wav) == 0:
            raise Vevo2Error("vevo2 produced empty audio")
        return dest_wav
