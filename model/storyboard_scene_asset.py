"""
Storyboard scene asset model - database operations for storyboard_scene_asset table.
"""
from typing import Optional, Dict, Any, List
from .database import execute_query, execute_update, execute_insert
import logging

logger = logging.getLogger(__name__)


class StoryboardSceneAsset:
    """StoryboardSceneAsset entity class."""

    def __init__(self, **kwargs):
        self.id = kwargs.get('id')
        self.scene_id = kwargs.get('scene_id')
        self.ai_tool_id = kwargs.get('ai_tool_id')
        self.asset_type = kwargs.get('asset_type')
        self.result_url = kwargs.get('result_url')
        self.create_at = kwargs.get('create_at')

    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'scene_id': self.scene_id,
            'ai_tool_id': self.ai_tool_id,
            'asset_type': self.asset_type,
            'result_url': self.result_url,
            'create_at': self.create_at.isoformat() if self.create_at else None,
        }


class StoryboardSceneAssetModel:
    """StoryboardSceneAsset database operations."""

    _SELECT_COLUMN_MAP = {
        'first_frame': 'selected_first_frame_id',
        'last_frame': 'selected_last_frame_id',
        'video': 'selected_video_id',
    }

    @staticmethod
    def create(
        scene_id: int,
        asset_type: str,
        ai_tool_id: Optional[int] = None,
        result_url: Optional[str] = None,
    ) -> int:
        sql = """
            INSERT INTO storyboard_scene_asset
            (scene_id, ai_tool_id, asset_type, result_url)
            VALUES (%s, %s, %s, %s)
        """
        params = (scene_id, ai_tool_id, asset_type, result_url)
        try:
            record_id = execute_insert(sql, params)
            logger.info(f"Created storyboard_scene_asset with ID: {record_id}")
            return record_id
        except Exception as e:
            logger.error(f"Failed to create storyboard_scene_asset: {e}")
            raise

    @staticmethod
    def get_by_id(record_id: int) -> Optional[StoryboardSceneAsset]:
        sql = "SELECT * FROM storyboard_scene_asset WHERE id = %s"
        try:
            result = execute_query(sql, (record_id,), fetch_one=True)
            if result:
                return StoryboardSceneAsset(**result)
            return None
        except Exception as e:
            logger.error(f"Failed to get storyboard_scene_asset by ID {record_id}: {e}")
            raise

    @staticmethod
    def list_by_scene(scene_id: int, asset_type: Optional[str] = None) -> List[Dict]:
        if asset_type:
            sql = """
                SELECT * FROM storyboard_scene_asset
                WHERE scene_id = %s AND asset_type = %s
                ORDER BY create_at DESC, id DESC
            """
            params = (scene_id, asset_type)
        else:
            sql = """
                SELECT * FROM storyboard_scene_asset
                WHERE scene_id = %s
                ORDER BY create_at DESC, id DESC
            """
            params = (scene_id,)
        try:
            results = execute_query(sql, params, fetch_all=True)
            return [StoryboardSceneAsset(**row).to_dict() for row in results] if results else []
        except Exception as e:
            logger.error(f"Failed to list assets for scene {scene_id}: {e}")
            raise

    @staticmethod
    def set_selected(scene_id: int, asset_type: str, asset_id: int) -> int:
        column = StoryboardSceneAssetModel._SELECT_COLUMN_MAP.get(asset_type)
        if not column:
            raise ValueError(f"unknown asset_type: {asset_type}")
        sql = f"UPDATE storyboard_scene SET {column} = %s WHERE id = %s"
        try:
            affected = execute_update(sql, (asset_id, scene_id))
            logger.info(f"Set selected {asset_type} asset {asset_id} for scene {scene_id}")
            return affected
        except Exception as e:
            logger.error(f"Failed to set selected asset for scene {scene_id}: {e}")
            raise

    @staticmethod
    def update_result(record_id: int, result_url: Optional[str], ai_tool_id: Optional[int] = None) -> int:
        fields = []
        params: list = []
        if result_url is not None:
            fields.append("result_url = %s")
            params.append(result_url)
        if ai_tool_id is not None:
            fields.append("ai_tool_id = %s")
            params.append(ai_tool_id)
        if not fields:
            return 0
        params.append(record_id)
        sql = f"UPDATE storyboard_scene_asset SET {', '.join(fields)} WHERE id = %s"
        try:
            affected = execute_update(sql, tuple(params))
            logger.info(f"Updated storyboard_scene_asset {record_id}, affected rows: {affected}")
            return affected
        except Exception as e:
            logger.error(f"Failed to update storyboard_scene_asset {record_id}: {e}")
            raise

    @staticmethod
    def delete(record_id: int) -> int:
        sql = "DELETE FROM storyboard_scene_asset WHERE id = %s"
        try:
            affected = execute_update(sql, (record_id,))
            logger.info(f"Deleted storyboard_scene_asset {record_id}, affected rows: {affected}")
            return affected
        except Exception as e:
            logger.error(f"Failed to delete storyboard_scene_asset {record_id}: {e}")
            raise


__all__ = ["StoryboardSceneAsset", "StoryboardSceneAssetModel"]
