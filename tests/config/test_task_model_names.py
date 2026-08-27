"""统一任务配置的模型名契约。

``name`` 仍可承载历史任务标签；面向用户的新界面必须使用
``model_name``，能力或输入模式只能放在 ``variant_label``。
"""

from config.unified_config import ALL_TASK_CONFIGS, TaskTypeId, UnifiedConfigRegistry


def test_all_builtin_tasks_declare_model_name():
    missing = [config.key for config in ALL_TASK_CONFIGS if not config.model_name.strip()]

    assert missing == []


def test_image_binding_model_names_are_pure_and_consistent():
    expected = {
        TaskTypeId.GEMINI_2_5_FLASH_IMAGE: "nano-banana",
        TaskTypeId.GEMINI_3_PRO_IMAGE: "nano-banana Pro",
        TaskTypeId.GEMINI_3_1_FLASH_IMAGE: "nano-banana 2",
        TaskTypeId.SEEDREAM_TEXT_TO_IMAGE: "Seedream 5.0",
        TaskTypeId.SEEDREAM_4_5_IMAGE: "Seedream 4.5",
        TaskTypeId.SEEDREAM_5_0_PRO: "Seedream 5.0 Pro",
        TaskTypeId.GPT_IMAGE_2_EDIT: "GPT Image 2",
    }

    actual = {
        task_id: UnifiedConfigRegistry.get_by_id(task_id).get_model_name()
        for task_id in expected
    }
    assert actual == expected


def test_legacy_and_canonical_model_names_both_resolve():
    gpt_image = UnifiedConfigRegistry.get_by_id(TaskTypeId.GPT_IMAGE_2_EDIT)
    nano_pro = UnifiedConfigRegistry.get_by_id(TaskTypeId.GEMINI_3_PRO_IMAGE)

    assert gpt_image.matches_identifier("GPT Image 2")
    assert gpt_image.matches_identifier("GPT Image 2 图片编辑")
    assert nano_pro.matches_identifier("nano-banana Pro")
    assert nano_pro.matches_identifier("nano-banana-Pro")


def test_frontend_payload_exposes_model_name_and_variant_separately():
    reference_video = UnifiedConfigRegistry.get_by_id(
        TaskTypeId.MINIMAX_H3_REFERENCE_TO_VIDEO
    ).to_frontend_dict()

    assert reference_video["model_name"] == "MiniMax H3"
    assert reference_video["variant_label"] == "多参考"
    # 存量 name 保留，便于旧前端渐进迁移。
    assert reference_video["name"] == "MiniMax H3 参考生视频"
