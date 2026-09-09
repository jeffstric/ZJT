"""SenseVoiceAsrDriver 单元测试（httpx 全部 mock）。"""
import os
import unittest
from unittest.mock import patch

import httpx

from config.constant import VoiceReplaceConstants as C
from services.voice_replace.asr_driver import (
    SenseVoiceAsrDriver,
    SenseVoiceAsrError,
    get_asr_base_url,
    parse_asr_segments_payload,
)


class FakeResponse:
    def __init__(self, payload=None, status_code=200, text="", content=b""):
        self._payload = payload if payload is not None else {}
        self.status_code = status_code
        self.text = text
        self.content = content
        self.request = httpx.Request("POST", "http://example.test/api")

    def json(self):
        if self._payload is httpx.Response:
            raise ValueError("not json")
        if isinstance(self._payload, Exception):
            raise self._payload
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


class TestParsePayload(unittest.TestCase):
    def test_parses_segments(self):
        segs = parse_asr_segments_payload(
            {
                "result": [
                    {"start": 0.42, "end": 5.6, "text": "开放时间早上9点至下午5点。"},
                    {"start": 6.0, "end": 7.1, "raw_text": "再见"},
                ],
                "count": 2,
            }
        )
        self.assertEqual(len(segs), 2)
        self.assertAlmostEqual(segs[0].start, 0.42)
        self.assertAlmostEqual(segs[0].end, 5.6)
        self.assertEqual(segs[0].text, "开放时间早上9点至下午5点。")
        self.assertEqual(segs[1].text, "再见")

    def test_skips_empty_zero_span(self):
        segs = parse_asr_segments_payload({"result": [{"start": 0, "end": 0, "text": ""}]})
        self.assertEqual(segs, [])

    def test_missing_result_raises(self):
        with self.assertRaises(SenseVoiceAsrError):
            parse_asr_segments_payload({"count": 0})

    def test_swaps_inverted_times(self):
        segs = parse_asr_segments_payload(
            {"result": [{"start": 3, "end": 1, "text": "hi"}]}
        )
        self.assertEqual(len(segs), 1)
        self.assertEqual(segs[0].start, 3)
        self.assertEqual(segs[0].end, 3)


def _env_without_asr_url():
    return {
        k: v
        for k, v in os.environ.items()
        if k not in ("SENSEVOICE_ASR_URL", "VOICE_REPLACE_ASR_URL")
    }


class TestGetAsrBaseUrl(unittest.TestCase):
    def test_env_overrides_yaml(self):
        with patch.dict(os.environ, {"SENSEVOICE_ASR_URL": "http://10.0.0.1:7861/"}):
            self.assertEqual(get_asr_base_url(), "http://10.0.0.1:7861")

    def test_yaml_overrides_constant(self):
        with patch.dict(os.environ, _env_without_asr_url(), clear=True):
            with patch(
                "services.voice_replace.asr_driver.get_config_value",
                return_value="http://yaml:9",
            ):
                self.assertEqual(get_asr_base_url(), "http://yaml:9")

    def test_default_constant(self):
        with patch.dict(os.environ, _env_without_asr_url(), clear=True):
            with patch(
                "services.voice_replace.asr_driver.get_config_value",
                return_value=None,
            ):
                self.assertEqual(get_asr_base_url(), C.ASR_BASE_URL.rstrip("/"))

    def test_missing_yaml_falls_back_to_constant(self):
        with patch.dict(os.environ, _env_without_asr_url(), clear=True):
            with patch(
                "services.voice_replace.asr_driver.get_config_value",
                side_effect=FileNotFoundError("config_dev.yml"),
            ):
                self.assertEqual(get_asr_base_url(), C.ASR_BASE_URL.rstrip("/"))


class TestSenseVoiceAsrDriver(unittest.IsolatedAsyncioTestCase):
    async def test_transcribe_bytes_posts_multipart(self):
        client = FakeClient(
            FakeResponse(
                {
                    "result": [
                        {"start": 0.42, "end": 5.6, "text": "开放时间早上9点至下午5点。"}
                    ],
                    "count": 1,
                }
            )
        )
        driver = SenseVoiceAsrDriver(base_url="http://127.0.0.1:7861", client=client)
        segs = await driver.transcribe_segments(b"RIFF....", language="zh", filename="zh.wav")
        self.assertEqual(len(segs), 1)
        self.assertEqual(segs[0].text, "开放时间早上9点至下午5点。")
        post = client.posts[0]
        self.assertEqual(post["url"], "http://127.0.0.1:7861/api/v1/asr_segments")
        self.assertEqual(post["data"]["lang"], "zh")
        self.assertEqual(post["files"]["file"][0], "zh.wav")
        self.assertEqual(post["files"]["file"][2], "audio/wav")

    async def test_http_500_raises(self):
        client = FakeClient(FakeResponse(payload={"detail": "boom"}, status_code=500, text="boom"))
        driver = SenseVoiceAsrDriver(base_url="http://asr", client=client)
        with self.assertRaises(SenseVoiceAsrError) as ctx:
            await driver.transcribe_segments(b"abc")
        self.assertIn("500", str(ctx.exception))

    async def test_timeout_raises(self):
        client = FakeClient(error=httpx.ReadTimeout("slow"))
        driver = SenseVoiceAsrDriver(base_url="http://asr", client=client)
        with self.assertRaises(SenseVoiceAsrError) as ctx:
            await driver.transcribe_segments(b"abc")
        self.assertIn("timeout", str(ctx.exception))

    async def test_empty_bytes_raises(self):
        driver = SenseVoiceAsrDriver(base_url="http://asr", client=FakeClient())
        with self.assertRaises(SenseVoiceAsrError):
            await driver.transcribe_segments(b"")

    async def test_missing_file_raises(self):
        driver = SenseVoiceAsrDriver(base_url="http://asr", client=FakeClient())
        with self.assertRaises(SenseVoiceAsrError):
            await driver.transcribe_segments("/no/such/audio.wav")

    async def test_health_ok(self):
        client = FakeClient(FakeResponse({"ok": True, "device": "cuda:0"}))
        driver = SenseVoiceAsrDriver(base_url="http://asr", client=client)
        self.assertTrue(await driver.health())
        self.assertEqual(client.gets[0]["url"], "http://asr/health")

    async def test_health_false_on_connect_error(self):
        client = FakeClient(error=httpx.ConnectError("down"))
        driver = SenseVoiceAsrDriver(base_url="http://asr", client=client)
        self.assertFalse(await driver.health())

    async def test_download_then_transcribe(self):
        client = FakeClient()

        async def get(url, timeout=None):
            client.gets.append({"url": url})
            return FakeResponse(content=b"WAVDATA")

        async def post(url, files=None, data=None, timeout=None):
            client.posts.append({"url": url, "files": files, "data": data})
            return FakeResponse({"result": [{"start": 0, "end": 1.2, "text": "你好"}]})

        client.get = get
        client.post = post
        driver = SenseVoiceAsrDriver(base_url="http://asr", client=client)
        segs = await driver.transcribe_segments("http://cdn.example/a.wav")
        self.assertEqual(segs[0].text, "你好")
        self.assertEqual(client.gets[0]["url"], "http://cdn.example/a.wav")
        self.assertEqual(client.posts[0]["files"]["file"][1], b"WAVDATA")


if __name__ == "__main__":
    unittest.main()
