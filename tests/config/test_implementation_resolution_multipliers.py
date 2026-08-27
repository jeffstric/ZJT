"""同一模型下按实现方覆盖分辨率算力倍率。"""

from unittest.mock import patch

from config.unified_config import (
    PowerModifier,
    TaskCategory,
    TaskTypeId,
    UnifiedConfigRegistry,
    UnifiedTaskConfig,
)
from utils.computing_power import (
    default_resolution_multipliers,
    effective_resolution_multipliers,
    resolution_options_for_driver_key,
    sort_resolution_options,
)


def test_sort_resolution_options_puts_1k_first():
    assert sort_resolution_options(["2K", "3K", "4K", "1K"]) == ["1K", "2K", "3K", "4K"]
    assert sort_resolution_options(["1080P", "480P", "720P"]) == ["480P", "720P", "1080P"]


def test_gemini_flash_resolution_options_include_supported_sizes():
    task = UnifiedConfigRegistry.get_by_id(TaskTypeId.GEMINI_3_1_FLASH_IMAGE)
    options = resolution_options_for_driver_key(task.driver_name)
    assert "1K" in options
    assert "2K" in options
    assert "4K" in options
    assert options.index("1K") < options.index("2K") < options.index("4K")


def test_default_resolution_multipliers_fill_missing_with_one():
    task = UnifiedConfigRegistry.get_by_id(TaskTypeId.GEMINI_3_1_FLASH_IMAGE)
    defaults = default_resolution_multipliers(task.driver_name)
    assert defaults["1K"] == 1.0
    assert defaults["2K"] == 1.0


def test_effective_resolution_multipliers_overlay_db_values():
    task = UnifiedConfigRegistry.get_by_id(TaskTypeId.GEMINI_3_1_FLASH_IMAGE)
    with patch(
        "model.implementation_power.ImplementationPowerModel.get_modifiers",
        return_value={"resolution": {"2K": 1.5, "4K": 2.0, "_default": 1.0}},
    ):
        payload = effective_resolution_multipliers(
            task.driver_name, "gemini_image_preview_site0_v1"
        )
    assert payload["resolution_multipliers"]["1K"] == 1.0
    assert payload["resolution_multipliers"]["2K"] == 1.5
    assert payload["resolution_multipliers"]["4K"] == 2.0


def test_get_computing_power_uses_implementation_resolution_overlay():
    task = UnifiedConfigRegistry.get_by_id(TaskTypeId.GEMINI_3_1_FLASH_IMAGE)
    with patch(
        "model.implementation_power.ImplementationPowerModel.get_modifiers",
        return_value={"resolution": {"2K": 2.0, "_default": 1.0}},
    ):
        base = task.get_computing_power(implementation="gemini_duomi_v1")
        overlay = task.get_computing_power(
            implementation="gemini_duomi_v1",
            context={"resolution": "2K"},
        )
    assert overlay == int(__import__("math").ceil(base * 2.0))


def test_get_computing_power_keeps_task_modifiers_without_implementation():
    task = UnifiedTaskConfig(
        id=91001,
        key="test-res-task",
        name="test",
        category=TaskCategory.IMAGE_EDIT,
        provider="test",
        driver_name="test_driver",
        computing_power=10,
        power_modifiers=[
            PowerModifier(attribute="resolution", values={"2K": 1.5}, default=1.0)
        ],
    )
    assert task.get_computing_power(context={"resolution": "2K"}) == 15


def test_set_modifiers_keeps_fixed_power():
    from model.implementation_power import ImplementationPowerModel

    stored = {"power_config": '{"fixed": 3}'}
    captured = {}

    def fake_query(sql, params=None, fetch_one=False, fetch_all=False):
        if fetch_one:
            return stored
        return []

    def fake_update(sql, params):
        captured["json"] = params[0]
        return 1

    with patch("model.implementation_power.execute_query", fake_query), patch(
        "model.implementation_power.execute_update", fake_update
    ), patch("model.implementation_power.execute_insert"):
        ImplementationPowerModel.set_modifiers(
            "gemini_duomi_v1",
            "gemini_3_1_flash_image_edit",
            "resolution",
            {"2K": 1.5},
            default=1.0,
        )
    import json

    payload = json.loads(captured["json"])
    assert payload["fixed"] == 3
    assert payload["modifiers"]["resolution"]["2K"] == 1.5
    assert payload["modifiers"]["resolution"]["_default"] == 1.0
