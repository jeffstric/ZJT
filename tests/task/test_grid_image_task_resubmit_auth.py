"""
_resubmit_image_request 的鉴权头回归测试。

线上事故：宫格几何校验失败后的自动重试经 /api/image-edit、/api/text-to-image 重新提交时，
auth_token 只放在 form data 里而未带 Authorization 头。/api/* 的 require_permission 只认
Authorization 头（form 字段不过鉴权），导致重试 100% 被 401 拒绝、max_retries 形同虚设，
几何校验失败一次即任务终态死亡（2026-10-11 单日 58 次 401、10+ 学员任务全军覆没）。
"""
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from tests.base.test_isolation import stub_modules

# 只 mock database 层，保持 model 包真实导入（与既有 grid_image_task 测试一致）
with stub_modules({
    'model.database': MagicMock(),
}):
    from task.grid_image_task import _resubmit_image_request


def _make_task(**overrides):
    kwargs = dict(
        task_key="grid:1:2:1075",
        prompt="a 2x2 grid",
        task_config_id=26,
        comfyui_base_url="http://127.0.0.1:5173",
        auth_token="tok-abc",
        user_id=1,
        aspect_ratio="9:16",
        image_size=None,
        reference_images=None,
    )
    kwargs.update(overrides)
    return SimpleNamespace(**kwargs)


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class TestResubmitImageRequestAuthHeader(unittest.TestCase):
    """重试提交必须携带 Authorization 头，否则 require_permission 必返 401。"""

    @patch("task.grid_image_task.httpx.post")
    def test_text_to_image_retry_sends_bearer_header(self, mock_post):
        mock_post.return_value = _FakeResponse({"project_ids": ["p-1"]})
        task = _make_task()

        new_project_id = _resubmit_image_request(task)

        self.assertEqual(new_project_id, "p-1")
        _, kwargs = mock_post.call_args
        self.assertEqual(
            kwargs["headers"],
            {"Authorization": "Bearer tok-abc"},
        )

    @patch("task.grid_image_task.httpx.post")
    def test_image_edit_retry_sends_bearer_header(self, mock_post):
        mock_post.return_value = _FakeResponse({"project_ids": ["p-2"]})
        task = _make_task(
            reference_images=[{"url": "http://127.0.0.1:5173/upload/a.png"}],
        )

        new_project_id = _resubmit_image_request(task)

        self.assertEqual(new_project_id, "p-2")
        _, kwargs = mock_post.call_args
        self.assertEqual(
            kwargs["headers"],
            {"Authorization": "Bearer tok-abc"},
        )
        self.assertIn("/api/image-edit", mock_post.call_args.args[0])

    @patch("task.grid_image_task.httpx.post")
    def test_missing_auth_token_sends_no_header(self, mock_post):
        mock_post.return_value = _FakeResponse({"project_ids": ["p-3"]})
        task = _make_task(auth_token=None)

        new_project_id = _resubmit_image_request(task)

        self.assertEqual(new_project_id, "p-3")
        _, kwargs = mock_post.call_args
        self.assertIsNone(kwargs["headers"])


if __name__ == "__main__":
    unittest.main()
