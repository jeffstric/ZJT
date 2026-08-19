"""
人脸遮盖「黑框还原句」提示词处理（seedance 系 driver 公共逻辑）

提示词基线（智能体 / 用户生成）不包含黑框还原句；还原句的唯一写入方是
ensure_face_mask_hint（volcengine / oversea / kkidc 在素材被本地遮盖时按
RESTORE_HINT 常量原文追加）。本模块对该常量做精确追加 / 移除，保证供应商轮换
（跨实现方重试）下「提示词内容」与「素材状态」始终一致：

- 消费遮盖结果的 driver（volcengine / oversea / kkidc）：
  ensure_face_mask_hint() —— 素材已遮盖且提示词无还原句时追加常量原文
- 使用原始素材的 driver（huimengi，网关 human_review 自动处理人脸）：
  strip_face_mask_hint() —— 精确移除 ensure 写入的还原句（跨实现方重试场景），
  为 ensure 的逆变换，不做模糊匹配
"""
import logging

from config.constant import FaceMaskPromptConstants
from model.ai_tool_pipeline_steps import (
    PipelineStage,
    PipelineStepModel,
    PipelineStepStatus,
    PipelineStepType,
)

logger = logging.getLogger(__name__)


def contains_face_mask_hint(prompt: str) -> bool:
    """提示词中是否已含黑框还原句（精确匹配 ensure 写入的常量原文）"""
    if not prompt:
        return False
    return FaceMaskPromptConstants.RESTORE_HINT in prompt


def has_applied_face_mask(ai_tool) -> bool:
    """
    素材是否已执行本地人脸遮盖

    与 seedance_volcengine_v1_driver._resolve_video_path_with_face_mask 使用同一信号：
    PARAM_PREPARE 阶段存在已完成（COMPLETED 且 result_url 非空）的
    face_mask / image_face_mask 步骤。查询失败时按未遮盖返回 False，不阻塞提交。
    """
    try:
        steps = PipelineStepModel.get_by_ai_tool_and_stage(
            ai_tool.id, PipelineStage.PARAM_PREPARE
        )
    except Exception as e:
        logger.warning(
            f"查询人脸遮盖 pipeline steps 失败，按未遮盖处理: "
            f"ai_tool_id={getattr(ai_tool, 'id', None)}, error={e}"
        )
        return False
    for step in steps or []:
        if (step.step_type in (PipelineStepType.FACE_MASK, PipelineStepType.IMAGE_FACE_MASK)
                and step.status == PipelineStepStatus.COMPLETED
                and step.result_url):
            return True
    return False


def ensure_face_mask_hint(prompt: str, ai_tool) -> str:
    """
    素材已本地遮盖时，确保提示词末尾带黑框还原句（幂等）

    素材未遮盖（含 steps 查询失败回退）或提示词已含还原句时原样返回。
    """
    if not has_applied_face_mask(ai_tool):
        return prompt
    if contains_face_mask_hint(prompt):
        return prompt
    base = (prompt or '').rstrip()
    hint = FaceMaskPromptConstants.RESTORE_HINT
    if not base:
        logger.info(f"素材已人脸遮盖，填充黑框还原句: ai_tool_id={getattr(ai_tool, 'id', None)}")
        return hint
    logger.info(f"素材已人脸遮盖，追加黑框还原句: ai_tool_id={getattr(ai_tool, 'id', None)}")
    if base[-1] in FaceMaskPromptConstants.TERMINATORS_OR_JOINER:
        return base + hint
    return base + FaceMaskPromptConstants.HINT_JOINER + hint


def strip_face_mask_hint(prompt: str) -> str:
    """
    移除 ensure_face_mask_hint 写入的黑框还原句（幂等，无匹配时原样返回）

    供使用原始素材（无本地遮盖）的 driver 调用：画面中没有黑色方框，保留还原句
    会导致模型凭空还原不存在的黑框。ensure 的写入形态只有两种——逗号衔接
    （「...复刻，将人脸...」）或句终符后直接拼接——先移除逗号衔接形态再做裸替换，
    基线即可原样恢复，无悬挂标点。
    """
    hint = FaceMaskPromptConstants.RESTORE_HINT
    if not prompt or hint not in prompt:
        return prompt
    result = prompt.replace(FaceMaskPromptConstants.HINT_JOINER + hint, '').replace(hint, '')
    logger.info(f"素材未本地遮盖，已移除提示词中的黑框还原句: {prompt!r} -> {result!r}")
    return result
