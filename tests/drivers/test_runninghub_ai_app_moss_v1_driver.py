"""
moss 文生图驱动（RunningHub AI App moss v1）单元测试
纯单元测试，不依赖数据库，使用 mock 替代所有外部依赖。
依赖 stub 通过 tests/base/test_isolation.py 官方工具安装并恢复。
"""
import asyncio
import unittest
from unittest.mock import patch, MagicMock

from tests.base.test_isolation import stub_modules

with stub_modules({
    'utils.sentry_util': MagicMock(),
}):
    from task.visual_drivers.runninghub_ai_app_moss_v1_driver import RunninghubAiAppMossV1Driver


def _fake_dynamic_config(section, key, default=None):
    """动态配置 fake：api_key/host 返回测试值，其余（如 webapp id）走默认值"""
    if key in ('api_key', 'host'):
        return 'test_value'
    return default


def _create_driver():
    """创建驱动实例（mock 所有外部依赖）"""
    with patch('task.visual_drivers.runninghub_ai_app_moss_v1_driver.get_dynamic_config_value',
               side_effect=_fake_dynamic_config):
        return RunninghubAiAppMossV1Driver()


def _make_ai_tool(prompt='一只戴墨镜的橘猫', image_path=None,
                  ratio='1:1', image_size='2K'):
    """创建模拟的 ai_tool 对象"""
    tool = MagicMock()
    tool.id = 2001
    tool.prompt = prompt
    tool.image_path = image_path
    tool.ratio = ratio
    tool.image_size = image_size
    return tool


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
        self.assertEqual(self.driver._map_aspect_ratio('2:3'), '2:3 (Portrait Photo)')
        self.assertEqual(self.driver._map_aspect_ratio('3:2'), '3:2 (Photo)')
        self.assertEqual(self.driver._map_aspect_ratio('4:3'), '4:3 (Standard)')

    def test_map_aspect_ratio_unknown_falls_back(self):
        """未知比例回落 9:16（上游默认比例）"""
        self.assertEqual(self.driver._map_aspect_ratio('5:7'), '9:16 (Portrait Widescreen)')
        self.assertEqual(self.driver._map_aspect_ratio(''), '9:16 (Portrait Widescreen)')
        self.assertEqual(self.driver._map_aspect_ratio(None), '9:16 (Portrait Widescreen)')

    def test_map_megapixels(self):
        """分辨率档位映射为百万像素值"""
        self.assertEqual(self.driver._map_megapixels('1K'), '1')
        self.assertEqual(self.driver._map_megapixels('2k'), '2')
        self.assertEqual(self.driver._map_megapixels('4K'), '4')
        self.assertEqual(self.driver._map_megapixels('2K'), '2')

    def test_map_megapixels_invalid_falls_back(self):
        """非法分辨率回落 2（200 万像素，上游默认 1088x1920）"""
        self.assertEqual(self.driver._map_megapixels(None), '2')
        self.assertEqual(self.driver._map_megapixels(''), '2')
        self.assertEqual(self.driver._map_megapixels('abc'), '2')

    def test_map_megapixels_clamped(self):
        """越界值限制在 1-4 范围"""
        self.assertEqual(self.driver._map_megapixels('99K'), '4')
        self.assertEqual(self.driver._map_megapixels('0K'), '1')


class TestBuildCreateRequest(unittest.TestCase):
    """测试 build_create_request 请求构造（仅文生图）"""

    def setUp(self):
        self.driver = _create_driver()

    def _run_async(self, coro):
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    def test_request_structure(self):
        """文生图请求包含全部节点映射与 Bearer 认证"""
        tool = _make_ai_tool(ratio='16:9', image_size='4K')
        request = self._run_async(self.driver.build_create_request(tool))

        self.assertIn('/openapi/v2/run/ai-app/', request['url'])
        self.assertIn(self.driver.DEFAULT_WEBAPP_ID, request['url'])
        self.assertEqual(request['method'], 'POST')
        self.assertEqual(request['headers']['Authorization'], f'Bearer {self.driver._api_key}')

        body = request['json']
        self.assertEqual(body['instanceType'], 'default')
        self.assertEqual(body['usePersonalQueue'], 'false')

        node_list = body['nodeInfoList']
        aspect = _find_node(node_list, '8', 'aspect_ratio')
        self.assertIsNotNone(aspect)
        self.assertEqual(aspect['fieldValue'], '16:9 (Widescreen)')
        megapixels = _find_node(node_list, '8', 'megapixels')
        self.assertIsNotNone(megapixels)
        self.assertEqual(megapixels['fieldValue'], '4')
        text = _find_node(node_list, '1', 'text')
        self.assertIsNotNone(text)
        self.assertEqual(text['fieldValue'], '一只戴墨镜的橘猫')
        steps = _find_node(node_list, '13', 'steps')
        self.assertEqual(steps['fieldValue'], '25')
        strength = _find_node(node_list, '18', 'strength_model')
        self.assertEqual(strength['fieldValue'], '1')

    def test_no_image_nodes(self):
        """仅文生图：请求体不含任何图片节点"""
        tool = _make_ai_tool()
        request = self._run_async(self.driver.build_create_request(tool))
        image_nodes = [n for n in request['json']['nodeInfoList'] if n['fieldName'] == 'image']
        self.assertEqual(image_nodes, [])

    def test_empty_prompt_allowed(self):
        """空提示词不报错，按空字符串提交"""
        tool = _make_ai_tool(prompt='')
        request = self._run_async(self.driver.build_create_request(tool))
        text = _find_node(request['json']['nodeInfoList'], '1', 'text')
        self.assertEqual(text['fieldValue'], '')

    def test_image_path_rejected(self):
        """带参考图直接拒绝（仅文生图）"""
        tool = _make_ai_tool(image_path='http://example.com/a.png')
        with self.assertRaises(ValueError):
            self._run_async(self.driver.build_create_request(tool))


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

    def test_submit_success(self):
        """文生图提交成功返回 taskId"""
        tool = _make_ai_tool()
        self.driver._request = MagicMock(return_value={
            "taskId": "2112932", "status": "RUNNING", "errorCode": "", "errorMessage": ""
        })

        result = self._run_async(self.driver.submit_task(tool))
        self.assertTrue(result['success'])
        self.assertEqual(result['project_id'], '2112932')

    def test_submit_with_image_returns_user_error(self):
        """带参考图提交被拒绝：USER 错误且不重试"""
        tool = _make_ai_tool(image_path='http://example.com/a.png')
        result = self._run_async(self.driver.submit_task(tool))
        self.assertFalse(result['success'])
        self.assertEqual(result['error_type'], 'USER')
        self.assertFalse(result.get('retry', False))

    def test_submit_business_error(self):
        """业务错误返回 USER 错误"""
        tool = _make_ai_tool()
        self.driver._request = MagicMock(return_value={
            "taskId": "", "status": "FAILED",
            "errorCode": "INVALID_PARAM", "errorMessage": "参数错误"
        })

        result = self._run_async(self.driver.submit_task(tool))
        self.assertFalse(result['success'])
        self.assertEqual(result['error_type'], 'USER')
        self.assertFalse(result.get('retry', False))

    def test_submit_upstream_congested_retries(self):
        """上游拥堵（errorCode=421）返回可重试结果"""
        tool = _make_ai_tool()
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
        tool = _make_ai_tool()
        self.driver._request = MagicMock(side_effect=ConnectionError("timeout"))

        result = self._run_async(self.driver.submit_task(tool))
        self.assertFalse(result['success'])
        self.assertTrue(result.get('retry'))

    def test_submit_missing_task_id_returns_system_error(self):
        """响应缺 taskId 返回 SYSTEM 错误"""
        tool = _make_ai_tool()
        self.driver._request = MagicMock(return_value={"taskId": "", "status": "RUNNING"})

        result = self._run_async(self.driver.submit_task(tool))
        self.assertFalse(result['success'])
        self.assertEqual(result['error_type'], 'SYSTEM')


class TestBuildCheckQuery(unittest.TestCase):
    """测试 build_check_query 方法"""

    def setUp(self):
        self.driver = _create_driver()

    def test_check_query_structure(self):
        """v2 查询走 /openapi/v2/query + Bearer 认证，不在 body 放 apiKey"""
        result = self.driver.build_check_query('task_12345')
        self.assertIn('/openapi/v2/query', result['url'])
        self.assertEqual(result['method'], 'POST')
        self.assertEqual(result['json']['taskId'], 'task_12345')
        self.assertNotIn('apiKey', result['json'])
        self.assertIn('Bearer', result['headers']['Authorization'])


class TestCheckStatus(unittest.TestCase):
    """测试 check_status 方法"""

    def setUp(self):
        self.driver = _create_driver()

    def test_success_status_with_png_url(self):
        """任务成功提取 png 产物 URL"""
        self.driver._request = MagicMock(return_value={
            "taskId": "task_12345", "status": "SUCCESS",
            "results": [
                {"url": "http://cdn.example.com/result.png", "nodeId": "2", "outputType": "png"},
            ],
        })

        result = self.driver.check_status('task_12345')
        self.assertEqual(result['status'], 'SUCCESS')
        self.assertEqual(result['result_url'], 'http://cdn.example.com/result.png')

    def test_success_status_prefers_png(self):
        """多个产物时优先取 png"""
        self.driver._request = MagicMock(return_value={
            "taskId": "task_12345", "status": "SUCCESS",
            "results": [
                {"url": "http://cdn.example.com/readme.txt", "nodeId": "2", "outputType": "txt"},
                {"url": "http://cdn.example.com/result.png", "nodeId": "2", "outputType": "png"},
            ],
        })

        result = self.driver.check_status('task_12345')
        self.assertEqual(result['result_url'], 'http://cdn.example.com/result.png')

    def test_success_without_results_keeps_terminal(self):
        """SUCCESS 但无产物：保持 SUCCESS+None 终态语义（真实无产物）"""
        self.driver._request = MagicMock(return_value={
            "taskId": "task_12345", "status": "SUCCESS", "results": None,
        })

        result = self.driver.check_status('task_12345')
        self.assertEqual(result['status'], 'SUCCESS')
        self.assertIsNone(result['result_url'])

    def test_failed_status_with_error_message(self):
        """失败透传 errorMessage"""
        self.driver._request = MagicMock(return_value={
            "taskId": "task_12345", "status": "FAILED",
            "errorMessage": "工作流执行失败",
        })

        result = self.driver.check_status('task_12345')
        self.assertEqual(result['status'], 'FAILED')
        self.assertEqual(result['error'], '工作流执行失败')

    def test_failed_status_falls_back_to_failed_reason(self):
        """errorMessage 为空时回落 failedReason"""
        self.driver._request = MagicMock(return_value={
            "taskId": "task_12345", "status": "FAILED",
            "errorMessage": "",
            "failedReason": {"nodeType": "KSampler", "message": "OOM"},
        })

        result = self.driver.check_status('task_12345')
        self.assertEqual(result['status'], 'FAILED')
        self.assertIn('OOM', result['error'])

    def test_running_status(self):
        self.driver._request = MagicMock(return_value={
            "taskId": "task_12345", "status": "RUNNING", "results": None,
        })
        result = self.driver.check_status('task_12345')
        self.assertEqual(result['status'], 'RUNNING')

    def test_queued_status_returns_running(self):
        self.driver._request = MagicMock(return_value={
            "taskId": "task_12345", "status": "QUEUED", "results": None,
        })
        result = self.driver.check_status('task_12345')
        self.assertEqual(result['status'], 'RUNNING')

    def test_network_error_returns_running(self):
        """网络错误返回 RUNNING（允许重试）"""
        self.driver._request = MagicMock(side_effect=ConnectionError("timeout"))
        result = self.driver.check_status('task_12345')
        self.assertEqual(result['status'], 'RUNNING')

    def test_invalid_response_format_returns_failed(self):
        """响应缺 status 字段：SYSTEM 失败"""
        self.driver._request = MagicMock(return_value={"code": 1, "msg": "invalid"})
        result = self.driver.check_status('task_12345')
        self.assertEqual(result['status'], 'FAILED')
        self.assertEqual(result['error_type'], 'SYSTEM')


class TestExtractHelpers(unittest.TestCase):
    """测试 results / failedReason 解析辅助方法"""

    def setUp(self):
        self.driver = _create_driver()

    def test_extract_result_url_none_and_malformed(self):
        self.assertIsNone(RunninghubAiAppMossV1Driver._extract_result_url(None))
        self.assertIsNone(RunninghubAiAppMossV1Driver._extract_result_url([]))
        self.assertIsNone(RunninghubAiAppMossV1Driver._extract_result_url([{"nodeId": "2"}]))
        self.assertIsNone(RunninghubAiAppMossV1Driver._extract_result_url("not a list"))

    def test_extract_result_url_first_fallback(self):
        """无 png 时回落第一个带 url 的产物"""
        results = [
            {"url": "http://cdn.example.com/a.txt", "outputType": "txt"},
            {"url": "http://cdn.example.com/b.jpg", "outputType": "jpg"},
        ]
        self.assertEqual(
            RunninghubAiAppMossV1Driver._extract_result_url(results),
            'http://cdn.example.com/a.txt'
        )

    def test_extract_failed_reason_default(self):
        """全部为空时返回兜底文案"""
        self.assertEqual(
            self.driver._extract_failed_reason({"status": "FAILED"}),
            '任务失败'
        )


class TestFactoryRegistration(unittest.TestCase):
    """测试驱动工厂注册"""

    def test_registered_by_type_53(self):
        from task.visual_drivers import register_all_drivers
        from task.visual_drivers.driver_factory import VideoDriverFactory
        from config.unified_config import DriverImplementation

        register_all_drivers()
        # 工厂创建真实驱动实例需要 RunningHub 配置存在，mock 动态配置
        with patch('task.visual_drivers.runninghub_ai_app_moss_v1_driver.get_dynamic_config_value',
                   return_value='test_value'):
            driver = VideoDriverFactory.create_driver_by_implementation(
                DriverImplementation.RUNNINGHUB_AI_APP_MOSS_V1)
            self.assertIsNotNone(driver)
            self.assertEqual(driver.driver_type, 53)
            self.assertEqual(driver.driver_name, 'runninghub_ai_app_moss_v1')

    def test_task_config_registry(self):
        """统一任务配置注册：仅文生图、算力 1、不支持宫格"""
        from config.unified_config import UnifiedConfigRegistry, TaskCategory, TaskTypeId

        config = UnifiedConfigRegistry.get_by_id(TaskTypeId.MOSS_IMAGE)
        self.assertIsNotNone(config)
        self.assertEqual(config.category, TaskCategory.TEXT_TO_IMAGE)
        self.assertEqual(config.categories, [])
        self.assertEqual(config.computing_power, 1)
        self.assertFalse(config.supports_grid_image)
        self.assertEqual(config.provider, 'runninghub')

        # 文生图列表可见、图片编辑列表不可见
        t2i_ids = [c.id for c in UnifiedConfigRegistry.get_by_category(TaskCategory.TEXT_TO_IMAGE)]
        edit_ids = [c.id for c in UnifiedConfigRegistry.get_by_category(TaskCategory.IMAGE_EDIT)]
        self.assertIn(TaskTypeId.MOSS_IMAGE, t2i_ids)
        self.assertNotIn(TaskTypeId.MOSS_IMAGE, edit_ids)


if __name__ == '__main__':
    unittest.main()
