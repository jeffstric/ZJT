"""
Tasks 表 CRUD 测试
"""
import unittest
from datetime import datetime, timedelta
from .base_db_test import DatabaseTestCase


class TestTasksCRUD(DatabaseTestCase):
    """Tasks 表增删改查测试"""
    
    def test_create_task(self):
        """测试创建任务"""
        task_id = self.insert_fixture('tasks', {
            'task_type': 'video_generation',
            'task_id': 1001,
            'try_count': 0,
            'status': 0
        })
        
        self.assertIsNotNone(task_id)
        self.assertGreater(task_id, 0)
    
    def test_read_task(self):
        """测试查询任务"""
        task_id = self.insert_fixture('tasks', {
            'task_type': 'audio_generation',
            'task_id': 1002,
            'try_count': 0,
            'status': 1
        })
        
        result = self.execute_query(
            "SELECT * FROM `tasks` WHERE id = %s",
            (task_id,)
        )
        
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['task_type'], 'audio_generation')
        self.assertEqual(result[0]['task_id'], 1002)
        self.assertEqual(result[0]['status'], 1)
    
    def test_update_task(self):
        """测试更新任务"""
        task_id = self.insert_fixture('tasks', {
            'task_type': 'image_generation',
            'task_id': 1003,
            'try_count': 0,
            'status': 0
        })
        
        affected_rows = self.execute_update(
            "UPDATE `tasks` SET status = %s, try_count = %s, updated_at = %s WHERE id = %s",
            (1, 1, datetime.now(), task_id)
        )
        
        self.assertEqual(affected_rows, 1)
        
        result = self.execute_query(
            "SELECT * FROM `tasks` WHERE id = %s",
            (task_id,)
        )
        
        self.assertEqual(result[0]['status'], 1)
        self.assertEqual(result[0]['try_count'], 1)
    
    def test_delete_task(self):
        """测试删除任务"""
        task_id = self.insert_fixture('tasks', {
            'task_type': 'temp_task',
            'task_id': 1004,
            'try_count': 0,
            'status': 2
        })
        
        count_before = self.count_rows('tasks', 'id = %s', (task_id,))
        self.assertEqual(count_before, 1)
        
        affected_rows = self.execute_update(
            "DELETE FROM `tasks` WHERE id = %s",
            (task_id,)
        )
        
        self.assertEqual(affected_rows, 1)
        
        count_after = self.count_rows('tasks', 'id = %s', (task_id,))
        self.assertEqual(count_after, 0)
    
    def test_query_tasks_by_type_and_status(self):
        """测试按类型和状态查询任务"""
        self.insert_fixture('tasks', {
            'task_type': 'video_generation',
            'task_id': 1005,
            'try_count': 0,
            'status': 0
        })
        self.insert_fixture('tasks', {
            'task_type': 'video_generation',
            'task_id': 1006,
            'try_count': 0,
            'status': 0
        })
        self.insert_fixture('tasks', {
            'task_type': 'audio_generation',
            'task_id': 1007,
            'try_count': 0,
            'status': 0
        })
        
        result = self.execute_query(
            "SELECT * FROM `tasks` WHERE task_type = %s AND status = %s",
            ('video_generation', 0)
        )
        
        self.assertEqual(len(result), 2)
        for row in result:
            self.assertEqual(row['task_type'], 'video_generation')
            self.assertEqual(row['status'], 0)
    
    def test_query_failed_tasks(self):
        """测试查询失败任务"""
        self.insert_fixture('tasks', {
            'task_type': 'video_generation',
            'task_id': 1008,
            'try_count': 3,
            'status': -1
        })
        self.insert_fixture('tasks', {
            'task_type': 'audio_generation',
            'task_id': 1009,
            'try_count': 2,
            'status': -1
        })
        
        result = self.execute_query(
            "SELECT * FROM `tasks` WHERE status = %s",
            (-1,)
        )
        
        self.assertGreaterEqual(len(result), 2)
        for row in result:
            self.assertEqual(row['status'], -1)
    
    def test_query_tasks_by_next_trigger(self):
        """测试按下次执行时间查询任务"""
        future_time = datetime.now() + timedelta(hours=1)
        
        task_id = self.insert_fixture('tasks', {
            'task_type': 'scheduled_task',
            'task_id': 1010,
            'try_count': 0,
            'status': 0
        })
        
        self.execute_update(
            "UPDATE `tasks` SET next_trigger = %s WHERE id = %s",
            (future_time, task_id)
        )
        
        result = self.execute_query(
            "SELECT * FROM `tasks` WHERE next_trigger > %s AND status = %s",
            (datetime.now(), 0)
        )
        
        self.assertGreaterEqual(len(result), 1)
    
    def test_increment_try_count(self):
        """测试增加重试次数"""
        task_id = self.insert_fixture('tasks', {
            'task_type': 'retry_task',
            'task_id': 1011,
            'try_count': 0,
            'status': 0
        })
        
        for i in range(1, 4):
            self.execute_update(
                "UPDATE `tasks` SET try_count = try_count + 1 WHERE id = %s",
                (task_id,)
            )
            
            result = self.execute_query(
                "SELECT try_count FROM `tasks` WHERE id = %s",
                (task_id,)
            )
            
            self.assertEqual(result[0]['try_count'], i)
    
    def test_query_pending_tasks(self):
        """测试查询待处理任务"""
        self.insert_fixture('tasks', {
            'task_type': 'video_generation',
            'task_id': 1012,
            'try_count': 0,
            'status': 0
        })
        self.insert_fixture('tasks', {
            'task_type': 'audio_generation',
            'task_id': 1013,
            'try_count': 0,
            'status': 0
        })
        
        result = self.execute_query(
            "SELECT * FROM `tasks` WHERE status = %s ORDER BY created_at",
            (0,)
        )
        
        self.assertGreaterEqual(len(result), 2)


if __name__ == '__main__':
    unittest.main()
