"""
Gemini Image Preview Common 驱动测试
测试通用供应商的 Gemini 原生 API 格式驱动
支持多模型切换
"""
import sys
from unittest.mock import patch, MagicMock

sys.modules['utils.sentry_util'] = MagicMock()
sys.modules['aiofiles'] = MagicMock()
sys.modules['aiohttp'] = MagicMock()

from tests.base.base_video_driver_test import BaseVideoDriverTest, mock_get_dynamic_config_value
from task.visual_drivers.gemini_image_preview_common_v1_driver import GeminiImagePreviewSite1V1Driver
from config.constant import AI_TOOL_STATUS_PENDING, AI_TOOL_STATUS_PROCESSING, AI_TOOL_STATUS_COMPLETED, AI_TOOL_STATUS_FAILED
from config.unified_config import TaskTypeId


class TestGeminiImagePreviewCommonDriver(BaseVideoDriverTest):
    """Gemini Image Preview Common 驱动测试"""

    def setUp(self):
        """测试前准备"""
        super().setUp()
        with patch('task.visual_drivers.gemini_image_preview_common_v1_driver.get_dynamic_config_value', side_effect=mock_get_dynamic_config_value):
            with patch.object(GeminiImagePreviewSite1V1Driver, '_validate_required'):
                self.driver = GeminiImagePreviewSite1V1Driver()

    def test_driver_initialization(self):
        """测试驱动初始化"""
        self.assertIsNotNone(self.driver)
        self.assertEqual(self.driver.driver_name, 'gemini_common_site_1')
        self.assertEqual(self.driver.DEFAULT_MODEL, 'gemini-2.5-flash-image')

    def test_model_mapping(self):
        """测试模型映射"""
        # 验证模型映射正确
        self.assertEqual(
            self.driver.MODEL_MAPPING[TaskTypeId.GEMINI_2_5_FLASH_IMAGE],
            'gemini-2.5-flash-image'
        )
        self.assertEqual(
            self.driver.MODEL_MAPPING[TaskTypeId.GEMINI_3_PRO_IMAGE],
            'gemini-3-pro-image-preview'
        )
        self.assertEqual(
            self.driver.MODEL_MAPPING[TaskTypeId.GEMINI_3_1_FLASH_IMAGE],
            'gemini-3.1-flash-image-preview'
        )

    def test_build_create_request_text_only(self):
        """测试构建创建任务请求参数 - 仅文本"""
        task_id = self.create_test_ai_tool(
            ai_tool_type=7,  # GEMINI_3_PRO_IMAGE
            prompt='生成一张美丽的风景图',
            ratio='16:9',
            image_size='1K',
            status=AI_TOOL_STATUS_PENDING
        )

        tool = self.get_ai_tool_from_db(task_id)
        req = self.driver.build_create_request(tool)

        # 验证 URL 包含正确的路径和 key 参数（使用 Bearer Token 认证）
        self.assertIn('/v1beta/models/gemini-3-pro-image-preview:generateContent', req['url'])

        # 验证使用 Bearer Token 认证（不在 URL 中包含 key）
        self.assertIn('Authorization', req['headers'])
        self.assertIn('Bearer', req['headers']['Authorization'])

        # 验证 method
        self.assertEqual(req['method'], 'POST')

        # 验证 json 结构
        self.assertIn('contents', req['json'])
        self.assertIn('generationConfig', req['json'])

        # 验证 contents
        contents = req['json']['contents']
        self.assertEqual(len(contents), 1)
        self.assertEqual(contents[0]['role'], 'user')
        self.assertEqual(len(contents[0]['parts']), 1)
        self.assertEqual(contents[0]['parts'][0]['text'], '生成一张美丽的风景图')

        # 验证 generationConfig
        gen_config = req['json']['generationConfig']
        self.assertEqual(gen_config['responseModalities'], ['TEXT', 'IMAGE'])
        self.assertEqual(gen_config['imageConfig']['aspectRatio'], '16:9')
        self.assertEqual(gen_config['imageConfig']['imageSize'], '1K')

        # 验证 headers
        self.assertEqual(req['headers']['Content-Type'], 'application/json')

    def test_build_create_request_with_gemini_2_5_flash(self):
        """测试构建创建任务请求参数 - gemini-2.5-flash-image 模型"""
        task_id = self.create_test_ai_tool(
            ai_tool_type=1,  # GEMINI_2_5_FLASH_IMAGE
            prompt='使用 2.5 Flash 模型生成图片',
            ratio='9:16',
            image_size='1K',
            status=AI_TOOL_STATUS_PENDING
        )

        tool = self.get_ai_tool_from_db(task_id)
        req = self.driver.build_create_request(tool)

        # 验证 URL 包含正确的模型名称
        self.assertIn('/v1beta/models/gemini-2.5-flash-image:generateContent', req['url'])

    def test_build_create_request_with_gemini_3_1_flash(self):
        """测试构建创建任务请求参数 - gemini-3.1-flash-image-preview 模型"""
        task_id = self.create_test_ai_tool(
            ai_tool_type=17,  # GEMINI_3_1_FLASH_IMAGE
            prompt='使用 3.1 Flash 模型生成图片',
            ratio='9:16',
            image_size='2K',
            status=AI_TOOL_STATUS_PENDING
        )

        tool = self.get_ai_tool_from_db(task_id)
        req = self.driver.build_create_request(tool)

        # 验证 URL 包含正确的模型名称
        self.assertIn('/v1beta/models/gemini-3.1-flash-image-preview:generateContent', req['url'])

    def test_build_create_request_with_image(self):
        """测试构建创建任务请求参数 - 带图片（使用 mock）"""
        task_id = self.create_test_ai_tool(
            ai_tool_type=7,
            prompt='在这张图片上添加一只羊驼',
            image_path='https://example.com/test.jpg',
            ratio='9:16',
            image_size='2K',
            status=AI_TOOL_STATUS_PENDING
        )

        tool = self.get_ai_tool_from_db(task_id)

        # Mock 图片下载
        mock_base64 = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=='
        with patch.object(self.driver, '_download_image_as_base64') as mock_download:
            mock_download.return_value = (mock_base64, 'image/jpeg')

            req = self.driver.build_create_request(tool)

            # 验证图片下载被调用
            mock_download.assert_called_once_with('https://example.com/test.jpg')

            # 验证 contents 包含文本和图片
            contents = req['json']['contents']
            self.assertEqual(len(contents[0]['parts']), 2)
            self.assertEqual(contents[0]['parts'][0]['text'], '在这张图片上添加一只羊驼')
            # 验证新格式 inlineData（驼峰格式）
            self.assertEqual(contents[0]['parts'][1]['inlineData']['mimeType'], 'image/jpeg')
            self.assertEqual(contents[0]['parts'][1]['inlineData']['data'], mock_base64)

            # 验证宽高比和尺寸
            self.assertEqual(req['json']['generationConfig']['imageConfig']['aspectRatio'], '9:16')
            self.assertEqual(req['json']['generationConfig']['imageConfig']['imageSize'], '2K')

    def test_build_create_request_with_multiple_images(self):
        """测试构建创建任务请求参数 - 多张图片"""
        task_id = self.create_test_ai_tool(
            ai_tool_type=7,
            prompt='合成这些图片',
            image_path='https://example.com/img1.jpg,https://example.com/img2.jpg',
            ratio='1:1',
            status=AI_TOOL_STATUS_PENDING
        )

        tool = self.get_ai_tool_from_db(task_id)

        # Mock 图片下载
        mock_base64 = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=='
        with patch.object(self.driver, '_download_image_as_base64') as mock_download:
            mock_download.return_value = (mock_base64, 'image/jpeg')

            req = self.driver.build_create_request(tool)

            # 验证图片下载被调用两次
            self.assertEqual(mock_download.call_count, 2)

            # 验证 contents 包含文本和两张图片
            contents = req['json']['contents']
            self.assertEqual(len(contents[0]['parts']), 3)  # 1 文本 + 2 图片

    def test_submit_task_success(self):
        """测试提交任务 - 成功"""
        task_id = self.create_test_ai_tool(
            ai_tool_type=7,
            prompt='生成一张测试图片',
            ratio='9:16',
            image_size='1K',
            status=AI_TOOL_STATUS_PROCESSING
        )

        tool = self.get_ai_tool_from_db(task_id)

        # Mock API 响应（使用新的驼峰格式）
        mock_response = {
            "candidates": [{
                "content": {
                    "parts": [{
                        "inlineData": {
                            "mimeType": "image/png",
                            "data": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
                        }
                    }]
                }
            }]
        }

        with patch.object(self.driver, '_request') as mock_req:
            mock_req.return_value = mock_response

            # Mock 缓存保存（避免 base64 解码错误）
            mock_cache_manager = MagicMock()
            mock_cache_manager.save_data_url_to_cache.return_value = 'https://cdn.example.com/cached.png'
            with patch('task.visual_drivers.gemini_image_preview_common_v1_driver.get_cache_manager', return_value=mock_cache_manager):
                result = self.driver.submit_task(tool)

                # 验证 _request 被调用
                mock_req.assert_called_once()

                # 验证返回结果
                self.assertTrue(result['success'])
                self.assertTrue(result.get('sync_mode'))
                self.assertIn('result_url', result)

    def test_submit_task_with_old_format_response(self):
        """测试提交任务 - 兼容旧格式响应（下划线格式）"""
        task_id = self.create_test_ai_tool(
            ai_tool_type=7,
            prompt='生成一张测试图片',
            ratio='9:16',
            image_size='1K',
            status=AI_TOOL_STATUS_PROCESSING
        )

        tool = self.get_ai_tool_from_db(task_id)

        # Mock API 响应（使用旧的下划线格式）
        mock_response = {
            "candidates": [{
                "content": {
                    "parts": [{
                        "inline_data": {
                            "mime_type": "image/png",
                            "data": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
                        }
                    }]
                }
            }]
        }

        with patch.object(self.driver, '_request') as mock_req:
            mock_req.return_value = mock_response

            # Mock 缓存保存（避免 base64 解码错误）
            mock_cache_manager = MagicMock()
            mock_cache_manager.save_data_url_to_cache.return_value = 'https://cdn.example.com/cached.png'
            with patch('task.visual_drivers.gemini_image_preview_common_v1_driver.get_cache_manager', return_value=mock_cache_manager):
                result = self.driver.submit_task(tool)

                # 验证返回结果（应该兼容旧格式）
                self.assertTrue(result['success'])
                self.assertTrue(result.get('sync_mode'))
                self.assertIn('result_url', result)

    def test_submit_task_with_image_input(self):
        """测试提交任务 - 带图片输入"""
        task_id = self.create_test_ai_tool(
            ai_tool_type=7,
            prompt='编辑这张图片',
            image_path='https://example.com/test.jpg',
            ratio='16:9',
            status=AI_TOOL_STATUS_PROCESSING
        )

        tool = self.get_ai_tool_from_db(task_id)

        # Mock 图片下载和 API 响应
        mock_base64 = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=='
        mock_response = {
            "candidates": [{
                "content": {
                    "parts": [{
                        "inlineData": {
                            "mimeType": "image/png",
                            "data": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
                        }
                    }]
                }
            }]
        }

        with patch.object(self.driver, '_download_image_as_base64') as mock_download, \
             patch.object(self.driver, '_request') as mock_req:
            mock_download.return_value = (mock_base64, 'image/jpeg')
            mock_req.return_value = mock_response

            # Mock 缓存保存
            mock_cache_manager = MagicMock()
            mock_cache_manager.save_data_url_to_cache.return_value = 'https://cdn.example.com/cached.png'
            with patch('task.visual_drivers.gemini_image_preview_common_v1_driver.get_cache_manager', return_value=mock_cache_manager):
                result = self.driver.submit_task(tool)

                # 验证图片下载被调用
                mock_download.assert_called_once()

                # 验证返回结果
                self.assertTrue(result['success'])
                self.assertTrue(result.get('sync_mode'))

    def test_submit_task_api_error(self):
        """测试提交任务 - API 错误"""
        task_id = self.create_test_ai_tool(
            ai_tool_type=7,
            prompt='测试错误',
            ratio='9:16',
            status=AI_TOOL_STATUS_PENDING
        )

        tool = self.get_ai_tool_from_db(task_id)

        # Mock API 错误响应
        mock_response = {
            "error": {
                "message": "Invalid API key"
            }
        }

        with patch.object(self.driver, '_request') as mock_req:
            mock_req.return_value = mock_response

            result = self.driver.submit_task(tool)

            self.assertFalse(result['success'])
            self.assertEqual(result['error_type'], 'USER')
            self.assertIn('Invalid API key', result['error'])

    def test_submit_task_network_error(self):
        """测试提交任务 - 网络错误"""
        task_id = self.create_test_ai_tool(
            ai_tool_type=7,
            prompt='测试网络错误',
            ratio='9:16',
            status=AI_TOOL_STATUS_PENDING
        )

        tool = self.get_ai_tool_from_db(task_id)

        with patch.object(self.driver, '_request') as mock_req:
            mock_req.side_effect = ConnectionError('Network timeout')

            result = self.driver.submit_task(tool)

            self.assertFalse(result['success'])
            self.assertTrue(result['retry'])

    def test_submit_task_no_image_in_response(self):
        """测试提交任务 - 响应中没有图片"""
        task_id = self.create_test_ai_tool(
            ai_tool_type=7,
            prompt='测试无图片响应',
            ratio='9:16',
            status=AI_TOOL_STATUS_PENDING
        )

        tool = self.get_ai_tool_from_db(task_id)

        # Mock 空响应
        mock_response = {
            "candidates": [{
                "content": {
                    "parts": [{"text": "Only text response"}]
                }
            }]
        }

        with patch.object(self.driver, '_request') as mock_req, \
             patch.object(self.driver, '_send_alert') as mock_alert:
            mock_req.return_value = mock_response

            result = self.driver.submit_task(tool)

            self.assertFalse(result['success'])
            self.assertEqual(result['error_type'], 'SYSTEM')
            # 验证报警被发送
            mock_alert.assert_called_once()

    def test_check_status(self):
        """测试检查状态 - 同步接口直接返回成功"""
        result = self.driver.check_status('test_project_id')

        # 同步接口直接返回成功
        self.assertEqual(result['status'], 'SUCCESS')

    def test_validate_parameters_valid(self):
        """测试参数验证 - 有效参数"""
        class MockTool:
            prompt = '测试提示词'
            image_path = None
            ratio = '9:16'
            image_size = '1K'

        tool = MockTool()
        is_valid, error = self.driver.validate_parameters(tool)

        self.assertTrue(is_valid)
        self.assertIsNone(error)

    def test_validate_parameters_no_prompt_or_image(self):
        """测试参数验证 - 无提示词和图片"""
        class MockTool:
            prompt = None
            image_path = None
            ratio = '9:16'
            image_size = '1K'

        tool = MockTool()
        is_valid, error = self.driver.validate_parameters(tool)

        self.assertFalse(is_valid)
        self.assertIn('缺少提示词或图片', error)

    def test_validate_parameters_invalid_size(self):
        """测试参数验证 - 无效的图片尺寸"""
        class MockTool:
            prompt = '测试'
            image_path = None
            ratio = '9:16'
            image_size = '5K'

        tool = MockTool()
        is_valid, error = self.driver.validate_parameters(tool)

        self.assertFalse(is_valid)
        self.assertIn('不支持的图片尺寸', error)

    def test_validate_parameters_valid_ratio_21_9(self):
        """测试参数验证 - 21:9 比例（新版支持）"""
        class MockTool:
            prompt = '测试'
            image_path = None
            ratio = '21:9'
            image_size = '1K'

        tool = MockTool()
        is_valid, error = self.driver.validate_parameters(tool)

        # 新版支持 21:9 比例
        self.assertTrue(is_valid)

    def test_validate_parameters_invalid_ratio(self):
        """测试参数验证 - 无效的宽高比"""
        class MockTool:
            prompt = '测试'
            image_path = None
            ratio = '10:9'
            image_size = '1K'

        tool = MockTool()
        is_valid, error = self.driver.validate_parameters(tool)

        self.assertFalse(is_valid)
        self.assertIn('不支持的宽高比', error)

    def test_validate_parameters_image_only(self):
        """测试参数验证 - 仅图片（无提示词）"""
        class MockTool:
            prompt = None
            image_path = 'https://example.com/test.jpg'
            ratio = '9:16'
            image_size = '1K'

        tool = MockTool()
        is_valid, error = self.driver.validate_parameters(tool)

        # 只有图片也应该是有效的
        self.assertTrue(is_valid)

    def test_download_image_as_base64(self):
        """测试图片下载和 base64 转换"""
        # Mock requests.get
        mock_response = MagicMock()
        mock_response.headers = {'Content-Type': 'image/png'}
        mock_response.content = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR'
        mock_response.raise_for_status = MagicMock()

        with patch('requests.get') as mock_get:
            mock_get.return_value = mock_response

            base64_data, mime_type = self.driver._download_image_as_base64('https://example.com/test.png')

            # 验证返回值
            self.assertEqual(mime_type, 'image/png')
            self.assertIsInstance(base64_data, str)

    def test_download_image_jpeg(self):
        """测试 JPEG 图片下载"""
        mock_response = MagicMock()
        mock_response.headers = {'Content-Type': 'image/jpeg'}
        mock_response.content = b'\xff\xd8\xff\xe0'
        mock_response.raise_for_status = MagicMock()

        with patch('requests.get') as mock_get:
            mock_get.return_value = mock_response

            base64_data, mime_type = self.driver._download_image_as_base64('https://example.com/test.jpg')

            self.assertEqual(mime_type, 'image/jpeg')

    def test_extract_image_from_response_with_inline_data_new_format(self):
        """测试从响应中提取图片 - inlineData 格式（新格式）"""
        response = {
            "candidates": [{
                "content": {
                    "parts": [{
                        "inlineData": {
                            "mimeType": "image/png",
                            "data": "test_base64_data"
                        }
                    }]
                }
            }]
        }

        result = self.driver._extract_image_from_response(response)

        self.assertIsNotNone(result)
        self.assertEqual(result, "data:image/png;base64,test_base64_data")

    def test_extract_image_from_response_with_inline_data_old_format(self):
        """测试从响应中提取图片 - inline_data 格式（旧格式兼容）"""
        response = {
            "candidates": [{
                "content": {
                    "parts": [{
                        "inline_data": {
                            "mime_type": "image/png",
                            "data": "test_base64_data"
                        }
                    }]
                }
            }]
        }

        result = self.driver._extract_image_from_response(response)

        self.assertIsNotNone(result)
        self.assertEqual(result, "data:image/png;base64,test_base64_data")

    def test_extract_image_from_response_empty(self):
        """测试从响应中提取图片 - 空响应"""
        response = {
            "candidates": []
        }

        result = self.driver._extract_image_from_response(response)

        self.assertIsNone(result)

    def test_extract_image_from_response_no_parts(self):
        """测试从响应中提取图片 - 无 parts"""
        response = {
            "candidates": [{
                "content": {
                    "parts": []
                }
            }]
        }

        result = self.driver._extract_image_from_response(response)

        self.assertIsNone(result)


if __name__ == '__main__':
    import unittest
    unittest.main()
