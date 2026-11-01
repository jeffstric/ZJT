"""剧本拆分角色名称与图片/视频提示词硬契约。

角色库快照是数据库角色名称的唯一真值。校验器不调用 LLM、不访问数据库，
可在单段、合并和发布三个阶段复用。任何返回错误都带 ``_hard_gate``，调用方
不得通过普通 QC 的 ``_forced_accept`` 路径接纳。

默认（``CHARACTER_CONTRACT_STRICT_MODE = False``）为放行模式：所有不匹配项
仅记录 warning 日志并返回空列表，不阻塞剧本拆分；strict 模式恢复硬门禁。
"""
from __future__ import annotations

import logging
import re
import unicodedata
from typing import Any, Dict, Iterable, List, Optional, Tuple

from config.constant import ScriptSplitConstants
from model.character import CharacterModel

logger = logging.getLogger(__name__)


CHARACTER_CONTRACT_CONFIG_KEY = ScriptSplitConstants.CHARACTER_CONTRACT_CONFIG_KEY
CHARACTER_CONTRACT_VERSION = ScriptSplitConstants.CHARACTER_CONTRACT_VERSION

_CHARACTER_TOKEN_RE = re.compile(r"【【([^【】\r\n]+)】】")
_IMAGE_PROMPT_FIELDS = ("opening_frame_description", "scene_detail")
_VIDEO_PROMPT_FIELDS = ("description", "scene_detail", "action")
_VISUAL_PROMPT_FIELDS = tuple(dict.fromkeys(_IMAGE_PROMPT_FIELDS + _VIDEO_PROMPT_FIELDS))


def _nfc(value: Any) -> str:
    return unicodedata.normalize("NFC", str(value or ""))


def _clean_name(value: Any) -> str:
    return _nfc(value).strip()


def _controlled_alias(name: str) -> str:
    """返回项目中 ``中文名_EnglishName`` 约定的受控短别名。"""
    canonical = _clean_name(name)
    if "_" not in canonical:
        return ""
    alias = canonical.split("_", 1)[0].strip()
    return alias if alias and alias != canonical else ""


def _snapshot_rows(world_id: int) -> List[Dict[str, Any]]:
    """同步分页读取完整角色列表；异步调用方必须通过 asyncio.to_thread 包装。"""
    page = 1
    page_size = ScriptSplitConstants.CHARACTER_CONTRACT_PAGE_SIZE
    rows: List[Dict[str, Any]] = []
    while True:
        result = CharacterModel.list_by_world(
            world_id=int(world_id),
            page=page,
            page_size=page_size,
            order_by="id",
            order_direction="ASC",
        ) or {}
        batch = result.get("data") or []
        rows.extend(item for item in batch if isinstance(item, dict))
        total = int(result.get("total") or len(rows))
        if not batch or len(rows) >= total:
            break
        page += 1
    return rows


def build_character_contract_snapshot(world_id: Optional[int]) -> Dict[str, Any]:
    """构建可持久化到 ``script_split_task.request_config`` 的不可变角色快照。"""
    if world_id in (None, ""):
        return {"version": CHARACTER_CONTRACT_VERSION, "world_id": None, "characters": []}
    rows = _snapshot_rows(int(world_id))
    characters = []
    for row in rows:
        name = _clean_name(row.get("name"))
        db_id = row.get("id")
        if not name or db_id in (None, ""):
            continue
        characters.append({
            "character_db_id": int(db_id),
            "canonical_name": name,
            # 保留原提示词已有的角色识别上下文；不保存声音、图片或用户信息。
            "identity": row.get("identity") or "",
            "appearance": row.get("appearance") or "",
            "personality": row.get("personality") or "",
        })
    return {
        "version": CHARACTER_CONTRACT_VERSION,
        "world_id": int(world_id),
        "characters": characters,
    }


def contract_to_parser_characters(contract: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """把角色契约转换为 script_parser 原有数据库角色提示结构。"""
    result = []
    for item in (contract or {}).get("characters") or []:
        if not isinstance(item, dict):
            continue
        result.append({
            "id": item.get("character_db_id"),
            "name": item.get("canonical_name"),
            "identity": item.get("identity") or "",
            "appearance": item.get("appearance") or "",
            "personality": item.get("personality") or "",
        })
    return result


def _hard_error(code: str, message: str, **details: Any) -> Dict[str, Any]:
    return {
        "code": code,
        "severity": "error",
        "message": message,
        "_hard_gate": True,
        "_hard_gate_type": "character_prompt",
        **details,
    }


def _contract_indexes(contract: Optional[Dict[str, Any]]) -> Tuple[Dict[str, str], Dict[str, List[str]]]:
    by_db_id: Dict[str, str] = {}
    aliases: Dict[str, List[str]] = {}
    for item in (contract or {}).get("characters") or []:
        if not isinstance(item, dict):
            continue
        db_id = str(item.get("character_db_id") or "").strip()
        name = _clean_name(item.get("canonical_name"))
        if not db_id or not name:
            continue
        by_db_id[db_id] = name
        alias = _controlled_alias(name)
        if alias:
            aliases.setdefault(alias, []).append(name)
    return by_db_id, aliases


def _entity_map(entities: Iterable[Any]) -> Dict[str, Dict[str, Any]]:
    result: Dict[str, Dict[str, Any]] = {}
    for entity in entities:
        if not isinstance(entity, dict):
            continue
        entity_id = str(entity.get("id") or entity.get("character_id") or "").strip()
        if entity_id:
            result[entity_id] = entity
    return result


def _shot_ref(group: Dict[str, Any], shot: Dict[str, Any], group_index: int, shot_index: int) -> str:
    group_id = group.get("group_id") or group.get("id") or f"group_{group_index + 1}"
    shot_id = shot.get("shot_id") or shot.get("shot_number") or shot_index + 1
    return f"{group_id}/shot_{shot_id}"


def _extract_tokens(text: str) -> Tuple[List[str], bool]:
    tokens = [match.group(1) for match in _CHARACTER_TOKEN_RE.finditer(text)]
    remainder = _CHARACTER_TOKEN_RE.sub("", text)
    malformed = "【【" in remainder or "】】" in remainder
    return tokens, malformed


def validate_segment_character_contract(
    parsed: Dict[str, Any],
    character_contract: Optional[Dict[str, Any]],
    accepted_registry: Optional[Dict[str, Any]] = None,
    strict: Optional[bool] = None,
) -> List[Dict[str, Any]]:
    """验证角色实体名称及最终图片/视频提示词中的角色 token。

    数据库角色按 ``character_db_id`` 锁定名称；任务中新角色可首次登记，但若名称
    命中某个数据库角色的唯一受控短别名，则视为不完整名称并拒绝。

    ``strict`` 为 None 时读取 ``ScriptSplitConstants.CHARACTER_CONTRACT_STRICT_MODE``。
    非严格模式下所有不匹配项仅记录 warning 日志并返回空列表，不阻塞拆分。
    """
    if strict is None:
        strict = bool(ScriptSplitConstants.CHARACTER_CONTRACT_STRICT_MODE)

    if not isinstance(parsed, dict):
        payload_error = _hard_error("character_contract_payload_invalid", "拆分结果不是对象")
        if strict:
            return [payload_error]
        logger.warning("角色契约校验放行: %s", payload_error)
        return []

    errors: List[Dict[str, Any]] = []

    def _emit(error: Dict[str, Any]) -> None:
        if strict:
            errors.append(error)
        else:
            logger.warning("角色契约校验放行: %s", error)

    by_db_id, aliases = _contract_indexes(character_contract)
    registry_entities = _entity_map((accepted_registry or {}).get("characters") or [])
    parsed_entities = _entity_map(parsed.get("characters") or [])
    canonical_by_id: Dict[str, str] = {}

    # 已接受注册表优先于模型本轮返回，禁止 parsed_data 用短名称覆盖任务真值。
    for character_id, entity in registry_entities.items():
        name = _clean_name(entity.get("name") or entity.get("character_name"))
        if name:
            canonical_by_id[character_id] = name

    for character_id, entity in parsed_entities.items():
        actual_name = _clean_name(entity.get("name") or entity.get("character_name"))
        db_id = str(entity.get("character_db_id") or "").strip()
        expected_name = by_db_id.get(db_id) if db_id else canonical_by_id.get(character_id)

        if db_id and not expected_name:
            _emit(_hard_error(
                "character_db_id_unknown",
                f"角色 {character_id} 引用了角色契约中不存在的 character_db_id={db_id}",
                field="characters.name",
                character_id=character_id,
                character_db_id=db_id,
                actual_name=actual_name,
            ))
            continue

        if not expected_name and actual_name:
            alias_targets = aliases.get(actual_name) or []
            if len(alias_targets) == 1:
                expected_name = alias_targets[0]
                _emit(_hard_error(
                    "character_name_incomplete",
                    f"角色名称“{actual_name}”不完整，必须使用“{expected_name}”",
                    field="characters.name",
                    character_id=character_id,
                    character_db_id=db_id or None,
                    actual_name=actual_name,
                    expected_name=expected_name,
                ))
            elif len(alias_targets) > 1:
                _emit(_hard_error(
                    "character_name_alias_ambiguous",
                    f"角色短名称“{actual_name}”对应多个角色，无法确定完整名称",
                    field="characters.name",
                    character_id=character_id,
                    actual_name=actual_name,
                    expected_names=alias_targets,
                ))

        if expected_name:
            canonical_by_id[character_id] = expected_name
            if actual_name != expected_name:
                _emit(_hard_error(
                    "character_name_mismatch",
                    f"角色 {character_id} 名称必须为“{expected_name}”，实际为“{actual_name or '空'}”",
                    field="characters.name",
                    character_id=character_id,
                    character_db_id=db_id or None,
                    actual_name=actual_name,
                    expected_name=expected_name,
                ))
        elif actual_name:
            canonical_by_id[character_id] = actual_name
        else:
            _emit(_hard_error(
                "character_name_missing",
                f"角色 {character_id} 缺少名称",
                field="characters.name",
                character_id=character_id,
            ))

    allowed_names = set(by_db_id.values()) | set(canonical_by_id.values())

    for group_index, group in enumerate(parsed.get("shot_groups") or []):
        if not isinstance(group, dict):
            continue
        for shot_index, shot in enumerate(group.get("shots") or []):
            if not isinstance(shot, dict):
                continue
            ref = _shot_ref(group, shot, group_index, shot_index)
            segment_id = shot.get("_segment_id")
            field_tokens: Dict[str, List[str]] = {}
            for field in _VISUAL_PROMPT_FIELDS:
                text = _nfc(shot.get(field))
                tokens, malformed = _extract_tokens(text)
                field_tokens[field] = tokens
                if malformed:
                    _emit(_hard_error(
                        "character_token_malformed",
                        f"{ref} 的 {field} 含未闭合或嵌套错误的角色标记",
                        shot_ref=ref,
                        field=field,
                        segment_id=segment_id,
                    ))
                for token in tokens:
                    if token != token.strip() or not token.strip():
                        _emit(_hard_error(
                            "character_token_malformed",
                            f"{ref} 的 {field} 含空名称或首尾空格角色标记",
                            shot_ref=ref,
                            field=field,
                            segment_id=segment_id,
                            actual_name=token,
                        ))
                        continue
                    token_name = _nfc(token)
                    if token_name not in allowed_names:
                        alias_targets = aliases.get(token_name) or []
                        expected = alias_targets[0] if len(alias_targets) == 1 else None
                        message = (
                            f"{ref} 的 {field} 使用了不完整角色名“{token_name}”，必须使用“{expected}”"
                            if expected else
                            f"{ref} 的 {field} 使用了未登记角色名“{token_name}”"
                        )
                        _emit(_hard_error(
                            "character_prompt_name_invalid",
                            message,
                            shot_ref=ref,
                            field=field,
                            segment_id=segment_id,
                            actual_name=token_name,
                            expected_name=expected,
                        ))

            image_tokens = set(
                token
                for field in _IMAGE_PROMPT_FIELDS
                for token in (field_tokens.get(field) or [])
            )
            video_tokens = set(
                token
                for field in _VIDEO_PROMPT_FIELDS
                for token in (field_tokens.get(field) or [])
            )
            for raw_character in shot.get("characters_present") or []:
                character_id = str(
                    (raw_character.get("id") or raw_character.get("character_id"))
                    if isinstance(raw_character, dict) else raw_character or ""
                ).strip()
                expected_name = canonical_by_id.get(character_id)
                if not expected_name:
                    _emit(_hard_error(
                        "character_present_unresolvable",
                        f"{ref} 的 characters_present 角色 {character_id or '空'} 无法解析完整名称",
                        shot_ref=ref,
                        field="characters_present",
                        segment_id=segment_id,
                        character_id=character_id,
                    ))
                    continue
                if expected_name not in image_tokens:
                    _emit(_hard_error(
                        "character_missing_from_image_prompt",
                        f"{ref} 图片提示词缺少完整角色标记【【{expected_name}】】",
                        shot_ref=ref,
                        field="opening_frame_description",
                        segment_id=segment_id,
                        character_id=character_id,
                        expected_name=expected_name,
                    ))
                if expected_name not in video_tokens:
                    _emit(_hard_error(
                        "character_missing_from_video_prompt",
                        f"{ref} 视频提示词缺少完整角色标记【【{expected_name}】】",
                        shot_ref=ref,
                        field="description/scene_detail/action",
                        segment_id=segment_id,
                        character_id=character_id,
                        expected_name=expected_name,
                    ))

    if not strict:
        return []

    # 同一根因常会同时触发实体和字段错误；按稳定关键字段去重，保留精确位置。
    deduped: List[Dict[str, Any]] = []
    seen = set()
    for error in errors:
        key = (
            error.get("code"), error.get("shot_ref"), error.get("field"),
            error.get("character_id"), error.get("actual_name"), error.get("expected_name"),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(error)
    return deduped


def first_character_contract_error_message(errors: List[Dict[str, Any]]) -> str:
    first = next((error for error in errors if error.get("_hard_gate_type") == "character_prompt"), {})
    detail = str(first.get("message") or "角色图片/视频提示词不符合完整名称契约")
    return f"角色提示词硬校验失败：{detail}"


def rename_character_tokens(parsed_data: Dict[str, Any], renamed: Dict[str, str]) -> None:
    """把 shot_groups 全树文本中的【【短名】】标记原地替换为【【完整名】】。

    只动标记形式（含括号转义语义），不碰普通文本，避免误替换。
    递归覆盖 shot 的全部字段（提示词、对白 text/character_name、
    spatial_layout 的 screen_composition/description 等机位锚文本），
    使任何读取这些字段的下游链路（生图参考解析、camera_anchor）按名
    查库都能命中完整名。供合并期归一化与发布期 bootstrap 共用。
    """
    if not renamed:
        return
    token_res = [
        re.compile(r"【【(" + re.escape(short) + r")】】")
        for short in renamed
    ]

    def _rewrite(value: Any) -> Any:
        if isinstance(value, str):
            if "【【" not in value:
                return value
            for token_re in token_res:
                value = token_re.sub(
                    lambda m, full=renamed: f"【【{full[m.group(1)]}】】", value,
                )
            return value
        if isinstance(value, list):
            return [_rewrite(item) for item in value]
        if isinstance(value, dict):
            return {key: _rewrite(item) for key, item in value.items()}
        return value

    for group in parsed_data.get("shot_groups") or []:
        if not isinstance(group, dict):
            continue
        for shot in group.get("shots") or []:
            if not isinstance(shot, dict):
                continue
            for key, item in shot.items():
                shot[key] = _rewrite(item)


def normalize_characters_by_db_id(
    parsed: Dict[str, Any],
    character_contract: Optional[Dict[str, Any]],
) -> Dict[str, str]:
    """以 ``character_db_id`` 为真值，把角色名归一化为契约完整名（方案A）。

    LLM 语义匹配通常能正确回填 ``character_db_id``，但 ``characters[].name``
    与提示词【【】】标记仍可能输出简称或分隔符变体（「哈利」→「哈利波特」、
    「德拉科莉亚·马尔福」→「德拉科莉亚马尔福」），而下游生图/参考图解析
    按名精确查库（``CharacterModel.get_by_name``）会 miss。

    本函数在合并期把已锁定 db_id 的角色名强制改写为契约 ``canonical_name``，
    并同步替换 shot 标记；仅当旧名不是库内任何角色的完整名时才替换，
    避免把恰好同名的另一角色的标记误改。

    Returns:
        {旧名: 完整名} 归一化映射；空 dict 表示无需归一化。
    """
    if not isinstance(parsed, dict):
        return {}
    by_db_id, _aliases = _contract_indexes(character_contract)
    if not by_db_id:
        return {}
    canonical_names = set(by_db_id.values())

    renamed: Dict[str, str] = {}
    for character in parsed.get("characters") or []:
        if not isinstance(character, dict):
            continue
        db_id = str(character.get("character_db_id") or "").strip()
        if not db_id:
            continue  # 库外新角色：交给发布期 bootstrap 按名/别名处理
        canonical_name = by_db_id.get(db_id)
        if not canonical_name:
            continue  # db_id 未命中契约：交给 validate 告警，不猜测
        actual_name = _clean_name(
            character.get("name") or character.get("character_name"),
        )
        if actual_name == canonical_name:
            continue
        if actual_name and actual_name in canonical_names:
            # 旧名与库内另一角色完整名相同：替换标记会误伤该角色，跳过
            logger.warning(
                "角色名归一化跳过: name=%r 与库内其他角色完整名冲突 "
                "(character_db_id=%s → %r)",
                actual_name, db_id, canonical_name,
            )
            continue
        if actual_name:
            existing_target = renamed.get(actual_name)
            if existing_target is not None and existing_target != canonical_name:
                # 极罕见：同名旧名映射到不同完整名，无法确定标记替换方向
                logger.warning(
                    "角色名归一化跳过: name=%r 已映射到 %r，忽略 %r",
                    actual_name, existing_target, canonical_name,
                )
                continue
            renamed[actual_name] = canonical_name
        character["name"] = canonical_name
        if character.get("character_name"):
            character["character_name"] = canonical_name

    if renamed:
        rename_character_tokens(parsed, renamed)
        logger.info(
            "按 character_db_id 归一化角色名: %s", renamed,
        )
    return renamed


__all__ = [
    "CHARACTER_CONTRACT_CONFIG_KEY",
    "build_character_contract_snapshot",
    "contract_to_parser_characters",
    "first_character_contract_error_message",
    "normalize_characters_by_db_id",
    "rename_character_tokens",
    "validate_segment_character_contract",
]
