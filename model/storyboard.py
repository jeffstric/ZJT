"""
Storyboard Model - Database operations for storyboard / storyboard_scene /
storyboard_dialogue / storyboard_dialogue_audio / storyboard_scene_asset tables
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
from config.constant import Edition
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
                'title': str, 'duration': int,
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
             video_type, video_config_json, last_modified_user_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
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
    ) -> int:
        """Append scenes and dialogues to an existing storyboard in one transaction."""
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
        update_storyboard_sql = """
            UPDATE storyboard
            SET total_duration = %s, update_at = CURRENT_TIMESTAMP
            WHERE id = %s
        """

        total_duration = sum(int(scene.get('duration') or 0) for scene in scenes)

        with transaction() as conn:
            for i, scene_data in enumerate(scenes):
                prompt = scene_data.get('prompt')
                prompt_str = json.dumps(prompt, ensure_ascii=False) if prompt else None
                video_config = scene_data.get('video_config')
                video_config_str = json.dumps(video_config, ensure_ascii=False) if video_config else None
                scene_params = (
                    storyboard_id,
                    float(i),
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
