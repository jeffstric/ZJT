"""
AIToolsModel CDN 同步功能集成测试（使用真实数据库）

测试 update_with_cdn_sync 和 update_by_project_id_with_cdn_sync 函数
覆盖 CDN 开启和关闭两种场景
"""
import unittest
from unittest.mock import patch, MagicMock
from .base_db_test import DatabaseTestCase


class TestAIToolsCDNIntegration(DatabaseTestCase):
    """AIToolsModel CDN 同步集成测试（数据库操作 + Mock CDN）"""

    def setUp(self):
        """测试前准备"""
        super().setUp()
        # 创建测试用的 ai_tools 记录
        self.test_user_id = 1
        # 延迟导入 model 模块，确保环境变量已设置
        from model.ai_tools import AIToolsModel
        self.AIToolsModel = AIToolsModel

    def _create_test_tool(self, **kwargs):
        """
        创建测试用的 ai_tools 记录

        Args:
            **kwargs: 覆盖默认值的字段

        Returns:
            创建的 tool_id
        """
        defaults = {
            'prompt': '测试提示词',
            'user_id': self.test_user_id,
            'type': 2,  # AI视频生成
            'status': 1,  # 处理中
        }
        defaults.update(kwargs)

        tool_id = self.execute_insert(
            """INSERT INTO ai_tools (prompt, user_id, type, status)
               VALUES (%s, %s, %s, %s)""",
            (defaults['prompt'], defaults['user_id'], defaults['type'], defaults['status'])
        )
        self._connection.commit()
        return tool_id

    @patch('utils.cdn_util.CDNUtil.trigger_cdn_upload')
    @patch('model.ai_tools.get_config')
    def test_update_with_cdn_sync_cdn_disabled(self, mock_config, mock_trigger):
        """测试 update_with_cdn_sync - CDN 关闭时不创建 media_file_mapping"""
        # 配置 CDN 关闭
        mock_config.return_value = {
            "server": {"auto_upload_to_cdn": False}
        }

        # 创建测试记录
        tool_id = self._create_test_tool()

        # 调用被测函数
        result = self.AIToolsModel.update_with_cdn_sync(
            record_id=tool_id,
            result_url='/upload/test_result.jpg',
            status=2,
            user_id=self.test_user_id
        )

        # 验证返回值
        self.assertEqual(result, 1)

        # 验证不触发 CDN 上传
        mock_trigger.assert_not_called()

        # 验证 ai_tools 记录已更新
        updated = self.execute_query(
            "SELECT * FROM ai_tools WHERE id = %s",
            (tool_id,)
        )
        self.assertEqual(len(updated), 1)
        self.assertEqual(updated[0]['result_url'], '/upload/test_result.jpg')
        self.assertEqual(updated[0]['status'], 2)
        # media_mapping_id 应为 NULL
        self.assertIsNone(updated[0]['media_mapping_id'])

    @patch('os.path.getsize')
    @patch('os.path.exists')
    @patch('utils.cdn_util.CDNUtil.trigger_cdn_upload')
    @patch('model.ai_tools.get_config')
    def test_update_with_cdn_sync_cdn_enabled(self, mock_config, mock_trigger, mock_exists, mock_getsize):
        """测试 update_with_cdn_sync - CDN 开启时创建 media_file_mapping"""
        # 配置 CDN 开启
        mock_config.return_value = {
            "server": {"auto_upload_to_cdn": True}
        }
        # Mock 文件存在和大小
        mock_exists.return_value = True
        mock_getsize.return_value = 1024000  # 1MB

        # 创建测试记录
        tool_id = self._create_test_tool()

        # 调用被测函数
        from config.constant import AI_TOOL_STATUS_COMPLETED

        result = self.AIToolsModel.update_with_cdn_sync(
            record_id=tool_id,
            result_url='/upload/test_video.mp4',
            status=AI_TOOL_STATUS_COMPLETED,
            user_id=self.test_user_id
        )

        # 验证返回值
        self.assertEqual(result, 1)

        # 验证触发 CDN 上传
        mock_trigger.assert_called_once()

        # 验证 ai_tools 记录已更新
        updated = self.execute_query(
            "SELECT * FROM ai_tools WHERE id = %s",
            (tool_id,)
        )
        self.assertEqual(len(updated), 1)
        self.assertEqual(updated[0]['result_url'], '/upload/test_video.mp4')
        self.assertEqual(updated[0]['status'], AI_TOOL_STATUS_COMPLETED)
        # media_mapping_id 应不为 NULL
        self.assertIsNotNone(updated[0]['media_mapping_id'])
        mapping_id = updated[0]['media_mapping_id']

        # 验证 media_file_mapping 记录已创建
        mapping = self.execute_query(
            "SELECT * FROM media_file_mapping WHERE id = %s",
            (mapping_id,)
        )
        self.assertEqual(len(mapping), 1)
        self.assertEqual(mapping[0]['local_path'], 'upload/test_video.mp4')
        self.assertEqual(mapping[0]['entity_type'], 1)  # AI_TOOLS = 1
        self.assertEqual(mapping[0]['source_id'], tool_id)
        self.assertEqual(mapping[0]['media_type'], 'video/mp4')
        self.assertEqual(mapping[0]['user_id'], self.test_user_id)

    @patch('utils.cdn_util.CDNUtil.trigger_cdn_upload')
    @patch('model.ai_tools.get_config')
    def test_update_with_cdn_sync_non_local_url(self, mock_config, mock_trigger):
        """测试 update_with_cdn_sync - CDN 开启但非本地路径时不创建映射"""
        # 配置 CDN 开启
        mock_config.return_value = {
            "server": {"auto_upload_to_cdn": True}
        }

        # 创建测试记录
        tool_id = self._create_test_tool()

        # 调用被测函数（使用外网 URL）
        result = self.AIToolsModel.update_with_cdn_sync(
            record_id=tool_id,
            result_url='https://external-cdn.com/video.mp4',
            status=2,
            user_id=self.test_user_id
        )

        # 验证返回值
        self.assertEqual(result, 1)

        # 验证不触发 CDN 上传（非本地路径）
        mock_trigger.assert_not_called()

        # 验证 ai_tools 记录已更新
        updated = self.execute_query(
            "SELECT * FROM ai_tools WHERE id = %s",
            (tool_id,)
        )
        self.assertEqual(len(updated), 1)
        self.assertEqual(updated[0]['result_url'], 'https://external-cdn.com/video.mp4')
        # media_mapping_id 应为 NULL
        self.assertIsNone(updated[0]['media_mapping_id'])

    @patch('utils.cdn_util.CDNUtil.trigger_cdn_upload')
    @patch('model.ai_tools.get_config')
    def test_update_with_cdn_sync_already_has_mapping(self, mock_config, mock_trigger):
        """测试 update_with_cdn_sync - 已有 media_mapping_id 时跳过创建"""
        # 配置 CDN 开启
        mock_config.return_value = {
            "server": {"auto_upload_to_cdn": True}
        }

        # 先创建 media_file_mapping 记录
        mapping_id = self.execute_insert(
            """INSERT INTO media_file_mapping
               (user_id, local_path, cloud_path, policy_code, entity_type, source_id, media_type, status)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
            (self.test_user_id, 'upload/existing.jpg', 'cdn/existing.jpg', 'media_cache', 1, 999, 'image/jpeg', 2)
        )
        self._connection.commit()

        # 创建 ai_tools 记录并设置 media_mapping_id
        tool_id = self._create_test_tool(media_mapping_id=mapping_id)
        # 更新记录设置 media_mapping_id
        self.execute_update(
            "UPDATE ai_tools SET media_mapping_id = %s WHERE id = %s",
            (mapping_id, tool_id)
        )
        self._connection.commit()

        # 调用被测函数
        result = self.AIToolsModel.update_with_cdn_sync(
            record_id=tool_id,
            result_url='/upload/new_result.jpg',
            status=2,
            user_id=self.test_user_id
        )

        # 验证返回值
        self.assertEqual(result, 1)

        # 验证不触发新的 CDN 上传
        mock_trigger.assert_not_called()

        # 验证 ai_tools 记录已更新
        updated = self.execute_query(
            "SELECT * FROM ai_tools WHERE id = %s",
            (tool_id,)
        )
        self.assertEqual(len(updated), 1)
        self.assertEqual(updated[0]['result_url'], '/upload/new_result.jpg')
        # media_mapping_id 应保持不变
        self.assertEqual(updated[0]['media_mapping_id'], mapping_id)

        # 验证 media_file_mapping 记录数量没有增加（只有本测试插入的那一条）
        mapping_count = self.count_rows('media_file_mapping', 'id = %s', (mapping_id,))
        self.assertEqual(mapping_count, 1)

    @patch('utils.cdn_util.CDNUtil.trigger_cdn_upload')
    @patch('model.ai_tools.get_config')
    def test_update_by_project_id_with_cdn_sync_cdn_disabled(self, mock_config, mock_trigger):
        """测试 update_by_project_id_with_cdn_sync - CDN 关闭时不创建 media_file_mapping"""
        # 配置 CDN 关闭
        mock_config.return_value = {
            "server": {"auto_upload_to_cdn": False}
        }

        # 创建测试记录
        project_id = 'test_proj_001'
        tool_id = self._create_test_tool(project_id=project_id)
        # 更新 project_id
        self.execute_update(
            "UPDATE ai_tools SET project_id = %s WHERE id = %s",
            (project_id, tool_id)
        )
        self._connection.commit()

        # 调用被测函数
        result = self.AIToolsModel.update_by_project_id_with_cdn_sync(
            project_id=project_id,
            result_url='/upload/proj_result.jpg',
            status=2,
            user_id=self.test_user_id
        )

        # 验证返回值
        self.assertEqual(result, 1)

        # 验证不触发 CDN 上传
        mock_trigger.assert_not_called()

        # 验证 ai_tools 记录已更新
        updated = self.execute_query(
            "SELECT * FROM ai_tools WHERE project_id = %s",
            (project_id,)
        )
        self.assertEqual(len(updated), 1)
        self.assertEqual(updated[0]['result_url'], '/upload/proj_result.jpg')
        # media_mapping_id 应为 NULL
        self.assertIsNone(updated[0]['media_mapping_id'])

    @patch('os.path.getsize')
    @patch('os.path.exists')
    @patch('utils.cdn_util.CDNUtil.trigger_cdn_upload')
    @patch('model.ai_tools.get_config')
    def test_update_by_project_id_with_cdn_sync_cdn_enabled(self, mock_config, mock_trigger, mock_exists, mock_getsize):
        """测试 update_by_project_id_with_cdn_sync - CDN 开启时创建 media_file_mapping"""
        # 配置 CDN 开启
        mock_config.return_value = {
            "server": {"auto_upload_to_cdn": True}
        }
        # Mock 文件存在和大小
        mock_exists.return_value = True
        mock_getsize.return_value = 2048000  # 2MB

        # 创建测试记录
        project_id = 'test_proj_002'
        tool_id = self._create_test_tool(project_id=project_id)
        # 更新 project_id
        self.execute_update(
            "UPDATE ai_tools SET project_id = %s WHERE id = %s",
            (project_id, tool_id)
        )
        self._connection.commit()

        # 调用被测函数
        from config.constant import AI_TOOL_STATUS_COMPLETED

        result = self.AIToolsModel.update_by_project_id_with_cdn_sync(
            project_id=project_id,
            result_url='/upload/proj_video.mp4',
            status=AI_TOOL_STATUS_COMPLETED
        )

        # 验证返回值
        self.assertEqual(result, 1)

        # 验证触发 CDN 上传
        mock_trigger.assert_called_once()

        # 验证 ai_tools 记录已更新
        updated = self.execute_query(
            "SELECT * FROM ai_tools WHERE project_id = %s",
            (project_id,)
        )
        self.assertEqual(len(updated), 1)
        self.assertEqual(updated[0]['result_url'], '/upload/proj_video.mp4')
        self.assertEqual(updated[0]['status'], AI_TOOL_STATUS_COMPLETED)
        # media_mapping_id 应不为 NULL
        self.assertIsNotNone(updated[0]['media_mapping_id'])
        mapping_id = updated[0]['media_mapping_id']

        # 验证 media_file_mapping 记录已创建
        mapping = self.execute_query(
            "SELECT * FROM media_file_mapping WHERE id = %s",
            (mapping_id,)
        )
        self.assertEqual(len(mapping), 1)
        self.assertEqual(mapping[0]['local_path'], 'upload/proj_video.mp4')
        self.assertEqual(mapping[0]['entity_type'], 1)  # AI_TOOLS = 1
        self.assertEqual(mapping[0]['source_id'], tool_id)
        self.assertEqual(mapping[0]['media_type'], 'video/mp4')

    @patch('model.ai_tools.get_config')
    def test_update_by_project_id_with_cdn_sync_project_not_found(self, mock_config):
        """测试 update_by_project_id_with_cdn_sync - project_id 不存在时返回 0"""
        # 配置 CDN 开启（不影响结果）
        mock_config.return_value = {
            "server": {"auto_upload_to_cdn": True}
        }

        # 调用被测函数（使用不存在的 project_id）
        result = self.AIToolsModel.update_by_project_id_with_cdn_sync(
            project_id='nonexistent_project_id',
            result_url='/upload/result.jpg',
            status=2
        )

        # 验证返回 0（未找到记录）
        self.assertEqual(result, 0)


if __name__ == '__main__':
    unittest.main()
