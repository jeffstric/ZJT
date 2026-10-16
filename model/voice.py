"""
Voice Model - Database operations for voice table
音色库数据模型（系统预置音色 + 用户私有音色）

provider 维度：
- volcengine      火山引擎（豆包语音）预置音色，voice_type 为火山音色 ID（如 BV700_streaming）
- reference_audio 参考音频克隆音色（预留给 IndexTTS 链路，audio_url 为克隆源音频）。
  预置行的 voice_type 是 SQL NULL，不能写成字符串 NULL。

user_id=0 为系统预置（种子来自 config/volcengine_tts_constants.py 的
VOLCENGINE_TTS_VOICES，由迁移 no_145 幂等插入）；user_id>0 为用户私有（二期）。
"""
from typing import List, Optional, Dict, Any
from datetime import datetime
from .database import execute_query, execute_update, execute_insert
import logging

logger = logging.getLogger(__name__)

PROVIDER_VOLCENGINE = 'volcengine'
PROVIDER_REFERENCE_AUDIO = 'reference_audio'


class Voice:
    """Voice model class (public voice when user_id=0, private voice when user_id>0)"""

    def __init__(self, **kwargs):
        self.id = kwargs.get('id')
        self.user_id = kwargs.get('user_id', 0)
        self.provider = kwargs.get('provider') or PROVIDER_VOLCENGINE
        self.voice_type = kwargs.get('voice_type')
        self.name = kwargs.get('name')
        self.description = kwargs.get('description')
        self.voice_desc = kwargs.get('voice_desc')
        self.gender = kwargs.get('gender')
        self.language = kwargs.get('language')
        self.style = kwargs.get('style')
        self.sample_url = kwargs.get('sample_url')
        self.audio_url = kwargs.get('audio_url')
        self.sort_order = kwargs.get('sort_order', 0)
        self.is_active = kwargs.get('is_active', 1)
        self.create_at = kwargs.get('create_at')
        self.update_at = kwargs.get('update_at')

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            'id': self.id,
            'user_id': self.user_id,
            'provider': self.provider,
            'voice_type': self.voice_type,
            'name': self.name,
            'description': self.description,
            'voice_desc': self.voice_desc,
            'gender': self.gender,
            'language': self.language,
            'style': self.style,
            'sample_url': self.sample_url,
            'audio_url': self.audio_url,
            'sort_order': self.sort_order,
            'is_active': self.is_active,
            'create_at': self.create_at.isoformat() if self.create_at else None,
            'update_at': self.update_at.isoformat() if self.update_at else None
        }


class VoiceModel:
    """Voice database operations"""

    @staticmethod
    def create(
        name: str,
        provider: str = PROVIDER_VOLCENGINE,
        voice_type: Optional[str] = None,
        user_id: int = 0,
        description: Optional[str] = None,
        gender: Optional[str] = None,
        language: Optional[str] = None,
        style: Optional[str] = None,
        sample_url: Optional[str] = None,
        audio_url: Optional[str] = None,
        sort_order: int = 0,
        is_active: int = 1
    ) -> int:
        """
        Create a new voice record

        Args:
            name: Voice display name
            provider: 'volcengine' or 'reference_audio'
            voice_type: 火山音色 ID（provider=volcengine 必填）
            user_id: User ID (0 for public voice, >0 for private voice)
            description: Voice description (optional)
            gender: 'female' / 'male' / 'child' (optional)
            language: 'zh' / 'zh-dialect' / 'en' ... (optional)
            style: 风格标签，如"温柔知性" (optional)
            sample_url: 试听音频 URL (optional)
            audio_url: 参考音频 URL（provider=reference_audio 时为克隆源）
            sort_order: Sort order (default: 0)
            is_active: Is active flag (default: 1)

        Returns:
            Inserted record ID
        """
        sql = """
            INSERT INTO voice
            (user_id, provider, voice_type, name, description, gender, language,
             style, sample_url, audio_url, sort_order, is_active)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        params = (user_id, provider, voice_type, name, description, gender,
                  language, style, sample_url, audio_url, sort_order, is_active)

        try:
            record_id = execute_insert(sql, params)
            logger.info(f"Created voice record with ID: {record_id}, user_id: {user_id}, provider: {provider}")
            return record_id
        except Exception as e:
            logger.error(f"Failed to create voice record: {e}")
            raise

    @staticmethod
    def get_by_id(record_id: int) -> Optional[Voice]:
        """
        Get voice record by ID
        """
        sql = "SELECT * FROM voice WHERE id = %s"

        try:
            result = execute_query(sql, (record_id,), fetch_one=True)
            if result:
                return Voice(**result)
            return None
        except Exception as e:
            logger.error(f"Failed to get voice record by ID {record_id}: {e}")
            raise

    @staticmethod
    def get_by_voice_type(voice_type: str, provider: str = PROVIDER_VOLCENGINE) -> Optional[Voice]:
        """按火山音色 ID 查询（系统预置音色的业务键）"""
        sql = "SELECT * FROM voice WHERE voice_type = %s AND provider = %s ORDER BY user_id ASC LIMIT 1"
        try:
            result = execute_query(sql, (voice_type, provider), fetch_one=True)
            return Voice(**result) if result else None
        except Exception as e:
            logger.error(f"Failed to get voice by voice_type {voice_type}: {e}")
            raise

    @staticmethod
    def list_all(
        page: int = 1,
        page_size: int = 100,
        user_id: Optional[int] = None,
        provider: Optional[str] = None,
        gender: Optional[str] = None,
        language: Optional[str] = None,
        only_active: bool = True,
        keyword: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Get voice records list with pagination and filtering

        Args:
            page: Page number (starting from 1)
            page_size: Number of records per page (default: 100)
            user_id: Filter by user_id（None=全部；0=系统预置；>0=指定用户）
            provider: Filter by provider (optional)
            gender: Filter by gender (optional)
            language: Filter by language (optional)
            only_active: Only return active records (default: True)
            keyword: Search keyword for name/description (optional)

        Returns:
            Dictionary with 'total', 'page', 'page_size', 'data' keys
        """
        where_conditions = []
        params = []

        if only_active:
            where_conditions.append("is_active = 1")

        if user_id is not None:
            where_conditions.append("user_id = %s")
            params.append(user_id)

        if provider:
            where_conditions.append("provider = %s")
            params.append(provider)

        if gender:
            where_conditions.append("gender = %s")
            params.append(gender)

        if language:
            where_conditions.append("language = %s")
            params.append(language)

        if keyword:
            where_conditions.append("(name LIKE %s OR description LIKE %s)")
            kw = f"%{keyword}%"
            params.extend([kw, kw])

        where_clause = " AND ".join(where_conditions) if where_conditions else "1=1"

        count_sql = f"SELECT COUNT(*) as total FROM voice WHERE {where_clause}"
        count_result = execute_query(count_sql, tuple(params), fetch_one=True)
        total = count_result['total'] if count_result else 0

        offset = (page - 1) * page_size
        data_sql = f"""
            SELECT * FROM voice
            WHERE {where_clause}
            ORDER BY sort_order ASC, id ASC
            LIMIT %s OFFSET %s
        """

        params.extend([page_size, offset])

        try:
            results = execute_query(data_sql, tuple(params), fetch_all=True)
            voices = [Voice(**row).to_dict() for row in results] if results else []

            return {
                'total': total,
                'page': page,
                'page_size': page_size,
                'data': voices
            }
        except Exception as e:
            logger.error(f"Failed to list voices: {e}")
            raise

    @staticmethod
    def update(
        record_id: int,
        **kwargs
    ) -> int:
        """
        Update voice record

        Args:
            record_id: Record ID
            **kwargs: Fields to update
        """
        allowed_fields = ['user_id', 'provider', 'voice_type', 'name', 'description', 'voice_desc',
                          'sample_url', 'audio_url', 'gender', 'language', 'style',
                          'sort_order', 'is_active']

        update_fields = []
        params = []

        for field, value in kwargs.items():
            if field in allowed_fields:
                update_fields.append(f"{field} = %s")
                params.append(value)

        if not update_fields:
            logger.warning("No valid fields to update")
            return 0

        params.append(record_id)
        sql = f"UPDATE voice SET {', '.join(update_fields)} WHERE id = %s"

        try:
            affected_rows = execute_update(sql, tuple(params))
            logger.info(f"Updated voice record {record_id}, affected rows: {affected_rows}")
            return affected_rows
        except Exception as e:
            logger.error(f"Failed to update voice record: {e}")
            raise

    @staticmethod
    def delete(record_id: int) -> int:
        """
        Delete voice record by ID
        """
        sql = "DELETE FROM voice WHERE id = %s"

        try:
            affected_rows = execute_update(sql, (record_id,))
            logger.info(f"Deleted voice record {record_id}, affected rows: {affected_rows}")
            return affected_rows
        except Exception as e:
            logger.error(f"Failed to delete voice record: {e}")
            raise


# 与迁移 no_145_*_create_voice_library_volcengine_tts 保持一致；
# 字段语义见文件头部 docstring。
CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS `voice` (
  `id` int NOT NULL AUTO_INCREMENT,
  `user_id` int NOT NULL DEFAULT 0 COMMENT '0=系统预置音色，>0=用户私有音色',
  `provider` varchar(32) NOT NULL DEFAULT 'volcengine' COMMENT '音色提供方: volcengine/reference_audio',
  `voice_type` varchar(128) DEFAULT NULL COMMENT '提供方音色ID，如 BV700_streaming',
  `name` varchar(128) NOT NULL COMMENT '显示名',
  `description` varchar(512) DEFAULT NULL COMMENT '一句话人设描述',
  `voice_desc` varchar(1000) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '声学音色指纹（音频理解模型听预置样本生成，角色选用该音色时作为文字指纹）',
  `gender` varchar(16) DEFAULT NULL COMMENT 'female/male/child',
  `language` varchar(32) DEFAULT NULL COMMENT 'zh/zh-dialect/en 等',
  `style` varchar(64) DEFAULT NULL COMMENT '风格标签，如 温柔知性',
  `sample_url` varchar(512) DEFAULT NULL COMMENT '试听音频URL',
  `audio_url` varchar(512) DEFAULT NULL COMMENT '参考音频URL（reference_audio 克隆源）',
  `sort_order` int NOT NULL DEFAULT 0,
  `is_active` tinyint NOT NULL DEFAULT 1,
  `create_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `update_at` datetime DEFAULT NULL ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_provider` (`provider`),
  KEY `idx_user_id` (`user_id`),
  KEY `idx_voice_type` (`voice_type`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
"""
