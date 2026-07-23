"""
Script split planner - 纯函数：锚点化、分段计划校验。

见 docs/script/script_parser_incremental_split_design.md §6。
本模块不依赖 DB / LLM，所有函数纯函数化，便于单元测试。
"""
from typing import List, Dict, Any, Tuple
import hashlib
import re

from config.constant import ScriptSplitConstants

# ---- 锚点化 ----

# 场景/幕标记（复用 script_parser.py 的标记识别思路，但不导入以避免循环依赖）
_SCENE_MARKER_RE = re.compile(r'^#{1,3}\s*(?:场景|Scene)\s*[\d一二三四五六七八九十]', re.IGNORECASE)
_ACT_MARKER_RE = re.compile(r'^#{1,3}\s*(?:幕|Act)\s*[\d一二三四五六七八九十]', re.IGNORECASE)


def anchorize_script(script_content: str) -> List[Dict[str, Any]]:
    """对原始剧本建立稳定锚点。

    锚点优先用自然段（空行分隔的块）；若单段过长，再按场景/幕标记或换行细化。
    锚点化绝不改变原文内容或顺序。每个 block 记录行号范围、内容 sha256 和原文。

    见设计文档 §6.1。
    """
    if not script_content:
        return []

    lines = script_content.splitlines()
    blocks: List[Dict[str, Any]] = []
    current: List[str] = []
    start_line = 1

    def _flush(end_line: int):
        nonlocal current
        if not current:
            return
        content = "\n".join(current).rstrip()
        if not content:
            current = []
            return
        block_id = f"block_{len(blocks) + 1:04d}"
        blocks.append({
            "block_id": block_id,
            "start_line": start_line,
            "end_line": end_line,
            "content_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
            "content": content,
        })
        current = []

    # 按空行切自然段；同时尊重场景/幕标记作为强制边界
    for i, line in enumerate(lines, start=1):
        is_marker = bool(_SCENE_MARKER_RE.match(line.strip()) or _ACT_MARKER_RE.match(line.strip()))
        if is_marker and current:
            # 标记行开启新段，先把已积累的冲掉
            _flush(i - 1)
            start_line = i
            current.append(line)
            continue
        if line.strip() == "":
            # 空行：自然段边界
            _flush(i - 1)
            start_line = i + 1
            continue
        current.append(line)
    _flush(len(lines))

    # 兜底：整个剧本无空行且无标记 → 整篇作为一个 block
    if not blocks and script_content.strip():
        content = script_content.rstrip()
        blocks.append({
            "block_id": "block_0001",
            "start_line": 1,
            "end_line": len(lines),
            "content_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
            "content": content,
        })
    return blocks


# ---- 分段计划校验 ----

def validate_segment_plan(
    plan: Dict[str, Any],
    anchors: List[Dict[str, Any]],
) -> Tuple[bool, List[Dict[str, Any]]]:
    """校验模型返回的分段计划。

    见设计文档 §6.4。只验证、不替模型重新分段：
    1. segment_id 唯一且顺序稳定。
    2. 所有 block_id 来自原始锚点集合。
    3. 每个锚点恰好出现一次。
    4. 分段顺序与原文一致。
    5. 单个分段的 block_id 连续，不跨未包含文本。
    6. 不允许空分段。

    Returns:
        (ok, errors): ok=True 时 errors 为空。
    """
    errors: List[Dict[str, Any]] = []
    if not isinstance(plan, dict):
        return False, [{"code": "plan_not_dict", "message": "分段计划不是合法 JSON 对象"}]

    segments = plan.get("segments")
    if not isinstance(segments, list) or not segments:
        return False, [{"code": "plan_no_segments", "message": "分段计划缺少 segments 数组"}]

    valid_block_ids = [b["block_id"] for b in anchors]
    block_order = {bid: idx for idx, bid in enumerate(valid_block_ids)}
    anchor_set = set(valid_block_ids)

    seen_segment_ids = set()
    seen_block_ids = set()
    prev_max_order = -1

    for i, seg in enumerate(segments):
        if not isinstance(seg, dict):
            errors.append({"code": "segment_not_dict", "segment_index": i,
                           "message": f"第 {i+1} 段不是对象"})
            continue

        seg_id = seg.get("segment_id")
        if not seg_id:
            errors.append({"code": "segment_missing_id", "segment_index": i,
                           "message": f"第 {i+1} 段缺少 segment_id"})
        elif seg_id in seen_segment_ids:
            errors.append({"code": "segment_id_duplicate", "segment_index": i,
                           "segment_id": seg_id, "message": f"segment_id 重复: {seg_id}"})
        else:
            seen_segment_ids.add(seg_id)

        block_ids = seg.get("block_ids")
        if not isinstance(block_ids, list) or not block_ids:
            errors.append({"code": "segment_empty", "segment_index": i,
                           "segment_id": seg_id, "message": "分段为空或缺少 block_ids"})
            continue

        # 校验 block_id 来源合法性 + 连续性 + 顺序
        orders = []
        for bid in block_ids:
            if bid not in anchor_set:
                errors.append({"code": "block_id_unknown", "segment_index": i,
                               "segment_id": seg_id, "block_id": bid,
                               "message": f"block_id 不在原始锚点集合: {bid}"})
                continue
            if bid in seen_block_ids:
                errors.append({"code": "block_id_duplicate", "segment_index": i,
                               "segment_id": seg_id, "block_id": bid,
                               "message": f"block_id 被多段重复包含: {bid}"})
                continue
            seen_block_ids.add(bid)
            orders.append(block_order[bid])

        # 连续性：本段 block 的原文顺序必须递增
        if orders and orders != sorted(orders):
            errors.append({"code": "segment_block_disorder", "segment_index": i,
                           "segment_id": seg_id, "message": "段内 block_id 顺序与原文不一致"})

        # 跨段顺序：本段最小序号必须 > 上一段最大序号
        if orders:
            seg_min = min(orders)
            seg_max = max(orders)
            if seg_min <= prev_max_order:
                errors.append({"code": "segment_overlap", "segment_index": i,
                               "segment_id": seg_id,
                               "message": f"分段与前一区间重叠或乱序"})
            prev_max_order = max(prev_max_order, seg_max)

    # 完整覆盖
    missing = anchor_set - seen_block_ids
    if missing:
        errors.append({"code": "block_not_covered", "block_ids": sorted(missing),
                       "message": f"分段未覆盖全部锚点，缺少 {len(missing)} 个 block"})

    return (len(errors) == 0), errors


def split_text_at_natural_boundaries(text: str, max_chars: int) -> List[str]:
    """在不改变字符顺序的前提下，把超长单 block 切到指定上限内。"""
    if max_chars <= 0:
        raise ValueError("max_chars must be positive")
    if len(text) <= max_chars:
        return [text]

    parts: List[str] = []
    offset = 0
    punctuation_re = re.compile(r"[。！？!?；;]")
    while len(text) - offset > max_chars:
        window = text[offset:offset + max_chars]
        cut = window.rfind("\n\n")
        if cut >= 0:
            cut += 2
        else:
            cut = window.rfind("\n")
            if cut >= 0:
                cut += 1
            else:
                matches = list(punctuation_re.finditer(window))
                cut = matches[-1].end() if matches else max_chars
        if cut <= 0:
            cut = max_chars
        parts.append(text[offset:offset + cut])
        offset += cut
    if offset < len(text):
        parts.append(text[offset:])
    return parts


def _segment_record(
    segment_index: int,
    segment_id: str,
    block_ids: List[str],
    content: str,
) -> Dict[str, Any]:
    return {
        "segment_index": segment_index,
        "segment_id": segment_id,
        "source_block_ids": list(block_ids),
        "source_content": content,
        "source_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest() if content else "",
    }


def plan_to_segments(plan: Dict[str, Any], anchors: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """将已校验的计划展开为段记录（按原文顺序）。

    每段包含：segment_index, segment_id, source_block_ids, source_content, source_sha256。
    """
    anchor_map = {b["block_id"]: b for b in anchors}
    result: List[Dict[str, Any]] = []
    segments = plan.get("segments") or []
    max_chars = ScriptSplitConstants.SEGMENT_MAX_SOURCE_CHARS
    for seg_position, seg in enumerate(segments):
        block_ids = seg.get("block_ids") or []
        base_segment_id = seg.get("segment_id", f"seg_{seg_position + 1:04d}")
        groups: List[Tuple[List[str], str]] = []
        current_ids: List[str] = []
        current_content = ""

        def flush_current() -> None:
            nonlocal current_ids, current_content
            if current_ids:
                groups.append((current_ids, current_content))
                current_ids = []
                current_content = ""

        for bid in block_ids:
            a = anchor_map.get(bid)
            if not a:
                continue
            content = a["content"]
            if len(content) > max_chars:
                flush_current()
                for part in split_text_at_natural_boundaries(content, max_chars):
                    groups.append(([bid], part))
                continue

            candidate = content if not current_content else f"{current_content}\n\n{content}"
            if current_ids and len(candidate) > max_chars:
                flush_current()
                current_ids = [bid]
                current_content = content
            else:
                current_ids.append(bid)
                current_content = candidate
        flush_current()

        was_split = len(groups) > 1
        for part_index, (group_ids, group_content) in enumerate(groups, start=1):
            segment_id = (
                f"{base_segment_id}_part_{part_index:02d}"
                if was_split else base_segment_id
            )
            result.append(_segment_record(
                len(result) + 1,
                segment_id,
                group_ids,
                group_content,
            ))
    return result


__all__ = [
    "anchorize_script",
    "validate_segment_plan",
    "plan_to_segments",
    "split_text_at_natural_boundaries",
]
