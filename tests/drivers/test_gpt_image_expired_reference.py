"""
参考图 404 → 用户友好错误（ImageExpiredError）的单元测试。

背景（生产事故 app.2026-09-29）：任务 50937/50938 引用的参考图
upload/cache/2026-08-10/...png 已被定期清理（本地不存在 + 远程 404），驱动下载
404 后走 Unexpected exception 分支：触发 Sentry UNEXPECTED_EXCEPTION 系统告警，
用户看到的是误导性的"服务异常，请联系技术支持"，且重试必然失败。

修复后：_prepare_image_file / _download_image_as_base64 遇 404/410 抛
ImageExpiredError，submit_task 现有 except 分支将其转为 error_type=USER 的
明确提示（"参考图片已失效……请重新上传或更换参考图后重试"），不再触发系统告警。

验证点：
1. 下载 404/410 → 抛 ImageExpiredError，消息含"参考图片已失效"；
2. 下载其他状态码（500）仍走 raise_for_status 的 HTTPError（保持原系统错误语义）；
3. submit_task 捕获 ImageExpiredError 后返回 USER 错误且不触发 Sentry 告警。
"""
import logging
import os
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
import requests

os.environ.setdefault("comfyui_env", "prod")

from task.visual_drivers.exceptions import ImageExpiredError
from task.visual_drivers.gpt_image_common_v1_driver import GptImageCommonV1Driver


def make_driver():
    driver = GptImageCommonV1Driver.__new__(GptImageCommonV1Driver)
    driver._base_url = "https://yunwu.ai"
    driver._api_key = "test-key"
    driver._config = {}
    driver.logger = logging.getLogger("test_gpt_image_404")
    return driver


def _make_response(status_code):
    response = MagicMock()
    response.status_code = status_code
    response.headers = {}
    response.raise_for_status = MagicMock(
        side_effect=requests.HTTPError(f"{status_code} Error")
    )
    return response


DEAD_URL = "http://ailive.perseids.cn/upload/cache/2026-08-10/25547_deadbeef.png"


class TestPrepareImageFile404:
    """multipart 路径：远程下载 404/410 → ImageExpiredError"""

    @pytest.mark.parametrize("status", [404, 410])
    def test_404_raises_image_expired(self, status):
        driver = make_driver()
        with patch.object(driver, "_resolve_local_path"), \
                patch("task.visual_drivers.gpt_image_common_v1_driver.ensure_fresh_image_url_sync",
                      return_value=DEAD_URL), \
                patch("task.visual_drivers.gpt_image_common_v1_driver.try_map_url_to_local_file",
                      return_value=None), \
                patch("task.visual_drivers.gpt_image_common_v1_driver.extract_local_path_from_url",
                      return_value=None), \
                patch("task.visual_drivers.gpt_image_common_v1_driver.requests.get",
                      return_value=_make_response(status)):
            with pytest.raises(ImageExpiredError) as exc_info:
                driver._prepare_image_file(DEAD_URL)
        assert "参考图片已失效" in str(exc_info.value)

    def test_500_still_raises_http_error(self):
        """服务端 5xx 保持原语义（HTTPError），不算参考图失效"""
        driver = make_driver()
        with patch.object(driver, "_resolve_local_path"), \
                patch("task.visual_drivers.gpt_image_common_v1_driver.ensure_fresh_image_url_sync",
                      return_value=DEAD_URL), \
                patch("task.visual_drivers.gpt_image_common_v1_driver.try_map_url_to_local_file",
                      return_value=None), \
                patch("task.visual_drivers.gpt_image_common_v1_driver.extract_local_path_from_url",
                      return_value=None), \
                patch("task.visual_drivers.gpt_image_common_v1_driver.requests.get",
                      return_value=_make_response(500)):
            with pytest.raises(requests.HTTPError):
                driver._prepare_image_file(DEAD_URL)


class TestDownloadImageAsBase64404:
    """base64 路径：远程下载 404 → ImageExpiredError"""

    def test_404_raises_image_expired(self):
        driver = make_driver()
        with patch("task.visual_drivers.gpt_image_common_v1_driver.requests.get",
                   return_value=_make_response(404)):
            with pytest.raises(ImageExpiredError) as exc_info:
                driver._download_image_as_base64(DEAD_URL)
        assert "参考图片已失效" in str(exc_info.value)


class TestSubmitTaskMapsExpiredToUserError:
    """submit_task 捕获 ImageExpiredError → USER 错误，不触发系统告警"""

    def test_expired_image_returns_user_error_without_sentry(self):
        driver = make_driver()
        ai_tool = SimpleNamespace(
            id=50937,
            prompt="edit this",
            image_path=DEAD_URL,
            image_size="1k",
            ratio="16:9",
            extra_config={},
        )

        def _boom(_ai_tool):
            raise ImageExpiredError("参考图片已失效（原文件可能已被清理），请重新上传或更换参考图后重试")

        with patch.object(driver, "build_edit_request", side_effect=_boom), \
                patch.object(driver, "_send_alert") as mock_alert:
            result = driver.submit_task(ai_tool)

        assert result["success"] is False
        assert result["error_type"] == "USER"
        assert "参考图片已失效" in result["error"]
        mock_alert.assert_not_called()
