"""
Location Multi-Angle Tasks Model - Database operations for location_multi_angle_tasks table
场景多角度生图任务模型
"""
import json
from typing import List, Optional, Dict, Any
from datetime import datetime
from .database import execute_query, execute_update, execute_insert
import logging

logger = logging.getLogger(__name__)


class LocationMultiAngleTaskStatus:
    """场景多角度生图任务状态常量"""
    QUEUED = 0          # 队列中
    PROCESSING = 1     # 处理中
    COMPLETED = 2      # 完成
    FAILED = -1        # 失败


class LocationMultiAngleTask:
    """Location Multi-Angle Task model class"""

    def __init__(self, **kwargs):
        self.id = kwargs.get('id')
        self.task_key = kwargs.get('task_key')
        self.location_name = kwargs.get('location_name')
        self.user_id = kwargs.get('user_id')
        self.world_id = kwargs.get('world_id')
        self.main_image = kwargs.get('main_image')
        self.description = kwargs.get('description')
        self.angles = kwargs.get('angles')
        self.model = kwargs.get('model')
        self.auth_token = kwargs.get('auth_token')
        self.ai_tool_task_id = kwargs.get('ai_tool_task_id')
        self.status = kwargs.get('status', LocationMultiAngleTaskStatus.QUEUED)
        self.current_angle_index = kwargs.get('current_angle_index', 0)
        self.generated_images = kwargs.get('generated_images')
        self.error_message = kwargs.get('error_message')
        self.created_at = kwargs.get('created_at')
        self.updated_at = kwargs.get('updated_at')
        self.completed_at = kwargs.get('completed_at')
        self.failed_at = kwargs.get('failed_at')

    def get_angles_list(self) -> List[Dict[str, Any]]:
        """获取角度列表"""
        if isinstance(self.angles, str):
            try:
                return json.loads(self.angles)
            except:
                return []
        return self.angles or []

    def get_generated_images_list(self) -> List[Dict[str, Any]]:
        """获取已生成的图片列表"""
        if isinstance(self.generated_images, str):
            try:
                return json.loads(self.generated_images)
            except:
                return []
        return self.generated_images or []

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            'id': self.id,
            'task_key': self.task_key,
            'location_name': self.location_name,
            'user_id': self.user_id,
            'world_id': self.world_id,
            'main_image': self.main_image,
            'description': self.description,
            'angles': self.get_angles_list(),
            'model': self.model,
            'auth_token': self.auth_token,
            'ai_tool_task_id': self.ai_tool_task_id,
            'status': self.status,
            'current_angle_index': self.current_angle_index,
            'generated_images': self.get_generated_images_list(),
            'error_message': self.error_message,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
            'failed_at': self.failed_at.isoformat() if self.failed_at else None
        }


class LocationMultiAngleTasksModel:
    """Location Multi-Angle Tasks database operations"""

    @staticmethod
    def create(
        task_key: str,
        location_name: str,
        user_id: str,
        world_id: str,
        main_image: str,
        angles: List[Dict[str, Any]],
        description: str = None,
        model: str = None,
        auth_token: str = None
    ) -> int:
        """
        创建新的场景多角度生图任务

        Args:
            task_key: 任务唯一键
            location_name: 场景名称
            user_id: 用户ID
            world_id: 世界观ID
            main_image: 主参考图URL
            angles: 角度列表 [{angle: 90, label: '右侧', angleKey: 'right'}, ...]
            description: 场景描述
            model: 使用的模型
            auth_token: 认证令牌

        Returns:
            插入的记录ID
        """
        angles_json = json.dumps(angles, ensure_ascii=False) if angles else '[]'

        sql = """
            INSERT INTO location_multi_angle_tasks
            (task_key, location_name, user_id, world_id, main_image, description, angles, model, auth_token, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        params = (
            task_key, location_name, user_id, world_id, main_image,
            description, angles_json, model, auth_token, LocationMultiAngleTaskStatus.QUEUED
        )

        try:
            record_id = execute_insert(sql, params)
            logger.info(f"Created location multi-angle task: {task_key}, record_id: {record_id}")
            return record_id
        except Exception as e:
            logger.error(f"Failed to create location multi-angle task {task_key}: {e}")
            raise

    @staticmethod
    def get_by_task_key(task_key: str) -> Optional[LocationMultiAngleTask]:
        """
        根据task_key获取任务

        Args:
            task_key: 任务唯一键

        Returns:
            LocationMultiAngleTask对象或None
        """
        sql = "SELECT * FROM location_multi_angle_tasks WHERE task_key = %s"

        try:
            result = execute_query(sql, (task_key,), fetch_one=True)
            if result:
                return LocationMultiAngleTask(**result)
            return None
        except Exception as e:
            logger.error(f"Failed to get location multi-angle task by task_key {task_key}: {e}")
            raise

    @staticmethod
    def get_pending_tasks(limit: int = 10) -> List[LocationMultiAngleTask]:
        """
        获取待处理的任务（状态为QUEUED或PROCESSING）

        Args:
            limit: 最大返回数量

        Returns:
            LocationMultiAngleTask对象列表
        """
        sql = """
            SELECT * FROM location_multi_angle_tasks
            WHERE status IN (%s, %s)
            ORDER BY created_at ASC
            LIMIT %s
        """

        try:
            results = execute_query(
                sql,
                (LocationMultiAngleTaskStatus.QUEUED, LocationMultiAngleTaskStatus.PROCESSING, limit),
                fetch_all=True
            )
            tasks = [LocationMultiAngleTask(**row) for row in results] if results else []
            return tasks
        except Exception as e:
            logger.error(f"Failed to get pending location multi-angle tasks: {e}")
            raise

    @staticmethod
    def get_user_tasks(user_id: str, world_id: str = None, limit: int = 50) -> List[LocationMultiAngleTask]:
        """
        获取用户的任务列表

        Args:
            user_id: 用户ID
            world_id: 世界观ID（可选）
            limit: 最大返回数量

        Returns:
            LocationMultiAngleTask对象列表
        """
        if world_id:
            sql = """
                SELECT * FROM location_multi_angle_tasks
                WHERE user_id = %s AND world_id = %s
                ORDER BY created_at DESC
                LIMIT %s
            """
            params = (user_id, world_id, limit)
        else:
            sql = """
                SELECT * FROM location_multi_angle_tasks
                WHERE user_id = %s
                ORDER BY created_at DESC
                LIMIT %s
            """
            params = (user_id, limit)

        try:
            results = execute_query(sql, params, fetch_all=True)
            tasks = [LocationMultiAngleTask(**row) for row in results] if results else []
            return tasks
        except Exception as e:
            logger.error(f"Failed to get user location multi-angle tasks: {e}")
            raise

    @staticmethod
    def update_status(
        task_key: str,
        status: int,
        current_angle_index: int = None,
        generated_images: List[Dict[str, Any]] = None,
        error_message: str = None,
        ai_tool_task_id: int = None
    ) -> int:
        """
        更新任务状态

        Args:
            task_key: 任务唯一键
            status: 新状态
            current_angle_index: 当前视角索引
            generated_images: 已生成的图片列表
            error_message: 错误信息
            ai_tool_task_id: 关联的AI工具任务ID

        Returns:
            影响的行数
        """
        update_fields = ["status = %s"]
        params = [status]

        if current_angle_index is not None:
            update_fields.append("current_angle_index = %s")
            params.append(current_angle_index)

        if generated_images is not None:
            update_fields.append("generated_images = %s")
            params.append(json.dumps(generated_images, ensure_ascii=False))

        if error_message is not None:
            update_fields.append("error_message = %s")
            params.append(error_message)

        if ai_tool_task_id is not None:
            update_fields.append("ai_tool_task_id = %s")
            params.append(ai_tool_task_id)

        # 根据状态设置完成/失败时间
        if status == LocationMultiAngleTaskStatus.COMPLETED:
            update_fields.append("completed_at = NOW()")
        elif status == LocationMultiAngleTaskStatus.FAILED:
            update_fields.append("failed_at = NOW()")

        params.append(task_key)
        sql = f"UPDATE location_multi_angle_tasks SET {', '.join(update_fields)} WHERE task_key = %s"

        try:
            affected_rows = execute_update(sql, tuple(params))
            logger.info(f"Updated location multi-angle task {task_key} status to {status}")
            return affected_rows
        except Exception as e:
            logger.error(f"Failed to update location multi-angle task {task_key}: {e}")
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
        sql = "DELETE FROM location_multi_angle_tasks WHERE task_key = %s"

        try:
            affected_rows = execute_update(sql, (task_key,))
            logger.info(f"Deleted location multi-angle task {task_key}")
            return affected_rows
        except Exception as e:
            logger.error(f"Failed to delete location multi-angle task {task_key}: {e}")
            raise

    @staticmethod
    def has_running_task(user_id: str, world_id: str, location_name: str) -> Optional[LocationMultiAngleTask]:
        """
        检查是否存在正在执行中的任务

        Args:
            user_id: 用户ID
            world_id: 世界观ID
            location_name: 场景名称

        Returns:
            如果存在运行中的任务，返回该任务；否则返回None
        """
        sql = """
            SELECT * FROM location_multi_angle_tasks
            WHERE user_id = %s AND world_id = %s AND location_name = %s
              AND status IN (%s, %s)
            ORDER BY created_at DESC
            LIMIT 1
        """

        try:
            result = execute_query(
                sql,
                (user_id, world_id, location_name,
                 LocationMultiAngleTaskStatus.QUEUED, LocationMultiAngleTaskStatus.PROCESSING),
                fetch_one=True
            )
            if result:
                return LocationMultiAngleTask(**result)
            return None
        except Exception as e:
            logger.error(f"Failed to check running task for {location_name}: {e}")
            raise
