"""
Storyboard Model - Database operations for storyboard / storyboard_scene /
storyboard_dialogue / storyboard_dialogue_audio / storyboard_scene_asset tables
"""
from typing import Optional, Dict, Any, List, Union
from .database import execute_query, execute_update, execute_insert, transaction, execute_insert_in_transaction
from config.constant import Edition
from config.unified_config import SceneVideoType
import logging
import json

logger = logging.getLogger(__name__)


# ==================== 浮点二分排序（sort_order）====================

def compute_sort_between(left_value: Optional[Union[int, float]],
                         right_value: Optional[Union[int, float]]) -> float:
    """
    浮点二分：计算在 left_value 与 right_value 之间插入的 sort_order。

    - left_value 为 None：插到最前，返回 right_value - 1
    - right_value 为 None：插到最后，返回 left_value + 1
    - 两者都有：返回 (left + right) / 2
    """
    if left_value is None and right_value is None:
        return 0.0
    if left_value is None:
        return float(right_value) - 1.0
    if right_value is None:
        return float(left_value) + 1.0
    return (float(left_value) + float(right_value)) / 2.0


def is_precision_exhausted(mid: float,
                           left_value: Optional[Union[int, float]],
                           right_value: Optional[Union[int, float]]) -> bool:
    """
    检测浮点二分是否精度耗尽：mid 等于 left 或 right（IEEE-754 舍入导致无法区分相邻值）。
    返回 True 时调用方应 rebalance 后重算。
    """
    mid_f = float(mid)
    if left_value is not None and mid_f == float(left_value):
        return True
    if right_value is not None and mid_f == float(right_value):
        return True
    return False


# ==================== Entity Classes ====================

class Storyboard:
    """Storyboard entity class"""

    def __init__(self, **kwargs):
        self.id = kwargs.get('id')
        self.world_id = kwargs.get('world_id')
        self.user_id = kwargs.get('user_id')
        self.episode_number = kwargs.get('episode_number')
        self.workflow_id = kwargs.get('workflow_id')
        self.script_id = kwargs.get('script_id')
        self.title = kwargs.get('title')
        self.total_duration = kwargs.get('total_duration')
        self.status = kwargs.get('status')
        self.style = kwargs.get('style')
        self.style_reference_image = kwargs.get('style_reference_image')
        self.workflow_ratio = kwargs.get('workflow_ratio')
        self.composition_preference = kwargs.get('composition_preference')
        self.config_json = kwargs.get('config_json')
        self.create_at = kwargs.get('create_at')
        self.update_at = kwargs.get('update_at')

    def to_dict(self) -> Dict[str, Any]:
        config_json = self.config_json
        if isinstance(config_json, str):
            try:
                config_json = json.loads(config_json)
            except Exception:
                pass

        return {
            'id': self.id,
            'world_id': self.world_id,
            'user_id': self.user_id,
            'episode_number': self.episode_number,
            'workflow_id': self.workflow_id,
            'script_id': self.script_id,
            'title': self.title,
            'total_duration': self.total_duration,
            'status': self.status,
            'style': self.style,
            'style_reference_image': self.style_reference_image,
            'workflow_ratio': self.workflow_ratio,
            'composition_preference': self.composition_preference,
            'config_json': config_json,
            'create_at': self.create_at.isoformat() if self.create_at else None,
            'update_at': self.update_at.isoformat() if self.update_at else None,
        }


class StoryboardScene:
    """StoryboardScene entity class（2026-06-24 重构：精简字段 + 选中指针 + video_type）"""

    def __init__(self, **kwargs):
        self.id = kwargs.get('id')
        self.storyboard_id = kwargs.get('storyboard_id')
        self.sort_order = kwargs.get('sort_order')
        self.title = kwargs.get('title')
        self.duration = kwargs.get('duration')
        self.prompt_json = kwargs.get('prompt_json')
        self.video_prompt = kwargs.get('video_prompt')
        self.video_type = kwargs.get('video_type')
        self.video_config_json = kwargs.get('video_config_json')
        self.selected_first_frame_id = kwargs.get('selected_first_frame_id')
        self.selected_last_frame_id = kwargs.get('selected_last_frame_id')
        self.selected_video_id = kwargs.get('selected_video_id')
        self.last_modified_user_id = kwargs.get('last_modified_user_id')
        self.create_at = kwargs.get('create_at')
        self.update_at = kwargs.get('update_at')

    def to_dict(self) -> Dict[str, Any]:
        def _parse_json(val):
            if isinstance(val, str):
                try:
                    return json.loads(val)
                except Exception:
                    pass
            return val

        return {
            'id': self.id,
            'storyboard_id': self.storyboard_id,
            'sort_order': float(self.sort_order) if self.sort_order is not None else 0.0,
            'title': self.title,
            'duration': self.duration,
            'prompt_json': _parse_json(self.prompt_json),
            'video_prompt': self.video_prompt,
            'video_type': self.video_type,
            'video_config_json': _parse_json(self.video_config_json),
            'selected_first_frame_id': self.selected_first_frame_id,
            'selected_last_frame_id': self.selected_last_frame_id,
            'selected_video_id': self.selected_video_id,
            'last_modified_user_id': self.last_modified_user_id,
            'create_at': self.create_at.isoformat() if self.create_at else None,
            'update_at': self.update_at.isoformat() if self.update_at else None,
        }


class StoryboardDialogue:
    """StoryboardDialogue entity class（分镜对话/旁白）"""

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


class StoryboardDialogueAudio:
    """StoryboardDialogueAudio entity class（配音生成历史）"""

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


class StoryboardSceneAsset:
    """StoryboardSceneAsset entity class（分镜图片/视频资产候选与历史）"""

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


# ==================== Storyboard Model ====================

class StoryboardModel:
    """Storyboard 数据库操作"""

    @staticmethod
    def create(
        user_id: int,
        world_id: int,
        episode_number: int = 1,
        workflow_id: Optional[int] = None,
        script_id: Optional[int] = None,
        title: str = '',
        style: Optional[str] = None,
        style_reference_image: Optional[str] = None,
        workflow_ratio: Optional[str] = None,
        composition_preference: Optional[str] = None,
        config_json: Optional[Dict] = None,
    ) -> int:
        sql = """
            INSERT INTO storyboard
            (world_id, user_id, episode_number, workflow_id, script_id, title,
             style, style_reference_image, workflow_ratio, composition_preference, config_json)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        config_str = json.dumps(config_json) if config_json else None
        params = (world_id, user_id, episode_number, workflow_id, script_id, title,
                  style, style_reference_image, workflow_ratio, composition_preference, config_str)
        try:
            record_id = execute_insert(sql, params)
            logger.info(f"Created storyboard with ID: {record_id}")
            return record_id
        except Exception as e:
            logger.error(f"Failed to create storyboard: {e}")
            raise

    @staticmethod
    def get_by_id(record_id: int) -> Optional[Storyboard]:
        sql = "SELECT * FROM storyboard WHERE id = %s"
        try:
            result = execute_query(sql, (record_id,), fetch_one=True)
            if result:
                return Storyboard(**result)
            return None
        except Exception as e:
            logger.error(f"Failed to get storyboard by ID {record_id}: {e}")
            raise

    @staticmethod
    def get_by_user_world_episode(user_id: int, world_id: int, episode_number: int) -> Optional[Storyboard]:
        """幂等查询：按 user_id + world_id + episode_number 查找"""
        sql = "SELECT * FROM storyboard WHERE user_id = %s AND world_id = %s AND episode_number = %s"
        try:
            result = execute_query(sql, (user_id, world_id, episode_number), fetch_one=True)
            if result:
                return Storyboard(**result)
            return None
        except Exception as e:
            logger.error(f"Failed to get storyboard by user/world/episode: {e}")
            raise

    @staticmethod
    def list_by_user(
        user_id: int,
        page: int = 1,
        page_size: int = 20,
        order_by: str = 'update_at',
        order_direction: str = 'DESC',
        keyword: Optional[str] = None,
    ) -> Dict[str, Any]:
        valid_order_fields = ['id', 'create_at', 'update_at', 'title', 'episode_number']
        valid_directions = ['ASC', 'DESC']
        if order_by not in valid_order_fields:
            order_by = 'update_at'
        if order_direction.upper() not in valid_directions:
            order_direction = 'DESC'

        where_conditions = []
        params: list = []

        # 独立空间模式才按 user_id 过滤
        if Edition.is_space_isolated():
            where_conditions.append("user_id = %s")
            params.append(user_id)

        if keyword:
            where_conditions.append("title LIKE %s")
            params.append(f"%{keyword}%")

        where_clause = " AND ".join(where_conditions) if where_conditions else "1=1"

        count_sql = f"SELECT COUNT(*) as total FROM storyboard WHERE {where_clause}"
        count_result = execute_query(count_sql, tuple(params), fetch_one=True)
        total = count_result['total'] if count_result else 0

        offset = (page - 1) * page_size
        data_sql = f"""
            SELECT id, world_id, user_id, episode_number, workflow_id, script_id,
                   title, total_duration, status, style, style_reference_image,
                   workflow_ratio, composition_preference, create_at, update_at
            FROM storyboard
            WHERE {where_clause}
            ORDER BY {order_by} {order_direction}
            LIMIT %s OFFSET %s
        """
        params.extend([page_size, offset])

        try:
            results = execute_query(data_sql, tuple(params), fetch_all=True)
            items = [Storyboard(**row).to_dict() for row in results] if results else []
            return {'total': total, 'page': page, 'page_size': page_size, 'data': items}
        except Exception as e:
            logger.error(f"Failed to list storyboards: {e}")
            raise

    @staticmethod
    def list_folders_by_user(
        user_id: int,
        world_id: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        where_conditions = []
        params: list = []

        if Edition.is_space_isolated():
            where_conditions.append("sb.user_id = %s")
            params.append(user_id)

        if world_id is not None:
            where_conditions.append("sb.world_id = %s")
            params.append(world_id)

        where_clause = " AND ".join(where_conditions) if where_conditions else "1=1"
        sql = f"""
            SELECT sb.id, sb.world_id, sb.user_id, sb.episode_number, sb.workflow_id,
                   sb.script_id, sb.title, sb.status, sb.create_at, sb.update_at,
                   COUNT(sc.id) AS scene_count
            FROM storyboard sb
            LEFT JOIN storyboard_scene sc ON sc.storyboard_id = sb.id
            WHERE {where_clause}
            GROUP BY sb.id, sb.world_id, sb.user_id, sb.episode_number, sb.workflow_id,
                     sb.script_id, sb.title, sb.status, sb.create_at, sb.update_at
            ORDER BY sb.update_at DESC, sb.id DESC
        """

        try:
            results = execute_query(sql, tuple(params), fetch_all=True)
            return list(results) if results else []
        except Exception as e:
            logger.error(f"Failed to list storyboard folders: {e}")
            raise

    @staticmethod
    def update(record_id: int, **kwargs) -> int:
        allowed_fields = [
            'title', 'total_duration', 'status', 'style', 'style_reference_image',
            'workflow_ratio', 'composition_preference', 'workflow_id', 'script_id', 'config_json',
        ]
        update_fields = []
        params: list = []

        for field, value in kwargs.items():
            if field in allowed_fields:
                if field == 'config_json' and isinstance(value, dict):
                    value = json.dumps(value)
                update_fields.append(f"{field} = %s")
                params.append(value)

        if not update_fields:
            logger.warning("No valid fields to update for storyboard")
            return 0

        params.append(record_id)
        sql = f"UPDATE storyboard SET {', '.join(update_fields)} WHERE id = %s"

        try:
            affected = execute_update(sql, tuple(params))
            logger.info(f"Updated storyboard {record_id}, affected rows: {affected}")
            return affected
        except Exception as e:
            logger.error(f"Failed to update storyboard {record_id}: {e}")
            raise

    @staticmethod
    def delete(record_id: int) -> int:
        sql = "DELETE FROM storyboard WHERE id = %s"
        try:
            affected = execute_update(sql, (record_id,))
            logger.info(f"Deleted storyboard {record_id}, affected rows: {affected}")
            return affected
        except Exception as e:
            logger.error(f"Failed to delete storyboard {record_id}: {e}")
            raise

    @staticmethod
    def create_with_scenes(
        user_id: int,
        world_id: int,
        episode_number: int,
        scenes: List[Dict],
        workflow_id: Optional[int] = None,
        script_id: Optional[int] = None,
        title: str = '',
        style: Optional[str] = None,
        style_reference_image: Optional[str] = None,
        workflow_ratio: Optional[str] = None,
        composition_preference: Optional[str] = None,
        config_json: Optional[Dict] = None,
    ) -> int:
        """
        在事务中原子创建 storyboard + scenes + dialogues（幂等 get-or-create 的 create 部分）。

        scenes 元素结构：
            {
                'title': str, 'duration': int,
                'prompt': {perspective, style, scene_desc, character_desc},
                'video_prompt': str, 'video_type': str, 'video_config': dict,
                'dialogues': [{'character_id': int|None, 'text': str, 'speed': float, 'volume': int}, ...]
            }
        """
        config_str = json.dumps(config_json) if config_json else None

        insert_sb_sql = """
            INSERT INTO storyboard
            (world_id, user_id, episode_number, workflow_id, script_id, title,
             style, style_reference_image, workflow_ratio, composition_preference, config_json)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        insert_scene_sql = """
            INSERT INTO storyboard_scene
            (storyboard_id, sort_order, title, duration, prompt_json, video_prompt,
             video_type, video_config_json, last_modified_user_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        insert_dialogue_sql = """
            INSERT INTO storyboard_dialogue
            (scene_id, sort_order, character_id, text, speed, volume, last_modified_user_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """

        sb_params = (world_id, user_id, episode_number, workflow_id, script_id, title,
                     style, style_reference_image, workflow_ratio, composition_preference, config_str)

        with transaction() as conn:
            sb_id = execute_insert_in_transaction(conn, insert_sb_sql, sb_params)
            for i, scene_data in enumerate(scenes):
                prompt = scene_data.get('prompt')
                prompt_str = json.dumps(prompt, ensure_ascii=False) if prompt else None
                video_config = scene_data.get('video_config')
                video_config_str = json.dumps(video_config, ensure_ascii=False) if video_config else None
                scene_params = (
                    sb_id, float(i),
                    scene_data.get('title', f'分镜{i + 1}'),
                    scene_data.get('duration', 5),
                    prompt_str,
                    scene_data.get('video_prompt'),
                    scene_data.get('video_type', SceneVideoType.VIDEO),
                    video_config_str,
                    user_id,
                )
                scene_id = execute_insert_in_transaction(conn, insert_scene_sql, scene_params)
                for j, d in enumerate(scene_data.get('dialogues') or []):
                    d_params = (
                        scene_id, float(j),
                        d.get('character_id'),
                        d.get('text'),
                        d.get('speed', 1.0),
                        d.get('volume', 100),
                        user_id,
                    )
                    execute_insert_in_transaction(conn, insert_dialogue_sql, d_params)
            logger.info(f"Created storyboard {sb_id} with {len(scenes)} scenes")
            return sb_id


# ==================== StoryboardScene Model ====================

class StoryboardSceneModel:
    """StoryboardScene 数据库操作"""

    @staticmethod
    def create(
        storyboard_id: int,
        sort_order: float = 0.0,
        title: str = '',
        duration: int = 5,
        prompt_json: Optional[Dict] = None,
        video_prompt: Optional[str] = None,
        video_type: str = SceneVideoType.VIDEO,
        video_config_json: Optional[Dict] = None,
        last_modified_user_id: Optional[int] = None,
    ) -> int:
        sql = """
            INSERT INTO storyboard_scene
            (storyboard_id, sort_order, title, duration, prompt_json, video_prompt,
             video_type, video_config_json, last_modified_user_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        prompt_str = json.dumps(prompt_json, ensure_ascii=False) if prompt_json else None
        video_config_str = json.dumps(video_config_json, ensure_ascii=False) if video_config_json else None
        params = (storyboard_id, float(sort_order), title, duration, prompt_str, video_prompt,
                  video_type, video_config_str, last_modified_user_id)
        try:
            record_id = execute_insert(sql, params)
            logger.info(f"Created storyboard_scene with ID: {record_id}")
            return record_id
        except Exception as e:
            logger.error(f"Failed to create storyboard_scene: {e}")
            raise

    @staticmethod
    def get_by_id(record_id: int) -> Optional[StoryboardScene]:
        sql = "SELECT * FROM storyboard_scene WHERE id = %s"
        try:
            result = execute_query(sql, (record_id,), fetch_one=True)
            if result:
                return StoryboardScene(**result)
            return None
        except Exception as e:
            logger.error(f"Failed to get storyboard_scene by ID {record_id}: {e}")
            raise

    @staticmethod
    def list_by_storyboard(storyboard_id: int) -> List[Dict]:
        # LEFT JOIN 当前选中 asset 的 result_url，便于前端直接展示画面
        sql = """
            SELECT sc.*,
                   ff.result_url AS first_frame_url,
                   lf.result_url AS last_frame_url,
                   vd.result_url AS video_url
            FROM storyboard_scene sc
            LEFT JOIN storyboard_scene_asset ff ON ff.id = sc.selected_first_frame_id
            LEFT JOIN storyboard_scene_asset lf ON lf.id = sc.selected_last_frame_id
            LEFT JOIN storyboard_scene_asset vd ON vd.id = sc.selected_video_id
            WHERE sc.storyboard_id = %s
            ORDER BY sc.sort_order ASC, sc.id ASC
        """
        try:
            results = execute_query(sql, (storyboard_id,), fetch_all=True)
            out = []
            for row in (results or []):
                d = StoryboardScene(**row).to_dict()
                d['first_frame_url'] = row.get('first_frame_url')
                d['last_frame_url'] = row.get('last_frame_url')
                d['video_url'] = row.get('video_url')
                out.append(d)
            return out
        except Exception as e:
            logger.error(f"Failed to list scenes for storyboard {storyboard_id}: {e}")
            raise

    @staticmethod
    def update(record_id: int, **kwargs) -> int:
        allowed_fields = [
            'sort_order', 'title', 'duration', 'prompt_json', 'video_prompt',
            'video_type', 'video_config_json',
            'selected_first_frame_id', 'selected_last_frame_id', 'selected_video_id',
            'last_modified_user_id',
        ]
        update_fields = []
        params: list = []

        for field, value in kwargs.items():
            if field in allowed_fields:
                if field in ('prompt_json', 'video_config_json') and isinstance(value, dict):
                    value = json.dumps(value, ensure_ascii=False)
                if field == 'sort_order':
                    value = float(value)
                update_fields.append(f"{field} = %s")
                params.append(value)

        if not update_fields:
            logger.warning("No valid fields to update for storyboard_scene")
            return 0

        params.append(record_id)
        sql = f"UPDATE storyboard_scene SET {', '.join(update_fields)} WHERE id = %s"

        try:
            affected = execute_update(sql, tuple(params))
            logger.info(f"Updated storyboard_scene {record_id}, affected rows: {affected}")
            return affected
        except Exception as e:
            logger.error(f"Failed to update storyboard_scene {record_id}: {e}")
            raise

    @staticmethod
    def delete(record_id: int) -> int:
        sql = "DELETE FROM storyboard_scene WHERE id = %s"
        try:
            affected = execute_update(sql, (record_id,))
            logger.info(f"Deleted storyboard_scene {record_id}, affected rows: {affected}")
            return affected
        except Exception as e:
            logger.error(f"Failed to delete storyboard_scene {record_id}: {e}")
            raise

    @staticmethod
    def rebalance(storyboard_id: int) -> int:
        """
        对该 storyboard 下所有分镜按当前顺序重新分配 sort_order = 0, 1, 2, …
        用于浮点二分精度耗尽时重排。返回重排的记录数。
        """
        sql_select = (
            "SELECT id FROM storyboard_scene WHERE storyboard_id = %s "
            "ORDER BY sort_order ASC, id ASC"
        )
        try:
            rows = execute_query(sql_select, (storyboard_id,), fetch_all=True) or []
            if not rows:
                return 0
            sql_update = "UPDATE storyboard_scene SET sort_order = %s WHERE id = %s"
            for i, row in enumerate(rows):
                execute_update(sql_update, (float(i), row['id']))
            logger.info(f"Rebalanced {len(rows)} scenes for storyboard {storyboard_id}")
            return len(rows)
        except Exception as e:
            logger.error(f"Failed to rebalance scenes for storyboard {storyboard_id}: {e}")
            raise

    @staticmethod
    def next_sort_order(storyboard_id: int,
                        prev_sort: Optional[float],
                        next_sort: Optional[float]) -> float:
        """
        浮点二分：计算在 prev_sort 与 next_sort 之间插入的 sort_order。
        若精度耗尽，自动 rebalance(storyboard_id) 后按 prev/next 在重排序列中的新位置重算。
        """
        mid = compute_sort_between(prev_sort, next_sort)
        if is_precision_exhausted(mid, prev_sort, next_sort):
            StoryboardSceneModel.rebalance(storyboard_id)
            # 重排后重新定位 prev/next 的值（prev/next 是原邻居的值，重排后整体变 0,1,2...）
            # 简化：重排后插到 prev 对应记录之后
            if prev_sort is None:
                return 0.0
            # 找到原 prev_sort 对应的记录的新位置，插其后
            row = execute_query(
                "SELECT id, sort_order FROM storyboard_scene WHERE storyboard_id = %s "
                "ORDER BY sort_order ASC, id ASC",
                (storyboard_id,), fetch_all=True,
            ) or []
            # prev_sort 在重排前的值已无意义，按"插到末尾+1"的保守策略
            if row:
                last = row[-1]
                return float(last['sort_order']) + 1.0
            return 0.0
        return mid

    @staticmethod
    def duplicate(record_id: int) -> Optional[int]:
        """复制分镜（含对话，不含生成资产），返回新分镜 ID"""
        scene = StoryboardSceneModel.get_by_id(record_id)
        if not scene:
            return None

        def _loads(val):
            if isinstance(val, str):
                try:
                    return json.loads(val)
                except Exception:
                    return None
            return val

        prompt = _loads(scene.prompt_json)
        video_config = _loads(scene.video_config_json)

        new_id = StoryboardSceneModel.create(
            storyboard_id=scene.storyboard_id,
            sort_order=float(scene.sort_order) + 1.0 if scene.sort_order is not None else 0.0,
            title=f"{scene.title}(副本)" if scene.title else '分镜(副本)',
            duration=scene.duration,
            prompt_json=prompt if isinstance(prompt, dict) else None,
            video_prompt=scene.video_prompt,
            video_type=scene.video_type or SceneVideoType.VIDEO,
            video_config_json=video_config if isinstance(video_config, dict) else None,
            last_modified_user_id=scene.last_modified_user_id,
        )

        # 复制对话
        dialogues = StoryboardDialogueModel.list_by_scene(record_id)
        for d in dialogues:
            StoryboardDialogueModel.create(
                scene_id=new_id,
                sort_order=d.get('sort_order', 0.0),
                character_id=d.get('character_id'),
                text=d.get('text'),
                speed=d.get('speed', 1.0),
                volume=d.get('volume', 100),
                last_modified_user_id=scene.last_modified_user_id,
            )
        return new_id


# ==================== StoryboardDialogue Model ====================

class StoryboardDialogueModel:
    """StoryboardDialogue 数据库操作"""

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
        # LEFT JOIN 当前选中配音的 audio_url，便于前端直接播放
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
        """对该分镜下所有对话按当前顺序重新分配 sort_order = 0, 1, 2, …"""
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
        """浮点二分：在 prev_sort 与 next_sort 之间插入的 sort_order，精度耗尽自动 rebalance。"""
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


# ==================== StoryboardDialogueAudio Model ====================

class StoryboardDialogueAudioModel:
    """StoryboardDialogueAudio 数据库操作（配音生成历史）"""

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
        """设置某对话当前选中的配音（更新 storyboard_dialogue.selected_audio_id）"""
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


# ==================== StoryboardSceneAsset Model ====================

class StoryboardSceneAssetModel:
    """StoryboardSceneAsset 数据库操作（分镜图片/视频资产候选与历史）"""

    # asset_type → scene 表的选中指针列
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
        """
        列出某分镜的资产候选（可选按 asset_type 过滤），最新在前。
        """
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
        """
        设置某分镜某类型的当前选中资产（更新 storyboard_scene 对应的 selected_*_id 指针）。
        """
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
        """任务完成后回填结果 URL（与 ai_tool_id）"""
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


# ==================== CREATE_TABLE_SQL ====================

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS `storyboard` (
    `id` INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    `world_id` INT UNSIGNED NOT NULL COMMENT '关联世界ID',
    `user_id` INT UNSIGNED NOT NULL,
    `episode_number` INT NOT NULL DEFAULT 1 COMMENT '集数，一集一个故事板',
    `workflow_id` INT UNSIGNED DEFAULT NULL COMMENT '关联工作流ID（可选，一键转视频用）',
    `script_id` INT UNSIGNED DEFAULT NULL COMMENT '关联剧本ID',
    `title` VARCHAR(255) DEFAULT '' COMMENT '故事板标题',
    `total_duration` INT DEFAULT 0 COMMENT '总时长（秒）',
    `status` TINYINT DEFAULT 1 COMMENT '1=编辑中 2=已完成',
    `style` VARCHAR(255) DEFAULT NULL COMMENT '画风名称（同 video_workflow.style）',
    `style_reference_image` VARCHAR(500) DEFAULT NULL COMMENT '画风参考图URL',
    `workflow_ratio` VARCHAR(10) DEFAULT NULL COMMENT '画幅比例: 16:9 | 9:16',
    `composition_preference` VARCHAR(500) DEFAULT NULL COMMENT '构图倾向，来自 world.composition_preference',
    `config_json` JSON DEFAULT NULL COMMENT '全局配置: 分辨率/默认模型/UI状态',
    `create_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `update_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY `uk_user_world_episode` (`user_id`, `world_id`, `episode_number`),
    INDEX `idx_world_user` (`world_id`, `user_id`),
    INDEX `idx_workflow` (`workflow_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='故事板主表';

CREATE TABLE IF NOT EXISTS `storyboard_scene` (
    `id` INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    `storyboard_id` INT UNSIGNED NOT NULL,
    `sort_order` DOUBLE DEFAULT 0 COMMENT '排序序号（浮点二分，见文档 2.3.2）',
    `title` VARCHAR(255) DEFAULT '',
    `duration` INT DEFAULT 5,
    `prompt_json` JSON DEFAULT NULL COMMENT '画面提示词: perspective/style/scene_desc/character_desc',
    `video_prompt` TEXT DEFAULT NULL COMMENT '视频提示词（生视频/数字人动作描述）',
    `video_type` VARCHAR(32) NOT NULL DEFAULT 'video' COMMENT '分镜类型 image/video/digital_human，见 SceneVideoType',
    `video_config_json` JSON DEFAULT NULL COMMENT '视频生成参数偏好: 模型/分辨率/时长',
    `selected_first_frame_id` INT UNSIGNED DEFAULT NULL COMMENT '当前选中首帧 asset id',
    `selected_last_frame_id` INT UNSIGNED DEFAULT NULL COMMENT '当前选中尾帧 asset id',
    `selected_video_id` INT UNSIGNED DEFAULT NULL COMMENT '当前选中视频 asset id',
    `last_modified_user_id` INT UNSIGNED DEFAULT NULL COMMENT '最后修改人',
    `create_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `update_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX `idx_storyboard` (`storyboard_id`),
    INDEX `idx_sort` (`storyboard_id`, `sort_order`),
    INDEX `idx_video_type` (`video_type`),
    INDEX `idx_selected_video` (`selected_video_id`),
    FOREIGN KEY (`storyboard_id`) REFERENCES `storyboard`(`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='故事板分镜表';

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

CREATE TABLE IF NOT EXISTS `storyboard_dialogue_audio` (
    `id` INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    `dialogue_id` INT UNSIGNED NOT NULL,
    `ai_audio_id` INT DEFAULT NULL COMMENT '→ ai_audio.id（源表 int，不加外键）',
    `audio_url` VARCHAR(512) DEFAULT NULL COMMENT '配音结果 URL（冗余）',
    `create_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX `idx_dialogue` (`dialogue_id`),
    INDEX `idx_ai_audio` (`ai_audio_id`),
    FOREIGN KEY (`dialogue_id`) REFERENCES `storyboard_dialogue`(`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='分镜对话配音历史表';

CREATE TABLE IF NOT EXISTS `storyboard_scene_asset` (
    `id` INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    `scene_id` INT UNSIGNED NOT NULL,
    `ai_tool_id` INT DEFAULT NULL COMMENT '→ ai_tools.id（源表 int，不加外键）',
    `asset_type` VARCHAR(32) NOT NULL COMMENT 'first_frame / last_frame / video',
    `result_url` VARCHAR(512) DEFAULT NULL COMMENT '结果 URL（图片或视频，冗余）',
    `create_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX `idx_scene` (`scene_id`, `asset_type`),
    INDEX `idx_ai_tool` (`ai_tool_id`),
    FOREIGN KEY (`scene_id`) REFERENCES `storyboard_scene`(`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='分镜图片/视频资产表';
"""
