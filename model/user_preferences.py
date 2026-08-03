"""
User Preferences Model - 用户偏好配置持久化存储
支持生图模型、图片偏好、视频偏好等配置的数据库持久化
"""
from typing import Optional, Dict, Any
from .database import execute_query, execute_update, execute_insert
import logging
import json

logger = logging.getLogger(__name__)


class UserPreference:
    """UserPreference entity class"""

    def __init__(self, **kwargs):
        self.id = kwargs.get('id')
        self.user_id = kwargs.get('user_id')
        self.world_id = kwargs.get('world_id')
        self.pref_type = kwargs.get('pref_type')
        self.config_value = kwargs.get('config_value')
        self.create_at = kwargs.get('create_at')
        self.update_at = kwargs.get('update_at')

    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'user_id': self.user_id,
            'world_id': self.world_id,
            'pref_type': self.pref_type,
            'config_value': self.get_value(),
            'create_at': self.create_at.isoformat() if self.create_at else None,
            'update_at': self.update_at.isoformat() if self.update_at else None,
        }

    def get_value(self) -> Any:
        """解析 config_value JSON"""
        if self.config_value is None:
            return None
        if isinstance(self.config_value, str):
            try:
                return json.loads(self.config_value)
            except (json.JSONDecodeError, TypeError):
                return self.config_value
        return self.config_value


class UserPreferencesModel:
    """User preferences database operations"""

    @staticmethod
    def get(user_id: str, world_id: str, pref_type: str) -> Optional[UserPreference]:
        """获取用户偏好"""
        sql = """
            SELECT id, user_id, world_id, pref_type, config_value, create_at, update_at
            FROM user_preferences
            WHERE user_id = %s AND world_id = %s AND pref_type = %s
        """
        try:
            result = execute_query(sql, (user_id, world_id, pref_type), fetch_one=True)
            if result:
                return UserPreference(**result)
            return None
        except Exception as e:
            logger.error(f"Failed to get preference {pref_type} for user {user_id}: {e}")
            raise

    @staticmethod
    def upsert(user_id: str, world_id: str, pref_type: str, config_value: Any) -> int:
        """创建或更新用户偏好（INSERT ON DUPLICATE KEY UPDATE）"""
        value_json = json.dumps(config_value, ensure_ascii=False)
        sql = """
            INSERT INTO user_preferences (user_id, world_id, pref_type, config_value)
            VALUES (%s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE config_value = VALUES(config_value)
        """
        try:
            result = execute_update(sql, (user_id, world_id, pref_type, value_json))
            logger.info(f"Upserted preference {pref_type} for user {user_id}, world {world_id}")
            return result
        except Exception as e:
            logger.error(f"Failed to upsert preference {pref_type} for user {user_id}: {e}")
            raise

    @staticmethod
    def delete(user_id: str, world_id: str, pref_type: str) -> bool:
        """删除用户偏好"""
        sql = "DELETE FROM user_preferences WHERE user_id = %s AND world_id = %s AND pref_type = %s"
        try:
            affected = execute_update(sql, (user_id, world_id, pref_type))
            return affected > 0
        except Exception as e:
            logger.error(f"Failed to delete preference {pref_type} for user {user_id}: {e}")
            raise


# 偏好类型常量
PREF_TYPE_TEXT_TO_IMAGE_MODEL = "text_to_image_model"
PREF_TYPE_IMAGE_PREFERENCES = "image_preferences"
PREF_TYPE_VIDEO_PREFERENCES = "video_preferences"
PREF_TYPE_TEXT_TO_VIDEO_MODEL = "text_to_video_model"
PREF_TYPE_IMAGE_TO_VIDEO_MODEL = "image_to_video_model"
# 世界级默认对话模型：{model, model_id, vendor_id, name?}
PREF_TYPE_DEFAULT_LLM_MODEL = "default_llm_model"

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS `user_preferences` (
  `id` int NOT NULL AUTO_INCREMENT,
  `user_id` varchar(128) COLLATE utf8mb4_unicode_ci NOT NULL,
  `world_id` varchar(128) COLLATE utf8mb4_unicode_ci NOT NULL,
  `pref_type` varchar(64) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT 'text_to_image_model|image_preferences|video_preferences|text_to_video_model|image_to_video_model|default_llm_model|media_pref.*',
  `config_value` json NOT NULL,
  `create_at` datetime DEFAULT CURRENT_TIMESTAMP,
  `update_at` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_user_pref` (`user_id`, `world_id`, `pref_type`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""
