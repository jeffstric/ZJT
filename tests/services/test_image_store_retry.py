"""image_store 单图下载重试与落盘隔离测试（分支 review P1/P2 回归）。

P1（重试失效实证）：原实现以"last_error 是否为空"判定成败，第一次失败后即使
第二次重试成功，last_error 仍残留首次异常导致照常 raise——b008c3c8 的单图
重试机制完全无效。修复后以 response 是否拿到判定。

P2（红线 1）：落盘+媒体映射注册（同步 DB 读写/盘 IO）须隔离在 to_thread 的
_persist_image 中执行——测试通过 monkeypatch _persist_image 验证调用链，
不在测试环境触发真实写库。
"""
import asyncio

import pytest

from services.article_fetch import image_store
from services.article_fetch.image_store import download_and_store_image
from services.article_fetch.models import ArticleFetchUpstreamError


class _FakeResponse:
    def __init__(self, status_code=200, content=b"x" * 16, content_type="image/jpeg"):
        self.status_code = status_code
        self.content = content
        self.headers = {"Content-Type": content_type}


class _FakeSession:
    """按脚本顺序返回响应的假 AsyncSession，记录每次请求头。"""

    def __init__(self, script):
        self._script = list(script)
        self.captured_headers = []

    async def get(self, url, headers=None, impersonate=None):
        self.captured_headers.append(dict(headers or {}))
        item = self._script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


@pytest.fixture(autouse=True)
def _no_persist(monkeypatch, tmp_path):
    """隔离落盘与映射注册（同步 DB/盘 IO 已抽到 _persist_image，测试替换之）。"""
    calls = {"n": 0}
    monkeypatch.setattr(
        image_store, "_persist_image",
        lambda content, ext, user_id: calls.__setitem__("n", calls["n"] + 1) or "upload/marketing_fetched/20260929/test.jpg",
    )
    return calls


def test_retry_succeeds_after_first_failure(_no_persist):
    """P1 回归：第一次 503、第二次 200 → 必须成功，不得残留首次异常照常 raise。"""
    session = _FakeSession([
        _FakeResponse(status_code=503),
        _FakeResponse(status_code=200),
    ])

    image = asyncio.run(download_and_store_image(session, "https://rednotecdn.example/a.jpg", 0))

    assert image.url == "/upload/marketing_fetched/20260929/test.jpg"
    assert _no_persist["n"] == 1


def test_retry_exhausted_raises(_no_persist):
    session = _FakeSession([
        _FakeResponse(status_code=503),
        _FakeResponse(status_code=502),
    ])

    with pytest.raises(ArticleFetchUpstreamError, match="502"):
        asyncio.run(download_and_store_image(session, "https://rednotecdn.example/a.jpg", 0))
    assert _no_persist["n"] == 0


def test_first_success_no_retry(_no_persist):
    session = _FakeSession([_FakeResponse(status_code=200)])

    image = asyncio.run(download_and_store_image(session, "https://img.example/a.png", 3, user_id=55))

    assert image.index == 3 and image.original_url.endswith("a.png")
    assert len(session.captured_headers) == 1  # 未重试


def test_wechat_image_gets_referer(_no_persist):
    """微信图片域必须带 Referer（防盗链保险）。"""
    session = _FakeSession([_FakeResponse(status_code=200)])

    asyncio.run(download_and_store_image(session, "https://mmbiz.qpic.cn/mmbiz_jpg/abc.jpeg", 0))

    assert session.captured_headers[0].get("Referer") == "https://mp.weixin.qq.com/"


def test_referer_not_triggered_by_query_substring(_no_persist):
    """域名头按主机名后缀匹配：query 参数里出现域名子串不得误触发 Referer。"""
    session = _FakeSession([_FakeResponse(status_code=200)])

    asyncio.run(download_and_store_image(
        session, "https://cdn.example/a.jpg?from=mmbiz.qpic.cn", 0))

    assert "Referer" not in session.captured_headers[0]
