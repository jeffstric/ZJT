"""
Storyboard Model - database operations for storyboard table and aggregate helpers.
"""
from typing import Optional, Dict, Any, List
from .database import execute_query, execute_update, execute_insert, transaction, execute_insert_in_transaction
from .storyboard_scene import (
    StoryboardScene,
    StoryboardSceneModel,
    compute_sort_between,
    is_precision_exhausted,
)
from .storyboard_dialogue import StoryboardDialogue, StoryboardDialogueModel
from .storyboard_dialogue_audio import StoryboardDialogueAudio, StoryboardDialogueAudioModel
from .storyboard_scene_asset import StoryboardSceneAsset, StoryboardSceneAssetModel
from .world import WorldModel
from config.constant import Edition, SceneDifficulty
from config.unified_config import SceneVideoType
import logging
import json

logger = logging.getLogger(__name__)


# ==================== Entity Classes ====================

class Storyboard:
    """Storyboard entity class"""

    def __init__(self, **kwargs):
        self.id = kwargs.get('id')
        self.version = kwargs.get('version', 1)
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
            'version': self.version,
            'world_id': self.world_id,
            'user_id': self.user_id,
            'episode_number': self.episode_number,
            'workflow_id': self.workflow_id,
            'script_id': self.script_id,
            'title': self.title,
            'total_duration': float(self.total_duration) if self.total_duration is not None else None,
            'status': self.status,
            'style': self.style,
            'style_reference_image': self.style_reference_image,
            'workflow_ratio': self.workflow_ratio,
            'composition_preference': self.composition_preference,
            'config_json': config_json,
            'create_at': self.create_at.isoformat() if self.create_at else None,
            'update_at': self.update_at.isoformat() if self.update_at else None,
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
        version: int = 1,
    ) -> int:
        # 初始化画风和构图倾向：参考 video_workflow，从 world 继承（如果未提供）
        if not style or not composition_preference:
            try:
                world = WorldModel.get_by_id(world_id)
                if world:
                    if not style and hasattr(world, 'visual_style'):
                        style = world.visual_style
                    if not composition_preference and hasattr(world, 'composition_preference'):
                        composition_preference = world.composition_preference
            except Exception:
                pass

        sql = """
            INSERT INTO storyboard
            (version, world_id, user_id, episode_number, workflow_id, script_id, title,
             style, style_reference_image, workflow_ratio, composition_preference, config_json)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        config_str = json.dumps(config_json) if config_json else None
        params = (int(version or 1), world_id, user_id, episode_number, workflow_id, script_id, title,
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
    def list_ratios_by_world(user_id: int, world_id: int) -> List[Dict[str, Any]]:
        """
        列出某世界下故事板的集数与画幅比例，按 episode_number ASC。
        仅查必要字段，供创建时比例继承与 create-defaults 使用。
        """
        where_conditions = ["world_id = %s"]
        params: list = [world_id]
        if Edition.is_space_isolated():
            where_conditions.append("user_id = %s")
            params.append(user_id)
        where_clause = " AND ".join(where_conditions)
        sql = f"""
            SELECT id, episode_number, workflow_ratio
            FROM storyboard
            WHERE {where_clause}
            ORDER BY episode_number ASC, id ASC
        """
        try:
            results = execute_query(sql, tuple(params), fetch_all=True)
            return list(results) if results else []
        except Exception as e:
            logger.error(f"Failed to list storyboard ratios by world: {e}")
            raise

    @staticmethod
    def resolve_inherited_workflow_ratio(user_id: int, world_id: int) -> Optional[Dict[str, Any]]:
        """
        解析可继承的视频比例。
        规则：优先第 1 集；无第 1 集则取 episode_number 最小且 ratio 非空的故事板。
        返回 { workflow_ratio, source_episode_number, storyboard_count }；
        世界内无故事板时返回 None。
        """
        rows = StoryboardModel.list_ratios_by_world(user_id, world_id)
        if not rows:
            return None

        def _ratio_of(row) -> str:
            return str(row.get('workflow_ratio') or '').strip()

        ep1 = next(
            (r for r in rows if int(r.get('episode_number') or 0) == 1 and _ratio_of(r)),
            None,
        )
        if ep1:
            return {
                'workflow_ratio': _ratio_of(ep1),
                'source_episode_number': 1,
                'storyboard_count': len(rows),
            }

        for row in rows:
            ratio = _ratio_of(row)
            if ratio:
                return {
                    'workflow_ratio': ratio,
                    'source_episode_number': int(row.get('episode_number') or 0) or None,
                    'storyboard_count': len(rows),
                }

        return {
            'workflow_ratio': None,
            'source_episode_number': None,
            'storyboard_count': len(rows),
        }

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
            SELECT id, version, world_id, user_id, episode_number, workflow_id, script_id,
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
                   sb.version, sb.script_id, sb.title, sb.status, sb.create_at, sb.update_at,
                   COUNT(sc.id) AS scene_count
            FROM storyboard sb
            LEFT JOIN storyboard_scene sc ON sc.storyboard_id = sb.id
            WHERE {where_clause}
            GROUP BY sb.id, sb.world_id, sb.user_id, sb.episode_number, sb.workflow_id,
                     sb.version,
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
            'version',
        ]
        update_fields = []
        params: list = []

        for field, value in kwargs.items():
            if field in allowed_fields:
                if field == 'config_json' and isinstance(value, dict):
                    value = json.dumps(value)
                if field == 'version':
                    value = int(value or 1)
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
    def patch_config_json(record_id: int, updates: Dict[str, Any]) -> int:
        """使用 JSON_SET 原子更新 config_json 的指定顶层字段。"""
        if not updates:
            return 0
        allowed_fields = {
            'selectedTextToImageTaskId',
            'selectedImageEditTaskId',
            'selectedTextToVideoTaskId',
            'selectedImageToVideoTaskId',
            'selectedReferenceToVideoTaskId',
        }
        invalid = sorted(set(updates) - allowed_fields)
        if invalid:
            raise ValueError(f"Unsupported storyboard config fields: {invalid}")
        json_set_args = []
        params: list = []
        for field, value in updates.items():
            json_set_args.append("%s, CAST(%s AS JSON)")
            params.extend((f"$.{field}", json.dumps(value, ensure_ascii=False)))
        params.append(int(record_id))
        sql = (
            "UPDATE storyboard SET config_json = JSON_SET("
            "COALESCE(config_json, JSON_OBJECT()), "
            + ", ".join(json_set_args)
            + ") WHERE id = %s"
        )
        try:
            affected = execute_update(sql, tuple(params))
            logger.info("Patched storyboard %s config fields: %s", record_id, sorted(updates))
            return affected
        except Exception as e:
            logger.error("Failed to patch storyboard %s config_json: %s", record_id, e)
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
        version: int = 1,
    ) -> int:
        """
        在事务中原子创建 storyboard + scenes + dialogues（幂等 get-or-create 的 create 部分）。

        scenes 元素结构：
            {
                'title': str, 'duration': float,
                'prompt': {perspective, style, scene_desc, character_desc},
                'video_prompt': str, 'video_type': str, 'video_config': dict,
                'dialogues': [{'character_id': int|None, 'text': str, 'speed': float, 'volume': int}, ...]
            }
        """
        # 初始化画风和构图倾向：如果未提供，从 world 继承（参考 video_workflow 逻辑）
        if not style or not composition_preference:
            try:
                world = WorldModel.get_by_id(world_id)
                if world:
                    if not style and hasattr(world, 'visual_style'):
                        style = world.visual_style
                    if not composition_preference and hasattr(world, 'composition_preference'):
                        composition_preference = world.composition_preference
            except Exception:
                pass

        config_str = json.dumps(config_json) if config_json else None

        insert_sb_sql = """
            INSERT INTO storyboard
            (version, world_id, user_id, episode_number, workflow_id, script_id, title,
             style, style_reference_image, workflow_ratio, composition_preference, config_json)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        insert_scene_sql = """
            INSERT INTO storyboard_scene
            (storyboard_id, sort_order, title, duration, prompt_json, video_prompt,
             video_type, video_config_json, difficulty, act_name, last_modified_user_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        insert_dialogue_sql = """
            INSERT INTO storyboard_dialogue
            (scene_id, sort_order, character_id, text, speed, volume, last_modified_user_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """

        sb_params = (int(version or 1), world_id, user_id, episode_number, workflow_id, script_id, title,
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
                    SceneDifficulty.normalize(scene_data.get('difficulty')),
                    scene_data.get('act_name'),
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

    @staticmethod
    def create_scenes(
        storyboard_id: int,
        user_id: int,
        scenes: List[Dict],
        script_split_task_id: Optional[int] = None,
    ) -> int:
        """Append scenes and dialogues to an existing storyboard in one transaction.

        当传入 script_split_task_id 时，启用发布幂等：每个 scene 写入稳定的
        (script_split_task_id, source_shot_key)，靠唯一索引去重。发布重试时
        已存在的 shot_key 会被跳过，不重复创建。
        """
        insert_scene_sql = """
            INSERT INTO storyboard_scene
            (storyboard_id, sort_order, title, duration, prompt_json, video_prompt,
             video_type, video_config_json, audio_embedded, difficulty, act_name,
             last_modified_user_id, script_split_task_id, source_shot_key)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        insert_dialogue_sql = """
            INSERT INTO storyboard_dialogue
            (scene_id, sort_order, character_id, text, speed, volume, last_modified_user_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """
        update_storyboard_sql = """
            UPDATE storyboard
            SET total_duration = %s, update_at = CURRENT_TIMESTAMP
            WHERE id = %s
        """

        total_duration = sum(float(scene.get('duration') or 0) for scene in scenes)

        with transaction() as conn:
            for i, scene_data in enumerate(scenes):
                prompt = scene_data.get('prompt')
                prompt_str = json.dumps(prompt, ensure_ascii=False) if prompt else None
                video_config = scene_data.get('video_config')
                video_config_str = json.dumps(video_config, ensure_ascii=False) if video_config else None
                # audio_embedded：调用方未显式提供时，按 video_type 推导
                # （digital_human 产物已含口型音轨，默认声音同出）。
                video_type_val = scene_data.get('video_type', SceneVideoType.VIDEO)
                if 'audio_embedded' in scene_data and scene_data.get('audio_embedded') is not None:
                    audio_embedded_val = 1 if scene_data.get('audio_embedded') else 0
                else:
                    audio_embedded_val = 1 if video_type_val == SceneVideoType.DIGITAL_HUMAN else 0
                # 发布幂等：source_shot_key 稳定标识每个最终 shot
                source_shot_key = scene_data.get('source_shot_key') if script_split_task_id else None
                scene_params = (
                    storyboard_id,
                    float(i),
                    scene_data.get('title', f'分镜{i + 1}'),
                    scene_data.get('duration', 5),
                    prompt_str,
                    scene_data.get('video_prompt'),
                    video_type_val,
                    video_config_str,
                    audio_embedded_val,
                    SceneDifficulty.normalize(scene_data.get('difficulty')),
                    scene_data.get('act_name'),
                    user_id,
                    script_split_task_id,
                    source_shot_key,
                )
                scene_id = execute_insert_in_transaction(conn, insert_scene_sql, scene_params)
                for j, d in enumerate(scene_data.get('dialogues') or []):
                    d_params = (
                        scene_id,
                        float(j),
                        d.get('character_id'),
                        d.get('text'),
                        d.get('speed', 1.0),
                        d.get('volume', 100),
                        user_id,
                    )
                    execute_insert_in_transaction(conn, insert_dialogue_sql, d_params)
            with conn.cursor() as cursor:
                cursor.execute(update_storyboard_sql, (total_duration, storyboard_id))
            logger.info(f"Created {len(scenes)} scenes for storyboard {storyboard_id}")
            return len(scenes)

    @staticmethod
    def count_scenes_by_split_task(script_split_task_id: int) -> int:
        """统计某拆分任务已发布的分镜数（发布恢复时判断是否已全部落库）。"""
        rows = execute_query(
            "SELECT COUNT(*) AS cnt FROM storyboard_scene "
            "WHERE script_split_task_id = %s",
            (script_split_task_id,),
            fetch_one=True,
        )
        return int(rows['cnt']) if rows else 0

    @staticmethod
    def recalc_total_duration(storyboard_id: int) -> float:
        """Recompute and persist storyboard.total_duration from current scenes.

        Use after a single scene's duration changes (create/update/delete) so the
        aggregate stays consistent. Returns the new total_duration in seconds (float,
        millisecond precision per DECIMAL(10,3)).
        """
        select_sql = "SELECT duration FROM storyboard_scene WHERE storyboard_id = %s"
        update_sql = (
            "UPDATE storyboard SET total_duration = %s, update_at = CURRENT_TIMESTAMP "
            "WHERE id = %s"
        )
        try:
            rows = execute_query(select_sql, (storyboard_id,), fetch_all=True) or []
            total_duration = sum(float(row.get('duration') or 0) for row in rows)
            execute_update(update_sql, (total_duration, storyboard_id))
            logger.info(f"Recalculated total_duration={total_duration} for storyboard {storyboard_id}")
            return total_duration
        except Exception as e:
            logger.error(f"Failed to recalc total_duration for storyboard {storyboard_id}: {e}")
            raise


# ==================== CREATE_TABLE_SQL ====================

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS `storyboard` (
    `id` INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    `version` INT NOT NULL DEFAULT 1 COMMENT '???',
    `world_id` INT UNSIGNED NOT NULL COMMENT '关联世界ID',
    `user_id` INT UNSIGNED NOT NULL,
    `episode_number` INT NOT NULL DEFAULT 1 COMMENT '集数，一集一个故事板',
    `workflow_id` INT UNSIGNED DEFAULT NULL COMMENT '关联工作流ID（可选，一键转视频用）',
    `script_id` INT UNSIGNED DEFAULT NULL COMMENT '关联剧本ID',
    `title` VARCHAR(255) DEFAULT '' COMMENT '故事板标题',
    `total_duration` DECIMAL(10,3) DEFAULT 0.000 COMMENT '总时长（秒），由各分镜 duration 求和（毫秒级精度）',
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
"""
