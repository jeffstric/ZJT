"""Seed-VC Gradio 响应解析。"""
import unittest

from services.voice_replace.seedvc_driver import (
    extract_gradio_audio,
    parse_gradio_sse,
    rewrite_loopback_url,
)


class TestGradioParse(unittest.TestCase):
    def test_sse_complete_event(self):
        body = (
            "event: generating\n"
            "data: {\"output\": {\"data\": [null, null]}}\n\n"
            "event: complete\n"
            "data: {\"output\": {\"data\": [null, {\"path\": \"/tmp/out.wav\", \"url\": \"http://127.0.0.1:7860/gradio_api/file=/tmp/out.wav\"}]}}\n"
        )
        payload = parse_gradio_sse(body)
        audio = extract_gradio_audio(payload)
        self.assertEqual(audio["path"], "/tmp/out.wav")

    def test_prefers_non_stream_wav(self):
        payload = [
            {"path": "x/playlist.m3u8", "is_stream": True, "orig_name": "audio-stream.mp3"},
            {"path": "/tmp/audio.wav", "is_stream": False, "orig_name": "audio.wav"},
        ]
        audio = extract_gradio_audio(payload)
        self.assertEqual(audio["path"], "/tmp/audio.wav")

    def test_plain_json(self):
        payload = parse_gradio_sse('{"data": [null, {"path": "a.wav"}]}')
        self.assertEqual(extract_gradio_audio(payload)["path"], "a.wav")

    def test_rewrite_loopback(self):
        url = rewrite_loopback_url(
            "http://127.0.0.1:7860/gradio_api/file=/tmp/x.wav",
            "http://127.0.0.1:7860",
        )
        self.assertEqual(url, "http://127.0.0.1:7860/gradio_api/file=/tmp/x.wav")


if __name__ == "__main__":
    unittest.main()
