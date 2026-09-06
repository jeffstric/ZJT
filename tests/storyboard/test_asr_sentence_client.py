"""ASR 句级客户端单元测试（mock 网络层，不发真实请求）。"""
import json
from unittest import mock

import pytest

import services.asr_sentence_client as client
from services.asr_sentence_client import transcribe_sentences


def _fake_urlopen(payload, status_ok=True):
    body = json.dumps(payload).encode("utf-8")

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return body

    return lambda req, timeout: _Resp()


def test_missing_file_returns_empty(tmp_path):
    assert transcribe_sentences(str(tmp_path / "nope.wav")) == []
    assert transcribe_sentences("") == []


def test_disabled_config_returns_empty(tmp_path):
    wav = tmp_path / "a.wav"
    wav.write_bytes(b"RIFF")
    with mock.patch.object(client, "is_asr_enabled", return_value=False):
        assert transcribe_sentences(str(wav)) == []


def test_success_parses_sentences(tmp_path):
    wav = tmp_path / "a.wav"
    wav.write_bytes(b"RIFF")
    payload = {"result": [
        {"start": 1.0, "end": 3.5, "text": "你好。"},
        {"start": 0.0, "end": 0.8, "text": "嗯。"},
        {"start": "bad", "end": 2.0, "text": "跳过"},
        {"start": 4.0, "end": 4.0, "text": "零时长跳过"},
    ], "count": 4}
    with mock.patch.object(client, "is_asr_enabled", return_value=True), \
         mock.patch.object(client, "get_asr_api_url", return_value="http://asr:7861"), \
         mock.patch.object(client, "urlopen", _fake_urlopen(payload)):
        out = transcribe_sentences(str(wav), timeout=5)
    # 过滤非法项并按 start 升序
    assert [s["start"] for s in out] == [0.0, 1.0]
    assert out[0]["text"] == "嗯。"
    assert out[1]["text"] == "你好。"


def test_request_failure_returns_empty(tmp_path):
    wav = tmp_path / "a.wav"
    wav.write_bytes(b"RIFF")

    def _boom(req, timeout):
        raise OSError("connection refused")

    with mock.patch.object(client, "is_asr_enabled", return_value=True), \
         mock.patch.object(client, "get_asr_api_url", return_value="http://asr:7861"), \
         mock.patch.object(client, "urlopen", _boom):
        assert transcribe_sentences(str(wav), timeout=5) == []
