"""
Storyboard dialogue audio model - database operations for storyboard_dialogue_audio table.
"""
from typing import Optional, Dict, Any, List
from .database import execute_query, execute_update, execute_insert, execute_insert_in_transaction, execute_update_in_transaction
from config.constant import AIAudioStatus
import logging

logger = logging.getLogger(__name__)


class StoryboardDialogueAudio:
    """StoryboardDialogueAudio entity class."""

    def __init__(self, **kwargs):
        self.id = kwargs.get('id')
        self.dialogue_id = kwargs.get('dialogue_id')
        self.ai_audio_id = kwargs.get('ai_audio_id')
        self.audio_url = kwargs.get('audio_url')
        self.duration = kwargs.get('duration')
        self.create_at = kwargs.get('create_at')

    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'dialogue_id': self.dialogue_id,
            'ai_audio_id': self.ai_audio_id,
            'audio_url': self.audio_url,
            'duration': float(self.duration) if self.duration is not None else None,
            'create_at': self.create_at.isoformat() if self.create_at else None,
        }


class StoryboardDialogueAudioModel:
    """StoryboardDialogueAudio database operations."""

    @staticmethod
    def create(
        dialogue_id: int,
        ai_audio_id: Optional[int] = None,
        audio_url: Optional[str] = None,
        duration: Optional[float] = None,
    ) -> int:
        sql = """
            INSERT INTO storyboard_dialogue_audio
            (dialogue_id, ai_audio_id, audio_url, duration)
            VALUES (%s, %s, %s, %s)
        """
        params = (dialogue_id, ai_audio_id, audio_url, duration)
        try:
            record_id = execute_insert(sql, params)
            logger.info(f"Created storyboard_dialogue_audio with ID: {record_id}")
            return record_id
        except Exception as e:
            logger.error(f"Failed to create storyboard_dialogue_audio: {e}")
            raise

    @staticmethod
    def create_in_transaction(
        conn,
        dialogue_id: int,
        ai_audio_id: Optional[int] = None,
        audio_url: Optional[str] = None,
        duration: Optional[float] = None,
    ) -> int:
        """
        ⚠️ 仅供事务型原子配音提交内部调用，禁止在此 conn 上执行网络/文件/TTS 等慢操作。

        事务必须保持毫秒级短事务。禁止在持有 conn 期间做 HTTP/文件/IO/sleep 等
        可能超过 ~50ms 的操作，否则行锁长期持有会阻塞并发更新。
        见 docs/storyboard/storyboard_auto_voiceover_after_split_design.md §8.1。

        SQL 与参数与 create() 完全一致，仅换 execute_insert_in_transaction。
        """
        sql = """
            INSERT INTO storyboard_dialogue_audio
            (dialogue_id, ai_audio_id, audio_url, duration)
            VALUES (%s, %s, %s, %s)
        """
        params = (dialogue_id, ai_audio_id, audio_url, duration)
        return execute_insert_in_transaction(conn, sql, params)

    @staticmethod
    def get_by_id(record_id: int) -> Optional[StoryboardDialogueAudio]:
        sql = "SELECT * FROM storyboard_dialogue_audio WHERE id = %s"
        try:
            result = execute_query(sql, (record_id,), fetch_one=True)
            if result:
                return StoryboardDialogueAudio(**result)
            return None
        except Exception as e:
            logger.error(f"Failed to get storyboard_dialogue_audio by ID {record_id}: {e}")
            raise

    @staticmethod
    def list_by_dialogue(dialogue_id: int) -> List[Dict]:
        sql = """
            SELECT * FROM storyboard_dialogue_audio
            WHERE dialogue_id = %s
            ORDER BY create_at DESC, id DESC
        """
        try:
            results = execute_query(sql, (dialogue_id,), fetch_all=True)
            return [StoryboardDialogueAudio(**row).to_dict() for row in results] if results else []
        except Exception as e:
            logger.error(f"Failed to list audios for dialogue {dialogue_id}: {e}")
            raise

    @staticmethod
    def set_selected(dialogue_id: int, dialogue_audio_id: int) -> int:
        sql = "UPDATE storyboard_dialogue SET selected_audio_id = %s WHERE id = %s"
        try:
            affected = execute_update(sql, (dialogue_audio_id, dialogue_id))
            logger.info(f"Set selected audio {dialogue_audio_id} for dialogue {dialogue_id}")
            return affected
        except Exception as e:
            logger.error(f"Failed to set selected audio for dialogue {dialogue_id}: {e}")
            raise

    @staticmethod
    def set_selected_in_transaction(conn, dialogue_id: int, dialogue_audio_id: int) -> int:
        """
        ⚠️ 仅供事务型原子配音提交内部调用，禁止在此 conn 上执行网络/文件/TTS 等慢操作。

        事务必须保持毫秒级短事务。注意本方法 UPDATE 的是 storyboard_dialogue 表
        （设置其 selected_audio_id），不是 storyboard_dialogue_audio 表。
        SQL 与参数与 set_selected() 完全一致，仅换 execute_update_in_transaction。
        见 docs/storyboard/storyboard_auto_voiceover_after_split_design.md §8.1。
        """
        sql = "UPDATE storyboard_dialogue SET selected_audio_id = %s WHERE id = %s"
        return execute_update_in_transaction(conn, sql, (dialogue_audio_id, dialogue_id))

    @staticmethod
    def update_audio_url_by_ai_audio_id(ai_audio_id: int, audio_url: str) -> int:
        sql = "UPDATE storyboard_dialogue_audio SET audio_url = %s WHERE ai_audio_id = %s"
        try:
            affected = execute_update(sql, (audio_url, ai_audio_id))
            logger.info(f"Updated storyboard dialogue audio URL for ai_audio {ai_audio_id}, affected rows: {affected}")
            return affected
        except Exception as e:
            logger.error(f"Failed to update storyboard dialogue audio URL for ai_audio {ai_audio_id}: {e}")
            raise

    @staticmethod
    def update_duration_by_ai_audio_id(ai_audio_id: int, duration: float) -> int:
        """按 ai_audio_id 更新配音时长（秒）。"""
        sql = "UPDATE storyboard_dialogue_audio SET duration = %s WHERE ai_audio_id = %s"
        try:
            affected = execute_update(sql, (duration, ai_audio_id))
            logger.info(f"Updated duration {duration}s for ai_audio {ai_audio_id}, affected rows: {affected}")
            return affected
        except Exception as e:
            logger.error(f"Failed to update duration for ai_audio {ai_audio_id}: {e}")
            raise

    @staticmethod
    def get_by_ai_audio_id(ai_audio_id: int) -> Optional[StoryboardDialogueAudio]:
        """按 ai_audio_id 查询配音记录（一个 ai_audio 仅对应一条 dialogue_audio）。"""
        sql = "SELECT * FROM storyboard_dialogue_audio WHERE ai_audio_id = %s LIMIT 1"
        try:
            result = execute_query(sql, (ai_audio_id,), fetch_one=True)
            return StoryboardDialogueAudio(**result) if result else None
        except Exception as e:
            logger.error(f"Failed to get storyboard_dialogue_audio by ai_audio_id {ai_audio_id}: {e}")
            raise

    @staticmethod
    def sum_selected_durations_if_all_completed(scene_id: int) -> Optional[float]:
        """
        累计分镜下「已完成且选中」的配音时长，用于同步 storyboard_scene.duration。

        判定逻辑（通过 storyboard_dialogue.selected_audio_id 关联当前选中配音）：
        - 该分镜无任何 dialogue → 返回 None（不处理空场景，保留 LLM 估算值）。
        - 该分镜无任何「已完成」选中配音 → 返回 None（一条都没生成完，保留 LLM 估算值）。
        - 否则 → 返回所有「已完成」选中配音的 SUM(duration)。

        ⚠️ best-effort 语义（2026-08-13 修复）：
        旧逻辑要求「所有对白都有选中配音且全部 COMPLETED」才返回，任一对白缺配音就
        返回 None，导致 duration 永远停在 LLM 估算值。但前端 buildScenePlan 和导出
        _build_scene_audio 都只播放/拼接「已有配音」的部分——也就是说分镜实际播放时
        长就是「已完成配音」的累计。旧逻辑让这部分分镜的 duration < 实际播放音频时长，
        播放器 waitMs(duration) 提前切镜，把还在播的音频/视频掐断。
        现改为：只要有一条已完成的选中配音，就返回它们的累计时长，让 duration 与
        「实际会播出的音频」对齐。缺配音/未完成的对白被忽略（与前端/导出口径一致）。

        Returns:
            Optional[float]: 有已完成配音时返回累计秒数；无 dialogue 或无已完成配音返回 None。
        """
        sql = """
            SELECT
                COUNT(d.id) AS dialogue_count,
                SUM(
                    CASE
                        WHEN d.selected_audio_id IS NULL THEN 0
                        WHEN aa.status <> %s THEN 0
                        WHEN da.duration IS NULL THEN 0
                        ELSE da.duration
                    END
                ) AS total_duration,
                SUM(
                    CASE
                        WHEN d.selected_audio_id IS NULL THEN 0
                        WHEN aa.status <> %s THEN 0
                        WHEN da.duration IS NULL THEN 0
                        ELSE 1
                    END
                ) AS completed_audio_count
            FROM storyboard_dialogue d
            LEFT JOIN storyboard_dialogue_audio da ON da.id = d.selected_audio_id
            LEFT JOIN ai_audio aa ON aa.id = da.ai_audio_id
            WHERE d.scene_id = %s
        """
        try:
            row = execute_query(
                sql,
                (AIAudioStatus.COMPLETED, AIAudioStatus.COMPLETED, scene_id),
                fetch_one=True,
            )
            if not row:
                return None
            if not row.get('dialogue_count'):
                # 无 dialogue 的空场景
                return None
            completed_count = row.get('completed_audio_count') or 0
            if completed_count == 0:
                # 一条已完成的选中配音都没有 → 保留 LLM 估算值
                return None
            total = row.get('total_duration')
            return float(total) if total is not None else None
        except Exception as e:
            logger.error(f"Failed to sum selected durations for scene {scene_id}: {e}")
            raise

    @staticmethod
    def delete(record_id: int) -> int:
        sql = "DELETE FROM storyboard_dialogue_audio WHERE id = %s"
        try:
            affected = execute_update(sql, (record_id,))
            logger.info(f"Deleted storyboard_dialogue_audio {record_id}, affected rows: {affected}")
            return affected
        except Exception as e:
            logger.error(f"Failed to delete storyboard_dialogue_audio {record_id}: {e}")
            raise


# ==================== CREATE_TABLE_SQL ====================
CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS `storyboard_dialogue_audio` (
    `id` INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    `dialogue_id` INT UNSIGNED NOT NULL,
    `ai_audio_id` INT DEFAULT NULL COMMENT '→ ai_audio.id（源表 int，不加外键）',
    `audio_url` VARCHAR(512) DEFAULT NULL COMMENT '配音结果 URL（冗余）',
    `duration` DECIMAL(10,3) DEFAULT NULL COMMENT '音频时长（秒），生成完成时由 ffprobe 探测写入',
    `create_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX `idx_dialogue` (`dialogue_id`),
    INDEX `idx_ai_audio` (`ai_audio_id`),
    FOREIGN KEY (`dialogue_id`) REFERENCES `storyboard_dialogue`(`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='分镜对话配音历史表';
"""

# ==================== 增量迁移 SQL（手动执行或由 alembic 管理）====================
# 新增 duration 字段：记录每条配音的实际时长（秒），用于"分镜所有配音完成后自动重算分镜时长"
MIGRATION_ADD_DURATION_SQL = """
ALTER TABLE `storyboard_dialogue_audio`
ADD COLUMN `duration` DECIMAL(10,3) DEFAULT NULL COMMENT '音频时长（秒），生成完成时由 ffprobe 探测写入' AFTER `audio_url`;
"""

__all__ = ["StoryboardDialogueAudio", "StoryboardDialogueAudioModel"]
