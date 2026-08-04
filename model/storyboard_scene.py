"""
Storyboard scene model - database operations for storyboard_scene table.
"""
from typing import Optional, Dict, Any, List, Union
from .database import execute_query, execute_update, execute_insert
from config.unified_config import SceneVideoType
from config.constant import SceneDifficulty
import logging
import json

logger = logging.getLogger(__name__)


def compute_sort_between(left_value: Optional[Union[int, float]],
                         right_value: Optional[Union[int, float]]) -> float:
    """
    Floating midpoint order helper.

    - left_value is None: insert before right_value
    - right_value is None: insert after left_value
    - both present: insert at midpoint
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
    """Return True when floating midpoint cannot distinguish adjacent values."""
    mid_f = float(mid)
    if left_value is not None and mid_f == float(left_value):
        return True
    if right_value is not None and mid_f == float(right_value):
        return True
    return False


class StoryboardScene:
    """StoryboardScene entity class."""

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
        # 声音同出：选中视频已内嵌对话声音（如数字人 LTX2.3 产物），导出完整视频时
        # 保留视频原音轨、跳过 TTS 混音。DB 存 TINYINT(1) 0/1，读出统一转 bool。
        self.audio_embedded = bool(kwargs.get('audio_embedded'))
        self.difficulty = kwargs.get('difficulty') or SceneDifficulty.MEDIUM
        self.act_name = kwargs.get('act_name')
        self.selected_first_frame_id = kwargs.get('selected_first_frame_id')
        self.selected_last_frame_id = kwargs.get('selected_last_frame_id')
        self.selected_video_id = kwargs.get('selected_video_id')
        self.last_modified_user_id = kwargs.get('last_modified_user_id')
        # 剧本分段拆分发布幂等：标识本 scene 由哪个拆分任务的哪个 shot 生成。
        # 发布中断恢复时按 (script_split_task_id, source_shot_key) 去重，避免重复创建。
        # 非 script_split 来源的 scene（手工/其他）两个字段均为 NULL。
        self.script_split_task_id = kwargs.get('script_split_task_id')
        self.source_shot_key = kwargs.get('source_shot_key')
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
            'duration': float(self.duration) if self.duration is not None else None,
            'prompt_json': _parse_json(self.prompt_json),
            'video_prompt': self.video_prompt,
            'video_type': self.video_type,
            'video_config_json': _parse_json(self.video_config_json),
            'audio_embedded': self.audio_embedded,
            'difficulty': self.difficulty,
            'act_name': self.act_name,
            'selected_first_frame_id': self.selected_first_frame_id,
            'selected_last_frame_id': self.selected_last_frame_id,
            'selected_video_id': self.selected_video_id,
            'last_modified_user_id': self.last_modified_user_id,
            'script_split_task_id': self.script_split_task_id,
            'source_shot_key': self.source_shot_key,
            'create_at': self.create_at.isoformat() if self.create_at else None,
            'update_at': self.update_at.isoformat() if self.update_at else None,
        }


class StoryboardSceneModel:
    """StoryboardScene database operations."""

    @staticmethod
    def create(
        storyboard_id: int,
        sort_order: float = 0.0,
        title: str = '',
        duration: float = 5.0,
        prompt_json: Optional[Dict] = None,
        video_prompt: Optional[str] = None,
        video_type: str = SceneVideoType.VIDEO,
        video_config_json: Optional[Dict] = None,
        audio_embedded: Optional[bool] = None,
        difficulty: str = SceneDifficulty.MEDIUM,
        act_name: Optional[str] = None,
        last_modified_user_id: Optional[int] = None,
    ) -> int:
        # audio_embedded 默认按 video_type 推导：digital_human 产物已含口型音轨。
        # 调用方显式传 bool（含 False）则尊重其选择，不再覆盖。
        if audio_embedded is None:
            audio_embedded = (video_type == SceneVideoType.DIGITAL_HUMAN)
        sql = """
            INSERT INTO storyboard_scene
            (storyboard_id, sort_order, title, duration, prompt_json, video_prompt,
             video_type, video_config_json, audio_embedded, difficulty, act_name, last_modified_user_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        prompt_str = json.dumps(prompt_json, ensure_ascii=False) if prompt_json else None
        video_config_str = json.dumps(video_config_json, ensure_ascii=False) if video_config_json else None
        params = (storyboard_id, float(sort_order), title, duration, prompt_str, video_prompt,
                  video_type, video_config_str, 1 if audio_embedded else 0,
                  SceneDifficulty.normalize(difficulty),
                  act_name or None, last_modified_user_id)
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
        # result_url：asset 自身优先；空时用关联 ai_tools.result_url 兜底
        # （视频生成完成时常只写 ai_tools，asset.result_url 仍为空）
        sql = """
            SELECT sc.*,
                   COALESCE(NULLIF(ff.result_url, ''), fft.result_url) AS first_frame_url,
                   COALESCE(NULLIF(lf.result_url, ''), lft.result_url) AS last_frame_url,
                   COALESCE(NULLIF(vd.result_url, ''), vdt.result_url) AS video_url
            FROM storyboard_scene sc
            LEFT JOIN storyboard_scene_asset ff ON ff.id = sc.selected_first_frame_id
            LEFT JOIN ai_tools fft ON fft.id = ff.ai_tool_id
            LEFT JOIN storyboard_scene_asset lf ON lf.id = sc.selected_last_frame_id
            LEFT JOIN ai_tools lft ON lft.id = lf.ai_tool_id
            LEFT JOIN storyboard_scene_asset vd ON vd.id = sc.selected_video_id
            LEFT JOIN ai_tools vdt ON vdt.id = vd.ai_tool_id
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
            'video_type', 'video_config_json', 'audio_embedded', 'difficulty', 'act_name',
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
                if field == 'audio_embedded':
                    # bool / 0/1 / "true"/"false" 统一规整为 TINYINT 0/1
                    if isinstance(value, str):
                        value = 1 if value.strip().lower() in ('1', 'true', 'yes', 'y') else 0
                    else:
                        value = 1 if value else 0
                if field == 'difficulty':
                    value = SceneDifficulty.normalize(value)
                if field == 'act_name' and value is not None:
                    value = str(value).strip() or None
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
        mid = compute_sort_between(prev_sort, next_sort)
        if is_precision_exhausted(mid, prev_sort, next_sort):
            StoryboardSceneModel.rebalance(storyboard_id)
            if prev_sort is None:
                return 0.0
            row = execute_query(
                "SELECT id, sort_order FROM storyboard_scene WHERE storyboard_id = %s "
                "ORDER BY sort_order ASC, id ASC",
                (storyboard_id,), fetch_all=True,
            ) or []
            if row:
                last = row[-1]
                return float(last['sort_order']) + 1.0
            return 0.0
        return mid

    @staticmethod
    def _next_sort_after(storyboard_id: int,
                         cur_sort: Optional[float]) -> Optional[float]:
        """返回 storyboard 内 sort_order 严格大于 cur_sort 的第一个分镜的 sort_order；
        不存在（cur_sort 已是末尾）时返回 None。用于复制分镜时确定插入的右边界。"""
        if cur_sort is None:
            cur_sort = 0.0
        sql = (
            "SELECT sort_order FROM storyboard_scene "
            "WHERE storyboard_id = %s AND sort_order > %s "
            "ORDER BY sort_order ASC, id ASC LIMIT 1"
        )
        try:
            row = execute_query(sql, (storyboard_id, float(cur_sort)), fetch_one=True)
            return float(row['sort_order']) if row else None
        except Exception as e:
            logger.error(
                f"Failed to fetch next sort_order after {cur_sort} "
                f"for storyboard {storyboard_id}: {e}"
            )
            raise

    @staticmethod
    def duplicate(record_id: int) -> Optional[int]:
        """Duplicate a scene with dialogues, excluding generated assets."""
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

        # 新分镜插入到「原分镜」与「原分镜的下一个分镜」之间（浮点二分），
        # 而非简单 +1.0——后者会在连续整数序列下与下一个分镜的 sort_order 碰撞，
        # 经 ORDER BY sort_order, id 的 tie-break 后落到「下一个的下一个」。
        cur_sort = float(scene.sort_order) if scene.sort_order is not None else 0.0
        next_sort = StoryboardSceneModel._next_sort_after(scene.storyboard_id, cur_sort)
        new_sort = StoryboardSceneModel.next_sort_order(
            scene.storyboard_id, cur_sort, next_sort
        )

        new_id = StoryboardSceneModel.create(
            storyboard_id=scene.storyboard_id,
            sort_order=new_sort,
            title=f"{scene.title}(副本)" if scene.title else '分镜(副本)',
            duration=scene.duration,
            prompt_json=prompt if isinstance(prompt, dict) else None,
            video_prompt=scene.video_prompt,
            video_type=scene.video_type or SceneVideoType.VIDEO,
            video_config_json=video_config if isinstance(video_config, dict) else None,
            audio_embedded=bool(scene.audio_embedded),
            difficulty=scene.difficulty or SceneDifficulty.MEDIUM,
            act_name=scene.act_name,
            last_modified_user_id=scene.last_modified_user_id,
        )

        from .storyboard_dialogue import StoryboardDialogueModel

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


# ==================== CREATE_TABLE_SQL ====================
CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS `storyboard_scene` (
    `id` INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    `storyboard_id` INT UNSIGNED NOT NULL,
    `sort_order` DOUBLE DEFAULT 0 COMMENT '排序序号（浮点二分，见文档 2.3.2）',
    `title` VARCHAR(255) DEFAULT '',
    `duration` DECIMAL(10,3) DEFAULT 5.000 COMMENT '分镜时长（秒），音频全部完成时自动同步为选中配音求和（毫秒级精度）',
    `prompt_json` JSON DEFAULT NULL COMMENT '画面提示词: perspective/style/scene_desc/character_desc',
    `video_prompt` TEXT DEFAULT NULL COMMENT '视频提示词（生视频/数字人动作描述）',
    `video_type` VARCHAR(32) NOT NULL DEFAULT 'video' COMMENT '分镜类型 image/video/digital_human，见 SceneVideoType',
    `audio_embedded` TINYINT(1) NOT NULL DEFAULT 0 COMMENT '声音同出：选中视频已内嵌对话声音，导出完整视频时不混入TTS；digital_human 默认1',
    `video_config_json` JSON DEFAULT NULL COMMENT '视频生成参数偏好: 模型/分辨率/时长',
    `difficulty` VARCHAR(8) NOT NULL DEFAULT '中' COMMENT '分镜难易程度: 易/中/难，见 SceneDifficulty',
    `act_name` VARCHAR(255) DEFAULT NULL COMMENT '所属幕/分镜组名称（源自 LLM shot_group.group_name）',
    `selected_first_frame_id` INT UNSIGNED DEFAULT NULL COMMENT '当前选中首帧 asset id',
    `selected_last_frame_id` INT UNSIGNED DEFAULT NULL COMMENT '当前选中尾帧 asset id',
    `selected_video_id` INT UNSIGNED DEFAULT NULL COMMENT '当前选中视频 asset id',
    `last_modified_user_id` INT UNSIGNED DEFAULT NULL COMMENT '最后修改人',
    `script_split_task_id` BIGINT UNSIGNED DEFAULT NULL COMMENT '剧本分段拆分任务 id（发布幂等，NULL=非拆分来源）',
    `source_shot_key` VARCHAR(128) DEFAULT NULL COMMENT '拆分任务内稳定 shot 标识（发布幂等去重）',
    `create_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `update_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX `idx_storyboard` (`storyboard_id`),
    INDEX `idx_sort` (`storyboard_id`, `sort_order`),
    INDEX `idx_video_type` (`video_type`),
    INDEX `idx_selected_video` (`selected_video_id`),
    UNIQUE KEY `uk_storyboard_scene_split_source` (`script_split_task_id`, `source_shot_key`),
    FOREIGN KEY (`storyboard_id`) REFERENCES `storyboard`(`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='故事板分镜表';
"""

__all__ = [
    "StoryboardScene",
    "StoryboardSceneModel",
    "compute_sort_between",
    "is_precision_exhausted",
]
