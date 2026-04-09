"""
MediaFileMapping Model - Database operations for media_file_mapping table
"""
import json
from typing import Optional, Dict, Any, List
from .database import execute_query, execute_update, execute_insert
import logging

logger = logging.getLogger(__name__)


class MediaFileEntity:
    """媒体文件关联实体类型枚举"""
    CACHE = 0         # 临时缓存（无实体关联）
    AI_TOOLS = 1      # ai_tools 表
    CHARACTER = 2      # character 表
    LOCATION = 3      # location 表
    PROPS = 4         # props 表
    WORKFLOW = 5      # 工作流上传

    @staticmethod
    def get_entity_name(value: int) -> str:
        """数字枚举转实体表名"""
        mapping = {
            MediaFileEntity.CACHE: 'cache',
            MediaFileEntity.AI_TOOLS: 'ai_tools',
            MediaFileEntity.CHARACTER: 'character',
            MediaFileEntity.LOCATION: 'location',
            MediaFileEntity.PROPS: 'props',
            MediaFileEntity.WORKFLOW: 'workflow',
        }
        return mapping.get(value, 'unknown')

    @staticmethod
    def from_entity_name(name: str) -> int:
        """实体表名转数字枚举"""
        mapping = {
            'cache': MediaFileEntity.CACHE,
            'ai_tools': MediaFileEntity.AI_TOOLS,
            'character': MediaFileEntity.CHARACTER,
            'location': MediaFileEntity.LOCATION,
            'props': MediaFileEntity.PROPS,
            'workflow': MediaFileEntity.WORKFLOW,
        }
        return mapping.get(name, 0)


class MediaFileMapping:
    """MediaFileMapping model class"""

    def __init__(self, **kwargs):
        self.id = kwargs.get('id')
        self.user_id = kwargs.get('user_id')
        self.local_path = kwargs.get('local_path')
        self.cloud_path = kwargs.get('cloud_path')
        self.policy_code = kwargs.get('policy_code')
        self.entity_type = kwargs.get('entity_type')
        self.source_id = kwargs.get('source_id')
        self.media_type = kwargs.get('media_type')
        self.original_url = kwargs.get('original_url')
        self.file_size = kwargs.get('file_size')
        self.status = kwargs.get('status')
        self.created_at = kwargs.get('created_at')
        self.updated_at = kwargs.get('updated_at')

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            'id': self.id,
            'user_id': self.user_id,
            'local_path': self.local_path,
            'cloud_path': self.cloud_path,
            'policy_code': self.policy_code,
            'entity_type': self.entity_type,
            'entity_name': MediaFileEntity.get_entity_name(self.entity_type) if self.entity_type else None,
            'source_id': self.source_id,
            'media_type': self.media_type,
            'original_url': self.original_url,
            'file_size': self.file_size,
            'status': self.status,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }


class MediaFileMappingModel:
    """MediaFileMapping database operations"""

    @staticmethod
    def create(
        user_id: Optional[int],
        local_path: str,
        cloud_path: Optional[str] = None,
        policy_code: str = 'media_cache',
        entity_type: Optional[int] = None,
        source_id: Optional[int] = None,
        media_type: Optional[str] = None,
        original_url: Optional[str] = None,
        file_size: Optional[int] = None
    ) -> int:
        """
        Create a new media file mapping record

        Args:
            user_id: User ID
            local_path: Local file relative path
            cloud_path: Cloud storage path
            policy_code: Policy code (never_expire/media_cache)
            entity_type: Entity type (MediaFileEntity enum int)
            source_id: Source ID (int, e.g., character_id, task_id)
            media_type: Media type (MIME type string)
            original_url: Original URL if any
            file_size: File size in bytes

        Returns:
            Inserted record ID
        """
        sql = """
            INSERT INTO media_file_mapping
            (user_id, local_path, cloud_path, policy_code, entity_type, source_id, media_type, original_url, file_size, status, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'active', NOW(), NOW())
        """
        params = (user_id, local_path, cloud_path, policy_code, entity_type, source_id, media_type, original_url, file_size)

        try:
            record_id = execute_insert(sql, params)
            logger.info(f"Created media_file_mapping record with ID: {record_id}")
            return record_id
        except Exception as e:
            logger.error(f"Failed to create media_file_mapping record: {e}")
            raise

    @staticmethod
    def get_by_id(record_id: int) -> Optional[MediaFileMapping]:
        """
        Get media file mapping record by ID

        Args:
            record_id: Record ID

        Returns:
            MediaFileMapping object or None
        """
        sql = "SELECT * FROM media_file_mapping WHERE id = %s"

        try:
            result = execute_query(sql, (record_id,), fetch_one=True)
            if result:
                return MediaFileMapping(**result)
            return None
        except Exception as e:
            logger.error(f"Failed to get media_file_mapping by ID {record_id}: {e}")
            raise

    @staticmethod
    def get_by_local_path(local_path: str) -> Optional[MediaFileMapping]:
        """
        Get media file mapping record by local path

        Args:
            local_path: Local file relative path

        Returns:
            MediaFileMapping object or None
        """
        sql = "SELECT * FROM media_file_mapping WHERE local_path = %s LIMIT 1"

        try:
            result = execute_query(sql, (local_path,), fetch_one=True)
            if result:
                return MediaFileMapping(**result)
            return None
        except Exception as e:
            logger.error(f"Failed to get media_file_mapping by local_path '{local_path}': {e}")
            raise

    @staticmethod
    def update_cloud_path(local_path: str, cloud_path: str) -> bool:
        """
        Update cloud path after successful upload

        Args:
            local_path: Local file relative path
            cloud_path: Cloud storage path

        Returns:
            True if updated successfully
        """
        sql = """
            UPDATE media_file_mapping
            SET cloud_path = %s, status = 'active'
            WHERE local_path = %s
        """

        try:
            affected_rows = execute_update(sql, (cloud_path, local_path))
            logger.info(f"Updated cloud_path for '{local_path}' to '{cloud_path}', affected rows: {affected_rows}")
            return affected_rows > 0
        except Exception as e:
            logger.error(f"Failed to update cloud_path for '{local_path}': {e}")
            raise

    @staticmethod
    def update_status(local_path: str, status: str) -> bool:
        """
        Update mapping status

        Args:
            local_path: Local file relative path
            status: New status (active/syncing/deleted)

        Returns:
            True if updated successfully
        """
        sql = "UPDATE media_file_mapping SET status = %s WHERE local_path = %s"

        try:
            affected_rows = execute_update(sql, (status, local_path))
            return affected_rows > 0
        except Exception as e:
            logger.error(f"Failed to update status for '{local_path}': {e}")
            raise

    @staticmethod
    def delete_by_local_path(local_path: str) -> int:
        """
        Delete mapping record by local path

        Args:
            local_path: Local file relative path

        Returns:
            Number of affected rows
        """
        sql = "DELETE FROM media_file_mapping WHERE local_path = %s"

        try:
            affected_rows = execute_update(sql, (local_path,))
            logger.info(f"Deleted media_file_mapping for '{local_path}', affected rows: {affected_rows}")
            return affected_rows
        except Exception as e:
            logger.error(f"Failed to delete media_file_mapping for '{local_path}': {e}")
            raise

    @staticmethod
    def get_expired_files_by_policy(policy_code: str, max_days: int) -> List[MediaFileMapping]:
        """
        Get expired files by policy code

        Args:
            policy_code: Policy code
            max_days: Maximum days before expiration

        Returns:
            List of MediaFileMapping objects
        """
        sql = """
            SELECT * FROM media_file_mapping
            WHERE policy_code = %s
            AND status = 'active'
            AND cloud_path IS NOT NULL
            AND created_at < DATE_SUB(NOW(), INTERVAL %s DAY)
        """

        try:
            results = execute_query(sql, (policy_code, max_days), fetch_all=True)
            return [MediaFileMapping(**row) for row in results] if results else []
        except Exception as e:
            logger.error(f"Failed to get expired files for policy '{policy_code}': {e}")
            raise

    @staticmethod
    def list_active(
        page: int = 1,
        page_size: int = 100,
        user_id: Optional[int] = None,
        policy_code: Optional[str] = None,
        entity_type: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        List active mapping records with pagination

        Args:
            page: Page number (starting from 1)
            page_size: Number of records per page
            user_id: Filter by user ID (optional)
            policy_code: Filter by policy code (optional)
            entity_type: Filter by entity type (optional)

        Returns:
            Dictionary with 'total', 'page', 'page_size', 'data' keys
        """
        where_conditions = ["status = 'active'"]
        params = []

        if user_id is not None:
            where_conditions.append("user_id = %s")
            params.append(user_id)

        if policy_code:
            where_conditions.append("policy_code = %s")
            params.append(policy_code)

        if entity_type:
            where_conditions.append("entity_type = %s")
            params.append(entity_type)

        where_clause = " AND ".join(where_conditions)

        count_sql = f"SELECT COUNT(*) as total FROM media_file_mapping WHERE {where_clause}"
        count_result = execute_query(count_sql, tuple(params), fetch_one=True)
        total = count_result['total'] if count_result else 0

        offset = (page - 1) * page_size
        data_sql = f"""
            SELECT * FROM media_file_mapping
            WHERE {where_clause}
            ORDER BY created_at DESC
            LIMIT %s OFFSET %s
        """

        params.extend([page_size, offset])

        try:
            results = execute_query(data_sql, tuple(params), fetch_all=True)
            mappings = [MediaFileMapping(**row).to_dict() for row in results] if results else []

            return {
                'total': total,
                'page': page,
                'page_size': page_size,
                'data': mappings
            }
        except Exception as e:
            logger.error(f"Failed to list active media_file_mapping: {e}")
            raise

    @staticmethod
    def get_total_size_by_user(user_id: int) -> int:
        """
        Get total file size for a user

        Args:
            user_id: User ID

        Returns:
            Total file size in bytes
        """
        sql = """
            SELECT COALESCE(SUM(file_size), 0) as total_size
            FROM media_file_mapping
            WHERE user_id = %s AND status = 'active'
        """

        try:
            result = execute_query(sql, (user_id,), fetch_one=True)
            return result['total_size'] if result else 0
        except Exception as e:
            logger.error(f"Failed to get total size for user {user_id}: {e}")
            raise

    @staticmethod
    def get_by_entity(entity_type: int, source_id: int) -> List[MediaFileMapping]:
        """
        Get all mapping records by entity type and ID

        Args:
            entity_type: Entity type (MediaFileEntity enum int)
            source_id: Source ID (entity table primary key)

        Returns:
            List of MediaFileMapping objects
        """
        sql = """
            SELECT * FROM media_file_mapping
            WHERE entity_type = %s AND source_id = %s AND status = 'active'
        """

        try:
            results = execute_query(sql, (entity_type, source_id), fetch_all=True)
            return [MediaFileMapping(**row) for row in results] if results else []
        except Exception as e:
            logger.error(f"Failed to get media_file_mapping by entity_type={entity_type}, source_id={source_id}: {e}")
            raise
