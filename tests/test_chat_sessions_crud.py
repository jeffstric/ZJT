"""
Chat Sessions 表 CRUD 测试
"""
import unittest
import json
from datetime import datetime, timedelta
from .base_db_test import DatabaseTestCase


class TestChatSessionsCRUD(DatabaseTestCase):
    """ChatSessions 表增删改查测试"""

    def test_create_session(self):
        """测试创建会话"""
        session_id = "test-session-001"
        history = [{"role": "user", "content": "Hello"}]

        session_id_result = self.insert_fixture('chat_sessions', {
            'session_id': session_id,
            'user_id': '1',
            'world_id': '1',
            'auth_token': 'test_token',
            'model': 'gemini-2.0-flash-exp',
            'conversation_history': json.dumps(history),
            'total_input_tokens': 100,
            'total_output_tokens': 50
        })

        self.assertIsNotNone(session_id_result)
        self.assertGreater(session_id_result, 0)

    def test_read_session(self):
        """测试查询会话"""
        session_id = "test-session-002"
        history = [{"role": "user", "content": "Test message"}]

        inserted_id = self.insert_fixture('chat_sessions', {
            'session_id': session_id,
            'user_id': '2',
            'world_id': '1',
            'model': 'gemini-3-flash-preview',
            'conversation_history': json.dumps(history)
        })

        result = self.execute_query(
            "SELECT * FROM `chat_sessions` WHERE id = %s",
            (inserted_id,)
        )

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['session_id'], session_id)
        self.assertEqual(result[0]['user_id'], '2')
        self.assertEqual(result[0]['world_id'], '1')

    def test_update_conversation_history(self):
        """测试更新对话历史"""
        session_id = "test-session-003"
        initial_history = [{"role": "user", "content": "Initial"}]
        updated_history = [
            {"role": "user", "content": "Initial"},
            {"role": "assistant", "content": "Response"}
        ]

        inserted_id = self.insert_fixture('chat_sessions', {
            'session_id': session_id,
            'user_id': '3',
            'world_id': '1',
            'conversation_history': json.dumps(initial_history)
        })

        affected_rows = self.execute_update(
            "UPDATE `chat_sessions` SET conversation_history = %s, updated_at = %s WHERE id = %s",
            (json.dumps(updated_history), datetime.now(), inserted_id)
        )

        self.assertEqual(affected_rows, 1)

        result = self.execute_query(
            "SELECT conversation_history FROM `chat_sessions` WHERE id = %s",
            (inserted_id,)
        )

        retrieved_history = json.loads(result[0]['conversation_history'])
        self.assertEqual(len(retrieved_history), 2)

    def test_update_model(self):
        """测试更新会话模型"""
        session_id = "test-session-004"

        inserted_id = self.insert_fixture('chat_sessions', {
            'session_id': session_id,
            'user_id': '4',
            'world_id': '1',
            'model': 'gemini-2.0-flash-exp',
            'model_id': 1
        })

        affected_rows = self.execute_update(
            "UPDATE `chat_sessions` SET model = %s, model_id = %s WHERE id = %s",
            ('claude-3-7-sonnet', 2, inserted_id)
        )

        self.assertEqual(affected_rows, 1)

        result = self.execute_query(
            "SELECT model, model_id FROM `chat_sessions` WHERE id = %s",
            (inserted_id,)
        )

        self.assertEqual(result[0]['model'], 'claude-3-7-sonnet')
        self.assertEqual(result[0]['model_id'], 2)

    def test_clear_history(self):
        """测试清空对话历史"""
        session_id = "test-session-005"
        history = [{"role": "user", "content": "Message"}]

        inserted_id = self.insert_fixture('chat_sessions', {
            'session_id': session_id,
            'user_id': '5',
            'world_id': '1',
            'conversation_history': json.dumps(history)
        })

        affected_rows = self.execute_update(
            "UPDATE `chat_sessions` SET conversation_history = %s WHERE id = %s",
            (json.dumps([]), inserted_id)
        )

        self.assertEqual(affected_rows, 1)

        result = self.execute_query(
            "SELECT conversation_history FROM `chat_sessions` WHERE id = %s",
            (inserted_id,)
        )

        retrieved_history = json.loads(result[0]['conversation_history'])
        self.assertEqual(len(retrieved_history), 0)

    def test_soft_delete_session(self):
        """测试软删除会话"""
        session_id = "test-session-006"

        inserted_id = self.insert_fixture('chat_sessions', {
            'session_id': session_id,
            'user_id': '6',
            'world_id': '1'
        })

        # 验证初始状态为 active
        result = self.execute_query(
            "SELECT is_active FROM `chat_sessions` WHERE id = %s",
            (inserted_id,)
        )
        self.assertEqual(result[0]['is_active'], 1)

        # 软删除
        affected_rows = self.execute_update(
            "UPDATE `chat_sessions` SET is_active = 0 WHERE id = %s",
            (inserted_id,)
        )

        self.assertEqual(affected_rows, 1)

        # 验证已删除
        result = self.execute_query(
            "SELECT is_active FROM `chat_sessions` WHERE id = %s",
            (inserted_id,)
        )
        self.assertEqual(result[0]['is_active'], 0)

    def test_delete_expired_sessions(self):
        """测试删除过期会话"""
        # 创建已过期的会话
        expired_time = datetime.now() - timedelta(hours=25)

        self.insert_fixture('chat_sessions', {
            'session_id': 'expired-session-001',
            'user_id': '7',
            'world_id': '1',
            'expires_at': expired_time
        })

        # 创建未过期的会话
        future_time = datetime.now() + timedelta(hours=24)

        self.insert_fixture('chat_sessions', {
            'session_id': 'active-session-001',
            'user_id': '8',
            'world_id': '1',
            'expires_at': future_time
        })

        # 创建永不过期的会话
        self.insert_fixture('chat_sessions', {
            'session_id': 'never-expire-session-001',
            'user_id': '9',
            'world_id': '1',
            'expires_at': None
        })

        # 删除过期会话
        cutoff_time = datetime.now() - timedelta(hours=24)
        affected_rows = self.execute_update(
            "UPDATE `chat_sessions` SET is_active = 0 WHERE expires_at <= %s AND is_active = 1",
            (cutoff_time,)
        )

        self.assertGreaterEqual(affected_rows, 1)

        # 验证过期会话已被标记为不活跃
        result = self.execute_query(
            "SELECT is_active FROM `chat_sessions` WHERE session_id = %s",
            ('expired-session-001',)
        )
        self.assertEqual(result[0]['is_active'], 0)

        # 验证未过期会话仍然活跃
        result = self.execute_query(
            "SELECT is_active FROM `chat_sessions` WHERE session_id = %s",
            ('active-session-001',)
        )
        self.assertEqual(result[0]['is_active'], 1)

        # 验证永不过期的会话仍然活跃
        result = self.execute_query(
            "SELECT is_active FROM `chat_sessions` WHERE session_id = %s",
            ('never-expire-session-001',)
        )
        self.assertEqual(result[0]['is_active'], 1)

    def test_query_sessions_by_user(self):
        """测试按用户查询会话"""
        user_id = '10'

        self.insert_fixture('chat_sessions', {
            'session_id': 'user-session-001',
            'user_id': user_id,
            'world_id': '1'
        })

        self.insert_fixture('chat_sessions', {
            'session_id': 'user-session-002',
            'user_id': user_id,
            'world_id': '2'
        })

        self.insert_fixture('chat_sessions', {
            'session_id': 'other-session-001',
            'user_id': '11',
            'world_id': '1'
        })

        result = self.execute_query(
            "SELECT * FROM `chat_sessions` WHERE user_id = %s AND is_active = 1 ORDER BY created_at DESC",
            (user_id,)
        )

        self.assertEqual(len(result), 2)
        for row in result:
            self.assertEqual(row['user_id'], user_id)

    def test_query_sessions_by_user_and_world(self):
        """测试按用户和世界查询会话"""
        user_id = '12'
        world_id = '5'

        self.insert_fixture('chat_sessions', {
            'session_id': 'world-session-001',
            'user_id': user_id,
            'world_id': world_id
        })

        self.insert_fixture('chat_sessions', {
            'session_id': 'world-session-002',
            'user_id': user_id,
            'world_id': '6'
        })

        result = self.execute_query(
            "SELECT * FROM `chat_sessions` WHERE user_id = %s AND world_id = %s AND is_active = 1",
            (user_id, world_id)
        )

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['world_id'], world_id)

    def test_update_token_statistics(self):
        """测试更新 token 统计"""
        session_id = "test-session-007"

        inserted_id = self.insert_fixture('chat_sessions', {
            'session_id': session_id,
            'user_id': '13',
            'world_id': '1',
            'total_input_tokens': 100,
            'total_output_tokens': 50
        })

        # 累加 token
        affected_rows = self.execute_update(
            """UPDATE `chat_sessions`
               SET total_input_tokens = total_input_tokens + %s,
                   total_output_tokens = total_output_tokens + %s
               WHERE id = %s""",
            (200, 100, inserted_id)
        )

        self.assertEqual(affected_rows, 1)

        result = self.execute_query(
            "SELECT total_input_tokens, total_output_tokens FROM `chat_sessions` WHERE id = %s",
            (inserted_id,)
        )

        self.assertEqual(result[0]['total_input_tokens'], 300)
        self.assertEqual(result[0]['total_output_tokens'], 150)

    def test_query_active_sessions_only(self):
        """测试只查询活跃会话"""
        # 创建活跃会话
        self.insert_fixture('chat_sessions', {
            'session_id': 'active-session-002',
            'user_id': '14',
            'world_id': '1',
            'is_active': 1
        })

        # 创建不活跃会话
        self.insert_fixture('chat_sessions', {
            'session_id': 'inactive-session-001',
            'user_id': '15',
            'world_id': '1',
            'is_active': 0
        })

        # 只查询活跃会话
        result = self.execute_query(
            "SELECT * FROM `chat_sessions` WHERE is_active = 1"
        )

        # 验证结果中不包含不活跃会话
        session_ids = [row['session_id'] for row in result]
        self.assertNotIn('inactive-session-001', session_ids)
        self.assertIn('active-session-002', session_ids)


if __name__ == '__main__':
    unittest.main()
