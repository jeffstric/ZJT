"""
register_direct_uploaded_mapping 单元测试

前端直传七牛素材的 mapping 注册函数（upload-confirm 回源落盘后调用）：
- create 时 cloud_path 直接置位（不再 trigger_cdn_upload 重复上传）
- 同路径幂等复用（cloud_path 为空则补置位）
- 空路径 / create 异常不向上传播
"""
import unittest
from unittest.mock import patch, MagicMock
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


class TestRegisterDirectUploadedMapping(unittest.TestCase):
    """直传素材注册 CDN mapping 的单元测试"""

    @patch('utils.cdn_util.CDNUtil.trigger_cdn_upload')
    @patch('model.media_file_mapping.MediaFileMappingModel.get_by_local_path')
    @patch('model.media_file_mapping.MediaFileMappingModel.create')
    def test_creates_mapping_with_cloud_path_preset(
        self, mock_create, mock_get_by_local_path, mock_trigger
    ):
        """正常路径：cloud_path 直接置位且绝不触发服务端重复上传"""
        mock_get_by_local_path.return_value = None
        mock_create.return_value = 300

        from utils.media_mapping_util import register_direct_uploaded_mapping

        result = register_direct_uploaded_mapping(
            user_id=12,
            local_path='upload/workflow/12/workflow_20261102_100000_ab12cd34.mp4',
            entity_type=5,
            policy_code='never_expire',
            file_size=1024,
        )

        self.assertEqual(result, 300)
        create_kwargs = mock_create.call_args[1]
        self.assertEqual(create_kwargs['local_path'], 'upload/workflow/12/workflow_20261102_100000_ab12cd34.mp4')
        self.assertEqual(create_kwargs['cloud_path'], 'upload/workflow/12/workflow_20261102_100000_ab12cd34.mp4')
        self.assertEqual(create_kwargs['file_size'], 1024)
        self.assertEqual(create_kwargs['entity_type'], 5)
        self.assertEqual(create_kwargs['media_type'], 'video/mp4')
        mock_trigger.assert_not_called()

    @patch('model.media_file_mapping.MediaFileMappingModel.update_cloud_path')
    @patch('model.media_file_mapping.MediaFileMappingModel.get_by_local_path')
    @patch('model.media_file_mapping.MediaFileMappingModel.create')
    def test_reuses_existing_mapping_and_backfills_cloud_path(
        self, mock_create, mock_get_by_local_path, mock_update_cloud_path
    ):
        """幂等：同路径已注册时复用；cloud_path 为空则补置位"""
        mock_existing = MagicMock()
        mock_existing.id = 88
        mock_existing.cloud_path = None
        mock_get_by_local_path.return_value = mock_existing

        from utils.media_mapping_util import register_direct_uploaded_mapping

        result = register_direct_uploaded_mapping(
            user_id=1,
            local_path='upload/workflow/1/a.mp4',
            entity_type=5,
            policy_code='never_expire',
        )

        self.assertEqual(result, 88)
        mock_create.assert_not_called()
        mock_update_cloud_path.assert_called_once_with('upload/workflow/1/a.mp4', 'upload/workflow/1/a.mp4')

    @patch('model.media_file_mapping.MediaFileMappingModel.update_cloud_path')
    @patch('model.media_file_mapping.MediaFileMappingModel.get_by_local_path')
    @patch('model.media_file_mapping.MediaFileMappingModel.create')
    def test_reuses_existing_mapping_without_cloud_backfill(
        self, mock_create, mock_get_by_local_path, mock_update_cloud_path
    ):
        """幂等：已有 mapping 且 cloud_path 非空时不重复置位"""
        mock_existing = MagicMock()
        mock_existing.id = 89
        mock_existing.cloud_path = 'upload/workflow/1/a.mp4'
        mock_get_by_local_path.return_value = mock_existing

        from utils.media_mapping_util import register_direct_uploaded_mapping

        result = register_direct_uploaded_mapping(
            user_id=1, local_path='upload/workflow/1/a.mp4',
            entity_type=5, policy_code='never_expire',
        )

        self.assertEqual(result, 89)
        mock_update_cloud_path.assert_not_called()

    @patch('model.media_file_mapping.MediaFileMappingModel.get_by_local_path')
    @patch('model.media_file_mapping.MediaFileMappingModel.create')
    def test_skips_empty_local_path(self, mock_create, mock_get_by_local_path):
        """空路径应直接跳过"""
        from utils.media_mapping_util import register_direct_uploaded_mapping

        result = register_direct_uploaded_mapping(
            user_id=1, local_path='', entity_type=5, policy_code='never_expire',
        )

        self.assertIsNone(result)
        mock_create.assert_not_called()

    @patch('model.media_file_mapping.MediaFileMappingModel.get_by_local_path')
    @patch('model.media_file_mapping.MediaFileMappingModel.create')
    def test_swallows_create_exception(self, mock_create, mock_get_by_local_path):
        """create 抛异常时不应向上传播，返回 None"""
        mock_get_by_local_path.return_value = None
        mock_create.side_effect = RuntimeError("db down")

        from utils.media_mapping_util import register_direct_uploaded_mapping

        result = register_direct_uploaded_mapping(
            user_id=1, local_path='upload/workflow/1/a.png',
            entity_type=5, policy_code='never_expire',
        )

        self.assertIsNone(result)


if __name__ == '__main__':
    unittest.main()
