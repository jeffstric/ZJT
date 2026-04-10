"""
AIToolsModel CDN 同步功能单元测试
"""
import unittest
from unittest.mock import patch, MagicMock
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestAIToolsModelCDNSync(unittest.TestCase):
    """AIToolsModel CDN 同步方法单元测试"""

    @patch('model.ai_tools.AIToolsModel.get_by_id')
    def test_update_with_cdn_sync_skips_when_already_has_mapping(self, mock_get_by_id):
        """测试当已有 media_mapping_id 时跳过创建"""
        mock_existing = MagicMock()
        mock_existing.media_mapping_id = 123  # 已有映射
        mock_get_by_id.return_value = mock_existing

        from model.ai_tools import AIToolsModel

        result = AIToolsModel.update_with_cdn_sync(
            record_id=1,
            result_url='/upload/test.jpg',
            status=2
        )

        # 应该调用 update 而不是 create
        self.assertEqual(result, 1)  # update 返回 affected_rows

    @patch('model.media_file_mapping.MediaFileMappingModel.create')
    @patch('utils.cdn_util.CDNUtil.trigger_cdn_upload')
    @patch('model.ai_tools.AIToolsModel.update')
    @patch('model.ai_tools.AIToolsModel.get_by_id')
    def test_update_with_cdn_sync_creates_mapping(
        self, mock_get_by_id, mock_update, mock_trigger, mock_create
    ):
        """测试创建新的 media_file_mapping 记录"""
        mock_existing = MagicMock()
        mock_existing.media_mapping_id = None
        mock_get_by_id.return_value = mock_existing
        mock_create.return_value = 456
        mock_update.return_value = 1

        from model.ai_tools import AIToolsModel

        result = AIToolsModel.update_with_cdn_sync(
            record_id=1,
            result_url='/upload/test.jpg',
            status=2,
            user_id=1
        )

        mock_create.assert_called_once()
        mock_trigger.assert_called_once_with(456, 'upload/test.jpg')
        mock_update.assert_called_once()

        # 验证 update 调用参数包含 media_mapping_id
        call_args = mock_update.call_args
        self.assertEqual(call_args[0][0], 1)  # record_id
        self.assertEqual(call_args[1]['media_mapping_id'], 456)
        self.assertEqual(call_args[1]['result_url'], '/upload/test.jpg')

    @patch('model.ai_tools.AIToolsModel.update')
    def test_update_with_cdn_sync_skips_non_local_path(self, mock_update):
        """测试非本地路径不创建映射"""
        from model.ai_tools import AIToolsModel

        mock_update.return_value = 1

        result = AIToolsModel.update_with_cdn_sync(
            record_id=1,
            result_url='http://example.com/remote.jpg',
            status=2
        )

        # 不应该调用 update，因为 result_url 不是本地路径
        mock_update.assert_not_called()

    @patch('model.media_file_mapping.MediaFileMappingModel.create')
    @patch('utils.cdn_util.CDNUtil.trigger_cdn_upload')
    @patch('model.ai_tools.AIToolsModel.update')
    @patch('model.ai_tools.AIToolsModel.get_by_id')
    def test_update_with_cdn_sync_image_type_detection(
        self, mock_get_by_id, mock_update, mock_trigger, mock_create
    ):
        """测试媒体类型自动检测"""
        mock_existing = MagicMock()
        mock_existing.media_mapping_id = None
        mock_get_by_id.return_value = mock_existing
        mock_create.return_value = 789
        mock_update.return_value = 1

        from model.ai_tools import AIToolsModel

        # 测试图片类型
        AIToolsModel.update_with_cdn_sync(
            record_id=1,
            result_url='/upload/test_image.jpg',
            user_id=1
        )

        create_args = mock_create.call_args[0]
        self.assertEqual(create_args[6], 'image')  # media_type 位置

        # 重置 mock
        mock_create.reset_mock()

        # 测试视频类型
        AIToolsModel.update_with_cdn_sync(
            record_id=2,
            result_url='/upload/test_video.mp4',
            user_id=1
        )

        create_args = mock_create.call_args[0]
        self.assertEqual(create_args[6], 'video')  # media_type 位置

    @patch('model.ai_tools.AIToolsModel.get_by_project_id')
    def test_update_by_project_id_with_cdn_sync_skips_when_already_has_mapping(self, mock_get_by_project_id):
        """测试当已有 media_mapping_id 时跳过创建"""
        mock_existing = MagicMock()
        mock_existing.media_mapping_id = 123
        mock_existing.id = 1
        mock_existing.user_id = 1
        mock_get_by_project_id.return_value = mock_existing

        from model.ai_tools import AIToolsModel
        from unittest.mock import patch

        with patch.object(AIToolsModel, 'update_by_project_id', return_value=1) as mock_update:
            result = AIToolsModel.update_by_project_id_with_cdn_sync(
                project_id='proj_123',
                result_url='/upload/test.jpg',
                status=2
            )

            mock_update.assert_called_once()
            mock_get_by_project_id.assert_called_once_with('proj_123')

    @patch('model.media_file_mapping.MediaFileMappingModel.create')
    @patch('utils.cdn_util.CDNUtil.trigger_cdn_upload')
    @patch('model.ai_tools.AIToolsModel.update_by_project_id')
    @patch('model.ai_tools.AIToolsModel.get_by_project_id')
    def test_update_by_project_id_with_cdn_sync_creates_mapping(
        self, mock_get_by_project_id, mock_update, mock_trigger, mock_create
    ):
        """测试按 project_id 更新时创建映射"""
        mock_existing = MagicMock()
        mock_existing.media_mapping_id = None
        mock_existing.id = 1
        mock_existing.user_id = 1
        mock_get_by_project_id.return_value = mock_existing
        mock_create.return_value = 456
        mock_update.return_value = 1

        from model.ai_tools import AIToolsModel

        result = AIToolsModel.update_by_project_id_with_cdn_sync(
            project_id='proj_123',
            result_url='/upload/test.jpg',
            status=2
        )

        mock_create.assert_called_once()
        mock_trigger.assert_called_once_with(456, 'upload/test.jpg')
        mock_update.assert_called_once()

    @patch('model.ai_tools.AIToolsModel.get_by_project_id')
    def test_update_by_project_id_with_cdn_sync_returns_zero_when_not_found(self, mock_get_by_project_id):
        """测试未找到记录时返回 0"""
        mock_get_by_project_id.return_value = None

        from model.ai_tools import AIToolsModel

        result = AIToolsModel.update_by_project_id_with_cdn_sync(
            project_id='nonexistent',
            result_url='/upload/test.jpg'
        )

        self.assertEqual(result, 0)


if __name__ == '__main__':
    unittest.main()
