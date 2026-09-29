# -*- coding: utf-8 -*-
"""wechat_fetcher._attach_comments 回归测试。

评论是 best-effort 增强素材：TikHub 评论接口任何 ArticleFetchError 子类失败
都只记日志，不得阻断正文返回。
事故 2026-09-29：except 子句引用的 ArticleFetchError 基类漏 import，评论接口
一抛异常整个抓取就 NameError 判死（正文已抓到也被判失败）。
"""
import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.article_fetch.models import (  # noqa: E402
    ArticleComment,
    ArticleContent,
    ArticleFetchUpstreamError,
)
from services.article_fetch.wechat_fetcher import _attach_comments  # noqa: E402

_URL = "https://mp.weixin.qq.com/s/abc"


def _article():
    return ArticleContent(
        source_type="wechat",
        source_url=_URL,
        title="标题",
        author="公众号",
        text="正文",
        images=[],
    )


class TestAttachComments(unittest.TestCase):
    def test_comment_failure_swallowed(self):
        """评论接口抛 ArticleFetchError 子类 → 吞掉，comments 为空，不向上抛。"""
        article = _article()
        client = MagicMock()
        client.fetch_wechat_comments = AsyncMock(
            side_effect=ArticleFetchUpstreamError("信息采集供应商异常（HTTP 500）")
        )
        with patch("services.article_fetch.providers.tikhub.is_tikhub_configured", return_value=True), \
                patch("services.article_fetch.providers.tikhub.TikHubClient", return_value=client):
            asyncio.run(_attach_comments(article, _URL))
        self.assertEqual(article.comments, [])

    def test_comment_success_attached(self):
        """评论成功 → 结果挂到 article.comments。"""
        article = _article()
        client = MagicMock()
        client.fetch_wechat_comments = AsyncMock(return_value=[
            ArticleComment(nick_name="u1", content="好文", like_num=3, is_elected=True),
        ])
        with patch("services.article_fetch.providers.tikhub.is_tikhub_configured", return_value=True), \
                patch("services.article_fetch.providers.tikhub.TikHubClient", return_value=client):
            asyncio.run(_attach_comments(article, _URL))
        self.assertEqual(len(article.comments), 1)
        self.assertEqual(article.comments[0].content, "好文")


if __name__ == "__main__":
    unittest.main()
