# -*- coding: utf-8 -*-
"""TikHub 信息采集供应商验证脚本（需真实 API Key）。

用法：
    comfyui_env=prod TIKHUB_API_KEY=你的key python scripts/verify_tikhub_provider.py

依次验证（每步 ~$0.01，总计约 $0.03）：
  1. 公众号文章详情（fetch_article_detail_h5，含受限文章兜底路径）
  2. 公众号精选评论（fetch_article_comments，你提供的实测接口）
  3. 小红书笔记详情（get_image_note_detail / get_video_note_detail）
"""

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

WECHAT_URL = "https://mp.weixin.qq.com/s/ofy9nOEcDVYcZvwrZeA3zg"          # 普通文章
WECHAT_BLOCKED_URL = "https://mp.weixin.qq.com/s/pgP0Y3irfGMmhfct0UuxpQ"  # 受限文章（仅微信内查看）
# 小红书：乌灵睡眠王的图文笔记（2026-09-28 TikHub 实测通过，note_id=6a1f827a0000000022026118）
XHS_NOTE_URL = "https://www.xiaohongshu.com/discovery/item/6a1f827a0000000022026118"


async def main():
    from services.article_fetch.providers.tikhub import TikHubClient, get_tikhub_api_key

    api_key = get_tikhub_api_key()
    if not api_key:
        print("[FAIL] 未检测到 API Key（环境变量 TIKHUB_API_KEY 或配置 article_fetch.tikhub_api_key）")
        return 1
    print("[OK] API Key 已加载（尾号 ...%s）" % api_key[-4:])
    client = TikHubClient(api_key=api_key)

    # 1. 公众号详情（原始响应打印，便于核对字段映射）
    print("\n=== 1. 公众号文章详情（fetch_article_detail_h5）===")
    data = await client.fetch_wechat_article_raw(WECHAT_URL)
    print("响应顶层键:", list(data.keys())[:15])
    print(json.dumps(data, ensure_ascii=False, default=str)[:600])
    from services.article_fetch.providers.tikhub import parse_wechat_article

    parsed = parse_wechat_article(data, WECHAT_URL)
    print("解析 -> title=%r author=%r chars=%d images=%d" % (
        parsed["title"][:30], parsed["author"], len(parsed["text"]), len(parsed["image_urls"])))

    # 2. 受限文章（h5 通道成功率验证）
    print("\n=== 2. 受限文章（仅微信内查看）是否可抓 ===")
    try:
        data2 = await client.fetch_wechat_article_raw(WECHAT_BLOCKED_URL)
        parsed2 = parse_wechat_article(data2, WECHAT_BLOCKED_URL)
        print("[OK] 受限文章可抓: title=%r chars=%d" % (parsed2["title"][:30], len(parsed2["text"])))
    except Exception as e:
        print("[受限文章不可抓] %s（该结论用于确定 auto 兜底的实际边界）" % str(e)[:100])

    # 3. 评论
    print("\n=== 3. 公众号精选评论（fetch_article_comments）===")
    comments = await client.fetch_wechat_comments(WECHAT_URL, top_n=5)
    for c in comments[:5]:
        print("  %s（赞%d）: %s" % (c.nick_name, c.like_num, c.content[:40]))
    print("[OK] 共取到 %d 条评论" % len(comments))

    # 4. 小红书（note_id 优先；短链 xhslink.com 走 share_text 由供应商解析）
    print("\n=== 4. 小红书笔记详情（get_image_note_detail）===")
    try:
        from services.article_fetch.xhs_fetcher import _extract_note_id

        note_id = _extract_note_id(XHS_NOTE_URL) or ""
        raw = await client.fetch_xhs_note_raw(note_id=note_id, share_text="" if note_id else XHS_NOTE_URL)
        from services.article_fetch.providers.tikhub import parse_xhs_note

        parsed3 = parse_xhs_note(raw, XHS_NOTE_URL)
        print("解析 -> title=%r author=%r chars=%d images=%d" % (
            parsed3["title"][:30], parsed3["author"], len(parsed3["text"]), len(parsed3["image_urls"])))
        print("小红书短链 note_id 提取（应为 None 走 share_text）:", _extract_note_id("http://xhslink.com/o/8GqargIxrko"))
    except Exception as e:
        print("[小红书失败] %s（可能分享链接过期/风控，换新分享链接重试）" % str(e)[:120])

    print("\n验证完成。若 1/3/4 解析字段为空但响应有数据，把上面打印的响应键发给开发者调整 parse 映射。")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
