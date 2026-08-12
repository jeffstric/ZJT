"""
Storyboard voiceover bootstrap service.

剧本拆分发布后，自动为本任务产出的对白提交配音任务（方案 B：对账服务）。

## 事务边界与防腐化设计（重要）

本服务的核心约束：**单条对白配音的「行锁 + 四步写库」必须封装在一个毫秒级
短事务内，事务期间严禁夹带任何网络/文件/TTS/IO 慢操作。**

为从代码层面防止后来者在事务里堆积慢操作（导致行锁长期持有、阻塞并发更新），
本服务采用「conn 不外泄」设计：

- `_submit_dialogue_voiceover_atomically` 自包含事务：`with transaction() as conn:`
  在函数体内，conn 是局部变量，函数返回即销毁。调用方拿不到 conn，无法在事务
  中间插入任何代码。
- 业务校验（text 为空、角色无声音等）在事务**外**完成，跳过的不进事务。
- 批量对账（`ensure_for_split_task`）逐条调用原子函数，每条是独立短事务，
  不是一个大事务锁住多行。
- TTS 实际生成由独立的 13 秒音频调度器（task/audio_task.py）在事务外异步执行，
  本服务只负责「把任务可靠入队」。

见 docs/storyboard/storyboard_auto_voiceover_after_split_design.md §8.1。
"""
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from config.constant import (
    AI_AUDIO_STATUS_PENDING,
    AI_AUDIO_STATUS_PROCESSING,
    AI_AUDIO_STATUS_COMPLETED,
    AI_AUDIO_STATUS_FAILED,
    TASK_TYPE_GENERATE_AUDIO,
    TASK_STATUS_QUEUED,
    StoryboardAudioGenerateConstants,
    StoryboardAutoGenerateConstants,
)
from model.ai_audio import AIAudioModel
from model.character import CharacterModel
from model.database import (
    execute_query,
    execute_query_in_transaction,
    transaction,
)
from model.storyboard_dialogue import StoryboardDialogueModel
from model.storyboard_dialogue_audio import StoryboardDialogueAudioModel
from model.storyboard_scene import StoryboardSceneModel
from model.tasks import TasksModel

logger = logging.getLogger(__name__)

# 已选中配音视为「有效/可复用」的 ai_audio 状态（pending/processing/completed）
# 失败状态（-1）不自动覆盖，交 scheduler 重试或用户显式重试。
_REUSABLE_AI_AUDIO_STATUSES = (
    AI_AUDIO_STATUS_PENDING,
    AI_AUDIO_STATUS_PROCESSING,
    AI_AUDIO_STATUS_COMPLETED,
)


class StoryboardVoiceoverBootstrapService:
    """拆分发布后自动配音对账服务（方案 B）。"""

    # ------------------------------------------------------------------
    # 对外入口
    # ------------------------------------------------------------------

    def ensure_dialogue_voiceover(
        self,
        dialogue_id: int,
        user_id: int,
        *,
        config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """对外公开的单条对白配音入口（手动配音复用本方法）。

        业务校验在事务外完成，跳过的不进事务；仅当需要创建任务链时才进入
        原子函数（毫秒级短事务）。
        """
        config = config or {}
        constants = StoryboardAudioGenerateConstants

        dialogue = StoryboardDialogueModel.get_by_id(int(dialogue_id))
        if not dialogue:
            return {
                "success": False,
                "decision": "failed",
                "dialogue_id": int(dialogue_id),
                "reason": "dialogue_not_found",
                "message": "对话不存在",
            }
        scene_id = getattr(dialogue, "scene_id", None)
        text = str(config.get("text") or getattr(dialogue, "text", "") or "").strip()
        if not text:
            return self._skip(
                int(dialogue_id), scene_id,
                constants.SKIP_REASON_EMPTY_TEXT, "台词为空，无法生成配音",
            )

        # 参考声音：body 覆盖 > 角色 default_voice（旁白无角色则需系统默认音色）
        ref_path = config.get("ref_path")
        character_id = getattr(dialogue, "character_id", None)
        if not ref_path and character_id:
            character = CharacterModel.get_by_id(int(character_id))
            ref_path = getattr(character, "default_voice", None) if character else None

        if not ref_path:
            if not character_id:
                return self._skip(
                    int(dialogue_id), scene_id,
                    constants.SKIP_REASON_NARRATION_WITHOUT_VOICE, "旁白缺少默认音色",
                )
            return self._skip(
                int(dialogue_id), scene_id,
                constants.SKIP_REASON_MISSING_REFERENCE_AUDIO, "角色缺少参考音频",
            )

        # 情感向量仅经企业版门面解析；社区/个人版恒为 {}
        from services.dialogue_emotion import resolve_tts_emotion_kwargs
        extra_audio_kwargs = resolve_tts_emotion_kwargs(
            dialogue=dialogue, config=config,
        ) or None
        logger.info(
            "[dialogue-emotion][voiceover-bootstrap] ensure dialogue_id=%s scene_id=%s "
            "emo_control_method=%s emo_vec=%r text_preview=%r",
            dialogue_id,
            scene_id,
            (extra_audio_kwargs or {}).get("emo_control_method"),
            (extra_audio_kwargs or {}).get("emo_vec"),
            (text[:40] + "...") if len(text) > 40 else text,
        )

        # 进入原子提交（事务封闭在函数内）
        return self._submit_dialogue_voiceover_atomically(
            int(dialogue_id), int(user_id), ref_path=ref_path, text=text,
            scene_id=scene_id,
            extra_audio_kwargs=extra_audio_kwargs,
        )

    def ensure_for_scenes(
        self,
        storyboard_id: int,
        scene_ids: List[int],
        user_id: int,
    ) -> Dict[str, Any]:
        """Queue missing dialogue voiceovers for an explicit storyboard selection.

        The method only performs short database operations. Actual TTS work remains in
        the audio scheduler. Existing selected audio and scenes configured to use the
        generated video's own audio are never overwritten.
        """
        constants = StoryboardAudioGenerateConstants
        normalized = []
        seen = set()
        for raw_id in scene_ids or []:
            try:
                scene_id = int(raw_id)
            except (TypeError, ValueError):
                raise ValueError("scene_ids must contain integers")
            if scene_id <= 0:
                raise ValueError("scene_ids must contain positive integers")
            if scene_id not in seen:
                seen.add(scene_id)
                normalized.append(scene_id)
        if not normalized:
            raise ValueError("scene_ids must not be empty")
        if len(normalized) > StoryboardAutoGenerateConstants.MAX_SELECTED_SCENE_COUNT:
            raise ValueError("too many selected scenes")

        scenes = StoryboardSceneModel.list_by_storyboard(int(storyboard_id)) or []
        scenes_by_id = {int(scene.get("id") or 0): scene for scene in scenes}
        invalid_ids = sorted(set(normalized) - set(scenes_by_id))
        if invalid_ids:
            raise ValueError(f"selected scenes do not belong to storyboard: {invalid_ids}")

        summary: Dict[str, Any] = {
            "success": True,
            "storyboard_id": int(storyboard_id),
            "requested_scene_count": len(normalized),
            "eligible_dialogue_count": 0,
            "submitted_count": 0,
            "reused_count": 0,
            "skipped_count": 0,
            "failed_count": 0,
            "items": [],
        }

        for scene_id in normalized:
            scene = scenes_by_id[scene_id]
            if bool(scene.get("audio_embedded")):
                summary["skipped_count"] += 1
                summary["items"].append({
                    "scene_id": scene_id,
                    "dialogue_id": None,
                    "status": "skipped",
                    "reason": constants.SKIP_REASON_USES_VIDEO_AUDIO,
                    "message": "分镜已启用使用视频音频",
                })
                continue

            dialogues = StoryboardDialogueModel.list_by_scene(scene_id) or []
            if not dialogues:
                summary["skipped_count"] += 1
                summary["items"].append({
                    "scene_id": scene_id,
                    "dialogue_id": None,
                    "status": "skipped",
                    "reason": constants.SKIP_REASON_NO_DIALOGUE,
                    "message": "分镜没有对话",
                })
                continue

            for dialogue in dialogues:
                dialogue_id = int(dialogue.get("id") or 0)
                if dialogue.get("selected_audio_id"):
                    summary["reused_count"] += 1
                    summary["items"].append({
                        "scene_id": scene_id,
                        "dialogue_id": dialogue_id,
                        "status": "reused",
                        "reason": constants.SKIP_REASON_ALREADY_HAS_SELECTED_AUDIO,
                        "message": "对话已有选中配音",
                    })
                    continue

                summary["eligible_dialogue_count"] += 1
                try:
                    result = self.ensure_dialogue_voiceover(
                        dialogue_id,
                        int(user_id),
                        config={"skip_existing": True},
                    )
                except Exception as exc:
                    logger.warning(
                        "[voiceover-batch] storyboard=%s scene=%s dialogue=%s submit failed: %s",
                        storyboard_id, scene_id, dialogue_id, exc, exc_info=True,
                    )
                    result = {
                        "decision": "failed",
                        "scene_id": scene_id,
                        "dialogue_id": dialogue_id,
                        "reason": constants.SKIP_REASON_SUBMIT_FAILED,
                        "message": str(exc),
                    }

                decision = str(result.get("decision") or "failed")
                if decision == "submitted":
                    summary["submitted_count"] += 1
                elif decision == "reused":
                    summary["reused_count"] += 1
                elif decision == "skipped":
                    summary["skipped_count"] += 1
                else:
                    summary["failed_count"] += 1
                summary["items"].append({
                    "scene_id": scene_id,
                    "dialogue_id": dialogue_id,
                    "status": decision,
                    "reason": result.get("reason") or "",
                    "message": result.get("message") or "",
                    "audio_id": result.get("audio_id"),
                    "dialogue_audio_id": result.get("dialogue_audio_id"),
                })

        return summary

    @staticmethod
    def _is_eligible_dialogue(dialogue: Dict[str, Any]) -> bool:
        """可自动配音对账的对白：非空台词 + 有角色。"""
        return bool((dialogue.get("text") or "").strip() and dialogue.get("character_id"))

    def ensure_for_split_task(
        self,
        split_task_id: int,
        user_id: int,
        *,
        limit: Optional[int] = None,
    ) -> Dict[str, Any]:
        """对账本次拆分发布出的全部对白（方案 §7 + §10）。

        - 按 script_split_task_id 限定范围（JOIN storyboard_scene），避免误处理手工分镜。
        - 每个对白独立短事务，失败不影响其他条。
        - remaining_count>0 时调用方（step_publish）保持 publishing，下个 tick 继续。
        - remaining_count 只统计「仍可处理且未完成」的对白：
          有台词 + 有 character_id + 无 selected_audio_id，且本轮未业务 skip。
          无角色/空台词、或业务 skip（缺参考音等）不阻挡 completed。
        """
        constants = StoryboardAudioGenerateConstants
        batch_size = int(limit if limit is not None else constants.AUTO_VOICEOVER_SUBMIT_BATCH_SIZE)

        dialogues = self._list_dialogues_by_split_task(int(split_task_id))
        eligible = [d for d in dialogues if self._is_eligible_dialogue(d)]
        # 未选中配音的、且符合资格的，取前 batch_size 条本轮处理
        pending = [d for d in eligible if not d.get("selected_audio_id")][:batch_size]

        summary = {
            "enabled": bool(constants.ENABLE_AUTO_AFTER_SCRIPT_SPLIT),
            "eligible_count": len(eligible),
            "submitted_count": 0,
            "reused_count": 0,
            "skipped_count": 0,
            "failed_count": 0,
            "remaining_count": 0,
            "skipped": [],
            "failures": [],
        }
        if not summary["enabled"]:
            # 未启用：无可处理工作，不因未选中配音而卡住 publishing
            summary["remaining_count"] = 0
            return summary

        # 本轮已业务结案（skip/submitted/reused）的 id；skip 无 selected 也不再计入 remaining
        terminal_ids: set = set()

        for d in pending:
            try:
                item = self.ensure_dialogue_voiceover(
                    int(d["id"]), int(user_id), config={"skip_existing": True},
                )
            except Exception as exc:
                logger.warning(
                    "[voiceover-bootstrap] split_task=%s dialogue=%s scene=%s 提交异常: %s",
                    split_task_id, d.get("id"), d.get("scene_id"), exc, exc_info=True,
                )
                item = {
                    "success": False,
                    "decision": "failed",
                    "dialogue_id": int(d["id"]),
                    "scene_id": d.get("scene_id"),
                    "reason": constants.SKIP_REASON_SUBMIT_FAILED,
                    "message": str(exc),
                }
            decision = item.get("decision")
            logger.info(
                "[voiceover-bootstrap] split_task=%s dialogue=%s scene=%s decision=%s reason=%s",
                split_task_id, d.get("id"), d.get("scene_id"), decision, item.get("reason"),
            )
            dialogue_id = int(item.get("dialogue_id") or d["id"])
            if decision == "submitted":
                summary["submitted_count"] += 1
                terminal_ids.add(dialogue_id)
            elif decision == "reused":
                summary["reused_count"] += 1
                terminal_ids.add(dialogue_id)
            elif decision == "skipped":
                summary["skipped_count"] += 1
                terminal_ids.add(dialogue_id)
                summary["skipped"].append({
                    "dialogue_id": item.get("dialogue_id"),
                    "scene_id": item.get("scene_id"),
                    "reason": item.get("reason"),
                    "message": item.get("message"),
                })
            else:
                summary["failed_count"] += 1
                summary["failures"].append({
                    "dialogue_id": item.get("dialogue_id"),
                    "scene_id": item.get("scene_id"),
                    "reason": item.get("reason"),
                    "message": item.get("message"),
                })

        # remaining = 仍可处理且未完成：
        # 有台词 + 有角色 + 无 selected_audio_id，且本轮未 skip/submit/reuse 结案。
        # 不含无角色旁白等非 eligible，避免 publishing 永久卡住。
        dialogues_after = self._list_dialogues_by_split_task(int(split_task_id))
        summary["remaining_count"] = sum(
            1
            for d in dialogues_after
            if self._is_eligible_dialogue(d)
            and not d.get("selected_audio_id")
            and int(d["id"]) not in terminal_ids
        )
        return summary

    # ------------------------------------------------------------------
    # 原子提交（conn 不外泄）
    # ------------------------------------------------------------------

    def _submit_dialogue_voiceover_atomically(
        self,
        dialogue_id: int,
        user_id: int,
        *,
        ref_path: str,
        text: str,
        scene_id: Optional[int] = None,
        extra_audio_kwargs: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """单条对白配音任务的原子提交（方案 §8.1）。

        ⚠️ 本函数自包含事务：从 BEGIN 到 COMMIT 全部封闭在函数体内，调用方拿不到
        conn，无法在事务中间插入网络/文件/TTS 等慢操作。后续维护者如需扩展，只能
        在函数返回后（事务已提交）操作，或在函数内追加纯 DB 步骤（须保持毫秒级）。

        事务内严格只做：SELECT FOR UPDATE → 幂等判定 → INSERT ai_audio → INSERT tasks
        → INSERT dialogue_audio → UPDATE selected_audio_id。禁止 TTS/HTTP/文件 IO。
        TTS 生成由独立的 13 秒音频调度器（task/audio_task.py）在事务外异步执行。

        extra_audio_kwargs：透传给 AIAudioModel.create_in_transaction 的额外字段
        （如 emo_control_method / emo_weight / transaction_id），供手动入口使用；
        自动对账不传。
        """
        with transaction() as conn:
            # 1. 行锁 + 读取当前选中状态（幂等判定的基础）
            row = execute_query_in_transaction(
                conn,
                "SELECT id, selected_audio_id FROM storyboard_dialogue WHERE id = %s FOR UPDATE",
                (int(dialogue_id),),
                fetch_one=True,
            )
            if not row:
                return {
                    "success": False,
                    "decision": "failed",
                    "dialogue_id": int(dialogue_id),
                    "scene_id": scene_id,
                    "reason": "dialogue_not_found",
                    "message": "对话不存在",
                }

            selected_audio_id = row.get("selected_audio_id")

            # 2. 幂等判定（方案 §8.2）：已选中有效音频 → reused，绝不覆盖
            if selected_audio_id:
                verdict = self._check_selected_audio(conn, int(selected_audio_id))
                if verdict == "reused":
                    return {
                        "success": False,
                        "decision": "reused",
                        "dialogue_id": int(dialogue_id),
                        "scene_id": scene_id,
                        "reason": StoryboardAudioGenerateConstants.SKIP_REASON_ALREADY_HAS_SELECTED_AUDIO,
                        "message": "对话已存在选中配音",
                    }
                # verdict == "skip_failed"：选中的是失败音频，首次对账不自动覆盖，
                # 交由 scheduler 重试或用户显式重试（视为 reused 跳过本轮）
                return {
                    "success": False,
                    "decision": "reused",
                    "dialogue_id": int(dialogue_id),
                    "scene_id": scene_id,
                    "reason": StoryboardAudioGenerateConstants.SKIP_REASON_ALREADY_HAS_SELECTED_AUDIO,
                    "message": "对话已有（失败）选中配音，交由重试机制处理",
                }

            # 3. 四步原子写库（纯 DB，毫秒级）。任一步异常 → 整个事务回滚，无孤儿记录。
            audio_create_kwargs = dict(
                text=text, user_id=int(user_id), ref_path=ref_path,
                status=AI_AUDIO_STATUS_PENDING,
            )
            if extra_audio_kwargs:
                audio_create_kwargs.update(extra_audio_kwargs)
            audio_id = AIAudioModel.create_in_transaction(conn, **audio_create_kwargs)
            TasksModel.create_in_transaction(
                conn, task_type=TASK_TYPE_GENERATE_AUDIO, task_id=int(audio_id),
                status=TASK_STATUS_QUEUED,
            )
            dialogue_audio_id = StoryboardDialogueAudioModel.create_in_transaction(
                conn, dialogue_id=int(dialogue_id), ai_audio_id=int(audio_id),
            )
            StoryboardDialogueAudioModel.set_selected_in_transaction(
                conn, int(dialogue_id), int(dialogue_audio_id),
            )
            # 事务在此自动 commit（transaction 上下文管理器）。conn 不返回给调用方。
            return {
                "success": True,
                "decision": "submitted",
                "dialogue_id": int(dialogue_id),
                "scene_id": scene_id,
                "audio_id": int(audio_id),
                "dialogue_audio_id": int(dialogue_audio_id),
            }

    # ------------------------------------------------------------------
    # 内部辅助
    # ------------------------------------------------------------------

    def _check_selected_audio(self, conn, dialogue_audio_id: int) -> str:
        """在事务内检查选中的 dialogue_audio 是否有效（方案 §8.2）。

        返回 'reused'（pending/processing/completed 或已有 audio_url）或
        'skip_failed'（关联 ai_audio 失败）。必须在持有 conn 时调用，仅做 SELECT。
        """
        da = execute_query_in_transaction(
            conn,
            "SELECT ai_audio_id, audio_url FROM storyboard_dialogue_audio WHERE id = %s",
            (int(dialogue_audio_id),),
            fetch_one=True,
        )
        if not da:
            return "skip_failed"
        # 已有结果 URL（用户上传或已生成）→ 不覆盖
        if da.get("audio_url"):
            return "reused"
        ai_audio_id = da.get("ai_audio_id")
        if not ai_audio_id:
            return "reused"  # 无关联 ai_audio（如纯上传），视为可复用
        ai = execute_query_in_transaction(
            conn,
            "SELECT status FROM ai_audio WHERE id = %s",
            (int(ai_audio_id),),
            fetch_one=True,
        )
        if not ai:
            return "skip_failed"
        status = int(ai.get("status") or 0)
        if status in _REUSABLE_AI_AUDIO_STATUSES:
            return "reused"
        return "skip_failed"

    def _list_dialogues_by_split_task(self, split_task_id: int) -> List[Dict[str, Any]]:
        """查询本拆分任务产出的全部对白（JOIN storyboard_scene 限定范围）。

        避免误处理用户手工创建的旧分镜或另一次拆分任务的对白（方案 §7）。
        """
        sql = """
            SELECT d.id, d.scene_id, d.character_id, d.text, d.selected_audio_id,
                   s.sort_order AS scene_sort_order
            FROM storyboard_dialogue d
            JOIN storyboard_scene s ON s.id = d.scene_id
            WHERE s.script_split_task_id = %s
            ORDER BY s.sort_order ASC, d.sort_order ASC, d.id ASC
        """
        rows = execute_query(sql, (int(split_task_id),), fetch_all=True)
        return rows or []

    def _skip(self, dialogue_id: int, scene_id: Optional[int], reason: str, message: str) -> Dict[str, Any]:
        return {
            "success": False,
            "decision": "skipped",
            "dialogue_id": int(dialogue_id),
            "scene_id": scene_id,
            "reason": reason,
            "message": message,
        }
