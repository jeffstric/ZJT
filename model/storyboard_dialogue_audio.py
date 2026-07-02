"""
Storyboard dialogue audio model - database operations for storyboard_dialogue_audio table.
"""
from typing import Optional, Dict, Any, List
from .database import execute_query, execute_update, execute_insert
import logging

logger = logging.getLogger(__name__)


class StoryboardDialogueAudio:
    """StoryboardDialogueAudio entity class."""

    def __init__(self, **kwargs):
        self.id = kwargs.get('id')
        self.dialogue_id = kwargs.get('dialogue_id')
        self.ai_audio_id = kwargs.get('ai_audio_id')
        self.audio_url = kwargs.get('audio_url')
        self.create_at = kwargs.get('create_at')

    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'dialogue_id': self.dialogue_id,
            'ai_audio_id': self.ai_audio_id,
            'audio_url': self.audio_url,
            'create_at': self.create_at.isoformat() if self.create_at else None,
        }


class StoryboardDialogueAudioModel:
    """StoryboardDialogueAudio database operations."""

    @staticmethod
    def create(
        dialogue_id: int,
        ai_audio_id: Optional[int] = None,
        audio_url: Optional[str] = None,
    ) -> int:
        sql = """
            INSERT INTO storyboard_dialogue_audio
            (dialogue_id, ai_audio_id, audio_url)
            VALUES (%s, %s, %s)
        """
        params = (dialogue_id, ai_audio_id, audio_url)
        try:
            record_id = execute_insert(sql, params)
            logger.info(f"Created storyboard_dialogue_audio with ID: {record_id}")
            return record_id
        except Exception as e:
            logger.error(f"Failed to create storyboard_dialogue_audio: {e}")
            raise

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
    def delete(record_id: int) -> int:
        sql = "DELETE FROM storyboard_dialogue_audio WHERE id = %s"
        try:
            affected = execute_update(sql, (record_id,))
            logger.info(f"Deleted storyboard_dialogue_audio {record_id}, affected rows: {affected}")
            return affected
        except Exception as e:
            logger.error(f"Failed to delete storyboard_dialogue_audio {record_id}: {e}")
            raise


__all__ = ["StoryboardDialogueAudio", "StoryboardDialogueAudioModel"]
