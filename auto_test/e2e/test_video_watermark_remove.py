"""
视频去水印 API 测试（2026-09 新增功能：POST /api/video-watermark-remove，
MiniMax H3 720P，时长 4-10 秒 / 帧率 1-120，server.py:4577）。

仅覆盖提交前的鉴权与参数校验（确定性路径）。真实提交需外部 RunningHub 与
外部算力平台（本环境拒收本地 token，与 /api/parse-script 400 同源），不覆盖。
"""
import httpx
import pytest

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.video_watermark,
    pytest.mark.p1,
]

URL = "/api/video-watermark-remove"


def _post_no_auth(base_url, **fields) -> httpx.Response:
    data = {"video_url": "http://127.0.0.1/none.mp4"}
    data.update(fields)
    return httpx.post(f"{base_url}{URL}", data=data, timeout=30)


def _detail(resp: httpx.Response) -> str:
    try:
        return resp.json().get("detail", "")
    except ValueError:
        return resp.text


def test_requires_login(base_url):
    """wm_001 - 未登录提交 401"""
    resp = _post_no_auth(base_url)
    assert resp.status_code == 401
    assert resp.json().get("error_code") == "missing_auth_token"


def test_invalid_token(base_url):
    """wm_002 - 无效 token 提交 401"""
    resp = httpx.post(
        f"{base_url}{URL}",
        data={"video_url": "http://127.0.0.1/none.mp4"},
        headers={"Authorization": "Bearer invalid-token-xyz"},
        timeout=30,
    )
    assert resp.status_code == 401
    assert resp.json().get("error_code") == "invalid_auth_token"


def test_user_id_mismatch(api_client):
    """wm_003 - Form user_id 与登录身份不一致 400"""
    resp = api_client.post(
        URL, data={"video_url": "http://127.0.0.1/none.mp4", "user_id": "999999999"}
    )
    assert resp.status_code == 400
    assert "用户ID不匹配" in _detail(resp)


def test_invalid_duration(api_client):
    """wm_004 - 时长超出 4-10 秒 400"""
    for bad in ("3", "11"):
        resp = api_client.post(URL, data={"duration_seconds": bad})
        assert resp.status_code == 400, f"duration={bad} 应 400: {resp.status_code} {resp.text}"
        assert "视频时长仅支持" in _detail(resp), f"detail 异常: {_detail(resp)}"


def test_fps_out_of_range(api_client):
    """wm_005 - 帧率超出 1-120 400"""
    for bad in ("0", "121"):
        resp = api_client.post(URL, data={"fps": bad})
        assert resp.status_code == 400, f"fps={bad} 应 400: {resp.status_code} {resp.text}"
        assert "帧率仅支持 1-120" in _detail(resp), f"detail 异常: {_detail(resp)}"


def test_no_media(api_client):
    """wm_006 - 未提供视频文件与地址 400"""
    resp = api_client.post(URL, data={"duration_seconds": "5", "fps": "24"})
    assert resp.status_code == 400
    assert "请上传视频文件或提供视频地址" in _detail(resp)


def test_prompt_too_long(api_client):
    """wm_007 - 提示词超过 2000 字符 400"""
    resp = api_client.post(URL, data={"prompt": "a" * 2001})
    assert resp.status_code == 400
    assert "提示词不能超过 2000" in _detail(resp)
