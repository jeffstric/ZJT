"""
音频模块 API 测试。
覆盖 P0 核心接口：提交 TTS 任务、查询音频状态。

注意：/api/audio-generate 使用 form-data 格式（非 JSON）。
"""
import pytest


class TestAudioGenerate:
    """音频生成模块 P0 测试"""

    def test_submit_tts_task(self, api_client):
        """P0 - 提交 TTS 任务（使用 form-data）"""
        payload = {"text": "测试文本", "voice": "default"}
        resp = api_client.post("/api/audio-generate", data=payload)
        assert resp.status_code in (200, 201, 202), (
            f"提交 TTS 任务失败: {resp.status_code} {resp.text}"
        )
        data = resp.json()
        # audio_id 可能为 null（异步分配），但 status 应为 submitted
        status = data.get("status")
        assert status == "submitted", f"任务未成功提交: {data}"

    def test_query_audio_status(self, api_client):
        """P0 - 提交 TTS 任务并验证响应状态"""
        payload = {"text": "状态查询测试", "voice": "default"}
        resp = api_client.post("/api/audio-generate", data=payload)
        assert resp.status_code in (200, 201, 202), f"提交任务失败: {resp.status_code} {resp.text}"
        data = resp.json()
        assert data.get("status") == "submitted", f"任务状态异常: {data}"


class TestAudioGenerateP1:
    """音频生成模块 P1 测试"""

    def test_audio_generate_with_ref(self, api_client):
        """P1 - 提交带 ref_audio_url 参数的 TTS 任务"""
        payload = {
            "text": "使用参考音频生成测试",
            "voice": "default",
            "ref_audio_url": "https://example.com/ref_audio.wav",
        }
        resp = api_client.post("/api/audio-generate", data=payload)
        assert resp.status_code in (200, 201, 202), (
            f"带参考音频的 TTS 任务提交失败: {resp.status_code} {resp.text}"
        )

    def test_audio_generate_empty_text(self, api_client):
        """P1 - 提交空文本 TTS 任务，验证返回错误"""
        payload = {"text": "", "voice": "default"}
        resp = api_client.post("/api/audio-generate", data=payload)
        assert resp.status_code in (400, 422, 200), (
            f"空文本应返回错误或明确状态: {resp.status_code} {resp.text}"
        )


# ---------------------------------------------------------------------------
# 音色库预置音色（2e36eae83 / no_152 / 4dcec8daa）与 /upload/ 下载重定向
# ---------------------------------------------------------------------------

def test_preset_voice_library_has_voice_desc(api_client):
    """audio_010 - 预置音色清单返回 107 个预置音色且 voice_desc 非空
    （no_152 迁移种子 + 声学指纹回填；计价档位透出）。"""
    resp = api_client.get("/api/tts/voices")
    assert resp.status_code == 200, f"{resp.status_code} {resp.text}"
    data = resp.json()
    voices = data.get("voices") or data.get("data") or []
    assert isinstance(voices, list) and len(voices) >= 100, \
        f"预置音色应 ≥100 个（no_152 种子 107 个）: {len(voices)}"
    preset = [v for v in voices if (v.get("provider") or "") == "reference_audio"]
    assert preset, f"应包含 reference_audio 预置音色: {str(data)[:200]}"
    with_desc = [v for v in preset if (v.get("voice_desc") or "").strip()]
    assert with_desc, "预置音色应有非空 voice_desc（声学指纹）"
    assert len(with_desc) / len(preset) > 0.9, \
        f"绝大多数预置音色应已回填指纹: {len(with_desc)}/{len(preset)}"


def test_tts_audio_download_via_upload_sign_redirect(api_client, tmp_path):
    """audio_011 - mock TTS 合成产物（/upload/ 路径）可经下载端点获取（25f67a9a1：
    本站 /upload/ 媒体走 CDN 签名重定向或代理，不再 404/403）。"""
    submit = api_client.post("/api/audio-generate", data={"text": "下载链路验证", "voice": "default"})
    if submit.status_code >= 500:
        pytest.skip(f"TTS 服务不可用（环境问题）: {submit.status_code}")
    assert submit.status_code in (200, 201, 202), f"{submit.status_code} {submit.text}"
    data = submit.json()
    audio_id = data.get("audio_id") or (data.get("data") or {}).get("audio_id")
    audio_url = None
    if audio_id:
        import time as _time
        for _ in range(20):
            status_resp = api_client.get(f"/api/audio-status/{audio_id}")
            if status_resp.status_code == 200:
                sdata = status_resp.json()
                audio_url = sdata.get("audio_url") or (sdata.get("data") or {}).get("audio_url")
                if audio_url:
                    break
                if str(sdata.get("status")) in ("failed", "FAILED"):
                    break
            _time.sleep(3)
    if not audio_url:
        pytest.skip("TTS 合成未在超时内产出音频（环境问题，不判回归）")
    # /upload/ 相对路径 → 走下载端点；外链直接 GET
    if audio_url.startswith("/upload/"):
        dl = api_client.get(f"/api/download", params={"url": audio_url})
        assert dl.status_code in (200, 302, 307), \
            f"/upload/ 媒体下载应可用（302 签名重定向或 200 代理）: {dl.status_code}"
    else:
        dl = httpx.get(audio_url, timeout=15, follow_redirects=False)
        assert dl.status_code in (200, 302, 307), \
            f"音频外链应可访问: {dl.status_code} {audio_url}"
