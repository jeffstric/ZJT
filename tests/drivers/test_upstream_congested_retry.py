"""
视频驱动「上游拥堵自动重试」识别单元测试

验证 RunningHub 视频驱动（以 LTX2.3 为代表）在 RunningHub 返回 errorCode=421
（账号并发超限 / 队列上限）时，正确返回 UPSTREAM_CONGESTED 可重试标记（而非直接判失败）；
同时对其他 errorCode（含 TASK_QUEUE_MAXED）和普通业务错误保持原有判失败行为（回归保护）。

注：识别仅依据 errorCode==421，与 errorMessage 文本无关。
"""
import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, AsyncMock

from task.visual_drivers.ltx2_3_runninghub_v1_driver import Ltx2Dot3RunninghubV1Driver


def make_driver():
    """绕过 __init__ 构造驱动，避免加载动态配置"""
    driver = Ltx2Dot3RunninghubV1Driver.__new__(Ltx2Dot3RunninghubV1Driver)
    driver.logger = MagicMock()
    # build_create_request 改为 AsyncMock，跳过图片上传等复杂逻辑
    driver.build_create_request = AsyncMock(return_value={
        "url": "http://example/run", "method": "POST", "json": {}, "headers": {}
    })
    return driver


def make_ai_tool():
    return SimpleNamespace(id=1, prompt="test", duration=5)


class TestUpstreamCongestedRetry(unittest.TestCase):
    """测试驱动对上游拥堵错误的识别"""

    def test_base_build_upstream_congested_result(self):
        """基类 _build_upstream_congested_result 返回标准可重试标记"""
        driver = make_driver()
        result = driver._build_upstream_congested_result()
        self.assertFalse(result["success"])
        self.assertTrue(result["retry"])
        self.assertEqual(result["retry_reason"], "UPSTREAM_CONGESTED")

    def test_error_code_421_returns_congested_retry(self):
        """RunningHub 返回 errorCode=421（队列上限）应识别为可重试"""
        driver = make_driver()
        driver._request = MagicMock(return_value={
            "taskId": "2019324151986266113",
            "status": "RUNNING",
            "errorCode": "421",
            "errorMessage": "api queue limit reached, please retry later|API发数已达上限，请降低并发或稍后重试",
        })
        result = asyncio.run(driver.submit_task(make_ai_tool()))
        self.assertFalse(result["success"])
        self.assertTrue(result["retry"])
        self.assertEqual(result["retry_reason"], "UPSTREAM_CONGESTED")

    def test_error_code_421_int_also_matched(self):
        """errorCode 为数字 421 时同样识别（str 兼容）"""
        driver = make_driver()
        driver._request = MagicMock(return_value={
            "taskId": "x", "status": "RUNNING",
            "errorCode": 421, "errorMessage": "",
        })
        result = asyncio.run(driver.submit_task(make_ai_tool()))
        self.assertEqual(result.get("retry_reason"), "UPSTREAM_CONGESTED")

    def test_non_421_error_code_not_treated_as_congested(self):
        """errorCode 非 421（如 TASK_QUEUE_MAXED）不识别为拥堵，走普通失败"""
        driver = make_driver()
        driver._request = MagicMock(return_value={
            "taskId": "x", "status": "RUNNING",
            "errorCode": "TASK_QUEUE_MAXED", "errorMessage": "",
        })
        result = asyncio.run(driver.submit_task(make_ai_tool()))
        self.assertFalse(result["success"])
        self.assertNotEqual(result.get("retry_reason"), "UPSTREAM_CONGESTED")

    def test_normal_business_error_still_fails(self):
        """普通业务错误仍判失败（不重试）—— 回归保护"""
        driver = make_driver()
        driver._request = MagicMock(return_value={
            "taskId": "x", "status": "RUNNING",
            "errorCode": "INVALID_PARAM", "errorMessage": "参数错误：prompt 不能为空",
        })
        result = asyncio.run(driver.submit_task(make_ai_tool()))
        self.assertFalse(result["success"])
        self.assertFalse(result.get("retry"))
        self.assertIn("任务提交失败", result["error"])


if __name__ == '__main__':
    unittest.main()
