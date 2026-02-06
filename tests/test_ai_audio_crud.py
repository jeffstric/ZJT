"""
AIAudio 表 CRUD 测试
"""
import unittest
from .base_db_test import DatabaseTestCase


class TestAIAudioCRUD(DatabaseTestCase):
    """AIAudio 表增删改查测试"""
    
    def test_create_ai_audio(self):
        """测试创建音频生成记录"""
        audio_id = self.insert_fixture('ai_audio', {
            'text': '这是一段需要生成语音的文本',
            'ref_path': 'https://example.com/ref_audio.mp3',
            'user_id': 1,
            'status': 0,
            'emo_control_method': 0
        })
        
        self.assertIsNotNone(audio_id)
        self.assertGreater(audio_id, 0)
    
    def test_read_ai_audio(self):
        """测试查询音频生成记录"""
        audio_id = self.insert_fixture('ai_audio', {
            'text': '测试文本内容',
            'ref_path': 'https://example.com/audio.mp3',
            'user_id': 1,
            'status': 1,
            'emo_control_method': 1,
            'emo_ref_path': 'https://example.com/emo_ref.mp3'
        })
        
        result = self.execute_query(
            "SELECT * FROM `ai_audio` WHERE id = %s",
            (audio_id,)
        )
        
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['text'], '测试文本内容')
        self.assertEqual(result[0]['status'], 1)
        self.assertEqual(result[0]['emo_control_method'], 1)
    
    def test_update_ai_audio(self):
        """测试更新音频生成记录"""
        audio_id = self.insert_fixture('ai_audio', {
            'text': '原始文本',
            'user_id': 1,
            'status': 0
        })
        
        affected_rows = self.execute_update(
            "UPDATE `ai_audio` SET status = %s, result_url = %s, transaction_id = %s WHERE id = %s",
            (2, 'https://example.com/result.mp3', 'txn_12345', audio_id)
        )
        
        self.assertEqual(affected_rows, 1)
        
        result = self.execute_query(
            "SELECT * FROM `ai_audio` WHERE id = %s",
            (audio_id,)
        )
        
        self.assertEqual(result[0]['status'], 2)
        self.assertEqual(result[0]['result_url'], 'https://example.com/result.mp3')
        self.assertEqual(result[0]['transaction_id'], 'txn_12345')
    
    def test_delete_ai_audio(self):
        """测试删除音频生成记录"""
        audio_id = self.insert_fixture('ai_audio', {
            'text': '临时记录',
            'user_id': 1,
            'status': -1
        })
        
        count_before = self.count_rows('ai_audio', 'id = %s', (audio_id,))
        self.assertEqual(count_before, 1)
        
        affected_rows = self.execute_update(
            "DELETE FROM `ai_audio` WHERE id = %s",
            (audio_id,)
        )
        
        self.assertEqual(affected_rows, 1)
        
        count_after = self.count_rows('ai_audio', 'id = %s', (audio_id,))
        self.assertEqual(count_after, 0)
    
    def test_query_audio_by_user_and_status(self):
        """测试按用户和状态查询音频记录"""
        self.insert_fixture('ai_audio', {
            'text': '已完成任务1',
            'user_id': 1,
            'status': 2
        })
        self.insert_fixture('ai_audio', {
            'text': '已完成任务2',
            'user_id': 1,
            'status': 2
        })
        self.insert_fixture('ai_audio', {
            'text': '处理中任务',
            'user_id': 1,
            'status': 1
        })
        
        result = self.execute_query(
            "SELECT * FROM `ai_audio` WHERE user_id = %s AND status = %s",
            (1, 2)
        )
        
        self.assertEqual(len(result), 2)
        for row in result:
            self.assertEqual(row['status'], 2)
    
    def test_emotion_control_methods(self):
        """测试不同情感控制方式"""
        audio_id_0 = self.insert_fixture('ai_audio', {
            'text': '情感控制方式0',
            'user_id': 1,
            'emo_control_method': 0,
            'status': 0
        })
        
        audio_id_1 = self.insert_fixture('ai_audio', {
            'text': '情感控制方式1',
            'user_id': 1,
            'emo_control_method': 1,
            'emo_ref_path': 'https://example.com/emo.mp3',
            'status': 0
        })
        
        audio_id_2 = self.insert_fixture('ai_audio', {
            'text': '情感控制方式2',
            'user_id': 1,
            'emo_control_method': 2,
            'emo_vec': '[0.1, 0.2, 0.3]',
            'status': 0
        })
        
        audio_id_3 = self.insert_fixture('ai_audio', {
            'text': '情感控制方式3',
            'user_id': 1,
            'emo_control_method': 3,
            'emo_text': '开心的语气',
            'emo_weight': 0.8,
            'status': 0
        })
        
        result = self.execute_query(
            "SELECT * FROM `ai_audio` WHERE id IN (%s, %s, %s, %s) ORDER BY emo_control_method",
            (audio_id_0, audio_id_1, audio_id_2, audio_id_3)
        )
        
        self.assertEqual(len(result), 4)
        self.assertEqual(result[0]['emo_control_method'], 0)
        self.assertEqual(result[1]['emo_control_method'], 1)
        self.assertEqual(result[2]['emo_control_method'], 2)
        self.assertEqual(result[3]['emo_control_method'], 3)


if __name__ == '__main__':
    unittest.main()
