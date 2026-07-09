"""
Grid Image Tasks Model - Database operations for grid_image_tasks table
宫格生图任务模型 - 支持多进程环境下的任务状态共享

⚠️ 与其他任务表的区别（易混淆，修改前请确认目标表）：
  - tasks: ComfyUI 视频/图片生成轮询队列，task_id 为 int（指向 ai_tools.id）
  - agent_tasks: Agent 对话任务（跨进程共享），task_id 为 UUID 字符串
  - async_tasks: 外部服务异步任务（RunningHub 等），有 implementation 字段
  - grid_image_tasks: 本表，宫格生图专用轮询，有 CANCELLED/DOWNLOAD_FAILED 状态

注意：GridImageTaskStatus 比 AsyncTaskStatus 多了 CANCELLED(-3) 和 DOWNLOAD_FAILED(-4) 两个状态

宫格规格支持（grid_size 列）：
  - 4  = 2x2 四宫格（grid_layout='2x2'，向后兼容默认值）
  - 9  = 3x3 九宫格（grid_layout='3x3'，子场景参考图）

宫格 item_type：
  - 4 = character_grid
  - 5 = location_grid
  - 6 = prop_grid
  - 8 = storyboard_first_frame_grid
"""
import json
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
from .database import execute_query, execute_update, execute_insert
import logging

logger = logging.getLogger(__name__)


class GridImageTaskStatus:
    """宫格生图任务状态常量"""
    QUEUED = 0          # 队列中
    PROCESSING = 1      # 处理中
    COMPLETED = 2       # 完成
    FAILED = -1         # 失败
    TIMEOUT = -2        # 超时
    CANCELLED = -3      # 取消
    DOWNLOAD_FAILED = -4  # 下载失败


class GridImageTask:
    """Grid Image Task model class"""
    
    def __init__(self, **kwargs):
        self.id = kwargs.get('id')
        self.task_key = kwargs.get('task_key')
        self.project_id = kwargs.get('project_id')
        self.item_type = kwargs.get('item_type')
        self.item_name = kwargs.get('item_name')
        self.item_names_json = kwargs.get('item_names_json')
        self.target_entity_ids_json = kwargs.get('target_entity_ids_json')
        self.reference_images = kwargs.get('reference_images')
        self.user_id = kwargs.get('user_id')
        self.world_id = kwargs.get('world_id')
        self.comfyui_base_url = kwargs.get('comfyui_base_url')
        self.auth_token = kwargs.get('auth_token')
        self.status = kwargs.get('status', GridImageTaskStatus.QUEUED)
        self.try_count = kwargs.get('try_count', 0)
        self.max_attempts = kwargs.get('max_attempts', 60)
        self.error_message = kwargs.get('error_message')
        self.result_url = kwargs.get('result_url')
        self.local_file_path = kwargs.get('local_file_path')
        self.update_success = kwargs.get('update_success', 0)
        self.prompt = kwargs.get('prompt')
        self.task_config_id = kwargs.get('task_config_id')
        self.aspect_ratio = kwargs.get('aspect_ratio')
        self.image_size = kwargs.get('image_size')
        self.grid_size = kwargs.get('grid_size', 4)
        self.grid_layout = kwargs.get('grid_layout', '2x2')
        self.is_grid = kwargs.get('is_grid', 0)
        self.retry_count = kwargs.get('retry_count', 0)
        self.max_retries = kwargs.get('max_retries', 0)
        self.ai_tool_result_url = kwargs.get('ai_tool_result_url')
        self.created_at = kwargs.get('created_at')
        self.updated_at = kwargs.get('updated_at')
        self.completed_at = kwargs.get('completed_at')
        self.failed_at = kwargs.get('failed_at')
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            'id': self.id,
            'task_key': self.task_key,
            'project_id': self.project_id,
            'item_type': self.item_type,
            'item_name': self.item_name,
            'item_names_json': self.item_names_json,
            'target_entity_ids_json': self.target_entity_ids_json,
            'reference_images': self.reference_images,
            'user_id': self.user_id,
            'world_id': self.world_id,
            'status': self.status,
            'try_count': self.try_count,
            'max_attempts': self.max_attempts,
            'error_message': self.error_message,
            'result_url': self.result_url,
            'local_file_path': self.local_file_path,
            'update_success': self.update_success,
            'prompt': self.prompt,
            'task_config_id': self.task_config_id,
            'aspect_ratio': self.aspect_ratio,
            'image_size': self.image_size,
            'grid_size': self.grid_size,
            'grid_layout': self.grid_layout,
            'is_grid': self.is_grid,
            'retry_count': self.retry_count,
            'max_retries': self.max_retries,
            'ai_tool_result_url': self.ai_tool_result_url,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
            'failed_at': self.failed_at.isoformat() if self.failed_at else None
        }

    # ---- 便捷解析方法（JSON 列 → Python 对象）----

    def get_item_names_list(self) -> List[str]:
        """优先从 item_names_json 解析名称列表；为空时 fallback 到 item_name 逗号 split。"""
        if self.item_names_json:
            try:
                parsed = self.item_names_json if isinstance(self.item_names_json, list) \
                    else json.loads(self.item_names_json)
                if isinstance(parsed, list):
                    return [str(n).strip() for n in parsed if str(n).strip()]
            except (ValueError, TypeError):
                pass
        if self.item_name:
            return [n.strip() for n in self.item_name.split(',') if n.strip()]
        return []

    def get_target_entity_ids_list(self) -> List[int]:
        """从 target_entity_ids_json 解析切图回写目标 DB id 列表。"""
        if not self.target_entity_ids_json:
            return []
        try:
            parsed = self.target_entity_ids_json if isinstance(self.target_entity_ids_json, list) \
                else json.loads(self.target_entity_ids_json)
            if isinstance(parsed, list):
                return [int(v) for v in parsed if v is not None]
        except (ValueError, TypeError):
            pass
        return []


class GridImageTasksModel:
    """Grid Image Tasks database operations"""
    
    @staticmethod
    def create(
        task_key: str,
        project_id: str,
        item_type: int,
        item_name: str,
        user_id: str,
        world_id: str,
        comfyui_base_url: str,
        auth_token: str,
        max_attempts: int = 60,
        prompt: str = None,
        task_config_id: str = None,
        aspect_ratio: str = None,
        image_size: str = None,
        is_grid: bool = False,
        max_retries: int = 0,
        grid_size: int = 4,
        grid_layout: str = '2x2',
        item_names: Optional[List[str]] = None,
        target_entity_ids: Optional[List[int]] = None,
        reference_images: Optional[List[Dict]] = None,
    ) -> int:
        """
        创建新的宫格生图任务

        Args:
            task_key: 任务唯一键
            project_id: ComfyUI project_id
            item_type: 项目类型
            item_name: 项目名称（逗号分隔，兼容旧逻辑；优先用 item_names）
            user_id: 用户ID
            world_id: 世界观ID
            comfyui_base_url: ComfyUI服务地址
            auth_token: 认证令牌
            max_attempts: 最大尝试次数
            prompt: 生图提示词（用于自动重试）
            task_config_id: 生图模型配置ID（用于自动重试）
            aspect_ratio: 图片宽高比（用于自动重试）
            image_size: 图片尺寸（用于自动重试）
            is_grid: 是否为宫格生成
            max_retries: 最大重试次数
            grid_size: 宫格总数（4=2x2, 9=3x3）
            grid_layout: 宫格布局描述（'2x2'/'3x3'）
            item_names: 结构化名称列表（写入 item_names_json，避免逗号拼接歧义）
            target_entity_ids: 切图回写目标 DB id 列表（写入 target_entity_ids_json，
                              使回写按 id 而非按名）
            reference_images: i2i 参考图列表 [{url, role_description}, ...]，
                              序列化为 JSON 存 TEXT 列，用于宫格图生图与重试复原。

        Returns:
            插入的记录ID

        Raises:
            Exception: 如果任务已存在（UNIQUE KEY冲突）
        """
        item_names_json = json.dumps(item_names, ensure_ascii=False) if item_names else None
        target_entity_ids_json = json.dumps(target_entity_ids) if target_entity_ids else None
        reference_images_str = json.dumps(reference_images, ensure_ascii=False) if reference_images else None

        sql = """
            INSERT INTO grid_image_tasks
            (task_key, project_id, item_type, item_name, user_id, world_id,
             comfyui_base_url, auth_token, status, max_attempts,
             prompt, task_config_id, aspect_ratio, image_size, is_grid, max_retries,
             grid_size, grid_layout, item_names_json, target_entity_ids_json, reference_images)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        params = (
            task_key, project_id, item_type, item_name, user_id, world_id,
            comfyui_base_url, auth_token, GridImageTaskStatus.QUEUED, max_attempts,
            prompt, task_config_id, aspect_ratio, image_size, 1 if is_grid else 0, max_retries,
            grid_size, grid_layout, item_names_json, target_entity_ids_json, reference_images_str,
        )

        try:
            record_id = execute_insert(sql, params)
            logger.info(f"Created grid image task: {task_key}, record_id: {record_id}")
            return record_id
        except Exception as e:
            logger.error(f"Failed to create grid image task {task_key}: {e}")
            raise
    
    @staticmethod
    def exists_by_project_id(project_id: str) -> bool:
        """
        检查是否存在关联指定 project_id 的活跃 grid_image_task
        
        Args:
            project_id: ai_tools.id（字符串形式）
        
        Returns:
            True 如果存在活跃的 grid_image_task
        """
        sql = "SELECT COUNT(*) as cnt FROM grid_image_tasks WHERE project_id = %s AND status IN (%s, %s)"

        try:
            result = execute_query(
                sql,
                (str(project_id), GridImageTaskStatus.QUEUED, GridImageTaskStatus.PROCESSING),
                fetch_one=True
            )
            return result and result.get('cnt', 0) > 0
        except Exception as e:
            logger.error(f"Failed to check grid image task by project_id {project_id}: {e}")
            return False

    @staticmethod
    def has_running_grid_for_entity(entity_id: int, item_type: int = 5) -> bool:
        """
        检查指定 entity_id 是否存在运行中（QUEUED/PROCESSING）的宫格任务。

        用于 Phase 6「外部 location grid readiness check」：分镜首帧生图前判断
        子场景 location 的九宫格参考图是否仍在生成。

        Args:
            entity_id: 切图回写目标 DB id（location.id）。匹配 target_entity_ids_json 数组。
            item_type: 宫格类型，默认 5（location_grid）。

        Returns:
            True 如果存在运行中的宫格任务且 target_entity_ids_json 包含该 entity_id。
        """
        if not entity_id:
            return False
        # JSON_CONTAINS 匹配 target_entity_ids_json 数组中是否含 entity_id。
        # 仅查 location_grid(item_type=5) 的活跃任务。
        sql = (
            "SELECT COUNT(*) as cnt FROM grid_image_tasks "
            "WHERE item_type = %s AND status IN (%s, %s) "
            "AND JSON_CONTAINS(target_entity_ids_json, %s, '$')"
        )
        # JSON_CONTAINS 的目标值需是合法 JSON 标量
        json_val = json.dumps(int(entity_id))
        try:
            result = execute_query(
                sql,
                (item_type, GridImageTaskStatus.QUEUED, GridImageTaskStatus.PROCESSING, json_val),
                fetch_one=True,
            )
            return bool(result and result.get('cnt', 0) > 0)
        except Exception as e:
            # target_entity_ids_json 为 NULL 的旧记录不会命中 JSON_CONTAINS，属预期行为
            logger.error(f"Failed to check running grid for entity {entity_id}: {e}")
            return False

    @staticmethod
    def get_by_task_key(task_key: str) -> Optional[GridImageTask]:
        """
        根据task_key获取任务
        
        Args:
            task_key: 任务唯一键
        
        Returns:
            GridImageTask对象或None
        """
        sql = "SELECT * FROM grid_image_tasks WHERE task_key = %s"
        
        try:
            result = execute_query(sql, (task_key,), fetch_one=True)
            if result:
                return GridImageTask(**result)
            return None
        except Exception as e:
            logger.error(f"Failed to get grid image task by task_key {task_key}: {e}")
            raise
    
    @staticmethod
    def get_by_id(record_id: int) -> Optional[GridImageTask]:
        """
        根据ID获取任务
        
        Args:
            record_id: 记录ID
        
        Returns:
            GridImageTask对象或None
        """
        sql = "SELECT * FROM grid_image_tasks WHERE id = %s"
        
        try:
            result = execute_query(sql, (record_id,), fetch_one=True)
            if result:
                return GridImageTask(**result)
            return None
        except Exception as e:
            logger.error(f"Failed to get grid image task by id {record_id}: {e}")
            raise
    
    @staticmethod
    def get_pending_tasks(limit: int = 100) -> List[GridImageTask]:
        """
        获取待处理的任务（状态为QUEUED或PROCESSING）
        
        Args:
            limit: 最大返回数量
        
        Returns:
            GridImageTask对象列表
        """
        sql = """
            SELECT * FROM grid_image_tasks 
            WHERE status IN (%s, %s)
            ORDER BY created_at ASC
            LIMIT %s
        """
        
        try:
            results = execute_query(
                sql, 
                (GridImageTaskStatus.QUEUED, GridImageTaskStatus.PROCESSING, limit),
                fetch_all=True
            )
            tasks = [GridImageTask(**row) for row in results] if results else []
            return tasks
        except Exception as e:
            logger.error(f"Failed to get pending grid image tasks: {e}")
            raise

    @staticmethod
    def get_late_completed_terminal_tasks(limit: int = 20) -> List[GridImageTask]:
        """
        获取已经被 grid 轮询标为终态，但绑定 ai_tools 后来成功的任务。

        典型场景：同步图片实现方耗时超过 grid_image_tasks.max_attempts，grid 任务先
        TIMEOUT 并停止轮询；几分钟后 ai_tools 成功写入 result_url。这里把这些
        "晚到成功"捞回同一套下载/校验/拆图回写流程。
        """
        sql = """
            SELECT g.*, a.result_url AS ai_tool_result_url
            FROM grid_image_tasks g
            JOIN ai_tools a ON a.id = CAST(g.project_id AS UNSIGNED)
            WHERE g.status IN (%s, %s)
              AND (g.result_url IS NULL OR g.result_url = '')
              AND a.status = %s
              AND a.result_url IS NOT NULL
              AND a.result_url <> ''
              AND g.item_type IN (4, 5, 6, 8)
            ORDER BY g.updated_at ASC
            LIMIT %s
        """
        try:
            results = execute_query(
                sql,
                (
                    GridImageTaskStatus.FAILED,
                    GridImageTaskStatus.TIMEOUT,
                    2,
                    limit,
                ),
                fetch_all=True,
            )
            return [GridImageTask(**row) for row in results] if results else []
        except Exception as e:
            logger.error(f"Failed to get late completed terminal grid image tasks: {e}")
            raise
    
    @staticmethod
    def get_user_tasks(user_id: str, world_id: str = None, limit: int = 50) -> List[GridImageTask]:
        """
        获取用户的任务列表
        
        Args:
            user_id: 用户ID
            world_id: 世界观ID（可选）
            limit: 最大返回数量
        
        Returns:
            GridImageTask对象列表
        """
        if world_id:
            sql = """
                SELECT * FROM grid_image_tasks 
                WHERE user_id = %s AND world_id = %s
                ORDER BY created_at DESC
                LIMIT %s
            """
            params = (user_id, world_id, limit)
        else:
            sql = """
                SELECT * FROM grid_image_tasks 
                WHERE user_id = %s
                ORDER BY created_at DESC
                LIMIT %s
            """
            params = (user_id, limit)
        
        try:
            results = execute_query(sql, params, fetch_all=True)
            tasks = [GridImageTask(**row) for row in results] if results else []
            return tasks
        except Exception as e:
            logger.error(f"Failed to get user grid image tasks: {e}")
            raise
    
    @staticmethod
    def update_status(
        task_key: str,
        status: int,
        error_message: str = None,
        result_url: str = None,
        local_file_path: str = None,
        update_success: int = None
    ) -> int:
        """
        更新任务状态
        
        Args:
            task_key: 任务唯一键
            status: 新状态
            error_message: 错误信息（可选）
            result_url: 结果URL（可选）
            local_file_path: 本地文件路径（可选）
            update_success: 是否成功更新到item（可选）
        
        Returns:
            影响的行数
        """
        update_fields = ["status = %s"]
        params = [status]
        
        if error_message is not None:
            update_fields.append("error_message = %s")
            params.append(error_message)
        
        if result_url is not None:
            update_fields.append("result_url = %s")
            params.append(result_url)
        
        if local_file_path is not None:
            update_fields.append("local_file_path = %s")
            params.append(local_file_path)
        
        if update_success is not None:
            update_fields.append("update_success = %s")
            params.append(update_success)
        
        # 根据状态设置完成/失败时间
        if status == GridImageTaskStatus.COMPLETED:
            update_fields.append("completed_at = NOW()")
        elif status in [GridImageTaskStatus.FAILED, GridImageTaskStatus.TIMEOUT, 
                       GridImageTaskStatus.DOWNLOAD_FAILED]:
            update_fields.append("failed_at = NOW()")
        
        params.append(task_key)
        sql = f"UPDATE grid_image_tasks SET {', '.join(update_fields)} WHERE task_key = %s"
        
        try:
            affected_rows = execute_update(sql, tuple(params))
            logger.info(f"Updated grid image task {task_key} status to {status}, affected rows: {affected_rows}")
            return affected_rows
        except Exception as e:
            logger.error(f"Failed to update grid image task {task_key}: {e}")
            raise
    
    @staticmethod
    def increment_try_count(task_key: str) -> int:
        """
        增加任务尝试次数
        
        Args:
            task_key: 任务唯一键
        
        Returns:
            影响的行数
        """
        sql = "UPDATE grid_image_tasks SET try_count = try_count + 1 WHERE task_key = %s"
        
        try:
            affected_rows = execute_update(sql, (task_key,))
            logger.info(f"Incremented try_count for task {task_key}, affected rows: {affected_rows}")
            return affected_rows
        except Exception as e:
            logger.error(f"Failed to increment try_count for task {task_key}: {e}")
            raise
    
    @staticmethod
    def delete_by_task_key(task_key: str) -> int:
        """
        删除任务
        
        Args:
            task_key: 任务唯一键
        
        Returns:
            影响的行数
        """
        sql = "DELETE FROM grid_image_tasks WHERE task_key = %s"
        
        try:
            affected_rows = execute_update(sql, (task_key,))
            logger.info(f"Deleted grid image task {task_key}, affected rows: {affected_rows}")
            return affected_rows
        except Exception as e:
            logger.error(f"Failed to delete grid image task {task_key}: {e}")
            raise
    
    @staticmethod
    def reset_for_retry(task_key: str, new_project_id: str) -> int:
        """
        重置任务以供重试（更新 project_id、重置状态、增加 retry_count）
        
        Args:
            task_key: 任务唯一键
            new_project_id: 新的 ComfyUI project_id
        
        Returns:
            影响的行数
        """
        sql = """
            UPDATE grid_image_tasks 
            SET project_id = %s, 
                status = %s, 
                try_count = 0, 
                retry_count = retry_count + 1,
                error_message = NULL,
                result_url = NULL,
                local_file_path = NULL,
                update_success = 0,
                failed_at = NULL,
                completed_at = NULL
            WHERE task_key = %s
        """
        params = (new_project_id, GridImageTaskStatus.QUEUED, task_key)
        
        try:
            affected_rows = execute_update(sql, params)
            logger.info(f"Reset grid image task {task_key} for retry, new project_id: {new_project_id}, affected rows: {affected_rows}")
            return affected_rows
        except Exception as e:
            logger.error(f"Failed to reset grid image task {task_key} for retry: {e}")
            raise
    
    @staticmethod
    def cleanup_old_tasks(days: int = 7) -> int:
        """
        清理旧任务（已完成或失败的任务）
        
        Args:
            days: 保留天数
        
        Returns:
            删除的行数
        """
        sql = """
            DELETE FROM grid_image_tasks 
            WHERE status IN (%s, %s, %s, %s, %s)
            AND created_at < DATE_SUB(NOW(), INTERVAL %s DAY)
        """
        params = (
            GridImageTaskStatus.COMPLETED,
            GridImageTaskStatus.FAILED,
            GridImageTaskStatus.TIMEOUT,
            GridImageTaskStatus.CANCELLED,
            GridImageTaskStatus.DOWNLOAD_FAILED,
            days
        )
        
        try:
            affected_rows = execute_update(sql, params)
            if affected_rows > 0:
                logger.info(f"Cleaned up {affected_rows} old grid image tasks (older than {days} days)")
            return affected_rows
        except Exception as e:
            logger.error(f"Failed to cleanup old grid image tasks: {e}")
            raise


CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS `grid_image_tasks` (
  `id` int NOT NULL AUTO_INCREMENT COMMENT '主键ID',
  `task_key` varchar(255) NOT NULL COMMENT '任务唯一键 (格式: item_type_item_name，九宫格用 grid:uid:wid:project_id 短键)',
  `project_id` varchar(100) NOT NULL COMMENT 'ComfyUI project_id',
  `item_type` tinyint NOT NULL COMMENT '项目类型 (0=general, 1=character, 2=location, 3=props, 4=character_grid, 5=location_grid, 6=prop_grid, 8=storyboard_first_frame_grid)',
  `item_name` varchar(255) NOT NULL COMMENT '项目名称（宫格任务为逗号分隔的多个名称，九宫格建议配合 item_names_json 使用）',
  `item_names_json` json DEFAULT NULL COMMENT '结构化名称列表（避免逗号拼接歧义 / 名称超长）',
  `target_entity_ids_json` json DEFAULT NULL COMMENT '切图回写目标 DB id 列表（回写按 id 而非按名）',
  `reference_images` text COMMENT 'i2i 参考图列表 JSON [{url, role_description}, ...]（用于宫格图生图与重试复原）',
  `user_id` varchar(50) NOT NULL COMMENT '用户ID',
  `world_id` varchar(50) NOT NULL COMMENT '世界观ID',
  `comfyui_base_url` varchar(500) NOT NULL COMMENT 'ComfyUI服务地址',
  `auth_token` varchar(500) NOT NULL COMMENT '认证令牌',
  `status` tinyint DEFAULT '0' COMMENT '状态（0-队列中, 1-处理中, 2-完成, -1-失败, -2-超时, -3-取消, -4-下载失败）',
  `try_count` int DEFAULT '0' COMMENT '尝试次数',
  `max_attempts` int DEFAULT '60' COMMENT '最大尝试次数',
  `error_message` text COMMENT '错误信息',
  `result_url` varchar(1000) DEFAULT NULL COMMENT '结果图片URL',
  `local_file_path` varchar(1000) DEFAULT NULL COMMENT '本地文件路径',
  `update_success` tinyint DEFAULT '0' COMMENT '是否成功更新到item (0-否, 1-是)',
  `prompt` text COMMENT '生图提示词（用于自动重试）',
  `task_config_id` varchar(100) DEFAULT NULL COMMENT '生图模型配置ID（用于自动重试）',
  `aspect_ratio` varchar(20) DEFAULT NULL COMMENT '图片宽高比（用于自动重试）',
  `image_size` varchar(20) DEFAULT NULL COMMENT '图片尺寸（用于自动重试）',
  `grid_size` tinyint NOT NULL DEFAULT '4' COMMENT '宫格总数 (4=2x2, 9=3x3)',
  `grid_layout` varchar(8) NOT NULL DEFAULT '2x2' COMMENT '宫格布局 (2x2/3x3)',
  `is_grid` tinyint DEFAULT '0' COMMENT '是否为宫格生成 (0-否, 1-是)',
  `retry_count` int DEFAULT '0' COMMENT '已重试次数',
  `max_retries` int DEFAULT '0' COMMENT '最大重试次数（0=不重试）',
  `created_at` datetime DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updated_at` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  `completed_at` datetime DEFAULT NULL COMMENT '完成时间',
  `failed_at` datetime DEFAULT NULL COMMENT '失败时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_task_key` (`task_key`),
  KEY `idx_status` (`status`),
  KEY `idx_user_world` (`user_id`,`world_id`),
  KEY `idx_created_at` (`created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='宫格生图任务表';
"""
