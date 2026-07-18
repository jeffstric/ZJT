"""
_location_grid_readiness 按 sequence_mode 条件阻止的判定矩阵测试。

不连接真实数据库：用 monkeypatch 替换 GridImageTasksModel.has_running_grid_for_entity。
"""
from unittest.mock import patch

import pytest

from services.storyboard_agent_cli_service import StoryboardAgentCliService, StoryboardCliError
from config.constant import LocationReferenceStatus


@pytest.fixture
def svc():
    return StoryboardAgentCliService()


CTX_HAS_IMG = {"location": {"id": 999, "reference_image": "http://h/img.png"}}
CTX_NO_IMG = {"location": {"id": 999, "reference_image": None}}


class TestLocationGridReadinessMatrix:
    """判定矩阵：
      | reference_image | 运行中任务 | quality 模式     | balanced/speed 模式 |
      | 有              | (任意)     | READY 放行       | READY 放行          |
      | 缺              | 有         | WAITING_GRID 阻止| WAITING_GRID 阻止   |
      | 缺              | 无         | WAITING_GRID 阻止| 放行(t2i 兜底)      |
    """

    def test_has_image_always_ready(self, svc):
        """有 reference_image → 任何模式都放行。"""
        for mode in ("quality", "balanced", "speed", None):
            svc._check_location_grid_readiness(CTX_HAS_IMG, sequence_mode=mode)
        # 不抛错即通过

    def test_no_image_with_running_task_blocks_all_modes(self, svc):
        """缺图 + 有运行中任务 → 所有模式都阻止。"""
        with patch(
            "model.grid_image_tasks.GridImageTasksModel.has_running_grid_for_entity",
            return_value=True,
        ):
            for mode in ("quality", "balanced", "speed", None):
                with pytest.raises(StoryboardCliError) as exc_info:
                    svc._check_location_grid_readiness(CTX_NO_IMG, sequence_mode=mode)
                assert exc_info.value.error_code == LocationReferenceStatus.WAITING_GRID
                # 有运行中任务的阻止不带 quality_mode 标记
                assert not exc_info.value.payload.get("quality_mode")

    def test_no_image_no_task_quality_mode_blocks(self, svc):
        """缺图 + 无任务 + quality → 阻止（带 quality_mode=True，供调度器做重试上限降级）。"""
        with patch(
            "model.grid_image_tasks.GridImageTasksModel.has_running_grid_for_entity",
            return_value=False,
        ):
            with pytest.raises(StoryboardCliError) as exc_info:
                svc._check_location_grid_readiness(CTX_NO_IMG, sequence_mode="quality")
            assert exc_info.value.error_code == LocationReferenceStatus.WAITING_GRID
            assert exc_info.value.payload.get("quality_mode") is True

    def test_no_image_no_task_balanced_mode_passes(self, svc):
        """缺图 + 无任务 + balanced/speed/None → 放行（走 t2i 兜底）。"""
        with patch(
            "model.grid_image_tasks.GridImageTasksModel.has_running_grid_for_entity",
            return_value=False,
        ):
            for mode in ("balanced", "speed", None):
                svc._check_location_grid_readiness(CTX_NO_IMG, sequence_mode=mode)
        # 不抛错即通过

    def test_no_location_dict_passes(self, svc):
        """无 location 上下文 → 放行（不阻塞）。"""
        svc._check_location_grid_readiness({}, sequence_mode="quality")
        svc._check_location_grid_readiness({"location": None}, sequence_mode="quality")

    def test_quality_mode_case_insensitive(self, svc):
        """quality 模式判定大小写不敏感。"""
        with patch(
            "model.grid_image_tasks.GridImageTasksModel.has_running_grid_for_entity",
            return_value=False,
        ):
            for mode_variant in ("QUALITY", "Quality", "  quality  "):
                with pytest.raises(StoryboardCliError):
                    svc._check_location_grid_readiness(CTX_NO_IMG, sequence_mode=mode_variant)
