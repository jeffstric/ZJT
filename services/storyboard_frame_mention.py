"""故事板全能参考：把提示词里的 @首帧图 / @尾帧图 排到参考图两端。

与画布分镜节点 placeShotFrameMentionImages 同一套规则。只改本次提交的
提示词和图片顺序，不回写 scene.video_prompt。image_mode 保持 multi_reference。

排图（prepare_frame_mentions）与裁图（trim_reference_images_for_implementation）
是两步：先排图产出「图N是首帧/尾帧」锚点句，再按选出的实现方上限裁中间参考。
首帧参考混合实现方挂载在参考生任务下（见 docs/video/h3_keyframe_ref_as_reference_impl_design.md），
点名与否由该实现方的 validate_input_compatibility 判定兼容，不再改交隐藏任务 50。
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from config.unified_config import DriverKey
from task.pipeline_drivers.h3_prompt_optimize_util import (
    _H3_FIRST_FRAME_MARK_RE,
    _H3_FIRST_FRAME_MENTION_RE,
    _H3_LAST_FRAME_MARK_RE,
    _H3_LAST_FRAME_MENTION_RE,
)

# 「@首帧图片」不能命中「@首帧图」。与前端正则一致（正则统一维护在
# h3_prompt_optimize_util，供驱动兼容钩子 / 排图 / 裁图三处同口径消费）。
# 前端插入的标记带唯一短 id 后缀（@首帧图:1c88f7a9），id 仅用于前端
# 胶囊与图片对位，服务端只按首帧/尾帧语义解析；消费时整体替换不留残渣。
_FIRST_MENTION_RE = _H3_FIRST_FRAME_MENTION_RE
_LAST_MENTION_RE = _H3_LAST_FRAME_MENTION_RE

H3_REFERENCE_MODEL_KEYS = frozenset({
    "minimax_h3_r2v",
    DriverKey.MINIMAX_H3_REFERENCE_TO_VIDEO,
})
# 首帧参考混合实现方（minimax_h3_keyframe_ref_runninghub_v1）的图片槽上限：
# 服务端按实现方裁图时用（两端保留裁中间），与驱动 _PICTURE_NODE_IDS 槽位数一致。
H3_KEYFRAME_REF_MAX_IMAGES = 3

_MISSING_FIRST = "视频提示词使用了 @首帧图，请先设置视频首帧"
_MISSING_LAST = "视频提示词使用了 @尾帧图，请先设置视频尾帧"
_OVER_CAPACITY = "当前模型的参考图数量不够同时放入首帧和尾帧"

# 句界切分：句末标点后跟非数字（防把「0.00 秒」切成「0.」「00 秒」），
# 与 h3_prompt_optimize_util.strip_h3_silent_audio_refs 的切句口径一致。
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?。！？])(?!\d)\s*")
# 图例句：以「图K是…」开头/独立成句的说明句（K 为 1-based 序号）；
# 首尾锚点句（图K是首帧/图K是尾帧）不匹配，由序号重排统一处理。
_LEGEND_SENTENCE_RE = re.compile(r"图(\d+)是(?!首帧|尾帧)")


class FrameMentionError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def prompt_has_frame_mention(prompt: Any) -> bool:
    text = "" if prompt is None else str(prompt)
    return bool(_FIRST_MENTION_RE.search(text) or _LAST_MENTION_RE.search(text))


def prompt_has_frame_mark(prompt: Any) -> bool:
    """排图改写后是否点名首帧/尾帧（「图N是首帧/尾帧」锚点句形式）"""
    text = "" if prompt is None else str(prompt)
    return bool(_H3_FIRST_FRAME_MARK_RE.search(text) or _H3_LAST_FRAME_MARK_RE.search(text))


def frame_mention_flags(prompt: Any) -> Tuple[bool, bool]:
    text = "" if prompt is None else str(prompt)
    return bool(_FIRST_MENTION_RE.search(text)), bool(_LAST_MENTION_RE.search(text))


def frame_mark_flags(prompt: Any) -> Tuple[bool, bool]:
    """排图改写后的点名标记（图N是首帧/尾帧），供裁图与兼容探测同源判定"""
    text = "" if prompt is None else str(prompt)
    return bool(_H3_FIRST_FRAME_MARK_RE.search(text)), bool(_H3_LAST_FRAME_MARK_RE.search(text))


def effective_frame_flags(prompt: Any) -> Tuple[bool, bool]:
    """点名首/尾帧的合并判定：@token（agent 原文）或「图N」锚点句（排图产物）任一命中。

    agent 对话链路（scene_ai_chat）排图改写后的提示词不回传，最终提交原文保留
    @首帧图 token；画布/单发/批量链路提交的是改写后的锚点句。裁图按本判定
    两端保留，两种链路口径一致。
    """
    text = "" if prompt is None else str(prompt)
    first = bool(_FIRST_MENTION_RE.search(text) or _H3_FIRST_FRAME_MARK_RE.search(text))
    last = bool(_LAST_MENTION_RE.search(text) or _H3_LAST_FRAME_MARK_RE.search(text))
    return first, last


def is_h3_reference_model(*keys: Any) -> bool:
    for key in keys:
        if str(key or "") in H3_REFERENCE_MODEL_KEYS:
            return True
    return False


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
) -> Tuple[str, List[str], List[Dict[str, Any]]]:
    """排图：把点名的首尾帧放到参考图两端，并改写本次提交的提示词。

    不做上限裁剪——裁图在选出实现方之后由 trim_reference_images_for_implementation
    完成（首帧参考混合实现方裁到 3，普通参考生按任务级上限）。

    没有 @ 标记时原样返回（调用方收集到的「分镜图」仍留在列表里）。
    点名首帧时，同一张图不再作为中间的「分镜图」。没被点名的帧不会新增成首帧或尾帧。
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

    middle_urls, middle_items = urls_in, items_in
    if wants_first:
        middle_urls, middle_items = _drop_url(middle_urls, middle_items, first)
    if wants_last:
        middle_urls, middle_items = _drop_url(middle_urls, middle_items, last)

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


def _remove_dropped_legend_sentences(text: str, dropped_indexes: set) -> str:
    """删除被裁参考图的图例句（「图K是角色/场景/道具…」整句）。

    图例句由前端 placeShotFrameMentionImages / _append_reference_prompt_suffix 生成，
    格式固定「图K是…」；K 为被裁序号时整句失去对位意义，保留会误导模型。
    首尾锚点句（图K是首帧/图K是尾帧）不匹配，不受影响。
    """
    if not dropped_indexes:
        return text

    kept_sentences: List[str] = []
    for line in text.splitlines(keepends=True):
        trailing_newline = "\n" if line.endswith("\n") else ""
        body = line[:-1] if trailing_newline else line
        sentences = _SENTENCE_SPLIT_RE.split(body)
        kept = []
        for sentence in sentences:
            match = _LEGEND_SENTENCE_RE.search(sentence)
            if match and int(match.group(1)) in dropped_indexes:
                continue
            kept.append(sentence)
        merged = "".join(kept).strip()
        if merged:
            kept_sentences.append(merged + trailing_newline)
    return "".join(kept_sentences).strip()


def _renumber_frame_references(text: str, index_map: Dict[int, int]) -> str:
    """按裁剪后的新位置重排提示词里的「图K」序号（一次遍历，防链式替换）"""
    if not index_map:
        return text

    def _replace(match: "re.Match") -> str:
        old = int(match.group(1))
        new = index_map.get(old)
        return f"图{new}" if new is not None else match.group(0)

    return re.sub(r"图(\d+)", _replace, text)


def trim_reference_images_for_implementation(
    prompt: Any,
    urls: Sequence[str],
    items: Optional[Sequence[Dict[str, Any]]] = None,
    *,
    max_images: int,
) -> Tuple[str, List[str], List[Dict[str, Any]]]:
    """按实现方上限裁参考图：点名首/尾帧两端保留，从中间参考的尾部裁。

    在选出实现方之后调用（首帧参考混合实现方 max_images=3，普通参考生为任务级
    上限 9）。同时清理提示词：被裁参考图的「图K是…」图例句整句删除，保留图的
    序号重排为连续（含正文里的「图K」引用）；首尾锚点句序号保持 1 / 新长度。

    reserved（点名首+尾的个数）超过 max_images 时抛 FrameMentionError
    （frame_mention_over_capacity），调用方不得建任务。
    """
    text = "" if prompt is None else str(prompt)
    urls_in = [str(url) for url in (urls or []) if str(url or "").strip()]
    items_in = [dict(item) for item in (items or []) if isinstance(item, dict)]
    while len(items_in) < len(urls_in):
        items_in.append({
            "type": "参考图",
            "source_type": "reference",
            "name": "",
            "label": "参考图",
            "url": urls_in[len(items_in)],
        })
    items_in = items_in[:len(urls_in)]

    limit = int(max_images or 0)
    if limit <= 0 or len(urls_in) <= limit:
        return text, urls_in, items_in

    wants_first, wants_last = effective_frame_flags(text)
    if not wants_first and not wants_last:
        # 没点名（理论上首帧参考实现方不会选中）：按普通上限裁尾部，无序号语义
        return text, urls_in[:limit], items_in[:limit]

    reserved = (1 if wants_first else 0) + (1 if wants_last else 0)
    if reserved > limit:
        raise FrameMentionError("frame_mention_over_capacity", _OVER_CAPACITY)

    middle_start = 1 if wants_first else 0
    middle_end = len(urls_in) - 1 if wants_last else len(urls_in)
    middle_urls = urls_in[middle_start:middle_end]
    middle_items = items_in[middle_start:middle_end]
    budget = max(0, limit - reserved)
    kept_middle_urls = middle_urls[:budget]
    kept_middle_items = middle_items[:len(kept_middle_urls)]

    out_urls: List[str] = []
    out_items: List[Dict[str, Any]] = []
    if wants_first:
        out_urls.append(urls_in[0])
        out_items.append(items_in[0])
    out_urls.extend(kept_middle_urls)
    out_items.extend(kept_middle_items)
    if wants_last:
        out_urls.append(urls_in[-1])
        out_items.append(items_in[-1])

    # 序号重排：旧 1-based 位置 → 新位置；被裁中间图的图例句先删再重排，
    # 防止「图5是道具」删除逻辑被重排后的序号干扰。
    index_map: Dict[int, int] = {}
    dropped_indexes: set = set()
    kept_url_set = {url_key(url) for url in out_urls}
    new_pos = 0
    for old_pos, url in enumerate(urls_in):
        if url_key(url) in kept_url_set:
            new_pos += 1
            index_map[old_pos + 1] = new_pos
        else:
            dropped_indexes.add(old_pos + 1)

    rewritten = _remove_dropped_legend_sentences(text, dropped_indexes)
    rewritten = _renumber_frame_references(rewritten, index_map)
    return rewritten, out_urls, out_items
