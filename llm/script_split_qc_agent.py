"""
剧本拆分结果质检智能体。

P0：规则预检（语言、结构硬规则）+ 可选 LLM 语义复核。
输出统一 QcReport，供 generate-from-script 循环与重拆 prompt 注入使用。
"""
from __future__ import annotations

import json
import logging
import re
import asyncio
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from config.constant import ScriptSplitQcConstants

logger = logging.getLogger(__name__)

_last_log_timestamp: Optional[datetime] = None
_RULE_ONLY_SYSTEM_PROMPT_STATUS = """execution_mode=rule_only
本轮 QC 未调用 LLM，因此不存在发送给模型的 system prompt。
质检由 llm/script_split_qc_agent.py 中的确定性规则执行；实际输入与规则输出见同前缀的 JSON 日志。
"""

# 提示词侧字段（应对齐 prompt_language）
_PROMPT_FIELDS = (
    "opening_frame_description",
    "description",
    "scene_detail",
    "action",
    "mood",
    "environment_sound",
    "background_music",
    "audio_notes",
    "narrative_purpose",
)

# 视频提示词组装源字段（与 api/storyboard.py 中 video_prompt 源一致，不含首帧）
_VIDEO_PROMPT_SOURCE_FIELDS = (
    "description",
    "scene_detail",
    "action",
)

_CJK_RE = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf]")
_LATIN_RE = re.compile(r"[A-Za-z]")
_WHITESPACE_RE = re.compile(r"\s+")


@dataclass
class QcIssue:
    code: str
    severity: str  # error | warning
    message: str
    shot_ref: str = ""
    field: str = ""
    evidence: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class QcReport:
    passed: bool
    issues: List[QcIssue] = field(default_factory=list)
    summary: str = ""
    stats: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "passed": self.passed,
            "summary": self.summary,
            "stats": self.stats,
            "issues": [i.to_dict() for i in self.issues],
        }

    def format_for_prompt(self, max_items: int = 40) -> str:
        if self.passed and not self.issues:
            return "质检通过，无问题。"
        lines = [self.summary or "质检未通过，请修复下列问题："]
        for i, issue in enumerate(self.issues[:max_items], 1):
            sev = issue.severity.upper()
            ref = f" @ {issue.shot_ref}" if issue.shot_ref else ""
            fld = f" field={issue.field}" if issue.field else ""
            ev = f" | 例: {issue.evidence[:80]}" if issue.evidence else ""
            lines.append(f"{i}. [{sev}][{issue.code}]{ref}{fld}: {issue.message}{ev}")
        if len(self.issues) > max_items:
            lines.append(f"... 另有 {len(self.issues) - max_items} 条问题未列出")
        return "\n".join(lines)


@dataclass
class ScriptSplitQcLogContext:
    """一次段级 QC 的诊断日志关联信息。"""

    task_id: int
    segment_id: str
    segment_index: int
    qc_round: int
    timestamp: str
    prefix: str


def create_qc_log_context(
    task_id: int,
    segment_id: str,
    segment_index: int,
    qc_round: int,
) -> Optional[ScriptSplitQcLogContext]:
    """创建无文件 I/O 的 QC 日志上下文；关闭开关时返回 None。"""
    if not ScriptSplitQcConstants.DIAGNOSTIC_LOGGING_ENABLED:
        return None

    global _last_log_timestamp
    now = datetime.now()
    if _last_log_timestamp is not None and now <= _last_log_timestamp:
        now = _last_log_timestamp + timedelta(microseconds=1)
    _last_log_timestamp = now
    timestamp = now.strftime("%Y%m%d_%H%M%S_%f")
    safe_segment_id = re.sub(r"[^A-Za-z0-9_-]", "_", str(segment_id or "unknown"))
    prefix = (
        f"script_split_qc_task_{task_id}_segment_{segment_index}_{safe_segment_id}_"
        f"{timestamp}_round_{qc_round}"
    )
    return ScriptSplitQcLogContext(
        task_id=task_id,
        segment_id=str(segment_id or ""),
        segment_index=segment_index,
        qc_round=qc_round,
        timestamp=timestamp,
        prefix=prefix,
    )


def _write_text_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


async def _write_diagnostic_file(
    context: Optional[ScriptSplitQcLogContext],
    suffix: str,
    content: str,
) -> None:
    if context is None:
        return
    path = Path(ScriptSplitQcConstants.DIAGNOSTIC_LOG_DIR) / f"{context.prefix}_{suffix}"
    try:
        await asyncio.to_thread(_write_text_file, path, content)
    except Exception as exc:
        logger.warning("script split QC diagnostic log write failed: %s", exc)


async def _write_json_log(
    context: Optional[ScriptSplitQcLogContext],
    suffix: str,
    payload: Any,
) -> None:
    await _write_diagnostic_file(
        context,
        suffix,
        json.dumps(payload, ensure_ascii=False, indent=2),
    )


def _lang_is_zh(name: str) -> bool:
    n = (name or "").strip().lower()
    return n in ("", "中文", "chinese", "zh", "zh-cn", "zh_cn", "mandarin")


def _lang_is_en(name: str) -> bool:
    n = (name or "").strip().lower()
    return n in ("english", "en", "en-us", "en_us")


def _text_stats(text: str) -> Dict[str, float]:
    s = str(text or "")
    if not s.strip():
        return {"len": 0, "cjk": 0.0, "latin": 0.0}
    cjk = len(_CJK_RE.findall(s))
    latin = len(_LATIN_RE.findall(s))
    total = max(1, cjk + latin)
    return {"len": len(s.strip()), "cjk": cjk / total, "latin": latin / total}


def _looks_like_wrong_lang_for_zh(text: str) -> bool:
    st = _text_stats(text)
    if st["len"] < ScriptSplitQcConstants.LANG_CHECK_MIN_CHARS:
        return False
    return st["latin"] >= ScriptSplitQcConstants.LATIN_RATIO_THRESHOLD and st["cjk"] < ScriptSplitQcConstants.CJK_RATIO_MIN_FOR_ZH


def _looks_like_wrong_lang_for_en(text: str) -> bool:
    st = _text_stats(text)
    if st["len"] < ScriptSplitQcConstants.LANG_CHECK_MIN_CHARS:
        return False
    # 要求英文时出现大量中文
    return st["cjk"] >= 0.4 and st["latin"] < 0.4


def _iter_shots(parsed: Dict[str, Any]):
    for gi, group in enumerate(parsed.get("shot_groups") or []):
        gid = group.get("group_id") or f"grp_{gi}"
        for si, shot in enumerate(group.get("shots") or []):
            sid = shot.get("shot_number") or shot.get("id") or si
            yield f"{gid}/shot_{sid}", shot, group


def _shot_has_dialogue(shot: Dict[str, Any]) -> bool:
    dlg = shot.get("dialogue") or shot.get("dialogues") or []
    if isinstance(dlg, dict):
        dlg = [dlg]
    if not isinstance(dlg, list):
        return False
    for d in dlg:
        if not isinstance(d, dict):
            continue
        if str(d.get("text") or "").strip():
            return True
    return False


def _normalize_dialogue_text_for_match(text: Any) -> str:
    """规范化台词，用于检查视频提示词是否包含完整对白。"""
    s = str(text or "")
    s = _WHITESPACE_RE.sub("", s)
    for src, dst in (
        ("“", '"'),
        ("”", '"'),
        ("‘", "'"),
        ("’", "'"),
        ("「", '"'),
        ("」", '"'),
        ("『", '"'),
        ("』", '"'),
        ("…", "..."),
        ("⋯", "..."),
        ("——", "-"),
        ("—", "-"),
        ("－", "-"),
    ):
        s = s.replace(src, dst)
    return s


def _shot_video_prompt_blob(shot: Dict[str, Any]) -> str:
    """合成视频提示词源文本（description + scene_detail + action）。"""
    parts: List[str] = []
    for field in _VIDEO_PROMPT_SOURCE_FIELDS:
        val = str(shot.get(field) or "").strip()
        if val:
            parts.append(val)
    return "\n".join(parts)


def _iter_shot_dialogue_texts(shot: Dict[str, Any]) -> List[tuple]:
    """返回 [(index, text), ...]，仅含非空台词。"""
    dlg = shot.get("dialogue") or shot.get("dialogues") or []
    if isinstance(dlg, dict):
        dlg = [dlg]
    if not isinstance(dlg, list):
        return []
    result: List[tuple] = []
    for di, d in enumerate(dlg):
        if not isinstance(d, dict):
            continue
        text = str(d.get("text") or "").strip()
        if text:
            result.append((di, text))
    return result


def _character_name_index(
    parsed_data: Dict[str, Any],
    known_characters: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, str]:
    """合并任务级角色与当前段角色，建立全局 ID 到显示名称的映射。"""
    result: Dict[str, str] = {}
    # 模型本轮返回先写入，任务级已接受角色后写入并覆盖；禁止错误短名称覆盖真值。
    for character in list(parsed_data.get("characters") or []) + list(known_characters or []):
        if not isinstance(character, dict):
            continue
        character_id = str(character.get("id") or "").strip()
        name = str(character.get("name") or character.get("character_name") or "").strip()
        if character_id and name:
            result[character_id] = name.strip("【】")
    return result


def run_rule_qc(
    parsed_data: Dict[str, Any],
    *,
    script_content: str = "",
    dialogue_language: str = "",
    prompt_language: str = "",
    max_group_duration: int = 15,
    known_characters: Optional[List[Dict[str, Any]]] = None,
) -> QcReport:
    """确定性规则质检（不调用 LLM）。"""
    issues: List[QcIssue] = []
    for diagnostic in parsed_data.get("_spatial_diagnostics") or []:
        if not isinstance(diagnostic, dict):
            continue
        severity = str(diagnostic.get("severity") or "warning")
        if severity != "warning":
            continue
        code = str(diagnostic.get("code") or "").strip()
        if not code.startswith("spatial_"):
            continue
        issues.append(QcIssue(
            code=code,
            severity="warning",
            message=str(diagnostic.get("message") or code),
            shot_ref=str(diagnostic.get("shot_ref") or ""),
            field="spatial_intent",
            evidence=str(diagnostic.get("change_id") or ""),
        ))
    groups = parsed_data.get("shot_groups") or []
    if not groups:
        issues.append(QcIssue(
            code="MISSING_SHOT_GROUPS",
            severity="error",
            message="缺少 shot_groups，拆分结果不可用",
        ))
        return QcReport(passed=False, issues=issues, summary="无分镜组")

    total_shots = 0
    empty_dlg_shots = 0
    prompt_lang_zh = _lang_is_zh(prompt_language)
    prompt_lang_en = _lang_is_en(prompt_language)
    dlg_lang_zh = _lang_is_zh(dialogue_language)
    dlg_lang_en = _lang_is_en(dialogue_language)
    # 默认提示词中文（与 parser 一致）
    if not (prompt_language or "").strip():
        prompt_lang_zh = True
    if not (dialogue_language or "").strip() and not (prompt_language or "").strip():
        dlg_lang_zh = True
    character_names = _character_name_index(parsed_data, known_characters)
    short_dialogue_texts: List[str] = []

    for ref, shot, group in _iter_shots(parsed_data):
        total_shots += 1
        if not _shot_has_dialogue(shot):
            empty_dlg_shots += 1

        # 组时长
        # （在 group 级累计更准，下面 group 循环再做）

        # 空 opening frame
        ofd = str(shot.get("opening_frame_description") or "").strip()
        if len(ofd) < 8:
            issues.append(QcIssue(
                code="EMPTY_OPENING_FRAME",
                severity="error",
                shot_ref=ref,
                field="opening_frame_description",
                message="首帧描述过短或为空",
                evidence=ofd[:60],
            ))

        # difficulty
        diff = str(shot.get("difficulty") or "").strip()
        if diff and diff not in ("易", "中", "难"):
            issues.append(QcIssue(
                code="INVALID_DIFFICULTY",
                severity="warning",
                shot_ref=ref,
                field="difficulty",
                message=f"difficulty 应为 易/中/难，当前为 {diff!r}",
            ))

        # presentation must be a single visible speaking character
        presentation = str(shot.get("presentation") or "").strip().lower()
        dlg = shot.get("dialogue") or shot.get("dialogues") or []
        if isinstance(dlg, dict):
            dlg = [dlg]
        speakers = set()
        if isinstance(dlg, list):
            for d in dlg:
                if not isinstance(d, dict):
                    continue
                if not str(d.get("text") or "").strip():
                    continue
                sp = d.get("character_id") or d.get("speaker") or d.get("character") or d.get("name")
                if sp is not None and str(sp).strip():
                    speakers.add(str(sp).strip())
        if presentation == "digital_human" and len(speakers) >= 2:
            issues.append(QcIssue(
                code="MULTI_SPEAKER_DH",
                severity="error",
                shot_ref=ref,
                field="presentation",
                message="多人说话却标为 digital_human，应改为 video",
            ))
        if presentation == "digital_human" and not _shot_has_dialogue(shot):
            issues.append(QcIssue(
                code="DH_WITHOUT_DIALOGUE",
                severity="error",
                shot_ref=ref,
                field="dialogue",
                message="digital_human 镜头缺少有效对白",
            ))

        visible_character_ids = set()
        raw_visible_characters = shot.get("characters_present") or []
        if isinstance(raw_visible_characters, list):
            for character in raw_visible_characters:
                if isinstance(character, dict):
                    character = character.get("character_id") or character.get("id")
                character_id = str(character or "").strip()
                if character_id:
                    visible_character_ids.add(character_id)

        if presentation == "digital_human" and len(visible_character_ids) != 1:
            issue_code = (
                "DH_WITHOUT_VISIBLE_CHARACTER"
                if not visible_character_ids
                else "MULTI_CHARACTER_DH"
            )
            issues.append(QcIssue(
                code=issue_code,
                severity="error",
                shot_ref=ref,
                field="characters_present",
                message=(
                    "digital_human 镜头必须恰好只有一个画内人物，当前无人出镜"
                    if not visible_character_ids
                    else "多人同框镜头不支持 digital_human，应改为 video"
                ),
            ))

        if (
            presentation == "digital_human"
            and len(speakers) == 1
            and len(visible_character_ids) == 1
            and speakers.isdisjoint(visible_character_ids)
        ):
            issues.append(QcIssue(
                code="DH_SPEAKER_NOT_VISIBLE",
                severity="error",
                shot_ref=ref,
                field="presentation",
                message="digital_human 的唯一说话角色必须是唯一画内人物；画外音镜头应改为 video",
            ))

        # characters_present in opening frame
        chars = shot.get("characters_present") or []
        if isinstance(chars, list) and ofd:
            missing_names = []
            for c in chars:
                character_id = ""
                name = ""
                if isinstance(c, dict):
                    character_id = str(c.get("id") or c.get("character_id") or "").strip()
                    name = str(c.get("name") or c.get("character_name") or "").strip()
                else:
                    character_id = str(c or "").strip()
                name = (name or character_names.get(character_id) or character_id).strip("【】")
                if not name:
                    continue
                if f"【【{name}】】" not in ofd:
                    missing_names.append(
                        f"{name}（{character_id}）" if character_id and character_id != name else name
                    )
            if missing_names:
                issues.append(QcIssue(
                    code="CHAR_NOT_IN_FRAME",
                    severity="error",
                    shot_ref=ref,
                    field="opening_frame_description",
                    message=f"characters_present 中角色未在首帧描述点名: {', '.join(missing_names[:5])}",
                ))

        # 语言：提示词
        for fld in _PROMPT_FIELDS:
            val = str(shot.get(fld) or "").strip()
            if not val:
                continue
            if prompt_lang_zh and _looks_like_wrong_lang_for_zh(val):
                issues.append(QcIssue(
                    code="LANG_PROMPT_NOT_TARGET",
                    severity="error",
                    shot_ref=ref,
                    field=fld,
                    message=f"提示词字段疑似未使用要求语言（期望中文/指定 prompt 语言）",
                    evidence=val[:100],
                ))
            if prompt_lang_en and _looks_like_wrong_lang_for_en(val):
                issues.append(QcIssue(
                    code="LANG_PROMPT_NOT_TARGET",
                    severity="error",
                    shot_ref=ref,
                    field=fld,
                    message="提示词字段疑似未使用英文",
                    evidence=val[:100],
                ))

        # 语言：对话
        if isinstance(dlg, list):
            for di, d in enumerate(dlg):
                if not isinstance(d, dict):
                    continue
                t = str(d.get("text") or "").strip()
                if not t:
                    continue
                if _text_stats(t)["len"] < ScriptSplitQcConstants.LANG_CHECK_MIN_CHARS:
                    short_dialogue_texts.append(t)
                if dlg_lang_zh and _looks_like_wrong_lang_for_zh(t):
                    issues.append(QcIssue(
                        code="LANG_DIALOGUE_NOT_TARGET",
                        severity="error",
                        shot_ref=ref,
                        field=f"dialogue[{di}].text",
                        message="对话文本疑似未使用要求语言（期望中文）",
                        evidence=t[:100],
                    ))
                if dlg_lang_en and _looks_like_wrong_lang_for_en(t):
                    issues.append(QcIssue(
                        code="LANG_DIALOGUE_NOT_TARGET",
                        severity="error",
                        shot_ref=ref,
                        field=f"dialogue[{di}].text",
                        message="对话文本疑似未使用英文",
                        evidence=t[:100],
                    ))

        # 视频提示词必须包含完整对白（与组装源 description/scene_detail/action 对齐）
        dialogue_texts = _iter_shot_dialogue_texts(shot)
        if dialogue_texts:
            video_blob = _shot_video_prompt_blob(shot)
            video_norm = _normalize_dialogue_text_for_match(video_blob)
            for di, text in dialogue_texts:
                text_norm = _normalize_dialogue_text_for_match(text)
                if not text_norm:
                    continue
                if not video_norm or text_norm not in video_norm:
                    issues.append(QcIssue(
                        code="DIALOGUE_NOT_IN_VIDEO_PROMPT",
                        severity="error",
                        shot_ref=ref,
                        field=f"dialogue[{di}].text",
                        message="视频提示词（description/scene_detail/action）缺少完整台词，禁止仅用「呵斥/说着话」等概括",
                        evidence=text[:100],
                    ))

    aggregated_short_dialogue = " ".join(short_dialogue_texts).strip()
    if aggregated_short_dialogue:
        wrong_for_target = (
            (dlg_lang_zh and _looks_like_wrong_lang_for_zh(aggregated_short_dialogue))
            or (dlg_lang_en and _looks_like_wrong_lang_for_en(aggregated_short_dialogue))
        )
        if wrong_for_target:
            target_name = "中文" if dlg_lang_zh else "英语"
            issues.append(QcIssue(
                code="LANG_DIALOGUE_NOT_TARGET",
                severity="error",
                field="dialogue",
                message=f"多条短对白合并后疑似未使用要求的{target_name}",
                evidence=aggregated_short_dialogue[:100],
            ))

    # 组时长
    for gi, group in enumerate(groups):
        gid = group.get("group_id") or f"grp_{gi}"
        total = 0.0
        for shot in group.get("shots") or []:
            try:
                total += float(shot.get("duration") or 0)
            except (TypeError, ValueError):
                pass
        if max_group_duration and total > float(max_group_duration) + 0.05:
            issues.append(QcIssue(
                code="DURATION_OVER_GROUP",
                severity="error",
                shot_ref=str(gid),
                field="duration",
                message=f"镜头组总时长 {total:.1f}s 超过上限 {max_group_duration}s",
            ))

    # 对白覆盖率仅用于诊断统计，不作为质检通过条件。
    empty_ratio = (empty_dlg_shots / total_shots) if total_shots else 0.0

    errors = [i for i in issues if i.severity == "error"]
    warnings = [i for i in issues if i.severity == "warning"]
    passed = len(errors) == 0
    summary = (
        "质检通过"
        if passed
        else f"质检未通过：{len(errors)} 个错误，{len(warnings)} 个警告"
    )
    if errors:
        # 汇总 codes
        codes = {}
        for e in errors:
            codes[e.code] = codes.get(e.code, 0) + 1
        top = ", ".join(f"{k}×{v}" for k, v in list(codes.items())[:6])
        summary = f"{summary}（{top}）"

    return QcReport(
        passed=passed,
        issues=issues,
        summary=summary,
        stats={
            "total_shots": total_shots,
            "empty_dialogue_shots": empty_dlg_shots,
            "empty_dialogue_ratio": round(empty_ratio, 3),
            "error_count": len(errors),
            "warning_count": len(warnings),
        },
    )


async def run_script_split_qc(
    parsed_data: Dict[str, Any],
    *,
    script_content: str = "",
    dialogue_language: str = "",
    prompt_language: str = "",
    max_group_duration: int = 15,
    use_llm: bool = False,
    model: Optional[str] = None,
    vendor_id: Optional[int] = None,
    model_id: Optional[int] = None,
    auth_token: Optional[str] = None,
    enable_thinking: bool = False,
    thinking_effort: str = "medium",
    known_characters: Optional[List[Dict[str, Any]]] = None,
    log_context: Optional[ScriptSplitQcLogContext] = None,
) -> QcReport:
    """
    执行质检：先规则，规则通过且 use_llm 时可选 LLM 复核（P0 默认规则足够则可关 LLM）。
    """
    await _write_diagnostic_file(
        log_context,
        "01_system_prompt.txt",
        _RULE_ONLY_SYSTEM_PROMPT_STATUS,
    )
    await _write_json_log(log_context, "02_input.json", {
        "execution_mode": "rule_only",
        "use_llm_requested": bool(use_llm),
        "task_id": log_context.task_id if log_context else None,
        "segment_id": log_context.segment_id if log_context else None,
        "segment_index": log_context.segment_index if log_context else None,
        "qc_round": log_context.qc_round if log_context else None,
        "script_content": script_content,
        "parsed_data": parsed_data,
        "known_characters": known_characters or [],
        "dialogue_language": dialogue_language,
        "prompt_language": prompt_language,
        "max_group_duration": max_group_duration,
    })
    try:
        report = run_rule_qc(
            parsed_data,
            script_content=script_content,
            dialogue_language=dialogue_language,
            prompt_language=prompt_language,
            max_group_duration=max_group_duration,
            known_characters=known_characters,
        )
    except Exception as exc:
        await _write_json_log(log_context, "03_error.json", {
            "error_type": type(exc).__name__,
            "message": str(exc),
        })
        raise

    # P0：规则有 error 则不必再花 LLM；规则通过时默认不强制 LLM（省算力）
    # use_llm=True 且规则已通过时，可做轻量语义复核——P0 跳过以控成本
    if use_llm and not report.passed:
        # 可选：用 LLM 对 issues 做归纳，不改变 passed
        pass

    logger.info(
        "script_split_qc passed=%s errors=%s warnings=%s",
        report.passed,
        report.stats.get("error_count"),
        report.stats.get("warning_count"),
    )
    await _write_json_log(log_context, "03_report.json", report.to_dict())
    return report


def compact_parsed_for_feedback(
    parsed_data: Dict[str, Any],
    max_chars: int = None,
) -> str:
    """压缩上一轮拆分结果，控制注入 prompt 体积。"""
    max_chars = max_chars or ScriptSplitQcConstants.PREVIOUS_RESULT_MAX_CHARS
    compact = {
        "characters": parsed_data.get("characters") or [],
        "locations": parsed_data.get("locations") or [],
        "props": parsed_data.get("props") or [],
        "shot_groups": [],
    }
    for group in parsed_data.get("shot_groups") or []:
        g = {
            "group_id": group.get("group_id"),
            "group_name": group.get("group_name"),
            "group_type": group.get("group_type"),
            "shots": [],
        }
        for shot in group.get("shots") or []:
            s = {
                "shot_number": shot.get("shot_number"),
                "duration": shot.get("duration"),
                "shot_type": shot.get("shot_type"),
                "camera_angle": shot.get("camera_angle"),
                "presentation": shot.get("presentation"),
                "difficulty": shot.get("difficulty"),
                "location_id": shot.get("location_id"),
                "characters_present": shot.get("characters_present"),
                "opening_frame_description": shot.get("opening_frame_description"),
                "description": shot.get("description"),
                "action": shot.get("action"),
                "scene_detail": shot.get("scene_detail"),
                "dialogue": shot.get("dialogue") or shot.get("dialogues"),
                "narrative_purpose": shot.get("narrative_purpose"),
            }
            g["shots"].append(s)
        compact["shot_groups"].append(g)

    text = json.dumps(compact, ensure_ascii=False)
    if len(text) > max_chars:
        text = text[: max_chars - 20] + "\n...[truncated]"
    return text
