"""
RunningHub Slots Model - 并发槽位管理
用于控制 RunningHub API 的并发请求数量，避免 TASK_QUEUE_MAXED 错误
"""
from typing import Optional
from .database import execute_query, execute_update, execute_insert
import logging
from config.config_util import get_dynamic_config_value

logger = logging.getLogger(__name__)


def _get_max_concurrent_slots():
    """动态获取最大槽位数量"""
    return get_dynamic_config_value("runninghub", "max_concurrent_slots", default=3)


class RunningHubSlot:
    """RunningHub 槽位模型类"""

    # source 常量
    SOURCE_TASK = 'task'    # 来自 tasks 表（视频生成）
    SOURCE_ASYNC = 'async'  # 来自 async_tasks 表（音频、人脸遮盖等）

    def __init__(self, **kwargs):
        self.id = kwargs.get('id')
        self.task_id = kwargs.get('task_id')
        self.project_id = kwargs.get('project_id')
        self.task_type = kwargs.get('task_type')
        self.api_key_index = kwargs.get('api_key_index', 0)
        self.source = kwargs.get('source', self.SOURCE_TASK)
        self.status = kwargs.get('status')
        self.acquired_at = kwargs.get('acquired_at')
        self.released_at = kwargs.get('released_at')
        self.created_at = kwargs.get('created_at')
        self.updated_at = kwargs.get('updated_at')

    def to_dict(self):
        """转换为字典"""
        return {
            'id': self.id,
            'task_id': self.task_id,
            'project_id': self.project_id,
            'task_type': self.task_type,
            'api_key_index': self.api_key_index,
            'source': self.source,
            'status': self.status,
            'acquired_at': self.acquired_at.isoformat() if self.acquired_at else None,
            'released_at': self.released_at.isoformat() if self.released_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }


class RunningHubSlotsModel:
    """RunningHub 槽位管理模型"""

    @staticmethod
    def count_active_slots() -> int:
        """
        统计当前活跃的槽位数量

        Returns:
            活跃槽位数量
        """
        sql = """
            SELECT COUNT(*) as count
            FROM runninghub_slots
            WHERE status = 1
        """
        try:
            result = execute_query(sql, fetch_one=True)
            count = result['count'] if result else 0
            logger.debug(f"Active RunningHub slots: {count}")
            return count
        except Exception as e:
            logger.error(f"Failed to count active slots: {e}")
            return 0

    @staticmethod
    def count_active_slots_by_key(api_key_index: int) -> int:
        """
        统计某个密钥当前活跃（占用中）的槽位数量。

        用于多密钥轮换时判断单个密钥是否达并发上限。

        Args:
            api_key_index: 密钥序号 (0=全局key, 1~10=密钥池)

        Returns:
            该密钥的活跃槽位数量
        """
        sql = """
            SELECT COUNT(*) as count
            FROM runninghub_slots
            WHERE status = 1 AND api_key_index = %s
        """
        try:
            result = execute_query(sql, (api_key_index,), fetch_one=True)
            count = result['count'] if result else 0
            logger.debug(f"Active RunningHub slots for api_key_index={api_key_index}: {count}")
            return count
        except Exception as e:
            logger.error(f"Failed to count active slots by key {api_key_index}: {e}")
            return 0

    @staticmethod
    def try_acquire_slot(task_id: int, task_type: int, source: str, max_slots: int = None, api_key_index: int = 0) -> bool:
        """
        尝试获取槽位（带并发检查，幂等操作）

        Args:
            task_id: 源表主键 (source='task' 时为 tasks.id, source='async' 时为 async_tasks.id)
            task_type: 任务类型 (10-LTX2.0, 11-Wan2.2, 1-异步音频, 2-异步人脸遮盖)
            source: 来源标识 (SOURCE_TASK 或 SOURCE_ASYNC)
            max_slots: 最大槽位数，默认从配置文件读取
            api_key_index: 所用密钥序号 (0=全局key, 1~10=密钥池)，用于多密钥轮换时记录关联

        Returns:
            是否成功获取槽位
        """
        try:
            if max_slots is None:
                max_slots = _get_max_concurrent_slots()

            # 先检查是否已持有活跃槽位（避免不必要的写操作）
            existing = RunningHubSlotsModel.get_slot(task_id, source)
            if existing and existing.status == 1:
                logger.info(f"Slot already active for {source} task {task_id}")
                return True

            current_count = RunningHubSlotsModel.count_active_slots()

            if current_count >= max_slots:
                logger.info(f"RunningHub slots full ({current_count}/{max_slots}), cannot acquire for {source} task {task_id}")
                return False

            # 使用 INSERT ON DUPLICATE KEY UPDATE 实现幂等
            # 解决任务重试时旧记录（status=2）仍存在导致唯一键冲突的问题
            sql = """
                INSERT INTO runninghub_slots
                (task_id, task_type, api_key_index, status, source, acquired_at)
                VALUES (%s, %s, %s, 1, %s, NOW())
                ON DUPLICATE KEY UPDATE
                    status = 1,
                    task_type = VALUES(task_type),
                    api_key_index = VALUES(api_key_index),
                    acquired_at = NOW(),
                    released_at = NULL
            """
            execute_insert(sql, (task_id, task_type, api_key_index, source))

            logger.info(f"Acquired RunningHub slot for {source} task {task_id} (key_index={api_key_index}), slots: {current_count + 1}/{max_slots}")
            return True

        except Exception as e:
            logger.warning(f"Failed to acquire slot for {source} task {task_id}: {e}")
            return False

    @staticmethod
    def update_project_id(task_id: int, project_id: str, source: str) -> int:
        """
        更新槽位的 project_id（任务提交成功后）

        Args:
            task_id: 源表主键
            project_id: RunningHub项目ID
            source: 来源标识

        Returns:
            影响的行数
        """
        sql = """
            UPDATE runninghub_slots
            SET project_id = %s
            WHERE task_id = %s AND source = %s AND status = 1
        """
        try:
            affected = execute_update(sql, (project_id, task_id, source))
            logger.info(f"Updated project_id for {source} task {task_id}: {project_id}")
            return affected
        except Exception as e:
            logger.error(f"Failed to update project_id for {source} task {task_id}: {e}")
            return 0

    @staticmethod
    def release_slot(task_id: int, source: str) -> int:
        """
        通过 task_id + source 释放槽位

        Args:
            task_id: 源表主键
            source: 来源标识

        Returns:
            影响的行数
        """
        sql = """
            UPDATE runninghub_slots
            SET status = 2, released_at = NOW()
            WHERE task_id = %s AND source = %s AND status = 1
        """
        try:
            affected = execute_update(sql, (task_id, source))
            if affected > 0:
                logger.info(f"Released RunningHub slot for {source} task {task_id}")
            return affected
        except Exception as e:
            logger.error(f"Failed to release slot for {source} task {task_id}: {e}")
            return 0

    @staticmethod
    def release_slot_by_project_id(project_id: str) -> int:
        """
        通过 project_id 释放槽位

        Args:
            project_id: RunningHub项目ID

        Returns:
            影响的行数
        """
        sql = """
            UPDATE runninghub_slots
            SET status = 2, released_at = NOW()
            WHERE project_id = %s AND status = 1
        """
        try:
            affected = execute_update(sql, (project_id,))
            if affected > 0:
                logger.info(f"Released RunningHub slot for project_id {project_id}")
            return affected
        except Exception as e:
            logger.error(f"Failed to release slot for project_id {project_id}: {e}")
            return 0

    @staticmethod
    def get_slot(task_id: int, source: str) -> Optional[RunningHubSlot]:
        """
        通过 task_id + source 获取槽位信息

        Args:
            task_id: 源表主键
            source: 来源标识

        Returns:
            RunningHubSlot 对象或 None
        """
        sql = """
            SELECT * FROM runninghub_slots
            WHERE task_id = %s AND source = %s
        """
        try:
            result = execute_query(sql, (task_id, source), fetch_one=True)
            if result:
                return RunningHubSlot(**result)
            return None
        except Exception as e:
            logger.error(f"Failed to get slot for {source} task {task_id}: {e}")
            return None

    @staticmethod
    def cleanup_stale_slots(timeout_minutes: int = 60) -> int:
        """
        清理超时的槽位（超过指定时间仍未完成的任务）

        Args:
            timeout_minutes: 超时时间（分钟），默认60分钟

        Returns:
            清理的槽位数量
        """
        sql = """
            UPDATE runninghub_slots
            SET status = 2, released_at = NOW()
            WHERE status = 1
            AND acquired_at < DATE_SUB(NOW(), INTERVAL %s MINUTE)
        """
        try:
            affected = execute_update(sql, (timeout_minutes,))
            if affected > 0:
                logger.warning(f"Cleaned up {affected} stale RunningHub slots (timeout: {timeout_minutes}min)")
            return affected
        except Exception as e:
            logger.error(f"Failed to cleanup stale slots: {e}")
            return 0


CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS `runninghub_slots` (
  `id` int unsigned NOT NULL AUTO_INCREMENT COMMENT '主键ID',
  `task_id` int unsigned NOT NULL DEFAULT '0' COMMENT 'source=task 时存 tasks.id，source=async 时存 async_tasks.id',
  `project_id` varchar(100) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT 'RunningHub项目ID（提交后才有）',
  `task_type` tinyint NOT NULL COMMENT '任务类型(10-LTX2.0, 11-Wan2.2, 1-异步音频, 2-异步人脸遮盖)',
  `api_key_index` int NOT NULL DEFAULT '0' COMMENT '所用密钥序号: 0=全局key(runninghub.api_key), 1~10=密钥池第N个',
  `source` varchar(10) NOT NULL DEFAULT 'task' COMMENT '来源: task-tasks表, async-async_tasks表',
  `status` tinyint NOT NULL DEFAULT '1' COMMENT '状态: 1-槽位占用中, 2-已释放',
  `acquired_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '槽位获取时间',
  `released_at` datetime DEFAULT NULL COMMENT '槽位释放时间',
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updated_at` datetime DEFAULT NULL ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_task_id_source` (`task_id`, `source`),
  KEY `idx_status_task_type` (`status`,`task_type`),
  KEY `idx_project_id` (`project_id`),
  KEY `idx_api_key_index` (`api_key_index`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='RunningHub并发槽位管理表';
"""
