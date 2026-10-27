"""剧本拆分角色形象变化变体服务。

见 docs/storyboard/script_split_character_variant.md。

职责链：
1. ``sanitize_and_propagate_appearance_changes``（纯函数）：清洗 LLM 输出的
   ``shot.character_appearance_changes``（形象变化点标记），并把持续状态沿镜头
   顺序向前传播，生成 ``shot._effective_appearance_changes``。LLM 只标记变化点，
   延续由代码保证，避免跨段漏标。
2. ``ensure_character_variants``（同步函数，调用方须 asyncio.to_thread 包装）：
   发布阶段按 ``(character_db_id, label)`` 去重建计划，复用 item_type=7 角色变体
   图生图管线（基于主参考图保持五官一致，产物由 grid_image_task 后台任务写回
   角色 ``reference_images[]``）。幂等、分批推进（每轮提交一批 pending、轮询一批
   submitted）。发布**不等待**变体图终态。
3. ``collect_ready_variant_map``：输出 ``{str(db_id): {label: url}}``，由
   build_storyboard_scenes_from_parsed_script 写入每个分镜的
   ``prompt_json.reference_selections``，生图与前端变体选择弹层自动消费新形象。
4. ``collect_pending_variant_map``：输出仍未终态的 ``{str(db_id): {label, ...}}``,
   落库时写入分镜 ``prompt_json.pending_reference_selections`` 作为待回填标记。
5. ``settle_pending_character_variant_references`` /
   ``backfill_variant_reference_selections``：grid_image_task item_type=7 终态
   回调——成功写 ``{url, label}`` 并删除 pending；失败/超时/取消只删 pending，
   镜头降级用主参考图。

失败策略：单个变体生成失败/超时/角色缺主图均降级为继续使用主参考图
（status=failed/skipped），不阻塞拆分任务。
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from config.constant import ScriptSplitConstants

logger = logging.getLogger(__name__)

# shot 级有效形象变化内部字段（传播产物；发布时消费，不进入 prompt_json）
EFFECTIVE_CHANGES_FIELD = "_effective_appearance_changes"
# final_result.metadata 中持久化的变体计划 key（跨 tick 幂等恢复）
PLAN_METADATA_KEY = "character_variant_plan"
# final_result.metadata 中全部终态后写入的执行摘要 key
SUMMARY_METADATA_KEY = "character_variant_summary"
# 分镜 prompt_json 中「变体未就绪待回填」标记 key（宫格任务终态后消费）
PENDING_SELECTIONS_PROMPT_KEY = "pending_reference_selections"

# 恢复默认形象的标记约定（LLM 输出 revert=true 或 label 为这些值）
_REVERT_LABELS = {"默认", "default", "恢复默认", "原状"}

# plan 条目状态
_STATUS_PENDING = "pending"
_STATUS_SUBMITTED = "submitted"
_STATUS_READY = "ready"
_STATUS_FAILED = "failed"
_STATUS_SKIPPED = "skipped"
_ACTIVE_STATUSES = (_STATUS_PENDING, _STATUS_SUBMITTED)

# grid_image_task 终态码 → 名称（用于失败 error 文案可读，避免 grid_task_-1）
_GRID_STATUS_NAMES = {-1: "FAILED", -2: "TIMEOUT", -3: "CANCELLED", -4: "DOWNLOAD_FAILED"}


def _clean_label(raw: Any) -> str:
    """规范化变体标签：去首尾空白并截断，保证 task_key 与 reference_images 可控。"""
    label = str(raw or "").strip()
    limit = int(ScriptSplitConstants.CHARACTER_VARIANT_LABEL_MAX_LENGTH)
    if len(label) > limit:
        label = label[:limit]
    return label


def _is_revert(change: Dict[str, Any], label: str) -> bool:
    if change.get("revert") is True:
        return True
    return label in _REVERT_LABELS


def _present_character_ids(shot: Dict[str, Any]) -> set:
    """提取 characters_present 中的内部角色 id 集合（兼容字符串/对象两种形态）。"""
    present = set()
    for raw in shot.get("characters_present") or []:
        if isinstance(raw, dict):
            value = raw.get("id") or raw.get("character_id")
        else:
            value = raw
        value = str(value or "").strip()
        if value:
            present.add(value)
    return present


def sanitize_and_propagate_appearance_changes(merged: Dict[str, Any]) -> Dict[str, Any]:
    """清洗形象变化标记并做确定性向前传播。

    只保留能映射到数据库角色（character_db_id 非空）的条目；``revert`` 清除该
    角色的持续状态。传播仅作用于角色在场的镜头：变化点之后、恢复之前，该角色
    出现的每个镜头都会得到 ``_effective_appearance_changes`` 条目。
    幂等：重复调用结果一致（显式标记以 shot 自身为准重新计算）。
    """
    if not isinstance(merged, dict):
        return merged

    db_id_by_internal: Dict[str, Any] = {}
    for character in merged.get("characters") or []:
        if not isinstance(character, dict):
            continue
        internal_id = str(character.get("id") or "")
        if internal_id and character.get("character_db_id") not in (None, ""):
            db_id_by_internal[internal_id] = character.get("character_db_id")

    current: Dict[str, str] = {}
    for group in merged.get("shot_groups") or []:
        if not isinstance(group, dict):
            continue
        for shot in group.get("shots") or []:
            if not isinstance(shot, dict):
                continue
            sanitized: List[Dict[str, Any]] = []
            for change in shot.get("character_appearance_changes") or []:
                if not isinstance(change, dict):
                    continue
                internal_id = str(change.get("character_id") or "").strip()
                if internal_id not in db_id_by_internal:
                    continue
                label = _clean_label(change.get("label"))
                if _is_revert(change, label):
                    current.pop(internal_id, None)
                    # revert 标记必须保留在 shot 上：传播幂等依赖它（重跑时
                    # 若丢失 revert 事件，持续状态会错误越过恢复点）
                    sanitized.append({
                        "character_id": internal_id,
                        "label": label or "默认",
                        "description": "",
                        "revert": True,
                    })
                    continue
                if not label:
                    continue
                current[internal_id] = label
                sanitized.append({
                    "character_id": internal_id,
                    "label": label,
                    "description": str(change.get("description") or "").strip(),
                })
            if sanitized:
                shot["character_appearance_changes"] = sanitized
            else:
                shot.pop("character_appearance_changes", None)

            effective = [
                item for item in sanitized if item.get("revert") is not True
            ]
            present = _present_character_ids(shot)
            for internal_id, label in current.items():
                if internal_id not in present:
                    continue
                if any(item["character_id"] == internal_id for item in effective):
                    continue
                effective.append({
                    "character_id": internal_id,
                    "label": label,
                    "description": "",
                })
            if effective:
                shot[EFFECTIVE_CHANGES_FIELD] = effective
            else:
                shot.pop(EFFECTIVE_CHANGES_FIELD, None)
    return merged


def collect_appearance_change_specs(merged: Dict[str, Any]) -> List[Dict[str, Any]]:
    """从合并结果收集待生成变体规格，按 (character_db_id, label) 去重。

    优先取显式变化点（character_appearance_changes）中的 description 作为变体
    提示词素材；延续条目（_effective_appearance_changes 中 description 为空）
    只补位。超过上限的部分丢弃（防 LLM 输出泛滥，分镜降级用主图）。
    """
    if not isinstance(merged, dict):
        return []

    db_id_by_internal: Dict[str, Any] = {}
    name_by_internal: Dict[str, str] = {}
    for character in merged.get("characters") or []:
        if not isinstance(character, dict):
            continue
        internal_id = str(character.get("id") or "")
        if not internal_id:
            continue
        name_by_internal[internal_id] = str(character.get("name") or "")
        if character.get("character_db_id") not in (None, ""):
            db_id_by_internal[internal_id] = character.get("character_db_id")

    descriptions: Dict[tuple, str] = {}
    order: List[tuple] = []
    seen: set = set()
    for group in merged.get("shot_groups") or []:
        if not isinstance(group, dict):
            continue
        for shot in group.get("shots") or []:
            if not isinstance(shot, dict):
                continue
            for source in (
                shot.get("character_appearance_changes") or [],
                shot.get(EFFECTIVE_CHANGES_FIELD) or [],
            ):
                for change in source:
                    if not isinstance(change, dict) or change.get("revert") is True:
                        continue
                    internal_id = str(change.get("character_id") or "").strip()
                    db_id = db_id_by_internal.get(internal_id)
                    if db_id in (None, ""):
                        continue
                    label = _clean_label(change.get("label"))
                    if not label:
                        continue
                    key = (str(db_id), label)
                    description = str(change.get("description") or "").strip()
                    # 判重必须用独立的 seen 集合：description 为空时 descriptions
                    # 不会记录该 key，若用 descriptions 判重会重复 append。
                    if key not in seen:
                        seen.add(key)
                        order.append(key)
                    if description and not descriptions.get(key):
                        descriptions[key] = description

    specs: List[Dict[str, Any]] = []
    for db_id, label in order:
        specs.append({
            "character_db_id": int(db_id),
            "character_name": "",
            "label": label,
            "description": descriptions.get((db_id, label), ""),
        })
    # 补齐角色名（internal_id 在上面循环外不可得，按 db_id 反查一次）
    name_by_db: Dict[str, str] = {}
    for internal_id, db_id in db_id_by_internal.items():
        name_by_db[str(db_id)] = name_by_internal.get(internal_id, "")
    for spec in specs:
        spec["character_name"] = name_by_db.get(str(spec["character_db_id"]), "")
    return specs[: int(ScriptSplitConstants.CHARACTER_VARIANT_MAX_COUNT)]


def build_variant_prompt(label: str, description: str) -> str:
    """构造角色造型变体图生图提示词（与 character-image-designer 模板对齐）。

    保持五官/发型基线/体型与参考图一致，仅更换服装造型；布局为左侧面部特写 +
    右侧正面/侧面/背面三视角，与角色主参考图格式一致，便于生图参考图复用。
    """
    detail = f"{description}（{label}）" if description else label
    return (
        "Based on the provided reference image of the SAME character, generate a "
        "character design sheet with a new outfit/styling. Keep the face, facial "
        "features, hairstyle (unless the new styling explicitly restyles it), body "
        "proportions and art style 100% identical to the reference image; only "
        "change the outfit/styling. Layout: the left side is a facial close-up "
        "portrait; the right side shows the same character in full-body three "
        "views (front view, side view, back view), standing pose, neutral "
        "expression, clean light background. "
        f"New outfit/styling: {detail}. Do not add any text or watermark."
    )


def _parse_reference_images(raw: Any) -> List[Dict[str, Any]]:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            return []
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict)]


def _find_variant_url(variants: List[Dict[str, Any]], label: str) -> str:
    for item in variants:
        if str(item.get("label") or "").strip() == label:
            return str(item.get("url") or item.get("file_url") or "").strip()
    return ""


def _mark_entry(entry: Dict[str, Any], status: str, **fields: Any) -> None:
    entry["status"] = status
    entry.update(fields)


def _refresh_submitted(entry: Dict[str, Any]) -> None:
    """轮询一个 submitted 条目的后台任务终态并回写 DB 中的变体 URL。"""
    from model.grid_image_tasks import GridImageTaskStatus, GridImageTasksModel

    task_key = str(entry.get("task_key") or "")
    if not task_key:
        _mark_entry(entry, _STATUS_FAILED, error="missing_task_key")
        return
    grid_task = GridImageTasksModel.get_by_task_key(task_key)
    if grid_task is None:
        _mark_entry(entry, _STATUS_FAILED, error="task_record_missing")
        return
    status = grid_task.status
    if status == GridImageTaskStatus.COMPLETED:
        url = _load_variant_url(int(entry["character_db_id"]), str(entry["label"]))
        if url:
            _mark_entry(entry, _STATUS_READY, url=url)
        else:
            _mark_entry(entry, _STATUS_FAILED, error="variant_not_written_back")
        return
    if status in (
        GridImageTaskStatus.FAILED,
        GridImageTaskStatus.TIMEOUT,
        GridImageTaskStatus.CANCELLED,
        GridImageTaskStatus.DOWNLOAD_FAILED,
    ):
        _mark_entry(entry, _STATUS_FAILED, error=f"grid_task_{_GRID_STATUS_NAMES.get(status, status)}")
        return
    # QUEUED / PROCESSING：超时判定
    submitted_at = str(entry.get("submitted_at") or "")
    if submitted_at:
        try:
            started = datetime.fromisoformat(submitted_at)
            elapsed = (datetime.now() - started).total_seconds()
            if elapsed > float(ScriptSplitConstants.CHARACTER_VARIANT_TASK_TIMEOUT_SECONDS):
                _mark_entry(
                    entry, _STATUS_FAILED,
                    error="variant_task_timeout",
                )
                return
        except ValueError:
            pass


def _load_variant_url(character_db_id: int, label: str) -> str:
    from model.character import CharacterModel

    character = CharacterModel.get_by_id(int(character_db_id))
    if character is None:
        return ""
    return _find_variant_url(_parse_reference_images(character.reference_images), label)


def _submit_pending(entry: Dict[str, Any], task, world_id: Any) -> None:
    """提交一个 pending 变体：预检 DB 角色 → 调用 item_type=7 图生图管线。"""
    from model.character import CharacterModel
    from script_writer_core.mcp_tool import generate_character_variant_image

    db_id = int(entry["character_db_id"])
    label = str(entry["label"])
    character = CharacterModel.get_by_id(db_id)
    if character is None:
        _mark_entry(entry, _STATUS_SKIPPED, error="character_not_found")
        return
    existing_url = _find_variant_url(
        _parse_reference_images(character.reference_images), label)
    if existing_url:
        _mark_entry(entry, _STATUS_READY, url=existing_url)
        return
    main_image = str(character.reference_image or "").strip()
    if not main_image:
        _mark_entry(entry, _STATUS_SKIPPED, error="no_main_image")
        return

    character_name = str(character.name or entry.get("character_name") or "").strip()
    prompt = build_variant_prompt(label, str(entry.get("description") or ""))
    try:
        result = generate_character_variant_image(
            user_id=str(task.user_id),
            world_id=str(world_id),
            auth_token=str(task.auth_token or ""),
            character_name=character_name,
            variant_label=label,
            variant_prompt=prompt,
            aspect_ratio=str(ScriptSplitConstants.CHARACTER_VARIANT_ASPECT_RATIO),
            force_update=False,
        )
    except Exception as exc:  # 单条提交失败不阻塞其余变体
        logger.warning(
            "script split character variant submit failed: character=%s label=%s err=%s",
            character_name, label, exc,
        )
        _mark_entry(entry, _STATUS_FAILED, error=str(exc) or "submit_failed")
        return

    if result.get("success"):
        _mark_entry(
            entry, _STATUS_SUBMITTED,
            task_key=str(result.get("task_id") or ""),
            submitted_at=datetime.now().isoformat(timespec="seconds"),
        )
        return
    if result.get("skip_reason") == "already_has_variant":
        # 拆分运行期间用户/其他流程已生成同标签变体：复用
        url = _load_variant_url(db_id, label)
        if url:
            _mark_entry(entry, _STATUS_READY, url=url)
        else:
            _mark_entry(entry, _STATUS_SKIPPED, error="already_has_variant")
        return
    logger.warning(
        "script split character variant submit rejected: character=%s label=%s err=%s",
        character_name, label, result.get("error"),
    )
    _mark_entry(entry, _STATUS_FAILED, error=str(result.get("error") or "submit_failed"))


def ensure_character_variants(task, final_result: Dict[str, Any]) -> Dict[str, Any]:
    """推进角色形象变体生成一轮（幂等，可跨 worker tick 恢复）。

    同步函数（内部含 DB 与 HTTP 提交调用），调用方必须用 ``asyncio.to_thread``
    包装。每个 tick：先轮询 submitted 终态，再按批提交 pending；未全部终态时
    返回 ``all_settled=False``，调用方保存 final_result 并保持 publishing 让出
    tick（与配音对账 _reconcile_voiceover_and_finalize 相同模式）。
    """
    metadata = final_result.setdefault("metadata", {})
    if not isinstance(metadata, dict):
        metadata = {}
        final_result["metadata"] = metadata
    plan = metadata.get(PLAN_METADATA_KEY)
    if not isinstance(plan, list):
        plan = []
    if not plan:
        specs = collect_appearance_change_specs(final_result)
        for spec in specs:
            plan.append({
                "character_db_id": spec["character_db_id"],
                "character_name": spec.get("character_name") or "",
                "label": spec["label"],
                "description": spec.get("description") or "",
                "status": _STATUS_PENDING,
                "task_key": "",
                "url": "",
                "error": "",
                "submitted_at": "",
            })
        metadata[PLAN_METADATA_KEY] = plan

    world_id = (task.get_request_config() or {}).get("world_id")

    # 1) 轮询 submitted
    for entry in plan:
        if not isinstance(entry, dict) or entry.get("status") != _STATUS_SUBMITTED:
            continue
        try:
            _refresh_submitted(entry)
        except Exception as exc:
            logger.warning(
                "script split character variant refresh failed: %s err=%s",
                entry.get("label"), exc,
            )
            _mark_entry(entry, _STATUS_FAILED, error=str(exc) or "refresh_failed")

    # 2) 分批提交 pending（edit_image 提交含同步 HTTP，须限批避免超 worker watchdog）
    submitted_budget = int(ScriptSplitConstants.CHARACTER_VARIANT_SUBMIT_BATCH_SIZE)
    for entry in plan:
        if submitted_budget <= 0:
            break
        if not isinstance(entry, dict) or entry.get("status") != _STATUS_PENDING:
            continue
        submitted_budget -= 1
        try:
            _submit_pending(entry, task, world_id)
        except Exception as exc:
            logger.warning(
                "script split character variant submit crashed: %s err=%s",
                entry.get("label"), exc, exc_info=True,
            )
            _mark_entry(entry, _STATUS_FAILED, error=str(exc) or "submit_crashed")

    counts = {_STATUS_PENDING: 0, _STATUS_SUBMITTED: 0, _STATUS_READY: 0,
              _STATUS_FAILED: 0, _STATUS_SKIPPED: 0}
    for entry in plan:
        status = str(entry.get("status") or "")
        if status in counts:
            counts[status] += 1
    return {
        "total": len(plan),
        "all_settled": not (counts[_STATUS_PENDING] or counts[_STATUS_SUBMITTED]),
        **counts,
    }


def collect_ready_variant_map(final_result: Dict[str, Any]) -> Dict[str, Dict[str, str]]:
    """输出 ready 变体映射 ``{str(character_db_id): {label: url}}``（发布消费）。"""
    metadata = final_result.get("metadata")
    plan = metadata.get(PLAN_METADATA_KEY) if isinstance(metadata, dict) else None
    result: Dict[str, Dict[str, str]] = {}
    if not isinstance(plan, list):
        return result
    for entry in plan:
        if not isinstance(entry, dict) or entry.get("status") != _STATUS_READY:
            continue
        url = str(entry.get("url") or "").strip()
        label = str(entry.get("label") or "").strip()
        db_id = str(entry.get("character_db_id") or "").strip()
        if not (url and label and db_id):
            continue
        result.setdefault(db_id, {})[label] = url
    return result


def collect_pending_variant_map(final_result: Dict[str, Any]) -> Dict[str, set]:
    """输出未终态变体映射 ``{str(character_db_id): {label, ...}}``（发布记待回填）。

    只收计划里状态为 pending / submitted 的 (character_db_id, label)；ready 已
    直接写入 reference_selections，failed / skipped 降级用主参考图，均不记。
    """
    metadata = final_result.get("metadata")
    plan = metadata.get(PLAN_METADATA_KEY) if isinstance(metadata, dict) else None
    result: Dict[str, set] = {}
    if not isinstance(plan, list):
        return result
    for entry in plan:
        if not isinstance(entry, dict) or entry.get("status") not in _ACTIVE_STATUSES:
            continue
        label = _clean_label(entry.get("label"))
        db_id = str(entry.get("character_db_id") or "").strip()
        if not (label and db_id):
            continue
        result.setdefault(db_id, set()).add(label)
    return result


def _parse_json_dict(raw: Any) -> Optional[Dict[str, Any]]:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            return None
    return raw if isinstance(raw, dict) else None


def backfill_variant_reference_selections(
    world_id: Any,
    character_db_id: Any,
    label: str,
    url: str = "",
) -> Dict[str, int]:
    """变体图终态后回填/清除分镜 ``pending_reference_selections``（同步函数）。

    由 task/grid_image_task.py（item_type=7）在 scheduler 进程调用，不进 web
    事件循环。按 world_id 扫描场景 prompt_json，命中「角色 id 与 label 均匹配」
    的 pending 条目：

    - ``url`` 非空（成功）：该角色无人工 ``reference_selections`` 选择时写入
      ``{url, label}``；已有人工选择只删 pending 不覆盖。
    - ``url`` 为空（FAILED/TIMEOUT/CANCELLED/DOWNLOAD_FAILED）：只删 pending，
      镜头降级用主参考图。

    幂等：pending 不存在时 no-op（变体在落库前已完成、发布第二次轮询直接写成
    reference_selections 的场景即如此）。返回 ``{"filled": n, "cleared": m}``。
    """
    from model.storyboard_scene import StoryboardSceneModel

    label_clean = _clean_label(label)
    db_id_key = str(character_db_id or "").strip()
    if not (label_clean and db_id_key):
        return {"filled": 0, "cleared": 0}

    rows = StoryboardSceneModel.list_prompt_json_by_world(
        int(world_id), PENDING_SELECTIONS_PROMPT_KEY,
    )
    filled = 0
    cleared = 0
    for row in rows:
        prompt = _parse_json_dict(row.get("prompt_json"))
        if not isinstance(prompt, dict):
            continue
        pending_block = _parse_json_dict(prompt.get(PENDING_SELECTIONS_PROMPT_KEY))
        pending_chars = (
            pending_block.get("characters") if isinstance(pending_block, dict) else None
        )
        if not isinstance(pending_chars, dict):
            continue
        entry = pending_chars.get(db_id_key)
        entry_label = _clean_label(entry.get("label")) if isinstance(entry, dict) else ""
        if entry_label != label_clean:
            continue

        # 命中：删除该 pending 条目（characters 清空则整块移除）
        pending_chars.pop(db_id_key, None)
        if pending_chars:
            pending_block["characters"] = pending_chars
        else:
            prompt.pop(PENDING_SELECTIONS_PROMPT_KEY, None)

        selections_block = _parse_json_dict(prompt.get("reference_selections"))
        selections_chars = (
            selections_block.get("characters")
            if isinstance(selections_block, dict) else None
        )
        has_choice = (
            isinstance(selections_chars, dict) and db_id_key in selections_chars
        )
        if url and not has_choice:
            if not isinstance(selections_chars, dict):
                selections_chars = {}
                prompt["reference_selections"] = {
                    "schema_version": 1,
                    "characters": selections_chars,
                }
            selections_chars[db_id_key] = {"url": str(url), "label": label_clean}
            filled += 1
        cleared += 1
        StoryboardSceneModel.update(int(row["id"]), prompt_json=prompt)

    if filled or cleared:
        logger.info(
            "character variant backfill: world=%s character=%s label=%s ok=%s"
            " filled=%s cleared=%s",
            world_id, db_id_key, label_clean, bool(url), filled, cleared,
        )
    return {"filled": filled, "cleared": cleared}


def settle_pending_character_variant_references(
    world_id: Any,
    item_name: Any,
    url: str = "",
) -> Dict[str, int]:
    """item_type=7 宫格任务终态入口：按 ``item_name("角色名|变体标签")`` 定位角色。

    成功（``url`` 非空）回填 ``{url, label}``；失败终态只清除匹配 pending。
    角色按名查不到或 item_name 非法时 no-op（pending 按 db_id 匹配，查不到即
    不可能命中）。
    """
    parts = str(item_name or "").split("|", 1)
    character_name = parts[0].strip()
    label = parts[1].strip() if len(parts) > 1 else ""
    if not character_name:
        return {"filled": 0, "cleared": 0}
    from model.character import CharacterModel

    character = CharacterModel.get_by_name(int(world_id), character_name)
    if character is None:
        return {"filled": 0, "cleared": 0}
    return backfill_variant_reference_selections(
        world_id, character.id, label, url=url,
    )


def build_character_variant_summary(final_result: Dict[str, Any]) -> Dict[str, Any]:
    """构造写入 final_result.metadata 的执行摘要（不含 URL，便于诊断）。"""
    metadata = final_result.get("metadata")
    plan = metadata.get(PLAN_METADATA_KEY) if isinstance(metadata, dict) else None
    items = []
    if isinstance(plan, list):
        for entry in plan:
            if not isinstance(entry, dict):
                continue
            items.append({
                "character_db_id": entry.get("character_db_id"),
                "character_name": entry.get("character_name"),
                "label": entry.get("label"),
                "status": entry.get("status"),
                "error": entry.get("error") or "",
            })
    counts = {_STATUS_PENDING: 0, _STATUS_SUBMITTED: 0, _STATUS_READY: 0,
              _STATUS_FAILED: 0, _STATUS_SKIPPED: 0}
    for item in items:
        status = str(item.get("status") or "")
        if status in counts:
            counts[status] += 1
    return {
        "total": len(items),
        **counts,
        "items": items,
        "completed_at": datetime.now().isoformat(timespec="seconds"),
    }


__all__ = [
    "EFFECTIVE_CHANGES_FIELD",
    "PLAN_METADATA_KEY",
    "SUMMARY_METADATA_KEY",
    "PENDING_SELECTIONS_PROMPT_KEY",
    "sanitize_and_propagate_appearance_changes",
    "collect_appearance_change_specs",
    "build_variant_prompt",
    "ensure_character_variants",
    "collect_ready_variant_map",
    "collect_pending_variant_map",
    "backfill_variant_reference_selections",
    "settle_pending_character_variant_references",
    "build_character_variant_summary",
]
