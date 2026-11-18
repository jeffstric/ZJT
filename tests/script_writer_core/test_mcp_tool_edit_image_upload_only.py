"""edit_image 图片参数只允许本站 /upload/ 资源的集成测试（13572 事故收敛）。

契约：
- 外部图片链接 / 裸磁盘路径 / 路径穿越 → 校验期即拒绝，错误文案指引用相对路径；
- 本站 /upload/ 相对路径原样通过；任意 host 的绝对 /upload URL 剥域名归一化；
- 归一化后的相对路径进入 /api/image-edit 请求的 ref_image_urls（host 无关落库形态）。
"""
import os
import sys
import unittest
from unittest.mock import patch

current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(current_dir))
sys.path.insert(0, project_root)

import script_writer_core.mcp_tool as mcp_tool


def _fake_httpx_response():
    class _FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {'project_ids': ['proj_test_1']}

    return _FakeResponse()


class TestEditImageUploadOnly(unittest.TestCase):
    """edit_image 图片参数校验与归一化"""

    def setUp(self):
        # 入口偏好快照：避免读 DB 偏好
        patcher = patch.object(mcp_tool, 'get_media_generation_snapshot', return_value=None)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_external_link_rejected_before_submission(self):
        result = mcp_tool.edit_image(
            user_id='8', world_id='1', auth_token='token-x',
            prompt='把背景换成海滩', image_url='https://cdn.example.com/photo.jpg',
            task_type=1,
        )
        self.assertFalse(result['success'])
        self.assertIn('仅支持本站 /upload/', result['error'])
        self.assertIn('https://cdn.example.com/photo.jpg', result['error'])

    def test_local_disk_path_rejected(self):
        result = mcp_tool.edit_image(
            user_id='8', world_id='1', auth_token='token-x',
            prompt='把背景换成海滩', image_url='C:\\data\\photo.png',
            task_type=1,
        )
        self.assertFalse(result['success'])
        self.assertIn('仅支持本站 /upload/', result['error'])

    def test_traversal_rejected(self):
        result = mcp_tool.edit_image(
            user_id='8', world_id='1', auth_token='token-x',
            prompt='把背景换成海滩', image_url='/upload/../secret.png',
            task_type=1,
        )
        self.assertFalse(result['success'])
        self.assertIn('仅支持本站 /upload/', result['error'])

    def test_relative_and_absolute_normalized_to_relative(self):
        captured = {}

        def fake_post(url, data=None, **kwargs):
            captured['url'] = url
            captured['data'] = dict(data or {})
            return _fake_httpx_response()

        config = {'server': {'comfyui_base_url_inner': 'http://testserver'}, 'image': {}}
        with patch.object(mcp_tool, 'get_config', return_value=config), \
             patch.object(mcp_tool, '_resolve_image_ratio_and_size_from_prefs',
                          return_value=('16:9', None, 'default')), \
             patch.object(mcp_tool, '_resolve_generation_count_from_prefs',
                          side_effect=lambda user_id, world_id, count: count), \
             patch('utils.computing_power.get_computing_power_for_task', return_value=10), \
             patch.object(mcp_tool.httpx, 'post', side_effect=fake_post), \
             patch('model.GridImageTasksModel.get_by_task_key', lambda key: None), \
             patch('model.GridImageTasksModel.create', lambda **kwargs: None):
            # 混合形态：LLM 拼造域名的绝对 URL + 相对路径（13572 事故形态）
            result = mcp_tool.edit_image(
                user_id='8', world_id='1', auth_token='token-x',
                prompt='把背景换成海滩',
                image_url='https://api.ai-arts.com/upload/asset_library/55/asset_55_1b64.png, /upload/character/pic/abc.png',
                task_type=1,
            )

        self.assertTrue(result['success'], result)
        self.assertEqual(
            captured['data']['ref_image_urls'],
            '/upload/asset_library/55/asset_55_1b64.png,/upload/character/pic/abc.png',
        )
        # 归一化后的相对路径直接请求本机静态路径（不再带域名）
        self.assertEqual(captured['url'], 'http://testserver/api/image-edit')


if __name__ == '__main__':
    unittest.main()
