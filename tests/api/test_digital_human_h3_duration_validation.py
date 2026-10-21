"""数字人 H3 端点时长校验防回归：单段 4-15 / 无分段超 15s 拒绝 / 分段口径不受牵连。

回归背景：c3d48902 恢复路由层 11-15s 单段（DIGITAL_HUMAN_H3_MAX_DURATION_SECONDS=15）
时，本端点单段校验漏改（仍是 4-10 口径），11-15s 口播 confirm 必被 400
「超过 10 秒的视频须提供 segment_audio」拒绝——378e56cb 修过的路由死角回归。

红线：端点校验与路由层必须共用 DIGITAL_HUMAN_H3_MAX_DURATION_SECONDS，
禁止再写死 10/15 数字。
"""
import json

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch):
    import server

    monkeypatch.setattr(
        "model.user_tokens.UserTokensModel.get_user_id_by_token",
        staticmethod(lambda token: 1 if token == "valid-token" else None),
    )
    # 放行落盘 / 算力 / DB 外部依赖，聚焦时长校验本身
    monkeypatch.setattr(server, "_save_uploaded_image", lambda f: "/upload/fake.png")
    monkeypatch.setattr(server, "_save_uploaded_audio_file", lambda f, idx: f"/upload/fake_seg{idx}.wav")
    monkeypatch.setattr(server, "CHECK_AUTH_TOKEN", False)
    monkeypatch.setattr(
        server.AIToolsModel, "create", staticmethod(lambda **kwargs: 999)
    )
    monkeypatch.setattr(server.TasksModel, "create", staticmethod(lambda **kwargs: None))
    # 分段提交会建 compose_jobs 编排单（compose_job 重构后的固定路径）
    monkeypatch.setattr(
        server.ComposeJobModel, "create", staticmethod(lambda **kwargs: 1001)
    )
    return TestClient(server.app)


def _post(client, duration, segment_durations=None):
    files = [
        ("image", ("img.png", b"\x89PNG\r\n\x1a\nfake", "image/png")),
        ("audio", ("a.wav", b"RIFFfake", "audio/wav")),
    ]
    data = {
        "text": "fixed camera digital human",
        "duration": str(duration),
        "user_id": "1",
    }
    if segment_durations:
        for i in range(len(segment_durations)):
            files.append(("segment_audio", (f"seg{i}.wav", b"RIFFseg", "audio/wav")))
        data["segment_durations"] = json.dumps(segment_durations)
    return client.post(
        "/api/digital-human-minimax-h3",
        files=files,
        data=data,
        headers={"Authorization": "Bearer valid-token", "X-User-Id": "1"},
    )


@pytest.mark.parametrize("duration", [11, 12, 13, 14, 15])
def test_single_segment_11_to_15s_accepted(client, duration):
    """路由层 ≤15s 单段（吸附 11-15 档）必须与端点单段口径一致，不再 400。"""
    resp = _post(client, duration)
    assert resp.status_code == 200, resp.text
    assert resp.json()["success"] is True


@pytest.mark.parametrize("duration", [4, 10])
def test_single_segment_4_to_10s_still_accepted(client, duration):
    resp = _post(client, duration)
    assert resp.status_code == 200, resp.text
    assert resp.json()["success"] is True


def test_single_segment_16s_without_segments_rejected(client):
    """>15s 无分段音频：必须拒绝并提示分段模式（错误信息随常量口径）。"""
    resp = _post(client, 16)
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert "15" in detail
    assert "segment_audio" in detail


def test_single_segment_below_4s_rejected(client):
    resp = _post(client, 3)
    assert resp.status_code == 400
    assert "4-15" in resp.json()["detail"]


def test_segmented_mode_within_15s_total_accepted(client):
    """显式分段（2 段 6+5=11s）：走 compose_job 编排路径放行，对外 project_id 带前缀。"""
    resp = _post(client, 11, segment_durations=[6, 5])
    assert resp.status_code == 200, resp.text
    assert resp.json()["success"] is True
    assert resp.json()["project_id"] == "compose_1001"


def test_segmented_mode_durations_must_match_total(client):
    """分段时长之和必须等于总时长（校验逻辑保留）。"""
    resp = _post(client, 12, segment_durations=[6, 5])
    assert resp.status_code == 400
    assert "须等于总时长" in resp.json()["detail"]


def _post_with_text(client, text):
    files = [
        ("image", ("img.png", b"\x89PNG\r\n\x1a\nfake", "image/png")),
        ("audio", ("a.wav", b"RIFFfake", "audio/wav")),
    ]
    return client.post(
        "/api/digital-human-minimax-h3",
        files=files,
        data={"text": text, "duration": "10", "user_id": "1"},
        headers={"Authorization": "Bearer valid-token", "X-User-Id": "1"},
    )


def test_motion_prompt_1001_to_4000_chars_accepted(client):
    """回归：H3 的 text 是锁镜头动作提示词（VL 产出可达 1300+ 字符），
    端点上限必须与客户端 H3_LOCKED_PROMPT_MAX_CHARS 一致（旧 1000 限会误拒）。"""
    from script_writer_core.digital_human_tts_tools import H3_LOCKED_PROMPT_MAX_CHARS

    assert H3_LOCKED_PROMPT_MAX_CHARS > 1000
    resp = _post_with_text(client, "x" * 1500)
    assert resp.status_code == 200, resp.text
    assert resp.json()["success"] is True


def test_motion_prompt_over_limit_rejected(client):
    from script_writer_core.digital_human_tts_tools import H3_LOCKED_PROMPT_MAX_CHARS

    resp = _post_with_text(client, "x" * (H3_LOCKED_PROMPT_MAX_CHARS + 1))
    assert resp.status_code == 400
    assert str(H3_LOCKED_PROMPT_MAX_CHARS) in resp.json()["detail"]
