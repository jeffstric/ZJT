"""Storyboard character bootstrap service.

剧本拆分（llm/script_parser）允许剧本新角色以 ``character_db_id=null`` 输出。
历史上这些角色不会落库，导致分镜提示词携带 ``【【角色名】】`` 标记但世界角色库
中无此角色（幽灵角色）：前端照样渲染角色框，生成分镜图时参考图解析静默跳过，
点击角色框则报"角色不存在"。

本服务在拆分发布（script_split_engine.step_publish）阶段把新角色自动入库：

  - 已携带 ``character_db_id`` 的角色直接复用，不重复入库；若 LLM 输出的
    name 是简称/变体（如「哈利」匹配到 db_id=哈利波特），按库内完整名
    归一化 name 并同步改写 shot 标记（合并期 normalize_characters_by_db_id
    已先行处理，此处兜底历史检查点恢复等绕过合并归一化的路径）；
  - LLM 输出短名（如 ``奶昔``）且世界库存在唯一受控别名目标
    （``奶昔_Milkshake``，见 script_split_character_contract._controlled_alias）时，
    归一化到完整名：回填 db_id、改写 parsed 角色 name，并把 shot 文本中的
    ``【【短名】】`` 标记替换为 ``【【完整名】】``，使生图按名查找能命中；
  - 其余新角色用 ``CharacterModel.create(source=script_split)`` 建库
    （缺参考图，other_info 带提示文案），回填真实 db_id；
    属主取世界属主（而非拆分任务发起人），与手动建角色口径一致；
  - 单角色失败仅记 warning 不阻塞发布（该角色保持幽灵，前端按"未入库"警示展示）。

幂等性：按 ``(world_id, name)`` 先查后建，重复发布/恢复重跑时复用既有行；
发布幂等检查（existing_count）亦保证 bootstrap 不会随 create_scenes 重复执行。

本服务为纯同步 DB 操作；web/异步调用时必须用 asyncio.to_thread 包装
（step_publish 已如此），与 storyboard_location_bootstrap_service 保持一致。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from config.constant import CharacterConstants
from model.character import CharacterModel
from model.world import WorldModel
from services.script_split_character_contract import (
    _controlled_alias,
    rename_character_tokens,
)

logger = logging.getLogger(__name__)

# 自动入库角色 other_info 提示文案（角色管理页可见，引导用户补参考图）
_AUTO_CREATED_OTHER_INFO = "该角色由剧本拆分自动创建，请补充参考图与详细设定。"


class StoryboardCharacterBootstrapService:
    """剧本拆分发布：新角色入库 + character_db_id 回填。"""

    def bootstrap(
        self,
        parsed_data: Dict[str, Any],
        world_id: int,
        user_id: int,
    ) -> Dict[str, Any]:
        """
        将 parsed_data.characters 中库外新角色落库并回填 character_db_id。

        Args:
            parsed_data: 拆分合并后的最终结果（会被原地修改：
                         characters[i].character_db_id/name、
                         shot_groups[].shots[] 文本中的角色标记）。
            world_id: 世界观 DB id。
            user_id: 拆分任务发起人 DB id（仅作世界行缺失时的属主回退）。

        Returns:
            {
                'created_character_count': int,  # 新建角色数
                'reused_character_count': int,   # 复用/归一化既有角色数
                'id_map': {char_xxx -> db_id},   # 内部 id 到 DB id 映射
                'renamed': {短名 -> 完整名},     # 短名归一化记录
                'warnings': List[str],
            }
        """
        warnings: List[str] = []
        id_map: Dict[str, Optional[int]] = {}
        renamed: Dict[str, str] = {}
        created_count = 0
        reused_count = 0

        # 入库属主取世界属主而非拆分任务发起人：admin/课堂代跑场景下任务发起人
        # 不是世界主人，若按任务属主落库，世界主人在按属主校验的角色接口
        # （voice-desc/reference-audio）会被误拦 403；世界行缺失时回退任务属主
        world = WorldModel.get_by_id(int(world_id)) if world_id is not None else None
        owner_user_id = getattr(world, "user_id", None) or user_id

        characters = parsed_data.get("characters")
        if not isinstance(characters, list):
            return self._empty_result()

        # 一次分页读取世界角色行，别名索引与 db_id→完整名索引共用；
        # 读取失败退化为空索引（不阻塞发布，仅跳过归一化/别名复用）
        try:
            world_rows = self._list_world_characters(world_id)
        except Exception as exc:
            logger.warning(
                "[character-bootstrap] list world characters failed world_id=%s: %s",
                world_id, exc,
            )
            world_rows = []
        alias_index = self._build_alias_index(world_rows)
        db_name_index = self._build_db_name_index(world_rows)

        for character in characters:
            if not isinstance(character, dict):
                continue
            char_key = str(character.get("id") or "")
            if not char_key:
                continue

            db_id = self._safe_int(character.get("character_db_id"))
            if db_id is not None:
                # 已匹配库内角色：直接复用，不重复入库。LLM 语义匹配常能
                # 正确回填 db_id 但 name 输出简称/变体（「哈利」→库内
                # 「哈利波特」），按库内完整名归一化 name 与【【】】标记，
                # 避免下游按名精确查库 miss 或误建重复角色。
                self._normalize_matched_character(
                    character, db_id, db_name_index, renamed, warnings,
                )
                id_map[char_key] = db_id
                reused_count += 1
                continue

            name = self._clean_name(character.get("name"))
            if not name:
                warnings.append(f"char_key={char_key} 缺少 name，跳过入库")
                id_map[char_key] = None
                continue

            try:
                db_id, resolved_name, created = self._resolve_or_create(
                    world_id, int(owner_user_id), character, name, alias_index, warnings,
                )
            except Exception as exc:
                # 单角色失败不阻塞发布：该角色保持"幽灵"，前端按未入库警示展示
                warnings.append(f"char_key={char_key} name={name} 入库失败: {exc}")
                logger.warning(
                    "[character-bootstrap] create failed char_key=%s name=%r: %s",
                    char_key, name, exc, exc_info=True,
                )
                id_map[char_key] = None
                continue

            if db_id is None:
                id_map[char_key] = None
                continue

            if resolved_name != name:
                # 短名归一化：改写 parsed 角色名，并同步替换 shot 文本标记
                renamed[name] = resolved_name
                character["name"] = resolved_name
            character["character_db_id"] = db_id
            id_map[char_key] = db_id
            if created:
                created_count += 1
            else:
                reused_count += 1

        if renamed:
            rename_character_tokens(parsed_data, renamed)

        logger.info(
            "[character-bootstrap] world_id=%s created=%s reused=%s renamed=%s warnings=%s",
            world_id, created_count, reused_count, len(renamed), len(warnings),
        )

        return {
            "created_character_count": created_count,
            "reused_character_count": reused_count,
            "id_map": id_map,
            "renamed": renamed,
            "warnings": warnings,
        }

    # ---------- 内部辅助 ----------

    def _resolve_or_create(
        self,
        world_id: int,
        user_id: int,
        character: Dict[str, Any],
        name: str,
        alias_index: Dict[str, List[str]],
        warnings: List[str],
    ) -> tuple:
        """解析单个角色的落库结果，返回 (db_id, resolved_name, created)。

        短名唯一命中受控别名时归一化复用；同名行直接复用；否则新建。
        db_id 为 None 表示该角色无法入库（多义短名等），调用方跳过。
        """
        alias_targets = alias_index.get(name) or []
        if len(alias_targets) == 1:
            # 短名唯一命中（如「奶昔」→「奶昔_Milkshake」）：归一化复用
            resolved_name = alias_targets[0]
            existing = CharacterModel.get_by_name(world_id, resolved_name)
            if existing is not None:
                warnings.append(
                    f"角色短名 '{name}' 归一化为库内完整名 '{resolved_name}'"
                )
                return self._safe_int(getattr(existing, "id", None)), resolved_name, False
        elif len(alias_targets) > 1:
            # 多义短名无法确定目标：不自动建库（会产生与多个角色都相似的新行）
            warnings.append(
                f"角色短名 '{name}' 对应多个库内角色 {alias_targets}，未自动入库"
            )
            return None, name, False

        existing = CharacterModel.get_by_name(world_id, name)
        if existing is not None:
            # 同名既有角色：复用 id，不覆盖任何字段（保护参考图与设定）
            return self._safe_int(getattr(existing, "id", None)), name, False

        db_id = CharacterModel.create(
            world_id=world_id,
            name=name,
            user_id=user_id,
            age=self._compose_age(character),
            identity=self._clean_name(character.get("role")) or None,
            appearance=self._clean_name(character.get("description")) or None,
            other_info=_AUTO_CREATED_OTHER_INFO,
            source=CharacterConstants.SOURCE_SCRIPT_SPLIT,
        )
        return db_id, name, True

    def _normalize_matched_character(
        self,
        character: Dict[str, Any],
        db_id: int,
        db_name_index: Dict[int, str],
        renamed: Dict[str, str],
        warnings: List[str],
    ) -> None:
        """对已携带 character_db_id 的角色做名称一致性归一化（原地修改）。

        库内存在该 db_id 且 name 与完整名不一致时改写 name 并登记 renamed
        （旧名恰好是库内另一角色完整名时跳过，防止标记误替换）；
        db_id 已不在库中（角色被删）仅记 warning，保持既有复用行为。
        """
        canonical = db_name_index.get(db_id)
        name = self._clean_name(character.get("name"))
        if canonical is None:
            warnings.append(
                f"db_id={db_id} 在世界角色库中不存在（可能已被删除），按原样复用"
            )
            return
        if name == canonical:
            return
        if name and name in db_name_index.values():
            warnings.append(
                f"角色 '{name}'(db_id={db_id}) 与库内其他角色同名，"
                f"未归一化为 '{canonical}'"
            )
            return
        if name:
            renamed[name] = canonical
        character["name"] = canonical
        warnings.append(
            f"角色 '{name or character.get('id')}'(db_id={db_id}) "
            f"名称与库内不一致，已归一化为 '{canonical}'"
        )

    @staticmethod
    def _build_alias_index(rows: List[Dict[str, Any]]) -> Dict[str, List[str]]:
        """从世界角色行构建 {受控短名: [完整名, ...]} 索引（`中文名_English` 约定）。"""
        index: Dict[str, List[str]] = {}
        for row in rows:
            alias = _controlled_alias(row.get("name"))
            if alias:
                index.setdefault(alias, []).append(
                    str(row.get("name") or "").strip(),
                )
        return index

    @staticmethod
    def _build_db_name_index(rows: List[Dict[str, Any]]) -> Dict[int, str]:
        """从世界角色行构建 {character_db_id: 库内完整名} 索引（归一化真值）。"""
        index: Dict[int, str] = {}
        for row in rows:
            db_id = StoryboardCharacterBootstrapService._safe_int(row.get("id"))
            name = str(row.get("name") or "").strip()
            if db_id is not None and name:
                index[db_id] = name
        return index

    @staticmethod
    def _list_world_characters(world_id: int) -> List[Dict[str, Any]]:
        from config.constant import ScriptSplitConstants

        rows: List[Dict[str, Any]] = []
        page = 1
        while True:
            result = CharacterModel.list_by_world(
                world_id=int(world_id),
                page=page,
                page_size=ScriptSplitConstants.CHARACTER_CONTRACT_PAGE_SIZE,
                order_by="id",
                order_direction="ASC",
            ) or {}
            batch = result.get("data") or []
            rows.extend(
                {"id": item.get("id"), "name": str(item.get("name") or "").strip()}
                for item in batch
                if isinstance(item, dict) and item.get("name")
            )
            total = int(result.get("total") or len(rows))
            if not batch or len(rows) >= total:
                break
            page += 1
        return rows

    @staticmethod
    def _compose_age(character: Dict[str, Any]) -> Optional[str]:
        gender = str(character.get("gender") or "").strip()
        age_range = str(character.get("age_range") or "").strip()
        if gender and age_range:
            return f"{gender} / {age_range}"[:50]
        return (gender or age_range or None)

    @staticmethod
    def _empty_result() -> Dict[str, Any]:
        return {
            "created_character_count": 0,
            "reused_character_count": 0,
            "id_map": {},
            "renamed": {},
            "warnings": [],
        }

    @staticmethod
    def _safe_int(value: Any) -> Optional[int]:
        if value is None:
            return None
        try:
            iv = int(value)
            return iv if iv > 0 else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _clean_name(name: Any) -> str:
        return str(name or "").strip()
