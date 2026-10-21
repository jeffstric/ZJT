"""故事板全能参考：把提示词里的 @首帧图 / @尾帧图 排到参考图两端。

与画布分镜节点 placeShotFrameMentionImages 同一套规则。只改本次提交的
提示词和图片顺序，不回写 scene.video_prompt。image_mode 保持 multi_reference。
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from config.unified_config import DriverKey, TaskTypeId

# 「@首帧图片」不能命中「@首帧图」。与前端正则一致。
# 前端插入的标记带唯一短 id 后缀（@首帧图:1c88f7a9），id 仅用于前端
# 胶囊与图片对位，服务端只按首帧/尾帧语义解析；消费时整体替换不留残渣。
_MENTION_ID_SUFFIX = r"(?::[0-9a-f]{8})?"
_FIRST_MENTION_RE = re.compile(r"@首帧图" + _MENTION_ID_SUFFIX + r"(?![0-9a-f:\u4e00-\u9fff])")
_LAST_MENTION_RE = re.compile(r"@尾帧图" + _MENTION_ID_SUFFIX + r"(?![0-9a-f:\u4e00-\u9fff])")

H3_REFERENCE_MODEL_KEYS = frozenset({
    "minimax_h3_r2v",
    DriverKey.MINIMAX_H3_REFERENCE_TO_VIDEO,
})
H3_KEYFRAME_REF_MAX_IMAGES = 3

_MISSING_FIRST = "视频提示词使用了 @首帧图，请先设置视频首帧"
_MISSING_LAST = "视频提示词使用了 @尾帧图，请先设置视频尾帧"
_OVER_CAPACITY = "当前模型的参考图数量不够同时放入首帧和尾帧"


class FrameMentionError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def prompt_has_frame_mention(prompt: Any) -> bool:
    text = "" if prompt is None else str(prompt)
    return bool(_FIRST_MENTION_RE.search(text) or _LAST_MENTION_RE.search(text))


def frame_mention_flags(prompt: Any) -> Tuple[bool, bool]:
    text = "" if prompt is None else str(prompt)
    return bool(_FIRST_MENTION_RE.search(text)), bool(_LAST_MENTION_RE.search(text))


def is_h3_reference_model(*keys: Any) -> bool:
    for key in keys:
        if str(key or "") in H3_REFERENCE_MODEL_KEYS:
            return True
    return False


def should_use_h3_keyframe_ref(image_mode: Any, prompt: Any, *model_keys: Any) -> bool:
    """只有全能参考、当前是 H3 参考模型、并且点名了首帧或尾帧，才改交混合模型。"""
    return (
        str(image_mode or "") == "multi_reference"
        and is_h3_reference_model(*model_keys)
        and prompt_has_frame_mention(prompt)
    )


def h3_keyframe_ref_task_id() -> int:
    return int(TaskTypeId.MINIMAX_H3_KEYFRAME_REF_TO_VIDEO)


def url_key(url: Any) -> str:
    """同一张图的绝对地址和 /upload 路径视为同一个槽位。"""
    text = str(url or "").strip().replace("\\", "/")
    marker = "/upload/"
    index = text.find(marker)
    if index >= 0:
        return text[index:]
    return text.rstrip("/")


def read_explicit_frame_url(data: Any, key: str) -> Tuple[bool, str]:
    """请求里没有该字段时返回 (False, '')，调用方改用分镜已选资产。"""
    if not isinstance(data, dict) or key not in data:
        return False, ""
    return True, str(data.get(key) or "").strip()


def _drop_url(
    urls: Sequence[str],
    items: Sequence[Dict[str, Any]],
    target: str,
) -> Tuple[List[str], List[Dict[str, Any]]]:
    key = url_key(target)
    if not key:
        return list(urls), [dict(item) for item in items]
    kept_urls: List[str] = []
    kept_items: List[Dict[str, Any]] = []
    for index, url in enumerate(urls):
        if url_key(url) == key:
            continue
        kept_urls.append(url)
        if index < len(items):
            kept_items.append(dict(items[index]))
    return kept_urls, kept_items


def _frame_item(url: str, role: str) -> Dict[str, Any]:
    return {
        "type": role,
        "source_type": "asset",
        "name": "",
        "label": role,
        "url": url,
    }


def prepare_frame_mentions(
    prompt: Any,
    urls: Sequence[str],
    items: Sequence[Dict[str, Any]],
    *,
    image_mode: Any,
    first_url: Any = "",
    last_url: Any = "",
    max_images: Optional[int] = None,
) -> Tuple[str, List[str], List[Dict[str, Any]]]:
    """把点名的首尾帧放到参考图两端，并改写本次提交的提示词。

    没有 @ 标记时原样返回（调用方收集到的「分镜图」仍留在列表里）。
    点名首帧时，同一张图不再作为中间的「分镜图」。没被点名的帧不会新增成首帧或尾帧。
    超出 max_images 时保留两端的帧，从中间参考的尾部裁掉。
    """
    text = "" if prompt is None else str(prompt)
    urls_in = [str(url) for url in (urls or []) if str(url or "").strip()]
    items_in = [dict(item) for item in (items or []) if isinstance(item, dict)]
    if len(items_in) > len(urls_in):
        items_in = items_in[:len(urls_in)]
    while len(items_in) < len(urls_in):
        items_in.append({
            "type": "参考图",
            "source_type": "reference",
            "name": "",
            "label": "参考图",
            "url": urls_in[len(items_in)],
        })

    if str(image_mode or "") != "multi_reference":
        return text, urls_in, items_in

    wants_first, wants_last = frame_mention_flags(text)
    if not wants_first and not wants_last:
        return text, urls_in, items_in

    first = str(first_url or "").strip()
    last = str(last_url or "").strip()
    if wants_first and not first:
        raise FrameMentionError("frame_mention_missing_first", _MISSING_FIRST)
    if wants_last and not last:
        raise FrameMentionError("frame_mention_missing_last", _MISSING_LAST)

    reserved = (1 if wants_first else 0) + (1 if wants_last else 0)
    limit = int(max_images) if max_images else 0
    if limit > 0 and reserved > limit:
        raise FrameMentionError("frame_mention_over_capacity", _OVER_CAPACITY)

    middle_urls, middle_items = urls_in, items_in
    if wants_first:
        middle_urls, middle_items = _drop_url(middle_urls, middle_items, first)
    if wants_last:
        middle_urls, middle_items = _drop_url(middle_urls, middle_items, last)
    if limit > 0:
        middle_budget = max(0, limit - reserved)
        middle_urls = middle_urls[:middle_budget]
        middle_items = middle_items[:len(middle_urls)]

    out_urls: List[str] = []
    out_items: List[Dict[str, Any]] = []
    if wants_first:
        out_urls.append(first)
        out_items.append(_frame_item(first, "首帧"))
    out_urls.extend(middle_urls)
    out_items.extend(middle_items)
    if wants_last:
        out_urls.append(last)
        out_items.append(_frame_item(last, "尾帧"))

    rewritten = _FIRST_MENTION_RE.sub("图1", text) if wants_first else text
    if wants_last:
        rewritten = _LAST_MENTION_RE.sub(f"图{len(out_urls)}", rewritten)
    return rewritten, out_urls, out_items
