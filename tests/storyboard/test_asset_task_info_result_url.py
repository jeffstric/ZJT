"""
_asset_task_info 的结果 URL 优先级测试。

宫格拆分场景下，多个 storyboard_scene_asset 共享同一个 ai_tool（宫格生图任务），
而 ai_tool.result_url 是整张宫格图，asset.result_url 才是拆分后的单格图。
_asset_task_info 不应用 ai_tool.result_url 覆盖 asset 已有的 result_url，
否则前端轮询 task-status 时会把单格图回退成整张宫格图。
"""
import asyncio
import importlib
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

# mock database 层，避免真实 DB 连接
_saved_database = sys.modules.get("model.database")
sys.modules["model.database"] = MagicMock()

for _mod in [
    "model.storyboard_scene_asset",
    "model.ai_tools",
]:
    if _mod in sys.modules:
        importlib.reload(sys.modules[_mod])

if _saved_database is not None:
    sys.modules["model.database"] = _saved_database
else:
    sys.modules.pop("model.database", None)


def _make_asset(asset_id, result_url, ai_tool_id):
    return SimpleNamespace(
        id=asset_id,
        asset_type="first_frame",
        result_url=result_url,
        ai_tool_id=ai_tool_id,
    )


def _make_tool(tool_id, result_url, status=2):
    return SimpleNamespace(
        id=tool_id,
        result_url=result_url,
        status=status,
        message=None,
    )


class TestAssetTaskInfoResultUrlPriority:
    """asset.result_url 是权威值；ai_tool.result_url 仅在 asset 缺失时兜底。"""

    def test_asset_result_url_not_overwritten_by_ai_tool(self):
        """宫格拆分：asset 有单格图 url，不应被 ai_tool 的宫格图 url 覆盖。"""
        from api.storyboard import _asset_task_info

        scene = SimpleNamespace(
            selected_first_frame_id=261,
            selected_last_frame_id=None,
            selected_video_id=None,
        )
        asset = _make_asset(
            asset_id=261,
            result_url="http://localhost:9003/upload/storyboard/first_frame/single_cell.png",
            ai_tool_id=1083,
        )
        tool = _make_tool(
            tool_id=1083,
            result_url="http://localhost:9003/upload/storyboard/temp/1083_full_grid.png",
        )

        with patch("api.storyboard.StoryboardSceneAssetModel") as MockAssetModel, \
             patch("api.storyboard.AIToolsModel") as MockAIToolsModel:
            MockAssetModel.get_by_id.return_value = asset
            MockAIToolsModel.get_by_id.return_value = tool

            info = asyncio.run(_asset_task_info(scene, "first_frame"))

        # asset 的单格图 url 应被保留，不被 ai_tool 的宫格图覆盖
        assert info["result_url"] == "http://localhost:9003/upload/storyboard/first_frame/single_cell.png"
        assert info["asset_id"] == 261
        assert info["status"] == 2

    def test_falls_back_to_ai_tool_result_url_when_asset_missing(self):
        """非宫格路径：asset 创建时无 result_url（任务刚提交），用 ai_tool 兜底。"""
        from api.storyboard import _asset_task_info

        scene = SimpleNamespace(
            selected_first_frame_id=300,
            selected_last_frame_id=None,
            selected_video_id=None,
        )
        asset = _make_asset(
            asset_id=300,
            result_url=None,  # asset 没存 result_url
            ai_tool_id=500,
        )
        tool = _make_tool(
            tool_id=500,
            result_url="http://localhost:9003/upload/some_result.png",
        )

        with patch("api.storyboard.StoryboardSceneAssetModel") as MockAssetModel, \
             patch("api.storyboard.AIToolsModel") as MockAIToolsModel:
            MockAssetModel.get_by_id.return_value = asset
            MockAIToolsModel.get_by_id.return_value = tool

            info = asyncio.run(_asset_task_info(scene, "first_frame"))

        assert info["result_url"] == "http://localhost:9003/upload/some_result.png"

    def test_no_ai_tool_keeps_asset_url(self):
        """asset 无关联 ai_tool 时，保留 asset 自身的 result_url。"""
        from api.storyboard import _asset_task_info

        scene = SimpleNamespace(
            selected_first_frame_id=301,
            selected_last_frame_id=None,
            selected_video_id=None,
        )
        asset = _make_asset(
            asset_id=301,
            result_url="http://localhost:9003/upload/storyboard/first_frame/direct.png",
            ai_tool_id=None,
        )

        with patch("api.storyboard.StoryboardSceneAssetModel") as MockAssetModel:
            MockAssetModel.get_by_id.return_value = asset

            info = asyncio.run(_asset_task_info(scene, "first_frame"))

        assert info["result_url"] == "http://localhost:9003/upload/storyboard/first_frame/direct.png"


if __name__ == "__main__":
    import unittest
    unittest.main()
