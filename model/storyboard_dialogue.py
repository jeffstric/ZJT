"""
Storyboard dialogue model - database operations for storyboard_dialogue table.
"""
from typing import Optional, Dict, Any, List
from .database import execute_query, execute_update, execute_insert
from .storyboard_scene import compute_sort_between, is_precision_exhausted
import logging

logger = logging.getLogger(__name__)


class StoryboardDialogue:
    """StoryboardDialogue entity class."""

    def __init__(self, **kwargs):
        self.id = kwargs.get('id')
        self.scene_id = kwargs.get('scene_id')
        self.sort_order = kwargs.get('sort_order')
        self.character_id = kwargs.get('character_id')
        self.text = kwargs.get('text')
        self.speed = kwargs.get('speed')
        self.volume = kwargs.get('volume')
        self.selected_audio_id = kwargs.get('selected_audio_id')
        self.last_modified_user_id = kwargs.get('last_modified_user_id')
        self.create_at = kwargs.get('create_at')
        self.update_at = kwargs.get('update_at')

    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'scene_id': self.scene_id,
            'sort_order': float(self.sort_order) if self.sort_order is not None else 0.0,
            'character_id': self.character_id,
            'text': self.text,
            'speed': float(self.speed) if self.speed is not None else 1.0,
            'volume': self.volume if self.volume is not None else 100,
            'selected_audio_id': self.selected_audio_id,
            'last_modified_user_id': self.last_modified_user_id,
            'create_at': self.create_at.isoformat() if self.create_at else None,
            'update_at': self.update_at.isoformat() if self.update_at else None,
        }


class StoryboardDialogueModel:
    """StoryboardDialogue database operations."""

    @staticmethod
    def create(
        scene_id: int,
        sort_order: float = 0.0,
        character_id: Optional[int] = None,
        text: Optional[str] = None,
        speed: float = 1.0,
        volume: int = 100,
        last_modified_user_id: Optional[int] = None,
    ) -> int:
        sql = """
            INSERT INTO storyboard_dialogue
            (scene_id, sort_order, character_id, text, speed, volume, last_modified_user_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """
        params = (scene_id, float(sort_order), character_id, text, float(speed), volume, last_modified_user_id)
        try:
            record_id = execute_insert(sql, params)
            logger.info(f"Created storyboard_dialogue with ID: {record_id}")
            return record_id
        except Exception as e:
            logger.error(f"Failed to create storyboard_dialogue: {e}")
            raise

    @staticmethod
    def get_by_id(record_id: int) -> Optional[StoryboardDialogue]:
        sql = "SELECT * FROM storyboard_dialogue WHERE id = %s"
        try:
            result = execute_query(sql, (record_id,), fetch_one=True)
            if result:
                return StoryboardDialogue(**result)
            return None
        except Exception as e:
            logger.error(f"Failed to get storyboard_dialogue by ID {record_id}: {e}")
            raise

    @staticmethod
    def list_by_scene(scene_id: int) -> List[Dict]:
        sql = """
            SELECT d.*, da.audio_url
            FROM storyboard_dialogue d
            LEFT JOIN storyboard_dialogue_audio da ON da.id = d.selected_audio_id
            WHERE d.scene_id = %s
            ORDER BY d.sort_order ASC, d.id ASC
        """
        try:
            results = execute_query(sql, (scene_id,), fetch_all=True)
            out = []
            for row in (results or []):
                d = StoryboardDialogue(**row).to_dict()
                d['audio_url'] = row.get('audio_url')
                out.append(d)
            return out
        except Exception as e:
            logger.error(f"Failed to list dialogues for scene {scene_id}: {e}")
            raise

    @staticmethod
    def update(record_id: int, **kwargs) -> int:
        allowed_fields = [
            'sort_order', 'character_id', 'text', 'speed', 'volume',
            'selected_audio_id', 'last_modified_user_id',
        ]
        update_fields = []
        params: list = []

        for field, value in kwargs.items():
            if field in allowed_fields:
                if field == 'sort_order':
                    value = float(value)
                if field == 'speed':
                    value = float(value)
                update_fields.append(f"{field} = %s")
                params.append(value)

        if not update_fields:
            logger.warning("No valid fields to update for storyboard_dialogue")
            return 0

        params.append(record_id)
        sql = f"UPDATE storyboard_dialogue SET {', '.join(update_fields)} WHERE id = %s"

        try:
            affected = execute_update(sql, tuple(params))
            logger.info(f"Updated storyboard_dialogue {record_id}, affected rows: {affected}")
            return affected
        except Exception as e:
            logger.error(f"Failed to update storyboard_dialogue {record_id}: {e}")
            raise

    @staticmethod
    def delete(record_id: int) -> int:
        sql = "DELETE FROM storyboard_dialogue WHERE id = %s"
        try:
            affected = execute_update(sql, (record_id,))
            logger.info(f"Deleted storyboard_dialogue {record_id}, affected rows: {affected}")
            return affected
        except Exception as e:
            logger.error(f"Failed to delete storyboard_dialogue {record_id}: {e}")
            raise

    @staticmethod
    def rebalance(scene_id: int) -> int:
        sql_select = (
            "SELECT id FROM storyboard_dialogue WHERE scene_id = %s "
            "ORDER BY sort_order ASC, id ASC"
        )
        try:
            rows = execute_query(sql_select, (scene_id,), fetch_all=True) or []
            if not rows:
                return 0
            sql_update = "UPDATE storyboard_dialogue SET sort_order = %s WHERE id = %s"
            for i, row in enumerate(rows):
                execute_update(sql_update, (float(i), row['id']))
            logger.info(f"Rebalanced {len(rows)} dialogues for scene {scene_id}")
            return len(rows)
        except Exception as e:
            logger.error(f"Failed to rebalance dialogues for scene {scene_id}: {e}")
            raise

    @staticmethod
    def next_sort_order(scene_id: int,
                        prev_sort: Optional[float],
                        next_sort: Optional[float]) -> float:
        mid = compute_sort_between(prev_sort, next_sort)
        if is_precision_exhausted(mid, prev_sort, next_sort):
            StoryboardDialogueModel.rebalance(scene_id)
            row = execute_query(
                "SELECT sort_order FROM storyboard_dialogue WHERE scene_id = %s "
                "ORDER BY sort_order ASC, id ASC",
                (scene_id,), fetch_all=True,
            ) or []
            if row:
                return float(row[-1]['sort_order']) + 1.0
            return 0.0
        return mid


# ==================== CREATE_TABLE_SQL ====================
CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS `storyboard_dialogue` (
    `id` INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    `scene_id` INT UNSIGNED NOT NULL,
    `sort_order` DOUBLE DEFAULT 0 COMMENT '对话顺序（浮点二分，同 storyboard_scene）',
    `character_id` INT UNSIGNED DEFAULT NULL COMMENT '说话角色; NULL=旁白',
    `text` TEXT DEFAULT NULL COMMENT '台词',
    `speed` DECIMAL(4,2) NOT NULL DEFAULT 1.00 COMMENT '语速',
    `volume` INT NOT NULL DEFAULT 100 COMMENT '音量 0-100',
    `selected_audio_id` INT UNSIGNED DEFAULT NULL COMMENT '当前选中配音 → storyboard_dialogue_audio.id',
    `last_modified_user_id` INT UNSIGNED DEFAULT NULL COMMENT '最后修改人',
    `create_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `update_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX `idx_scene` (`scene_id`, `sort_order`),
    INDEX `idx_character` (`character_id`),
    FOREIGN KEY (`scene_id`) REFERENCES `storyboard_scene`(`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='分镜对话表';
"""

__all__ = ["StoryboardDialogue", "StoryboardDialogueModel"]
