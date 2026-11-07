"""重试候选选择：输入契约不兼容的实现方被跳过（validate_input_compatibility 钩子）。"""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from task.pipeline_drivers import PipelineDriverFactory

TASK_TYPE = 34
FAILED_IMPL_ID = 11  # minimax_h3_runninghub_v1（仅用于标记已尝试，name 查询被 mock）


def _stub_task_config(impl_names):
    """任务配置 stub：implementations 列表 + _get_implementations_info 固定顺序返回"""
    task_config = SimpleNamespace(
        implementations=impl_names,
        driver_name="minimax_h3",
        _get_implementations_info=lambda: [{"name": n} for n in impl_names],
    )
    return task_config


def _stub_impl_config():
    cfg = MagicMock()
    cfg.is_enabled.return_value = True
    return cfg


def _stub_driver(compatible=True, raise_error=False):
    driver = MagicMock()
    if raise_error:
        driver.validate_input_compatibility.side_effect = RuntimeError("boom")
    else:
        driver.validate_input_compatibility.return_value = (
            (True, None) if compatible else (False, "不兼容原因")
        )
    return driver


def _run_select(impl_names, drivers_by_impl, db_returns_none=False):
    """按实现名 → stub 驱动映射跑候选选择，返回候选步骤定义（或 None）"""

    def fake_create(impl_name):
        return drivers_by_impl.get(impl_name)

    def fake_get_impl(impl_name):
        if impl_name in drivers_by_impl:
            return _stub_impl_config()
        return None

    ai_tool = None if db_returns_none else SimpleNamespace(image_path="first.png")
    with patch("task.pipeline_drivers.UnifiedConfigRegistry") as mock_registry, \
         patch("task.pipeline_drivers.get_implementation_name", return_value="failed_impl"), \
         patch("task.pipeline_drivers.AIToolsModel") as mock_ai_tools, \
         patch("model.implementation_attempts.ImplementationAttemptModel") as mock_attempts, \
         patch("task.visual_drivers.VideoDriverFactory") as mock_factory:
        mock_registry.get_by_id.return_value = _stub_task_config(impl_names)
        mock_registry.get_implementation.side_effect = fake_get_impl
        mock_ai_tools.get_by_id.return_value = ai_tool
        mock_attempts.get_attempted_implementations.return_value = {FAILED_IMPL_ID}
        mock_attempts.get_retry_implementation_count.return_value = 0
        mock_factory.create_driver_by_implementation.side_effect = fake_create
        candidate = PipelineDriverFactory.select_before_finish_retry_candidate(
            ai_tool_id=101,
            ai_tool_type=TASK_TYPE,
            failed_implementation=FAILED_IMPL_ID,
            failure_reason="upstream failed",
        )
    return candidate


def test_incompatible_candidate_skipped_next_selected():
    """首尾帧单图任务：autodl first_last 不兼容被跳过，选中后面的兼容候选"""
    drivers = {
        "minimax_h3_turbo_runninghub_v1": _stub_driver(compatible=True),
        "minimax_h3_first_last_autodl_v1": _stub_driver(compatible=False),
    }
    candidate = _run_select(
        ["minimax_h3_turbo_runninghub_v1", "minimax_h3_first_last_autodl_v1"], drivers)
    assert candidate is not None
    assert candidate["params"]["target_implementation"] == "minimax_h3_turbo_runninghub_v1"


def test_all_remaining_incompatible_returns_none():
    """剩余候选全部不兼容：无候选返回 None（任务走直接失败，而非切到必败实现）"""
    drivers = {
        "minimax_h3_turbo_runninghub_v1": _stub_driver(compatible=False),
        "minimax_h3_first_last_autodl_v1": _stub_driver(compatible=False),
    }
    candidate = _run_select(
        ["minimax_h3_turbo_runninghub_v1", "minimax_h3_first_last_autodl_v1"], drivers)
    assert candidate is None


def test_compatible_later_candidate_selected_after_skip():
    """前一候选不兼容时，后面的兼容候选（如 autodl）仍可被选中"""
    drivers = {
        "minimax_h3_turbo_runninghub_v1": _stub_driver(compatible=False),
        "minimax_h3_first_last_autodl_v1": _stub_driver(compatible=True),
    }
    candidate = _run_select(
        ["minimax_h3_turbo_runninghub_v1", "minimax_h3_first_last_autodl_v1"], drivers)
    assert candidate is not None
    assert candidate["params"]["target_implementation"] == "minimax_h3_first_last_autodl_v1"


def test_compat_check_exception_skips_candidate():
    """钩子抛异常按不兼容处理（跳过），不中断候选遍历"""
    drivers = {
        "minimax_h3_turbo_runninghub_v1": _stub_driver(raise_error=True),
        "minimax_h3_first_last_autodl_v1": _stub_driver(compatible=True),
    }
    candidate = _run_select(
        ["minimax_h3_turbo_runninghub_v1", "minimax_h3_first_last_autodl_v1"], drivers)
    assert candidate is not None
    assert candidate["params"]["target_implementation"] == "minimax_h3_first_last_autodl_v1"


def test_ai_tool_load_failure_does_not_block_selection():
    """ai_tool 读取失败（DB 返回 None）时跳过能力校验（保持旧行为），仍按序选候选"""
    drivers = {
        "minimax_h3_turbo_runninghub_v1": _stub_driver(compatible=False),
    }
    candidate = _run_select(
        ["minimax_h3_turbo_runninghub_v1"], drivers, db_returns_none=True)
    # get_by_id 返回 None → 不做兼容校验 → 选中（回退到旧行为）
    assert candidate is not None
    assert candidate["params"]["target_implementation"] == "minimax_h3_turbo_runninghub_v1"
