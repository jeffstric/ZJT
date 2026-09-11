"""视频成片对白音色替换任务。"""
from typing import Any, Dict, List, Optional
import json
import logging

from .database import execute_insert, execute_query, execute_update
from config.constant import VoiceReplaceConstants, VoiceReplaceJobStatus

logger = logging.getLogger(__name__)


class VideoVoiceReplaceJob:
    def __init__(self, **kwargs):
        self.id = kwargs.get("id")
        self.user_id = kwargs.get("user_id")
        self.source_type = kwargs.get("source_type")
        self.scene_id = kwargs.get("scene_id")
        self.workflow_id = kwargs.get("workflow_id")
        self.node_id = kwargs.get("node_id")
        self.source_video_url = kwargs.get("source_video_url")
        self.result_video_url = kwargs.get("result_video_url")
        self.status = kwargs.get("status", VoiceReplaceJobStatus.QUEUED)
        self.match_json = kwargs.get("match_json")
        self.skip_reason = kwargs.get("skip_reason")
        self.error_message = kwargs.get("error_message")
        self.create_at = kwargs.get("create_at")
        self.update_at = kwargs.get("update_at")

    def to_dict(self) -> Dict[str, Any]:
        match_json = self.match_json
        if isinstance(match_json, str):
            try:
                match_json = json.loads(match_json)
            except (TypeError, ValueError):
                pass
        return {
            "id": self.id,
            "user_id": self.user_id,
            "source_type": self.source_type,
            "scene_id": self.scene_id,
            "workflow_id": self.workflow_id,
            "node_id": self.node_id,
            "source_video_url": self.source_video_url,
            "result_video_url": self.result_video_url,
            "status": self.status,
            "match_json": match_json,
            "skip_reason": self.skip_reason,
            "error_message": self.error_message,
            "create_at": self.create_at.isoformat() if self.create_at else None,
            "update_at": self.update_at.isoformat() if self.update_at else None,
        }


class VideoVoiceReplaceSegment:
    def __init__(self, **kwargs):
        self.id = kwargs.get("id")
        self.job_id = kwargs.get("job_id")
        self.start_ms = kwargs.get("start_ms")
        self.end_ms = kwargs.get("end_ms")
        self.speaker_id = kwargs.get("speaker_id")
        self.asr_text = kwargs.get("asr_text")
        self.dialogue_id = kwargs.get("dialogue_id")
        self.character_id = kwargs.get("character_id")
        self.match_method = kwargs.get("match_method")
        self.match_confidence = kwargs.get("match_confidence")
        self.source_clip_url = kwargs.get("source_clip_url")
        self.converted_clip_url = kwargs.get("converted_clip_url")
        self.create_at = kwargs.get("create_at")
        self.update_at = kwargs.get("update_at")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "job_id": self.job_id,
            "start_ms": self.start_ms,
            "end_ms": self.end_ms,
            "speaker_id": self.speaker_id,
            "asr_text": self.asr_text,
            "dialogue_id": self.dialogue_id,
            "character_id": self.character_id,
            "match_method": self.match_method,
            "match_confidence": float(self.match_confidence) if self.match_confidence is not None else None,
            "source_clip_url": self.source_clip_url,
            "converted_clip_url": self.converted_clip_url,
            "create_at": self.create_at.isoformat() if self.create_at else None,
            "update_at": self.update_at.isoformat() if self.update_at else None,
        }


class VideoVoiceReplaceJobModel:
    @staticmethod
    def create(
        user_id: int,
        source_type: str,
        source_video_url: Optional[str] = None,
        scene_id: Optional[int] = None,
        workflow_id: Optional[str] = None,
        node_id: Optional[str] = None,
        status: str = VoiceReplaceJobStatus.QUEUED,
    ) -> int:
        sql = """
            INSERT INTO video_voice_replace_job
            (user_id, source_type, scene_id, workflow_id, node_id, source_video_url, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """
        return execute_insert(
            sql,
            (user_id, source_type, scene_id, workflow_id, node_id, source_video_url, status),
        )

    @staticmethod
    def get_by_id(record_id: int) -> Optional[VideoVoiceReplaceJob]:
        row = execute_query(
            "SELECT * FROM video_voice_replace_job WHERE id = %s",
            (record_id,),
            fetch_one=True,
        )
        return VideoVoiceReplaceJob(**row) if row else None

    @staticmethod
    def list_queued(limit: int = 1) -> List["VideoVoiceReplaceJob"]:
        rows = execute_query(
            """
            SELECT * FROM video_voice_replace_job
            WHERE status = %s
            ORDER BY id ASC
            LIMIT %s
            """,
            (VoiceReplaceJobStatus.QUEUED, int(limit)),
            fetch_all=True,
        ) or []
        return [VideoVoiceReplaceJob(**row) for row in rows]

    @staticmethod
    def claim(job_id: int, expected_status: str, new_status: str) -> bool:
        affected = execute_update(
            """
            UPDATE video_voice_replace_job
            SET status = %s
            WHERE id = %s AND status = %s
            """,
            (new_status, job_id, expected_status),
        )
        return bool(affected)

    @staticmethod
    def list_by_scene(scene_id: int) -> List[Dict]:
        return execute_query(
            """
            SELECT * FROM video_voice_replace_job
            WHERE scene_id = %s
            ORDER BY id DESC
            """,
            (scene_id,),
            fetch_all=True,
        ) or []

    @staticmethod
    def get_latest_by_scene(scene_id: int) -> Optional[VideoVoiceReplaceJob]:
        row = execute_query(
            """
            SELECT * FROM video_voice_replace_job
            WHERE scene_id = %s
            ORDER BY id DESC
            LIMIT 1
            """,
            (scene_id,),
            fetch_one=True,
        )
        return VideoVoiceReplaceJob(**row) if row else None

    @staticmethod
    def find_in_flight(scene_id: int, source_video_url: str) -> Optional[VideoVoiceReplaceJob]:
        inflight = list(VoiceReplaceConstants.IN_FLIGHT_STATUSES)
        marks = ", ".join(["%s"] * len(inflight))
        row = execute_query(
            f"""
            SELECT * FROM video_voice_replace_job
            WHERE scene_id = %s AND source_video_url = %s
              AND status IN ({marks})
            ORDER BY id DESC
            LIMIT 1
            """,
            (scene_id, source_video_url, *inflight),
            fetch_one=True,
        )
        return VideoVoiceReplaceJob(**row) if row else None

    @staticmethod
    def update_status(
        record_id: int,
        status: str,
        result_video_url: Optional[str] = None,
        match_json: Optional[Any] = None,
        skip_reason: Optional[str] = None,
        error_message: Optional[str] = None,
        source_video_url: Optional[str] = None,
    ) -> int:
        fields = ["status = %s"]
        params: List[Any] = [status]
        if result_video_url is not None:
            fields.append("result_video_url = %s")
            params.append(result_video_url)
        if match_json is not None:
            fields.append("match_json = %s")
            params.append(json.dumps(match_json, ensure_ascii=False) if not isinstance(match_json, str) else match_json)
        if skip_reason is not None:
            fields.append("skip_reason = %s")
            params.append(skip_reason)
        if error_message is not None:
            fields.append("error_message = %s")
            params.append(error_message)
        if source_video_url is not None:
            fields.append("source_video_url = %s")
            params.append(source_video_url)
        params.append(record_id)
        sql = f"UPDATE video_voice_replace_job SET {', '.join(fields)} WHERE id = %s"
        return execute_update(sql, tuple(params))


class VideoVoiceReplaceSegmentModel:
    @staticmethod
    def create(
        job_id: int,
        start_ms: int,
        end_ms: int,
        asr_text: Optional[str] = None,
        dialogue_id: Optional[int] = None,
        character_id: Optional[int] = None,
        match_method: Optional[str] = None,
        match_confidence: Optional[float] = None,
        speaker_id: Optional[str] = None,
        source_clip_url: Optional[str] = None,
        converted_clip_url: Optional[str] = None,
    ) -> int:
        sql = """
            INSERT INTO video_voice_replace_segment
            (job_id, start_ms, end_ms, speaker_id, asr_text, dialogue_id, character_id,
             match_method, match_confidence, source_clip_url, converted_clip_url)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        return execute_insert(
            sql,
            (
                job_id, start_ms, end_ms, speaker_id, asr_text, dialogue_id, character_id,
                match_method, match_confidence, source_clip_url, converted_clip_url,
            ),
        )

    @staticmethod
    def list_by_job(job_id: int) -> List[Dict]:
        return execute_query(
            """
            SELECT * FROM video_voice_replace_segment
            WHERE job_id = %s
            ORDER BY start_ms ASC, id ASC
            """,
            (job_id,),
            fetch_all=True,
        ) or []


CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS `video_voice_replace_job` (
    `id` INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    `user_id` INT UNSIGNED NOT NULL,
    `source_type` VARCHAR(32) NOT NULL COMMENT 'storyboard_scene | workflow_node',
    `scene_id` INT UNSIGNED DEFAULT NULL,
    `workflow_id` VARCHAR(64) DEFAULT NULL,
    `node_id` VARCHAR(64) DEFAULT NULL,
    `source_video_url` VARCHAR(1024) DEFAULT NULL,
    `result_video_url` VARCHAR(1024) DEFAULT NULL,
    `status` VARCHAR(32) NOT NULL DEFAULT 'queued',
    `match_json` JSON DEFAULT NULL,
    `skip_reason` VARCHAR(64) DEFAULT NULL,
    `error_message` VARCHAR(512) DEFAULT NULL,
    `create_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `update_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX `idx_user_status` (`user_id`, `status`),
    INDEX `idx_scene` (`scene_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='成片对白音色替换任务';

CREATE TABLE IF NOT EXISTS `video_voice_replace_segment` (
    `id` INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    `job_id` INT UNSIGNED NOT NULL,
    `start_ms` INT NOT NULL DEFAULT 0,
    `end_ms` INT NOT NULL DEFAULT 0,
    `speaker_id` VARCHAR(32) DEFAULT NULL,
    `asr_text` TEXT DEFAULT NULL,
    `dialogue_id` INT UNSIGNED DEFAULT NULL,
    `character_id` INT UNSIGNED DEFAULT NULL,
    `match_method` VARCHAR(32) DEFAULT NULL,
    `match_confidence` DECIMAL(6,4) DEFAULT NULL,
    `source_clip_url` VARCHAR(1024) DEFAULT NULL,
    `converted_clip_url` VARCHAR(1024) DEFAULT NULL,
    `create_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `update_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX `idx_job` (`job_id`, `start_ms`),
    CONSTRAINT `fk_voice_replace_seg_job` FOREIGN KEY (`job_id`)
        REFERENCES `video_voice_replace_job` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='成片对白音色替换切段';
"""

__all__ = [
    "VideoVoiceReplaceJob",
    "VideoVoiceReplaceJobModel",
    "VideoVoiceReplaceSegment",
    "VideoVoiceReplaceSegmentModel",
]
