"""UvrDriver 单元测试（httpx 全部 mock）。"""
import io
import os
import tempfile
import unittest
import zipfile
from unittest.mock import patch

import httpx

from config.constant import VoiceReplaceConstants as C
from services.voice_replace.uvr_driver import (
    UvrDriver,
    UvrError,
    get_uvr_base_url,
    parse_uvr_zip,
)


def _zip_bytes(vocals=b"VOCAL", instrumental=b"INST"):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("vocals.wav", vocals)
        if instrumental is not None:
            zf.writestr("instrumental.wav", instrumental)
    return buf.getvalue()


class FakeResponse:
    def __init__(self, content=b"", status_code=200, text="", payload=None):
        self.content = content
        self.status_code = status_code
        self.text = text
        self._payload = payload if payload is not None else {}
        self.request = httpx.Request("POST", "http://example.test/api")

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"{self.status_code}",
                request=self.request,
                response=self,
            )


class FakeClient:
    def __init__(self, response=None, error=None):
        self.response = response or FakeResponse()
        self.error = error
        self.posts = []
        self.gets = []

    async def post(self, url, files=None, data=None, timeout=None):
        self.posts.append({"url": url, "files": files, "data": data, "timeout": timeout})
        if self.error:
            raise self.error
        return self.response

    async def get(self, url, timeout=None):
        self.gets.append({"url": url, "timeout": timeout})
        if self.error:
            raise self.error
        return self.response


class TestParseUvrZip(unittest.TestCase):
    def test_writes_both_stems(self):
        with tempfile.TemporaryDirectory() as tmp:
            vocals = os.path.join(tmp, "v.wav")
            inst = os.path.join(tmp, "i.wav")
            v, i = parse_uvr_zip(_zip_bytes(), vocals, inst)
            self.assertEqual(v, vocals)
            self.assertEqual(i, inst)
            self.assertEqual(open(v, "rb").read(), b"VOCAL")
            self.assertEqual(open(i, "rb").read(), b"INST")

    def test_missing_vocals_raises(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("instrumental.wav", b"x")
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(UvrError):
                parse_uvr_zip(
                    buf.getvalue(),
                    os.path.join(tmp, "v.wav"),
                    os.path.join(tmp, "i.wav"),
                )

    def test_bad_zip_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(UvrError):
                parse_uvr_zip(b"not-a-zip", os.path.join(tmp, "v.wav"), os.path.join(tmp, "i.wav"))


def _env_without_uvr_url():
    return {
        k: v
        for k, v in os.environ.items()
        if k not in ("UVR_URL", "VOICE_REPLACE_UVR_URL")
    }


class TestGetUvrBaseUrl(unittest.TestCase):
    def test_env_overrides_yaml(self):
        with patch.dict(os.environ, {"UVR_URL": "http://10.0.0.1:7862/"}):
            self.assertEqual(get_uvr_base_url(), "http://10.0.0.1:7862")

    def test_yaml_overrides_constant(self):
        with patch.dict(os.environ, _env_without_uvr_url(), clear=True):
            with patch(
                "services.voice_replace.uvr_driver.get_config_value",
                return_value="http://yaml:9",
            ):
                self.assertEqual(get_uvr_base_url(), "http://yaml:9")

    def test_missing_yaml_falls_back_to_constant(self):
        with patch.dict(os.environ, _env_without_uvr_url(), clear=True):
            with patch(
                "services.voice_replace.uvr_driver.get_config_value",
                side_effect=FileNotFoundError("config_dev.yml"),
            ):
                self.assertEqual(get_uvr_base_url(), C.UVR_BASE_URL.rstrip("/"))


class TestUvrDriver(unittest.IsolatedAsyncioTestCase):
    async def test_separate_posts_multipart(self):
        client = FakeClient(FakeResponse(content=_zip_bytes()))
        driver = UvrDriver(base_url="http://127.0.0.1:7862", client=client)
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "source.wav")
            open(src, "wb").write(b"RIFF")
            vocals, inst = await driver.separate(
                src, os.path.join(tmp, "vocals.wav"), os.path.join(tmp, "inst.wav")
            )
        self.assertTrue(vocals.endswith("vocals.wav"))
        self.assertTrue(inst.endswith("inst.wav"))
        post = client.posts[0]
        self.assertEqual(post["url"], "http://127.0.0.1:7862/api/v1/uvr")
        self.assertEqual(post["files"]["file"][0], "source.wav")

    async def test_http_500_raises(self):
        client = FakeClient(FakeResponse(status_code=500, text="boom"))
        driver = UvrDriver(base_url="http://uvr", client=client)
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "s.wav")
            open(src, "wb").write(b"x")
            with self.assertRaises(UvrError) as ctx:
                await driver.separate(src, os.path.join(tmp, "v.wav"), os.path.join(tmp, "i.wav"))
        self.assertIn("500", str(ctx.exception))

    async def test_timeout_raises(self):
        client = FakeClient(error=httpx.ReadTimeout("slow"))
        driver = UvrDriver(base_url="http://uvr", client=client)
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "s.wav")
            open(src, "wb").write(b"x")
            with self.assertRaises(UvrError) as ctx:
                await driver.separate(src, os.path.join(tmp, "v.wav"), os.path.join(tmp, "i.wav"))
        self.assertIn("timeout", str(ctx.exception))

    async def test_missing_file_raises(self):
        driver = UvrDriver(base_url="http://uvr", client=FakeClient())
        with self.assertRaises(UvrError):
            await driver.separate("/no/such.wav", "/tmp/v.wav", "/tmp/i.wav")

    async def test_health_ok(self):
        client = FakeClient(FakeResponse(payload={"ok": True, "device": "cuda:0"}))
        driver = UvrDriver(base_url="http://uvr", client=client)
        self.assertTrue(await driver.health())
        self.assertEqual(client.gets[0]["url"], "http://uvr/health")


if __name__ == "__main__":
    unittest.main()
