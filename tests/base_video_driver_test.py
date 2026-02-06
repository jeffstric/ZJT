"""
视频驱动测试基类
提供视频驱动测试的通用方法和数据库操作
"""
from tests.base_db_test import DatabaseTestCase


class BaseVideoDriverTest(DatabaseTestCase):
    """视频驱动测试基类"""
    
    def create_test_ai_tool(self, ai_tool_type, **kwargs):
        """
        创建测试用的 AI 工具记录
        
        Args:
            ai_tool_type: AI 工具类型
            **kwargs: 其他字段
        
        Returns:
            int: AI 工具 ID
        """
        default_data = {
            'prompt': '测试提示词',
            'user_id': 1001,
            'type': ai_tool_type,
            'status': 0
        }
        default_data.update(kwargs)
        
        return self.insert_fixture('ai_tools', default_data)
    
    def get_ai_tool_from_db(self, ai_tool_id):
        """
        从数据库获取 AI 工具对象
        
        Args:
            ai_tool_id: AI 工具 ID
        
        Returns:
            object: AI 工具对象
        """
        result = self.execute_query(
            "SELECT * FROM `ai_tools` WHERE id = %s",
            (ai_tool_id,)
        )
        if result:
            # 将字典转换为对象，方便访问属性
            ai_tool = type('AITool', (), result[0])()
            return ai_tool
        return None
    
    def update_ai_tool_status(self, ai_tool_id, status, **kwargs):
        """
        更新 AI 工具状态
        
        Args:
            ai_tool_id: AI 工具 ID
            status: 状态值
            **kwargs: 其他要更新的字段
        """
        updates = {'status': status}
        updates.update(kwargs)
        
        set_clause = ', '.join([f"{k} = %s" for k in updates.keys()])
        values = list(updates.values()) + [ai_tool_id]
        
        return self.execute_update(
            f"UPDATE `ai_tools` SET {set_clause} WHERE id = %s",
            tuple(values)
        )
    
    def create_test_task(self, task_type, task_id, **kwargs):
        """
        创建测试任务记录
        
        Args:
            task_type: 任务类型
            task_id: 任务 ID
            **kwargs: 其他字段
        
        Returns:
            int: 任务表 ID
        """
        default_data = {
            'task_type': task_type,
            'task_id': task_id,
            'try_count': 0,
            'status': 0
        }
        default_data.update(kwargs)
        
        return self.insert_fixture('tasks', default_data)
    
    def assert_ai_tool_status(self, ai_tool_id, expected_status):
        """
        断言 AI 工具状态
        
        Args:
            ai_tool_id: AI 工具 ID
            expected_status: 期望的状态
        """
        result = self.execute_query(
            "SELECT status FROM `ai_tools` WHERE id = %s",
            (ai_tool_id,)
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['status'], expected_status)
    
    def assert_ai_tool_has_project_id(self, ai_tool_id):
        """
        断言 AI 工具有 project_id
        
        Args:
            ai_tool_id: AI 工具 ID
        
        Returns:
            str: project_id
        """
        result = self.execute_query(
            "SELECT project_id FROM `ai_tools` WHERE id = %s",
            (ai_tool_id,)
        )
        self.assertEqual(len(result), 1)
        self.assertIsNotNone(result[0]['project_id'])
        return result[0]['project_id']
    
    def assert_ai_tool_has_result(self, ai_tool_id):
        """
        断言 AI 工具有结果 URL
        
        Args:
            ai_tool_id: AI 工具 ID
        
        Returns:
            str: result_url
        """
        result = self.execute_query(
            "SELECT result_url FROM `ai_tools` WHERE id = %s",
            (ai_tool_id,)
        )
        self.assertEqual(len(result), 1)
        self.assertIsNotNone(result[0]['result_url'])
        return result[0]['result_url']
