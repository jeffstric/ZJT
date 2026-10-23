"""
RunningHub AI App 图片 v1 驱动单元测试
纯单元测试，不依赖数据库，使用 mock 替代所有外部依赖。
依赖 stub 通过 tests/base/test_isolation.py 官方工具安装并恢复。
"""
import asyncio
import unittest
from unittest.mock import patch, MagicMock, AsyncMock

from tests.base.test_isolation import stub_modules

with stub_modules({
    'utils.sentry_util': MagicMock(),
    'utils.file_storage': MagicMock(),
    'qiniu': MagicMock(),
}):
    from task.visual_drivers.runninghub_ai_app_image_v1_driver import RunninghubAiAppImageV1Driver


def _create_driver():
    """创建驱动实例（mock 所有外部依赖）"""
    with patch('task.visual_drivers.runninghub_ai_app_image_v1_driver.get_dynamic_config_value',
               return_value='test_value'), \
         patch('task.visual_drivers.runninghub_ai_app_image_v1_driver.get_config',
               return_value={}):
        return RunninghubAiAppImageV1Driver()


def _make_ai_tool(prompt='把人物衣服换成红色', image_path=None,
                  ratio='1:1', image_size='2K', extra_config=None):
    """创建模拟的 ai_tool 对象"""
    tool = MagicMock()
    tool.id = 1001
    tool.prompt = prompt
    tool.image_path = image_path
    tool.ratio = ratio
    tool.image_size = image_size
    tool.extra_config = extra_config
    return tool


def _mock_upload(driver, key='pasted/uploaded.png'):
    """mock 图床上传成功"""
    upload_result = MagicMock()
    upload_result.success = True
    upload_result.url = None
    upload_result.key = key
    driver._storage.upload_file = AsyncMock(return_value=upload_result)


def _find_node(node_list, node_id, field_name):
    """按 nodeId + fieldName 查找节点，找不到返回 None"""
    return next((n for n in node_list
                 if n['nodeId'] == node_id and n['fieldName'] == field_name), None)


class TestMappings(unittest.TestCase):
    """测试比例 / 百万像素映射"""

    def setUp(self):
        self.driver = _create_driver()

    def test_map_aspect_ratio_known(self):
        """已知比例映射为工作流枚举值"""
        self.assertEqual(self.driver._map_aspect_ratio('1:1'), '1:1 (Square)')
        self.assertEqual(self.driver._map_aspect_ratio('9:16'), '9:16 (Portrait Widescreen)')
        self.assertEqual(self.driver._map_aspect_ratio('16:9'), '16:9 (Widescreen)')
        self.assertEqual(self.driver._map_aspect_ratio('21:9'), '21:9 (Ultrawide)')
        self.assertEqual(self.driver._map_aspect_ratio('3:4'), '3:4 (Portrait Standard)')

    def test_map_aspect_ratio_unknown_falls_back(self):
        """未知比例回落 1:1"""
        self.assertEqual(self.driver._map_aspect_ratio('5:7'), '1:1 (Square)')
        self.assertEqual(self.driver._map_aspect_ratio(''), '1:1 (Square)')
        self.assertEqual(self.driver._map_aspect_ratio(None), '1:1 (Square)')

    def test_map_megapixels(self):
        """分辨率档位映射为百万像素值"""
        self.assertEqual(self.driver._map_megapixels('1K'), '1')
        self.assertEqual(self.driver._map_megapixels('2k'), '2')
        self.assertEqual(self.driver._map_megapixels('4K'), '4')
        self.assertEqual(self.driver._map_megapixels('2K'), '2')

    def test_map_megapixels_invalid_falls_back(self):
        """非法分辨率回落 2（200 万像素）"""
        self.assertEqual(self.driver._map_megapixels(None), '2')
        self.assertEqual(self.driver._map_megapixels(''), '2')
        self.assertEqual(self.driver._map_megapixels('abc'), '2')

    def test_map_megapixels_clamped(self):
        """越界值限制在 1-4 范围"""
        self.assertEqual(self.driver._map_megapixels('99K'), '4')
        self.assertEqual(self.driver._map_megapixels('0K'), '1')


class TestBuildCreateRequestImageEdit(unittest.TestCase):
    """测试图片编辑模式（有参考图）的请求构建"""

    def setUp(self):
        self.driver = _create_driver()

    def _run_async(self, coro):
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    def test_edit_mode_single_image(self):
        """单图编辑：图1 传上传结果，其余槽位填 None，开启 25/29 且不传 28"""
        tool = _make_ai_tool(prompt='图片1 的人物穿上图片2的服饰',
                             image_path='http://example.com/a.png')
        _mock_upload(self.driver, key='pasted/aaa.png')

        result = self._run_async(self.driver.build_create_request(tool))

        self.assertIn('/openapi/v2/run/ai-app/', result['url'])
        node_list = result['json']['nodeInfoList']

        # 图片槽位：图1 有值，图2-6 全 None
        self.assertEqual(_find_node(node_list, '17', 'image')['fieldValue'], 'pasted/aaa.png')
        for node_id in ('18', '19', '20', '21', '22'):
            self.assertEqual(_find_node(node_list, node_id, 'image')['fieldValue'], 'None')

        # 提示词与反推开关
        self.assertEqual(_find_node(node_list, '23', 'value')['fieldValue'], tool.prompt)
        self.assertEqual(_find_node(node_list, '24', 'value')['fieldValue'], 'false')

        # 编辑模式：原图无偏移 + 使用图片尺寸开启，不传 28（跟随图1尺寸）
        self.assertEqual(_find_node(node_list, '25', 'value')['fieldValue'], 'true')
        self.assertEqual(_find_node(node_list, '29', 'value')['fieldValue'], 'true')
        self.assertIsNone(_find_node(node_list, '28', 'aspect_ratio'))
        self.assertIsNone(_find_node(node_list, '28', 'megapixels'))

    def test_edit_mode_multi_image(self):
        """多图编辑：按槽位顺序填充"""
        tool = _make_ai_tool(
            image_path='http://example.com/a.png,http://example.com/b.png,http://example.com/c.png')
        upload_result = MagicMock()
        upload_result.success = True
        upload_result.url = None

        def _upload(host, url):
            r = MagicMock()
            r.success = True
            r.url = None
            r.key = f'pasted/{url.split("/")[-1]}'
            return r

        self.driver._storage.upload_file = AsyncMock(side_effect=_upload)

        result = self._run_async(self.driver.build_create_request(tool))
        node_list = result['json']['nodeInfoList']

        self.assertEqual(_find_node(node_list, '17', 'image')['fieldValue'], 'pasted/a.png')
        self.assertEqual(_find_node(node_list, '18', 'image')['fieldValue'], 'pasted/b.png')
        self.assertEqual(_find_node(node_list, '19', 'image')['fieldValue'], 'pasted/c.png')
        self.assertEqual(_find_node(node_list, '20', 'image')['fieldValue'], 'None')

    def test_edit_mode_more_than_six_images_truncated(self):
        """超过 6 张图截断到 6 张（工作流仅 6 个图片槽位）"""
        urls = ','.join(f'http://example.com/{i}.png' for i in range(8))
        tool = _make_ai_tool(image_path=urls)
        _mock_upload(self.driver)

        result = self._run_async(self.driver.build_create_request(tool))
        node_list = result['json']['nodeInfoList']

        image_nodes = [n for n in node_list if n['fieldName'] == 'image']
        self.assertEqual(len(image_nodes), 6)
        self.assertTrue(all(n['fieldValue'] != 'None' for n in image_nodes))

    def test_upload_failure_raises(self):
        """上传失败抛 RuntimeError（避免过期 URL 透传导致下游 401 假象）"""
        tool = _make_ai_tool(image_path='http://example.com/a.png')
        upload_result = MagicMock()
        upload_result.success = False
        upload_result.error = 'Upload failed'
        self.driver._storage.upload_file = AsyncMock(return_value=upload_result)

        with self.assertRaises(RuntimeError) as ctx:
            self._run_async(self.driver.build_create_request(tool))
        self.assertIn('图片上传到 RunningHub 失败', str(ctx.exception))


class TestBuildCreateRequestTextToImage(unittest.TestCase):
    """测试文生图模式（无参考图）的请求构建"""

    def setUp(self):
        self.driver = _create_driver()

    def _run_async(self, coro):
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    def test_t2i_mode_nodes(self):
        """文生图：图片槽全 None、关闭 25/29、节点 28 显式比例+像素"""
        tool = _make_ai_tool(prompt='一只在月球上骑车的橘猫，赛博朋克风格',
                             image_path=None, ratio='9:16', image_size='4K')

        result = self._run_async(self.driver.build_create_request(tool))

        node_list = result['json']['nodeInfoList']

        # 图片槽全 None（工作流 skip_empty 自动忽略）
        for node_id in ('17', '18', '19', '20', '21', '22'):
            self.assertEqual(_find_node(node_list, node_id, 'image')['fieldValue'], 'None')

        self.assertEqual(_find_node(node_list, '23', 'value')['fieldValue'], tool.prompt)
        self.assertEqual(_find_node(node_list, '24', 'value')['fieldValue'], 'false')

        # 文生图必须关闭原图无偏移与使用图片尺寸
        self.assertEqual(_find_node(node_list, '25', 'value')['fieldValue'], 'false')
        self.assertEqual(_find_node(node_list, '29', 'value')['fieldValue'], 'false')

        # 显式比例 + 百万像素
        self.assertEqual(
            _find_node(node_list, '28', 'aspect_ratio')['fieldValue'],
            '9:16 (Portrait Widescreen)')
        self.assertEqual(_find_node(node_list, '28', 'megapixels')['fieldValue'], '4')

    def test_t2i_mode_empty_image_path_string(self):
        """空字符串 image_path 同样视为文生图"""
        tool = _make_ai_tool(image_path='', ratio='1:1', image_size='2K')

        result = self._run_async(self.driver.build_create_request(tool))
        node_list = result['json']['nodeInfoList']

        self.assertEqual(_find_node(node_list, '25', 'value')['fieldValue'], 'false')
        self.assertEqual(_find_node(node_list, '28', 'aspect_ratio')['fieldValue'], '1:1 (Square)')
        self.assertEqual(_find_node(node_list, '28', 'megapixels')['fieldValue'], '2')

    def test_request_structure(self):
        """请求体结构符合 RunningHub ai-app v2 接口"""
        tool = _make_ai_tool()
        result = self._run_async(self.driver.build_create_request(tool))

        self.assertEqual(result['method'], 'POST')
        self.assertEqual(result['json']['instanceType'], 'default')
        self.assertEqual(result['json']['usePersonalQueue'], 'false')
        self.assertTrue(result['headers']['Authorization'].startswith('Bearer '))


class TestValidateSubmitResponse(unittest.TestCase):
    """测试 _validate_submit_response 方法"""

    def setUp(self):
        self.driver = _create_driver()

    def test_valid_response(self):
        result = {"taskId": "12345", "status": "RUNNING", "errorCode": "", "errorMessage": ""}
        is_valid, error = self.driver._validate_submit_response(result)
        self.assertTrue(is_valid)
        self.assertIsNone(error)

    def test_missing_task_id(self):
        is_valid, error = self.driver._validate_submit_response({"status": "RUNNING"})
        self.assertFalse(is_valid)
        self.assertIn('taskId', error)

    def test_non_dict_response(self):
        is_valid, error = self.driver._validate_submit_response("not a dict")
        self.assertFalse(is_valid)
        self.assertIn('字典', error)


class TestSubmitTask(unittest.TestCase):
    """测试 submit_task 方法"""

    def setUp(self):
        self.driver = _create_driver()

    def _run_async(self, coro):
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    def test_submit_success_edit_mode(self):
        """编辑模式提交成功返回 taskId"""
        tool = _make_ai_tool(image_path='http://example.com/a.png')
        _mock_upload(self.driver)
        self.driver._request = MagicMock(return_value={
            "taskId": "2113539", "status": "RUNNING", "errorCode": "", "errorMessage": ""
        })

        result = self._run_async(self.driver.submit_task(tool))
        self.assertTrue(result['success'])
        self.assertEqual(result['project_id'], '2113539')

    def test_submit_success_t2i_mode(self):
        """文生图模式提交成功（无需上传）"""
        tool = _make_ai_tool(image_path=None)
        self.driver._request = MagicMock(return_value={
            "taskId": "2113540", "status": "RUNNING", "errorCode": "", "errorMessage": ""
        })

        result = self._run_async(self.driver.submit_task(tool))
        self.assertTrue(result['success'])
        self.assertEqual(result['project_id'], '2113540')

    def test_submit_business_error(self):
        """业务错误返回 USER 错误"""
        tool = _make_ai_tool(image_path=None)
        self.driver._request = MagicMock(return_value={
            "taskId": "", "status": "FAILED",
            "errorCode": "INVALID_PARAM", "errorMessage": "参数错误"
        })

        result = self._run_async(self.driver.submit_task(tool))
        self.assertFalse(result['success'])
        self.assertEqual(result['error_type'], 'USER')

    def test_submit_upstream_congested_retries(self):
        """上游拥堵（errorCode=421）返回可重试结果"""
        tool = _make_ai_tool(image_path=None)
        self.driver._request = MagicMock(return_value={
            "taskId": "", "status": "FAILED",
            "errorCode": "421", "errorMessage": "api queue limit reached"
        })

        result = self._run_async(self.driver.submit_task(tool))
        self.assertFalse(result['success'])
        self.assertTrue(result.get('retry'))
        self.assertEqual(result.get('retry_reason'), 'UPSTREAM_CONGESTED')

    def test_submit_network_error_retries(self):
        """网络异常允许重试"""
        tool = _make_ai_tool(image_path=None)
        self.driver._request = MagicMock(side_effect=ConnectionError("timeout"))

        result = self._run_async(self.driver.submit_task(tool))
        self.assertFalse(result['success'])
        self.assertTrue(result.get('retry'))

    def test_submit_upload_expired_image(self):
        """图片过期返回用户错误，不重试"""
        from task.visual_drivers.exceptions import ImageExpiredError
        tool = _make_ai_tool(image_path='http://example.com/expired.png')
        self.driver._storage.upload_file = AsyncMock(side_effect=ImageExpiredError('图片链接已过期'))

        result = self._run_async(self.driver.submit_task(tool))
        self.assertFalse(result['success'])
        self.assertEqual(result['error_type'], 'USER')
        self.assertFalse(result.get('retry', False))


class TestBuildCheckQuery(unittest.TestCase):
    """测试 build_check_query 方法"""

    def setUp(self):
        self.driver = _create_driver()

    def test_check_query_structure(self):
        result = self.driver.build_check_query('task_12345')
        self.assertIn('/task/openapi/status', result['url'])
        self.assertEqual(result['method'], 'POST')
        self.assertEqual(result['json']['taskId'], 'task_12345')
        self.assertIn('apiKey', result['json'])


class TestCheckStatus(unittest.TestCase):
    """测试 check_status 方法"""

    def setUp(self):
        self.driver = _create_driver()

    def test_success_status(self):
        """任务成功并提取输出 URL"""
        self.driver._request = MagicMock(side_effect=[
            {"code": 0, "data": "SUCCESS"},
            {"code": 0, "data": [{"fileUrl": "http://cdn.example.com/result.png"}]}
        ])

        result = self.driver.check_status('task_12345')
        self.assertEqual(result['status'], 'SUCCESS')
        self.assertEqual(result['result_url'], 'http://cdn.example.com/result.png')

    def test_failed_status(self):
        self.driver._request = MagicMock(return_value={"code": 0, "data": "FAILED"})
        result = self.driver.check_status('task_12345')
        self.assertEqual(result['status'], 'FAILED')

    def test_running_status(self):
        self.driver._request = MagicMock(return_value={"code": 0, "data": "RUNNING"})
        result = self.driver.check_status('task_12345')
        self.assertEqual(result['status'], 'RUNNING')

    def test_network_error_returns_running(self):
        """网络错误返回 RUNNING（允许重试）"""
        self.driver._request = MagicMock(side_effect=ConnectionError("timeout"))
        result = self.driver.check_status('task_12345')
        self.assertEqual(result['status'], 'RUNNING')

    def test_api_error_code(self):
        self.driver._request = MagicMock(return_value={"code": 1, "msg": "Invalid task"})
        result = self.driver.check_status('task_12345')
        self.assertEqual(result['status'], 'FAILED')
        self.assertEqual(result['error'], 'Invalid task')


class TestFactoryRegistration(unittest.TestCase):
    """测试驱动工厂注册"""

    def test_registered_by_type_52(self):
        from task.visual_drivers import register_all_drivers
        from task.visual_drivers.driver_factory import VideoDriverFactory
        from config.unified_config import DriverImplementation

        register_all_drivers()
        # 工厂创建真实驱动实例需要 RunningHub 配置存在，mock 动态配置
        with patch('task.visual_drivers.runninghub_ai_app_image_v1_driver.get_dynamic_config_value',
                   return_value='test_value'), \
             patch('task.visual_drivers.runninghub_ai_app_image_v1_driver.get_config',
                   return_value={}):
            driver = VideoDriverFactory.create_driver_by_implementation(
                DriverImplementation.RUNNINGHUB_AI_APP_IMAGE_V1)
            self.assertIsNotNone(driver)
            self.assertEqual(driver.driver_type, 52)
            self.assertEqual(driver.driver_name, 'runninghub_ai_app_image_v1')


if __name__ == '__main__':
    unittest.main()
