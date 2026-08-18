"""
Agent 生成工具算力确认门。

在 ExpertAgent 真正提交 generate_* 之前预估算力，并按用户软阈值 /
平台硬阈值决定是否弹出 verification。模型无法绕过此门。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional, Set

from config.constant import (
    AGENT_POWER_CONFIRM_HARD_THRESHOLD,
    AGENT_POWER_CONFIRM_THRESHOLD,
    PREF_WORLD_ID_GLOBAL,
)
from config.unified_config import TaskCategory, UnifiedConfigRegistry

logger = logging.getLogger(__name__)

BILLABLE_GENERATION_TOOLS: Set[str] = {
    "generate_text_to_image",
    "edit_image",
    "generate_text_to_video",
    "image_to_video",
    "generate_digital_human",
    "generate_4grid_character_images",
    "generate_4grid_location_images",
    "generate_4grid_prop_images",
    "generate_character_variant_image",
}

IMAGE_TOOLS = {
    "generate_text_to_image",
    "edit_image",
    "generate_4grid_character_images",
    "generate_4grid_location_images",
    "generate_4grid_prop_images",
    "generate_character_variant_image",
}

VIDEO_TOOLS = {
    "generate_text_to_video",
    "image_to_video",
}

TOOL_LABELS = {
    "generate_text_to_image": "文生图",
    "edit_image": "图片编辑",
    "generate_text_to_video": "文生视频",
    "image_to_video": "图生视频",
    "generate_digital_human": "数字人",
    "generate_4grid_character_images": "角色四宫格",
    "generate_4grid_location_images": "场景四宫格",
    "generate_4grid_prop_images": "道具四宫格",
    "generate_character_variant_image": "角色变体图",
}

OPTION_APPROVE = "确认生成"
OPTION_REJECT = "取消本次生成"
OPTION_SKIP_SESSION = "本次对话不再询问"
POWER_CONFIRM_OPTIONS = [OPTION_APPROVE, OPTION_REJECT, OPTION_SKIP_SESSION]

VERIFICATION_TYPE_POWER_CONFIRM = "computing_power_confirm"


class ConfirmAnswer(str, Enum):
    APPROVE = "approve"
    REJECT = "reject"
    SKIP_SESSION = "skip_session"


@dataclass
class PowerEstimate:
    cost: int = 0
    unknown: bool = False
    unit_cost: int = 0
    count: int = 1
    task_id: Optional[int] = None
    model_name: str = ""
    label: str = ""
    duration: Optional[int] = None
    resolution: Optional[str] = None
    breakdown: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None


@dataclass
class ConfirmDecision:
    need_confirm: bool
    reason: str
    projected_total: int


def get_platform_thresholds() -> tuple[int, int]:
    """返回 (soft_default, hard)。读取失败时回退常量。"""
    try:
        from config.config_util import get_dynamic_config_value
        soft = get_dynamic_config_value(
            "agent", "power_confirm_threshold",
            default=AGENT_POWER_CONFIRM_THRESHOLD,
        )
        hard = get_dynamic_config_value(
            "agent", "power_confirm_hard_threshold",
            default=AGENT_POWER_CONFIRM_HARD_THRESHOLD,
        )
    except Exception as e:
        logger.warning("读取平台算力确认阈值失败，使用常量兜底: %s", e)
        soft = AGENT_POWER_CONFIRM_THRESHOLD
        hard = AGENT_POWER_CONFIRM_HARD_THRESHOLD

    soft = _coerce_non_negative_int(soft, AGENT_POWER_CONFIRM_THRESHOLD)
    hard = _coerce_non_negative_int(hard, AGENT_POWER_CONFIRM_HARD_THRESHOLD)
    if hard < soft:
        hard = soft
    return soft, hard


def resolve_user_soft_threshold(user_id: Optional[str]) -> tuple[int, bool]:
    """
    解析当前用户生效的软阈值。

    Returns:
        (threshold, is_custom)
    """
    platform_soft, _hard = get_platform_thresholds()
    if not user_id:
        return platform_soft, False

    try:
        from model.user_preferences import PREF_TYPE_POWER_CONFIRM, UserPreferencesModel
        pref = UserPreferencesModel.get(
            str(user_id), PREF_WORLD_ID_GLOBAL, PREF_TYPE_POWER_CONFIRM
        )
    except Exception as e:
        logger.warning("读取用户算力确认偏好失败，回退平台默认: user_id=%s err=%s", user_id, e)
        return platform_soft, False

    if not pref or pref.config_value is None:
        return platform_soft, False

    value = pref.get_value()
    threshold = None
    if isinstance(value, dict):
        threshold = value.get("threshold")
    elif isinstance(value, (int, float, str)):
        threshold = value

    parsed = _try_parse_non_negative_int(threshold)
    if parsed is None:
        logger.warning("用户算力确认偏好非法，回退平台默认: user_id=%s value=%r", user_id, value)
        return platform_soft, False
    return parsed, True


def get_effective_thresholds(user_id: Optional[str]) -> tuple[int, int, bool]:
    """返回 (soft, hard, is_custom)。"""
    soft, is_custom = resolve_user_soft_threshold(user_id)
    _platform_soft, hard = get_platform_thresholds()
    return soft, hard, is_custom


def validate_threshold(raw: Any) -> int:
    """校验用户提交的软阈值，非法则抛 ValueError。"""
    parsed = _try_parse_non_negative_int(raw)
    if parsed is None:
        raise ValueError("threshold 必须是大于等于 0 的整数")
    return parsed


def should_confirm(
    cost: int,
    unconfirmed_cost: int,
    skip_session: bool,
    soft_threshold: int,
    hard_threshold: int,
    unknown: bool = False,
) -> ConfirmDecision:
    """判定本次生成是否需要弹出确认。"""
    projected = max(0, int(unconfirmed_cost or 0)) + max(0, int(cost or 0))
    if unknown:
        return ConfirmDecision(True, "unknown", projected)

    limit = hard_threshold if skip_session else soft_threshold
    if cost > limit or projected > limit:
        reason = "over_hard" if skip_session else "over_soft"
        return ConfirmDecision(True, reason, projected)
    return ConfirmDecision(False, "below_threshold", projected)


def parse_confirm_answer(user_input: Optional[str]) -> ConfirmAnswer:
    """解析用户对算力确认的回答。无法识别时视为拒绝（失败关闭）。"""
    text = (user_input or "").strip()
    if not text:
        return ConfirmAnswer.REJECT

    if text == OPTION_APPROVE:
        return ConfirmAnswer.APPROVE
    if text == OPTION_REJECT:
        return ConfirmAnswer.REJECT
    if text == OPTION_SKIP_SESSION:
        return ConfirmAnswer.SKIP_SESSION

    normalized = text.replace(" ", "")
    skip_keys = ("不再询问", "不用问", "无需确认", "不用确认", "直接生成")
    if any(key in normalized for key in skip_keys):
        return ConfirmAnswer.SKIP_SESSION
    reject_keys = ("取消", "不要", "拒绝", "算了", "停止")
    if any(key in normalized for key in reject_keys):
        return ConfirmAnswer.REJECT
    approve_keys = ("确认", "同意", "好的", "可以", "生成")
    if any(key in normalized for key in approve_keys):
        return ConfirmAnswer.APPROVE
    return ConfirmAnswer.REJECT


def build_confirm_description(
    estimate: PowerEstimate,
    balance: Optional[int],
    unconfirmed_cost: int,
    soft_threshold: int,
) -> str:
    lines = [
        f"即将提交：{estimate.label or '生成任务'} × {estimate.count}",
    ]
    detail_parts = []
    if estimate.model_name:
        detail_parts.append(estimate.model_name)
    if estimate.duration:
        detail_parts.append(f"{estimate.duration} 秒")
    if estimate.resolution:
        detail_parts.append(str(estimate.resolution))
    if detail_parts:
        lines.append("模型：" + " / ".join(detail_parts))

    if estimate.unknown:
        lines.append("预计消耗：暂无法精确估算，为保护算力需要您确认后才能提交。")
    else:
        unit_hint = ""
        if estimate.count > 1 and estimate.unit_cost:
            unit_hint = f"（单条 {estimate.unit_cost} × {estimate.count}）"
        lines.append(f"预计消耗：{estimate.cost} 算力{unit_hint}")

    if unconfirmed_cost:
        lines.append(f"本轮已用未确认：{unconfirmed_cost}")
    if balance is not None:
        lines.append(f"当前余额：{balance}")
    lines.append(f"您的自动确认上限：{soft_threshold}")
    lines.append("是否确认生成？")
    lines.append("（可在自定义设置中修改自动确认上限）")
    # 前端用 marked 渲染，单换行会被折叠，用空行保证逐条展示
    return "\n\n".join(lines)


def estimate_tool_computing_power(
    tool_name: str,
    tool_args: Optional[Dict[str, Any]],
    user_id: str,
    world_id: str,
    auth_token: str = "",
) -> PowerEstimate:
    """按与真实扣费相同的规则预估本次工具调用算力。失败则 unknown=True。"""
    args = dict(tool_args or {})
    label = TOOL_LABELS.get(tool_name, tool_name)
    try:
        if tool_name in IMAGE_TOOLS:
            return _estimate_image(tool_name, args, user_id, world_id, label)
        if tool_name in VIDEO_TOOLS:
            return _estimate_video(tool_name, args, user_id, world_id, label)
        if tool_name == "generate_digital_human":
            return _estimate_digital_human(label)
    except Exception as e:
        logger.warning("预估算力失败: tool=%s err=%s", tool_name, e, exc_info=True)
        return PowerEstimate(unknown=True, label=label, error=str(e), count=_safe_count(args))

    return PowerEstimate(unknown=True, label=label, count=_safe_count(args))


def query_user_balance(auth_token: Optional[str]) -> Optional[int]:
    """查询用户余额；失败返回 None，不阻断后续确认。"""
    if not auth_token:
        return None
    try:
        from script_writer_core.mcp_tool import get_user_computing_power
        result = get_user_computing_power(user_id="", world_id="", auth_token=auth_token)
        if isinstance(result, dict) and result.get("success"):
            return int(result.get("computing_power") or 0)
    except Exception as e:
        logger.warning("查询算力余额失败: %s", e)
    return None


def _estimate_image(
    tool_name: str,
    args: Dict[str, Any],
    user_id: str,
    world_id: str,
    label: str,
) -> PowerEstimate:
    from script_writer_core.mcp_tool import (
        _get_lowest_supported_image_size,
        _get_text_to_image_task_id,
        _resolve_image_ratio_and_size_from_prefs,
        _resolve_image_size_for_model,
        get_media_generation_snapshot,
    )
    from utils.computing_power import get_computing_power_for_task

    is_edit = tool_name == "edit_image"
    is_grid = tool_name.startswith("generate_4grid") or bool(args.get("is_grid"))
    mode = "image_edit" if is_edit else "text_to_image"
    locked = get_media_generation_snapshot("image", mode) or {}
    explicit_task = args.get("task_type") or args.get("task_id") or locked.get("task_id")
    if explicit_task not in (None, ""):
        task_id = int(explicit_task)
    else:
        task_id = _get_text_to_image_task_id(user_id, world_id)

    config = UnifiedConfigRegistry.get_by_id(task_id)
    model_name = config.name if config else ""

    image_size = args.get("image_size")
    if is_grid and config and config.supported_sizes:
        image_size = config.supported_sizes[-1]
    else:
        _ratio, image_size, size_source = _resolve_image_ratio_and_size_from_prefs(
            user_id=user_id,
            world_id=world_id,
            aspect_ratio=args.get("aspect_ratio") or "16:9",
            image_size=image_size,
            generation_snapshot=locked or None,
        )
        resolve_source = "preference" if size_source in ("preference", "snapshot") else size_source
        image_size, _err = _resolve_image_size_for_model(config, image_size, resolve_source)
        if not image_size and config:
            image_size = _get_lowest_supported_image_size(config) or config.default_size

    context = {"resolution": image_size} if image_size else None
    unit = int(get_computing_power_for_task(task_id, context=context) or 0)
    count = _safe_count(args)
    cost = unit * count
    unknown = unit <= 0
    return PowerEstimate(
        cost=cost,
        unknown=unknown,
        unit_cost=unit,
        count=count,
        task_id=task_id,
        model_name=model_name,
        label=label,
        resolution=image_size,
        breakdown={"task_id": task_id, "resolution": image_size, "is_grid": is_grid},
    )


def _estimate_video(
    tool_name: str,
    args: Dict[str, Any],
    user_id: str,
    world_id: str,
    label: str,
) -> PowerEstimate:
    from script_writer_core.mcp_tool import (
        _get_image_to_video_task_id,
        _get_text_to_video_task_id,
        _get_video_preferences,
        get_media_generation_snapshot,
    )
    from utils.computing_power import get_computing_power_for_task

    is_t2v = tool_name == "generate_text_to_video"
    snap_key = "text_to_video" if is_t2v else "image_to_video"
    locked = get_media_generation_snapshot("video", snap_key) or {}
    if not locked and not is_t2v:
        locked = get_media_generation_snapshot("video", "reference_to_video") or {}

    explicit_task = args.get("task_type") or args.get("task_id") or locked.get("task_id")
    task_id = None
    if explicit_task not in (None, ""):
        try:
            task_id = int(explicit_task)
        except (TypeError, ValueError):
            task_id = None
    if task_id is None:
        getter = _get_text_to_video_task_id if is_t2v else _get_image_to_video_task_id
        task_id = getter(user_id, world_id)
    if task_id is None:
        category = TaskCategory.TEXT_TO_VIDEO if is_t2v else TaskCategory.IMAGE_TO_VIDEO
        configs = [
            c for c in UnifiedConfigRegistry.get_by_category(category)
            if c.enabled and not c.hidden
        ]
        task_id = configs[0].id if configs else None

    if not task_id:
        return PowerEstimate(unknown=True, label=label, count=_safe_count(args), error="未找到视频模型")

    config = UnifiedConfigRegistry.get_by_id(task_id)
    model_name = config.name if config else ""
    user_prefs = {}
    try:
        user_prefs = _get_video_preferences(user_id, world_id) or {}
    except Exception:
        user_prefs = {}

    duration = _resolve_estimate_duration(args, locked, user_prefs, config)
    resolution = (
        args.get("resolution")
        or locked.get("resolution")
        or user_prefs.get("resolution")
    )
    if resolution and str(resolution).lower() == "auto":
        resolution = None

    context = {"resolution": resolution} if resolution else None
    image_mode = args.get("image_mode") or locked.get("image_mode") or user_prefs.get("image_mode")
    if image_mode:
        context = dict(context or {})
        context["image_mode"] = image_mode

    uid = None
    try:
        uid = int(user_id) if user_id else None
    except (TypeError, ValueError):
        uid = None
    unit = int(get_computing_power_for_task(
        task_id, duration=duration, user_id=uid, context=context
    ) or 0)
    count = _safe_count(args)
    cost = unit * count
    return PowerEstimate(
        cost=cost,
        unknown=unit <= 0,
        unit_cost=unit,
        count=count,
        task_id=task_id,
        model_name=model_name,
        label=label,
        duration=duration,
        resolution=resolution,
        breakdown={
            "task_id": task_id,
            "duration": duration,
            "resolution": resolution,
            "image_mode": image_mode,
        },
    )


def _estimate_digital_human(label: str) -> PowerEstimate:
    configs = UnifiedConfigRegistry.get_by_category(TaskCategory.DIGITAL_HUMAN)
    enabled = [c for c in configs if c.enabled and not c.hidden]
    if not enabled:
        return PowerEstimate(unknown=True, label=label, error="未找到数字人模型")
    config = enabled[0]
    unit = int(config.get_computing_power() or 0)
    return PowerEstimate(
        cost=unit,
        unknown=unit <= 0,
        unit_cost=unit,
        count=1,
        task_id=config.id,
        model_name=config.name,
        label=label,
        breakdown={"task_id": config.id},
    )


def _resolve_estimate_duration(
    args: Dict[str, Any],
    locked: Dict[str, Any],
    user_prefs: Dict[str, Any],
    config: Any,
) -> Optional[int]:
    raw = (
        args.get("duration_seconds")
        or locked.get("duration_seconds")
        or locked.get("duration")
        or user_prefs.get("duration")
    )
    supported = []
    if config and getattr(config, "supported_durations", None):
        try:
            supported = [int(d) for d in config.supported_durations]
        except (TypeError, ValueError):
            supported = []

    if raw is not None and str(raw).lower() == "auto":
        return max(supported) if supported else None

    duration = None
    if raw is not None and str(raw).isdigit():
        duration = int(raw)
    elif isinstance(raw, (int, float)):
        duration = int(raw)

    if duration is None:
        if config and getattr(config, "default_duration", None):
            try:
                duration = int(config.default_duration)
            except (TypeError, ValueError):
                duration = supported[0] if supported else 5
        else:
            duration = supported[0] if supported else 5

    if supported and duration not in supported:
        duration = min(supported, key=lambda d: abs(d - duration))
    return duration


def _safe_count(args: Dict[str, Any]) -> int:
    try:
        count = int(args.get("count") or 1)
    except (TypeError, ValueError):
        count = 1
    return max(1, count)


def _try_parse_non_negative_int(raw: Any) -> Optional[int]:
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, float) and not raw.is_integer():
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    if value < 0:
        return None
    return value


def _coerce_non_negative_int(raw: Any, default: int) -> int:
    parsed = _try_parse_non_negative_int(raw)
    return default if parsed is None else parsed
