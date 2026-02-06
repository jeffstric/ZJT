"""
RunningHubSlots 表 CRUD 测试
"""
import unittest
from datetime import datetime
from .base_db_test import DatabaseTestCase


class TestRunningHubSlotsCRUD(DatabaseTestCase):
    """RunningHubSlots 表增删改查测试"""
    
    def test_create_slot(self):
        """测试创建槽位"""
        slot_id = self.insert_fixture('runninghub_slots', {
            'task_id': 1001,
            'task_table_id': 2001,
            'project_id': 'rh_proj_123',
            'task_type': 10,
            'status': 1
        })
        
        self.assertIsNotNone(slot_id)
        self.assertGreater(slot_id, 0)
    
    def test_read_slot(self):
        """测试查询槽位"""
        slot_id = self.insert_fixture('runninghub_slots', {
            'task_id': 1002,
            'task_table_id': 2002,
            'task_type': 11,
            'status': 1
        })
        
        result = self.execute_query(
            "SELECT * FROM `runninghub_slots` WHERE id = %s",
            (slot_id,)
        )
        
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['task_id'], 1002)
        self.assertEqual(result[0]['task_type'], 11)
        self.assertEqual(result[0]['status'], 1)
    
    def test_update_slot(self):
        """测试更新槽位"""
        slot_id = self.insert_fixture('runninghub_slots', {
            'task_id': 1003,
            'task_table_id': 2003,
            'task_type': 10,
            'status': 1
        })
        
        affected_rows = self.execute_update(
            "UPDATE `runninghub_slots` SET status = %s, project_id = %s WHERE id = %s",
            (2, 'rh_proj_456', slot_id)
        )
        
        self.assertEqual(affected_rows, 1)
        
        result = self.execute_query(
            "SELECT * FROM `runninghub_slots` WHERE id = %s",
            (slot_id,)
        )
        
        self.assertEqual(result[0]['status'], 2)
        self.assertEqual(result[0]['project_id'], 'rh_proj_456')
    
    def test_delete_slot(self):
        """测试删除槽位"""
        slot_id = self.insert_fixture('runninghub_slots', {
            'task_id': 1004,
            'task_table_id': 2004,
            'task_type': 10,
            'status': 2
        })
        
        count_before = self.count_rows('runninghub_slots', 'id = %s', (slot_id,))
        self.assertEqual(count_before, 1)
        
        affected_rows = self.execute_update(
            "DELETE FROM `runninghub_slots` WHERE id = %s",
            (slot_id,)
        )
        
        self.assertEqual(affected_rows, 1)
        
        count_after = self.count_rows('runninghub_slots', 'id = %s', (slot_id,))
        self.assertEqual(count_after, 0)
    
    def test_query_slots_by_status_and_type(self):
        """测试按状态和类型查询槽位"""
        self.insert_fixture('runninghub_slots', {
            'task_id': 1005,
            'task_table_id': 2005,
            'task_type': 10,
            'status': 1
        })
        self.insert_fixture('runninghub_slots', {
            'task_id': 1006,
            'task_table_id': 2006,
            'task_type': 10,
            'status': 1
        })
        self.insert_fixture('runninghub_slots', {
            'task_id': 1007,
            'task_table_id': 2007,
            'task_type': 11,
            'status': 1
        })
        
        result = self.execute_query(
            "SELECT * FROM `runninghub_slots` WHERE status = %s AND task_type = %s",
            (1, 10)
        )
        
        self.assertEqual(len(result), 2)
        for row in result:
            self.assertEqual(row['status'], 1)
            self.assertEqual(row['task_type'], 10)
    
    def test_query_slot_by_task_table_id(self):
        """测试按 task_table_id 查询槽位（唯一键）"""
        task_table_id = 3001
        
        slot_id = self.insert_fixture('runninghub_slots', {
            'task_id': 1008,
            'task_table_id': task_table_id,
            'task_type': 10,
            'status': 1
        })
        
        result = self.execute_query(
            "SELECT * FROM `runninghub_slots` WHERE task_table_id = %s",
            (task_table_id,)
        )
        
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['task_table_id'], task_table_id)
        self.assertEqual(result[0]['id'], slot_id)


if __name__ == '__main__':
    unittest.main()
