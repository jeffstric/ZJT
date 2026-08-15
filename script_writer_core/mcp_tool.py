"""
MCP JSON生成工具集
提供标准化的角色、世界、地点、道具JSON文件创建功能，作为MCP工具供AI模型调用
"""

import json
import os
import re
import logging
import httpx
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Dict, Any, Optional, List
from datetime import datetime
from script_writer_core.file_manager import FileManager
from script_writer_core.skill_loader import SkillLoader
from script_writer_core.cron_task_manager import get_task_manager
from script_writer_core.constant import ItemType
from config.config_util import get_config
from config.constant import FilePathConstants, StoryType, GridConfig

# 模块级日志
logger = logging.getLogger(__name__)

# 设置技能调用日志
def setup_skill_logger():
    """设置技能调用专用日志记录器"""
    logger = logging.getLogger('skill_calls')
    if not logger.handlers:
        handler = logging.FileHandler('api_interaction.log', encoding='utf-8')
        formatter = logging.Formatter('%(asctime)s - %(message)s')
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    return logger

def log_skill_interaction(message: str, data: Any = None):
    """记录技能调用日志到文件"""
    logger = setup_skill_logger()
    if data:
        logger.info(f"{message} - Data: {json.dumps(data, ensure_ascii=False, indent=2)}")
    else:
        logger.info(message)

# ⚠️ 全局可变单例：延迟初始化，由 get_skill_loader() / get_file_manager() 按需创建
# _get_text_to_image_model_id_func 和 _get_image_preferences_func 由 script_writer_api.py 启动时注入
# 初始化顺序：script_writer_api.py → 注入函数引用 → mcp_tool 函数才能正常工作
_skill_loader = None
_file_manager = None
_get_text_to_image_model_id_func = None
_get_image_preferences_func = None
# 获取用户视频偏好的函数引用（由 script_writer_api.py 设置）
_get_video_preferences_func = None
_video_preferences_override = ContextVar("video_preferences_override", default=None)
_image_generation_snapshot_override = ContextVar(
    "image_generation_snapshot_override", default=None
)
_media_generation_snapshots_override = ContextVar(
    "media_generation_snapshots_override", default=None
)
# 获取视频模型 task_id 的函数引用（由 script_writer_api.py 设置）
_get_text_to_video_model_id_func = None
_get_image_to_video_model_id_func = None

# 默认生图模型 task_id (nano-banana-Pro)
DEFAULT_TEXT_TO_IMAGE_TASK_ID = 7


def set_text_to_image_model_getter(func):
    """设置获取生图模型 task_id 的函数"""
    global _get_text_to_image_model_id_func
    _get_text_to_image_model_id_func = func


def set_image_preferences_getter(func):
    """设置获取用户图片偏好的函数"""
    global _get_image_preferences_func
    _get_image_preferences_func = func


def set_video_preferences_getter(func):
    """设置获取用户视频偏好的函数"""
    global _get_video_preferences_func
    _get_video_preferences_func = func


@contextmanager
def scoped_video_preferences(preferences: Optional[Dict[str, Any]]):
    """Temporarily override video preferences for the current task execution context."""
    token = _video_preferences_override.set(
        dict(preferences) if preferences is not None else None
    )
    try:
        yield
    finally:
        _video_preferences_override.reset(token)


@contextmanager
def scoped_image_generation_snapshot(snapshot: Optional[Dict[str, Any]]):
    """在当前工具调用及其内部子调用中锁定图片模型快照。"""
    token = _image_generation_snapshot_override.set(
        dict(snapshot) if snapshot is not None else None
    )
    try:
        yield
    finally:
        _image_generation_snapshot_override.reset(token)


@contextmanager
def scoped_media_generation_snapshots(snapshots: Optional[Dict[str, Dict[str, Any]]]):
    """为一个 Agent 任务锁定多个媒体模式的模型快照。"""
    token = _media_generation_snapshots_override.set(
        dict(snapshots) if snapshots is not None else None
    )
    try:
        yield
    finally:
        _media_generation_snapshots_override.reset(token)


def get_media_generation_snapshot(media_type: str, mode: str) -> Optional[Dict[str, Any]]:
    snapshots = _media_generation_snapshots_override.get() or {}
    snapshot = snapshots.get(f"{media_type}.{mode}")
    return dict(snapshot) if isinstance(snapshot, dict) else None


def get_media_generation_snapshots() -> Dict[str, Dict[str, Any]]:
    snapshots = _media_generation_snapshots_override.get() or {}
    return {
        key: dict(value)
        for key, value in snapshots.items()
        if isinstance(value, dict)
    }


def set_text_to_video_model_getter(func):
    """设置获取文生视频模型 task_id 的函数"""
    global _get_text_to_video_model_id_func
    _get_text_to_video_model_id_func = func


def set_image_to_video_model_getter(func):
    """设置获取图生视频模型 task_id 的函数"""
    global _get_image_to_video_model_id_func
    _get_image_to_video_model_id_func = func


def _get_video_preferences(user_id: str, world_id: str) -> Dict[str, str]:
    """获取用户的视频偏好（比例、时长），默认返回空字典"""
    scoped = _video_preferences_override.get()
    if scoped is not None:
        return dict(scoped)
    if _get_video_preferences_func:
        return _get_video_preferences_func(user_id, world_id)
    return {}


def _get_text_to_image_task_id(user_id: str, world_id: str) -> int:
    """获取生图模型的 task_id，默认返回 7 (nano-banana-Pro)"""
    snapshot = _image_generation_snapshot_override.get()
    if snapshot and snapshot.get('task_id') not in (None, ''):
        return int(snapshot['task_id'])
    if _get_text_to_image_model_id_func:
        return _get_text_to_image_model_id_func(user_id, world_id)
    return DEFAULT_TEXT_TO_IMAGE_TASK_ID


def _get_text_to_video_task_id(user_id: str, world_id: str) -> Optional[int]:
    """获取文生视频模型的 task_id，默认返回 None（由调用方回退到 configs[0]）"""
    if _get_text_to_video_model_id_func:
        return _get_text_to_video_model_id_func(user_id, world_id)
    return None


def _get_image_to_video_task_id(user_id: str, world_id: str) -> Optional[int]:
    """获取图生视频模型的 task_id，默认返回 None（由调用方回退到 configs[0]）"""
    if _get_image_to_video_model_id_func:
        return _get_image_to_video_model_id_func(user_id, world_id)
    return None


def _get_image_preferences(user_id: str, world_id: str) -> Dict[str, str]:
    """获取用户的图片偏好（比例、分辨率），默认返回空字典"""
    if _get_image_preferences_func:
        return _get_image_preferences_func(user_id, world_id)
    return {}


def _get_model_name_by_task_id(task_id: int) -> str:
    """从统一配置获取模型名称"""
    from config.unified_config import UnifiedConfigRegistry
    config = UnifiedConfigRegistry.get_by_id(task_id)
    return config.name if config else "unknown"


def _get_lowest_supported_image_size(config) -> Optional[str]:
    """获取当前模型支持的最低输出分辨率。"""
    if not config:
        return None
    supported_sizes = getattr(config, 'supported_sizes', None) or []
    if supported_sizes:
        return supported_sizes[0]
    return getattr(config, 'default_size', None)


def _non_auto_pref(value: Any) -> Optional[str]:
    """返回非空且非 auto 的偏好字符串，否则 None。"""
    if value in (None, ''):
        return None
    text = str(value).strip()
    if not text or text.lower() == 'auto':
        return None
    return text


def _resolve_image_ratio_and_size_from_prefs(
    *,
    user_id: str,
    world_id: str,
    aspect_ratio: str,
    image_size: Optional[str],
    generation_snapshot: Optional[Dict[str, Any]] = None,
    apply_user_prefs: bool = True,
) -> tuple:
    """
    解析图片宽高比与分辨率。

    优先级（实现工具 schema「已由系统注入」语义）：
    1. 任务级 generation_snapshot.ratio / resolution（故事板 workflow_ratio 等）
    2. 世界级 image_preferences（营销页齿轮等）
    3. 调用方传入的 aspect_ratio / image_size

    返回 (aspect_ratio, image_size, image_size_source)。
    image_size_source: argument | snapshot | preference | default
    """
    image_size_source = "argument" if image_size else "default"
    snap = dict(generation_snapshot or {})
    snap_ratio = _non_auto_pref(snap.get('ratio'))
    snap_resolution = _non_auto_pref(snap.get('resolution'))

    if snap_ratio:
        aspect_ratio = snap_ratio
    elif apply_user_prefs:
        user_prefs = _get_image_preferences(user_id, world_id) or {}
        pref_ratio = _non_auto_pref(user_prefs.get('ratio'))
        if pref_ratio:
            aspect_ratio = pref_ratio

    if image_size:
        pass  # 显式参数保留，source 已为 argument
    elif snap_resolution:
        image_size = snap_resolution
        image_size_source = "snapshot"
    elif apply_user_prefs:
        user_prefs = _get_image_preferences(user_id, world_id) or {}
        pref_resolution = _non_auto_pref(user_prefs.get('resolution'))
        if pref_resolution:
            image_size = pref_resolution
            image_size_source = "preference"

    return aspect_ratio, image_size, image_size_source


def _resolve_image_size_for_model(config, image_size: Optional[str], image_size_source: str = "argument"):
    """
    解析图片输出分辨率。

    - auto/未指定：使用当前模型支持的最低输出分辨率
    - 旧偏好不再被当前模型支持：忽略旧偏好并使用最低输出分辨率
    - 显式参数不被支持：返回错误，避免悄悄违背调用者指令
    """
    default_size = _get_lowest_supported_image_size(config)
    if not image_size or str(image_size).lower() == 'auto':
        return default_size, None

    if config and getattr(config, 'supported_sizes', None):
        supported_lower = [str(s).lower() for s in config.supported_sizes]
        if str(image_size).lower() not in supported_lower:
            if image_size_source == "preference":
                logger.warning(
                    f"忽略不兼容的图片分辨率偏好: {image_size}, "
                    f"当前模型支持: {config.supported_sizes}, 使用: {default_size}"
                )
                return default_size, None
            return None, f'不支持的图片尺寸: {image_size}，当前模型支持: {config.supported_sizes}'

    return image_size, None


def _size_to_numeric(size: str) -> int:
    """把 '1K'/'2K'/'4K'/'3K' 等档位转为数值（去掉 K 后取 int），非法值返回 0。"""
    try:
        return int(str(size).strip().rstrip('Kk'))
    except (ValueError, TypeError):
        return 0


def _pick_grid_image_size(config, target_size: Optional[str]) -> Optional[str]:
    """
    根据模型 supported_sizes 选出最接近且不超过 target_size 的分辨率档位。

    - target_size 在 supported_sizes 中：直接用
    - 不在但有不超过它的档位：取其中最大者（如 target=4K，模型支持 1K/2K/3K → 选 3K）
    - 所有支持值都超过 target（如 target=2K，模型支持 3K/4K）：取最小支持值
    - config 无 supported_sizes：原样返回 target_size（交给端点/driver 处理）
    """
    if not target_size:
        return _get_lowest_supported_image_size(config)
    if not config:
        return target_size
    supported = getattr(config, 'supported_sizes', None) or []
    if not supported:
        return target_size
    if target_size in supported:
        return target_size
    target_num = _size_to_numeric(target_size)
    if target_num <= 0:
        return supported[0]
    # 不超过目标的最大档位
    not_exceed = [s for s in supported if _size_to_numeric(s) > 0 and _size_to_numeric(s) <= target_num]
    if not_exceed:
        return max(not_exceed, key=_size_to_numeric)
    # 所有支持值都超过目标 → 取最小支持值
    return min(supported, key=_size_to_numeric)


def get_text_to_image_model_info(user_id: str, world_id: str, auth_token: str) -> Dict[str, Any]:
    """
    获取当前用户/世界选中的生图模型信息 - MCP工具函数

    返回模型名称、算力、支持尺寸、是否支持宫格等信息，供 Agent 在生成前了解成本和能力。

    Args:
        user_id: 用户ID（必填）
        world_id: 世界ID（必填）
        auth_token: 认证令牌（必填）

    Returns:
        dict: 模型信息，包含 task_id、name、computing_power、supported_sizes、supports_grid_image 等
    """
    try:
        locked_image_snapshots = {
            key: value
            for key, value in get_media_generation_snapshots().items()
            if key.startswith('image.')
        }
        locked_default = locked_image_snapshots.get('image.text_to_image')
        task_id = int(locked_default['task_id']) if locked_default else _get_text_to_image_task_id(user_id, world_id)
        from config.unified_config import UnifiedConfigRegistry
        config = UnifiedConfigRegistry.get_by_id(task_id)
        if not config:
            return {'success': False, 'error': f'未找到模型配置: task_id={task_id}'}

        max_size = config.supported_sizes[-1] if config.supported_sizes else None
        default_size = config.default_size or max_size

        # 计算不同尺寸的单张算力
        from utils.computing_power import get_computing_power_for_task
        power_default = get_computing_power_for_task(task_id, context={'resolution': default_size} if default_size else None)
        power_max = get_computing_power_for_task(task_id, context={'resolution': max_size} if max_size else None)

        # 获取第一个顺位实现方的 agent_hint
        driver_hint = None
        try:
            from task.visual_drivers.driver_factory import VideoDriverFactory
            uid = int(user_id) if user_id else None
            hint_info = VideoDriverFactory.get_agent_hint_for_task(task_id, uid)
            if hint_info:
                driver_hint = hint_info['hint']
        except Exception:
            pass

        result = {
            'success': True,
            'task_id': task_id,
            'name': config.name,
            'computing_power': config.computing_power,
            'supported_sizes': config.supported_sizes,
            'supported_ratios': config.supported_ratios,
            'supports_grid_image': config.supports_grid_image,
            'default_size': default_size,
            'max_size': max_size,
            'cost_per_image_default_size': power_default,
            'cost_per_image_max_size': power_max,
        }
        if driver_hint:
            result['driver_hint'] = driver_hint
        if locked_image_snapshots:
            result['locked_models'] = {
                key: {
                    'task_id': value.get('task_id'),
                    'model_name': value.get('model_name'),
                    'mode': value.get('mode'),
                }
                for key, value in locked_image_snapshots.items()
            }

        return result
    except Exception as e:
        return {'success': False, 'error': f'获取模型信息失败: {str(e)}'}


def get_user_computing_power(user_id: str, world_id: str, auth_token: str) -> Dict[str, Any]:
    """
    查询用户剩余算力余额 - MCP工具函数

    Args:
        user_id: 用户ID（必填，用于格式兼容，实际鉴权使用 auth_token）
        world_id: 世界ID（必填，当前未使用，为兼容ToolExecutor调用签名）
        auth_token: 认证令牌（必填）

    Returns:
        dict: 包含 computing_power（剩余算力）的结果
    """
    try:
        if not auth_token:
            return {'success': False, 'error': '认证令牌不能为空'}

        from perseids_server.client import make_perseids_request
        success, message, data = make_perseids_request(
            endpoint='user/check_computing_power',
            method='GET',
            headers={'Authorization': f'Bearer {auth_token}'}
        )
        if not success:
            return {'success': False, 'error': message}

        return {
            'success': True,
            'computing_power': data.get('computing_power', 0),
            'message': f'当前剩余算力: {data.get("computing_power", 0)}'
        }
    except Exception as e:
        return {'success': False, 'error': f'查询算力失败: {str(e)}'}


def list_video_models(user_id: str, world_id: str, auth_token: str,
                      category: str = "image_to_video") -> Dict[str, Any]:
    """
    查询当前可用的视频模型列表 - MCP工具函数

    返回所有 enabled 且非 hidden 的视频模型（按 sort_order 升序），
    供 Agent 在调用 image_to_video / generate_text_to_video 前选取 task_id。
    视频生成工具要求显式传入 task_type（模型 task_id），不再隐式回退。

    Args:
        user_id: 用户ID（必填，签名兼容）
        world_id: 世界ID（必填，签名兼容）
        auth_token: 认证令牌（必填，签名兼容）
        category: 模型类别（可选，默认 image_to_video）：
                  image_to_video（图生视频）或 text_to_video（文生视频）

    Returns:
        dict: {success, category, models: [{task_id, name, short_key, computing_power,
              supported_durations, default_duration, supported_ratios,
              supported_image_modes, supports_last_frame}]}
    """
    try:
        from config.unified_config import UnifiedConfigRegistry, TaskCategory

        # 归一化 category：只接受两类视频，非法值统一回退图生视频
        if str(category).strip().lower() == "text_to_video":
            cat = TaskCategory.TEXT_TO_VIDEO
            cat_label = "text_to_video"
        else:
            cat = TaskCategory.IMAGE_TO_VIDEO
            cat_label = "image_to_video"

        locked_video_snapshots = {
            key: value
            for key, value in get_media_generation_snapshots().items()
            if key.startswith('video.')
            and (
                (cat_label == 'text_to_video' and key == 'video.text_to_video')
                or (cat_label == 'image_to_video' and key != 'video.text_to_video')
            )
        }
        if locked_video_snapshots:
            locked_ids = {
                int(value['task_id'])
                for value in locked_video_snapshots.values()
                if value.get('task_id') not in (None, '')
            }
            configs = [
                config
                for task_id in locked_ids
                for config in [UnifiedConfigRegistry.get_by_id(task_id)]
                if config is not None
            ]
        else:
            configs = UnifiedConfigRegistry.get_by_category(cat)
        # 与 /api/storyboard/models 同口径：sort_order 升序、过滤 disabled/hidden
        configs = sorted(
            configs,
            key=lambda c: (
                float(getattr(c, 'sort_order', 999999) or 999999),
                int(getattr(c, 'id', 0) or 0),
            ),
        )

        models = []
        for c in configs:
            if not c.enabled or (c.hidden and not locked_video_snapshots):
                continue
            item = {
                'task_id': c.id,
                'name': c.name,
                'short_key': getattr(c, 'short_key', None) or '',
                'computing_power': c.computing_power,
                'supported_durations': c.supported_durations or [],
                'default_duration': c.default_duration,
                'supported_ratios': c.supported_ratios or [],
            }
            # 图生视频额外暴露图模式能力，供 Agent 判断是否支持首尾帧/全能参考
            if cat == TaskCategory.IMAGE_TO_VIDEO:
                modes = list(getattr(c, 'supported_image_modes', None) or ['first_last_frame'])
                item['supported_image_modes'] = [str(m) for m in modes]
                item['supports_last_frame'] = bool(getattr(c, 'supports_last_frame', True))
            models.append(item)

        if not models:
            return {
                'success': False,
                'error': f'当前没有可用的 {cat_label} 模型（全部已禁用或隐藏）',
                'category': cat_label,
                'models': [],
            }

        return {
            'success': True,
            'category': cat_label,
            'models': models,
            'message': (
                f'当前任务已锁定 {len(models)} 个 {cat_label} 模式模型，执行器会强制使用对应快照。'
                if locked_video_snapshots
                else f'共 {len(models)} 个可用 {cat_label} 模型。'
            ),
        }
    except Exception as e:
        return {'success': False, 'error': f'查询视频模型列表失败: {str(e)}'}


def list_llm_models(user_id: str, world_id: str, auth_token: str) -> Dict[str, Any]:
    """
    查询当前可用的大语言模型（LLM）列表及费用 - MCP工具函数

    返回所有已配置（vendor API key 已填）且启用的 LLM 模型，含每档 token 的算力
    消耗率（threshold）和换算后的单价（元/百万 token）。供 Agent / CLI 调用方在
    调用 split-from-script 等需要 LLM 的命令前，查询模型并选取合适的 model_id。

    费用模型：vendor_model 表的三档 threshold（input/output/cache_read），
    含义为「多少个该类 token 消耗 1 点算力」。换算单价公式：
        单价(元/百万token) = 0.04 × 1_000_000 / threshold
    （1 算力 = 0.04 元）。threshold 越小 → 单价越高。

    Args:
        user_id: 用户ID（必填，签名兼容）
        world_id: 世界ID（必填，签名兼容）
        auth_token: 认证令牌（必填，签名兼容）

    Returns:
        dict: {success, models: [{model_id, name, vendor_id, vendor_name,
              context_window, supports_thinking, supports_vl,
              pricing: {input_threshold, output_threshold, cache_read_threshold,
                        input_price_per_million, output_price_per_million,
                        cache_read_price_per_million}}]}
    """
    try:
        from config.config_util import get_dynamic_config_value
        from model.model import ModelModel
        from model.vendor import VendorDAO
        from model.vendor_model import VendorModelModel

        # ---- 复用 get_available_models 的过滤逻辑（已配置 vendor + enabled + supports_tools）----
        vendors = {v.id: v for v in VendorDAO.get_all()}
        all_vendor_models = VendorModelModel.get_all()

        def _is_vendor_configured(vendor_name: str) -> bool:
            # 与 llm/llm_client_factory.py:is_vendor_configured 同口径
            vendor_config_map = {
                'google': ('llm', 'google', 'api_key'),
                'claude': ('llm', 'claude', 'api_key'),
                'aliyun': ('llm', 'qwen', 'api_key'),
                'ollama': ('llm', 'ollama', 'enabled'),
                'volcengine': ('volcengine', 'api_key'),
                'zjt_api': ('api_aggregator', 'site_0', 'api_key'),
                'deepseek': ('llm', 'deepseek', 'api_key'),
            }
            if vendor_name not in vendor_config_map:
                return True
            value = get_dynamic_config_value(*vendor_config_map[vendor_name], default='')
            if isinstance(value, bool):
                return value
            return bool(value and len(str(value).strip()) > 0)

        def _threshold_to_price(threshold):
            """threshold(多少token=1算力) → 单价(元/百万token)。None → None。"""
            if not threshold:
                return None
            try:
                return round(0.04 * 1_000_000 / float(threshold), 2)
            except (TypeError, ValueError, ZeroDivisionError):
                return None

        models = []
        added_pairs = set()
        for vm in all_vendor_models:
            model_id = vm.model_id
            vendor_id = vm.vendor_id
            vendor = vendors.get(vendor_id)
            vendor_name = vendor.vendor_name if vendor else 'unknown'

            if not _is_vendor_configured(vendor_name):
                continue
            if (model_id, vendor_id) in added_pairs:
                continue
            added_pairs.add((model_id, vendor_id))

            local_model = ModelModel.get_by_id(model_id)
            if not local_model or not local_model.supports_tools or not local_model.enabled:
                continue

            # 查计费档位：补全三档 threshold（get_available_models 只返回 input）
            # 按当前北京时间时段取价，配了峰谷则反映当前价
            in_th = out_th = cache_th = None
            try:
                from utils.billing_period import get_billing_period
                billing = VendorModelModel.get_by_vendor_model_for_billing(
                    vendor_id=vendor_id, model_id=model_id, raw_input_token=0,
                    time_period=get_billing_period(None),
                )
                if billing:
                    in_th = billing.input_token_threshold
                    out_th = billing.output_token_threshold
                    cache_th = billing.cache_read_threshold
            except Exception as vm_err:
                logger.warning(f"[list_llm_models] 获取 model_id={model_id} 计费失败: {vm_err}")

            models.append({
                'model_id': model_id,
                'name': local_model.model_name,
                'vendor_id': vendor_id,
                'vendor_name': vendor_name,
                'context_window': local_model.context_window,
                'supports_thinking': local_model.supports_thinking == 1,
                'supports_vl': local_model.supports_vl == 1,
                'pricing': {
                    'input_threshold': in_th,
                    'output_threshold': out_th,
                    'cache_read_threshold': cache_th,
                    # 换算单价（元/百万token），方便用户直接对比
                    'input_price_per_million': _threshold_to_price(in_th),
                    'output_price_per_million': _threshold_to_price(out_th),
                    'cache_read_price_per_million': _threshold_to_price(cache_th),
                },
            })

        if not models:
            return {
                'success': False,
                'error': '当前没有可用的 LLM 模型（vendor 未配置或模型未启用）',
                'models': [],
            }

        return {
            'success': True,
            'models': models,
            'message': (
                f'共 {len(models)} 个可用 LLM 模型。调用 split-from-script 时，'
                f'请将所选模型的 name 作为 model、model_id 作为 model_id、'
                f'vendor_id 作为 vendor_id 传入（pricing 用于对比费用）。'
            ),
        }
    except Exception as e:
        return {'success': False, 'error': f'查询 LLM 模型列表失败: {str(e)}'}


def fetch_image_as_base64(user_id: str, world_id: str, auth_token: str,
                          image_url: str, max_size_mb: float = 2.0) -> Dict[str, Any]:
    """
    读取本地图片并转为 base64 data URL - MCP工具函数

    供图片理解专家调用，当预加载的图片失败时，通过此工具重新获取图片 base64 数据。
    仅支持读取本地文件，不支持下载外部图片。

    支持的 image_url 格式：
    - 相对路径：以 / 开头，如 /upload/marketing/pic/xxx.png
    - 完整 URL：http/https，域名需匹配 server.host 配置，映射为本地文件

    Args:
        user_id: 用户ID（必填）
        world_id: 世界ID（必填）
        auth_token: 认证令牌（必填）
        image_url: 图片路径（必填），支持相对路径和匹配 server.host 的 URL
        max_size_mb: 最大文件大小 MB（可选，默认 2.0）

    Returns:
        dict: success=True 时包含 base64_data_url 和 size_kb；success=False 时包含 error
    """
    try:
        if not image_url or not isinstance(image_url, str):
            return {'success': False, 'error': 'image_url 参数不能为空且必须是字符串'}

        import os
        from urllib.parse import urlparse

        local_path = None

        if image_url.startswith('/'):
            # 相对路径：直接拼接项目根目录
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            local_path = os.path.join(project_root, image_url.lstrip('/'))
            if not os.path.exists(local_path):
                return {'success': False, 'error': f'本地文件不存在: {local_path}'}
            logger.info(f"[fetch_image_as_base64] 相对路径映射到本地文件: {local_path}")

        elif image_url.startswith(('http://', 'https://')):
            # 完整 URL：尝试映射到本地文件
            from utils.image_upload_utils import try_map_url_to_local_file
            config = get_config()
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            local_path = try_map_url_to_local_file(image_url, config, project_root)
            if not local_path:
                return {
                    'success': False,
                    'error': '不允许下载外部图片，仅支持本地图片。请使用相对路径（如 /upload/xxx.png）或匹配服务域名的 URL'
                }
            logger.info(f"[fetch_image_as_base64] URL 映射到本地文件: {local_path}")

        else:
            return {'success': False, 'error': f'不支持的图片路径格式: {image_url}，请使用相对路径（/开头）或 http/https URL'}

        # 从本地文件压缩并转 base64
        from utils.image_compressor import compress_local_image_to_base64
        # max_pixels=250_000 控制像素数以限制 token 消耗（与 expert_agent.py 一致）
        success, data_url, error = compress_local_image_to_base64(
            local_path, max_size_mb=max_size_mb, max_pixels=250_000
        )

        if success and data_url:
            size_kb = len(data_url) * 3 // 4 // 1024  # 近似原始大小
            return {
                'success': True,
                'base64_data_url': data_url,
                'size_kb': size_kb,
                'message': f'图片已成功加载（约 {size_kb} KB），图片将自动注入到你的对话中。'
            }
        else:
            return {'success': False, 'error': error or '图片压缩失败'}
    except Exception as e:
        logger.error(f"fetch_image_as_base64 失败: {e}", exc_info=True)
        return {'success': False, 'error': f'获取图片失败: {str(e)}'}


def get_skill_loader():
    """获取技能加载器实例（单例模式）"""
    global _skill_loader
    if _skill_loader is None:
        _skill_loader = SkillLoader()
    return _skill_loader

def set_file_manager(file_manager: FileManager):
    """设置全局文件管理器实例"""
    global _file_manager
    _file_manager = file_manager

def get_file_manager() -> FileManager:
    """获取文件管理器实例"""
    global _file_manager
    if _file_manager is None:
        # 如果没有设置，创建默认实例（向上两级到项目根目录）
        import os
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        _file_manager = FileManager(base_dir=project_root)
    return _file_manager


def get_task_status(user_id: str, world_id: str, auth_token: str, item_type: int, item_name: str) -> Dict[str, Any]:
    """
    查询指定项目的任务状态

    **重要限制**: 此函数仅支持单个图片生成任务（generate_text_to_image）的状态查询。
    不适用于多宫格图片生成任务（generate_4grid_character_images、generate_4grid_location_images、generate_4grid_prop_images）。
    请勿对多宫格生成任务调用此函数。

    ⚠️ 与 check_image_status 的区别：
      - get_task_status: 按 item_type + item_name 查询，适用于剧本创作场景（角色/场景/道具）
      - check_image_status: 按 project_id 查询，适用于营销等通用生图场景
    
    Args:
        user_id: 用户ID（必填）
        world_id: 世界ID（必填）
        auth_token: 认证令牌（必填）
        item_type: 项目类型 (1=character, 2=location, 3=props)
        item_name: 项目名称
    
    Returns:
        Dict[str, Any]: 包含任务状态信息的字典
    """
    try:
        
        # 使用task_manager读取任务状态
        task_manager = get_task_manager()
        data = task_manager._read_task_status_file(user_id, world_id)
        
        # 查找指定项目的状态
        item_type_key = str(item_type)
        if item_type_key not in data:
            return {
                'success': True,
                'status': 'not_found',
                'message': '未找到该项目的任务状态',
                'item_type': item_type,
                'item_name': item_name
            }
        
        # 查找具体项目（使用item_name作为key）
        items = data[item_type_key]
        if item_name in items:
            item = items[item_name]
            return {
                'success': True,
                'status': item.get('status', 'unknown'),
                'update_time': item.get('update_time', ''),
                'message': f"项目 '{item_name}' 的任务状态: {item.get('status', 'unknown')}",
                'item_type': item_type,
                'item_name': item_name
            }
        
        # 未找到指定项目
        return {
            'success': True,
            'status': 'not_found',
            'message': f"未找到项目 '{item_name}' 的任务状态",
            'item_type': item_type,
            'item_name': item_name
        }
        
    except Exception as e:
        return {
            'success': False,
            'error': str(e),
            'message': f"查询任务状态失败: {str(e)}",
            'item_type': item_type,
            'item_name': item_name
        }


def check_image_status(user_id: str, world_id: str, auth_token: str, project_id: str) -> Dict[str, Any]:
    """
    通过 project_id 查询图片生成结果（一次性查询，非轮询）

    后台 scheduler 会自动轮询 ComfyUI 状态并更新数据库，本函数直接读取数据库最终状态。
    适用于通用生图任务（营销等场景，不绑定 item_type/item_name）。

    建议在调用 generate_text_to_image 后等待一段时间再查询，确保后台有足够时间处理。

    Args:
        user_id: 用户ID（必填）
        world_id: 世界ID（必填）
        auth_token: 认证令牌（必填）
        project_id: 图片生成任务返回的 project_id（必填）

    Returns:
        Dict[str, Any]: 包含任务状态和图片URL的结果
    """
    try:
        from model import GridImageTasksModel, GridImageTaskStatus

        # 构造通用任务的 task_key（格式与 generate_text_to_image 中一致）
        task_key = f"{user_id}_0_{project_id}"

        task = GridImageTasksModel.get_by_task_key(task_key)
        if not task:
            return {
                'success': True,
                'status': 'not_found',
                'message': f'未找到 project_id={project_id} 对应的任务记录',
                'project_id': project_id
            }

        # 将数据库状态码转换为可读状态
        status_map = {
            GridImageTaskStatus.QUEUED: 'queued',
            GridImageTaskStatus.PROCESSING: 'processing',
            GridImageTaskStatus.COMPLETED: 'completed',
            GridImageTaskStatus.FAILED: 'failed',
            GridImageTaskStatus.TIMEOUT: 'timeout',
            GridImageTaskStatus.CANCELLED: 'cancelled',
            GridImageTaskStatus.DOWNLOAD_FAILED: 'download_failed',
        }
        readable_status = status_map.get(task.status, 'unknown')

        result = {
            'success': True,
            'status': readable_status,
            'project_id': project_id,
            'message': f'任务状态: {readable_status}'
        }

        # 如果完成，返回图片URL
        if task.status == GridImageTaskStatus.COMPLETED and task.result_url:
            result['image_url'] = task.result_url
            result['message'] = f'图片生成完成，图片URL: {task.result_url}'

        # 如果失败，返回错误信息
        if task.status in [GridImageTaskStatus.FAILED, GridImageTaskStatus.TIMEOUT,
                           GridImageTaskStatus.DOWNLOAD_FAILED]:
            result['error_message'] = task.error_message
            result['message'] = f'图片生成失败: {task.error_message or "未知错误"}'

        return result

    except Exception as e:
        return {
            'success': False,
            'error': str(e),
            'message': f"查询图片状态失败: {str(e)}",
            'project_id': project_id
        }


def edit_image(user_id: str, world_id: str, auth_token: str, prompt: str,
               image_url: str, aspect_ratio: str = "16:9", count: int = 1,
               image_size: Optional[str] = None,
               item_type: Optional[int] = None, item_name: Optional[str] = None,
               force_update_exist_image: bool = False,
               task_type: Optional[int] = None) -> Dict[str, Any]:
    """
    图片编辑（图生图）- MCP工具函数（非阻塞版本，支持后台任务处理）

    根据用户提供的图片 URL 和编辑指令，调用图片编辑 API 生成新图片。
    后台 scheduler 会自动跟踪进度，可通过 check_image_status / get_task_status 查询结果。

    注意：图片编辑模型由用户在前端界面选择，不同模型算力价格不同，请先调用 get_text_to_image_model_info 了解当前模型。

    Args:
        user_id: 用户ID（必填）
        world_id: 世界ID（必填）
        auth_token: 认证令牌（必填）
        prompt: 图片编辑指令（必填），例如："将背景替换为海滩"、"转为水彩画风格"
        image_url: 原始图片URL（必填），支持多张图片，用英文逗号分隔。需要编辑的源图片地址。
        aspect_ratio: 图片宽高比（默认：16:9）
        count: 生成图片数量（默认：1）
        image_size: 图片分辨率（可选），如 1K/2K/3K/4K
        item_type: 物品类型（可选）：1=角色, 2=地点, 3=道具, 7=角色变体图。传入后会绑定后台任务并自动写回对应字段
        item_name: 物品名称（可选），当指定 item_type 时必填；变体图格式为 "角色名|变体标签"
        force_update_exist_image: 是否强制覆盖已有图像/同标签变体（默认：False）

    Returns:
        dict: 操作结果，包含 success 状态、project_ids、task_id 等
    """
    # 获取用户配置的生图模型 task_id（图片编辑复用同一模型配置）
    locked_snapshot = get_media_generation_snapshot('image', 'image_edit')
    if locked_snapshot:
        task_type = locked_snapshot.get('task_id')
    text_to_image_task_id = (
        int(task_type)
        if task_type not in (None, '')
        else _get_text_to_image_task_id(user_id, world_id)
    )

    # 验证模型是否支持图片编辑
    from config.unified_config import UnifiedConfigRegistry, TaskCategory
    config = UnifiedConfigRegistry.get_by_id(text_to_image_task_id)
    if not config:
        return {'success': False, 'error': f'图片编辑模型（id={text_to_image_task_id}）不存在'}
    if not config.enabled or (config.hidden and not locked_snapshot):
        return {'success': False, 'error': f'图片编辑模型 {config.name} 已禁用或不可用'}
    if config.category != TaskCategory.IMAGE_EDIT and TaskCategory.IMAGE_EDIT not in getattr(config, 'categories', []):
        return {
            'success': False,
            'error': f'当前选中的模型（id={text_to_image_task_id}）不支持图片编辑'
        }

    model_name = _get_model_name_by_task_id(text_to_image_task_id)

    try:
        # 验证参数
        if not auth_token:
            return {'success': False, 'error': '认证令牌不能为空'}

        if not prompt or not isinstance(prompt, str):
            return {'success': False, 'error': '编辑指令不能为空且必须是字符串'}

        if not image_url or not isinstance(image_url, str):
            return {'success': False, 'error': '图片URL不能为空且必须是字符串'}

        # 解析图片 URL（支持逗号分隔的多图）
        parsed_urls = [u.strip() for u in image_url.split(',') if u.strip()]
        if not parsed_urls:
            return {'success': False, 'error': '解析后没有有效的图片URL'}
        # 验证 URL 格式：仅允许 http/https 协议，防止 SSRF
        from urllib.parse import urlparse
        for u in parsed_urls:
            parsed = urlparse(u)
            if parsed.scheme not in ('http', 'https'):
                return {'success': False, 'error': f'图片URL仅支持 http/https 协议: {u[:100]}'}
        logger.info(f"[edit_image] 解析到 {len(parsed_urls)} 张图片: {parsed_urls}")

        # 绑定 item 时做冲突与已有图像检查（与 generate_text_to_image 对齐）
        if item_type is not None:
            if not isinstance(item_type, int) or item_type not in [1, 2, 3, 7]:
                return {
                    'success': False,
                    'error': 'item_type参数错误。图片编辑支持：1=角色, 2=地点, 3=道具, 7=角色变体图'
                }
            if not item_name or not isinstance(item_name, str):
                return {
                    'success': False,
                    'error': '当指定item_type时，必须同时提供item_name参数'
                }

            task_manager = get_task_manager()
            if task_manager.is_item_generating(item_type, item_name, user_id):
                return {
                    'success': False,
                    'error': f'该项目正在生成图片中，请等待完成后再试。可以调用相关API查询任务状态。'
                }

            if not force_update_exist_image:
                file_manager = get_file_manager()
                if item_type == 1:
                    existing_data = file_manager.get_character_json(item_name, user_id, world_id)
                    if existing_data and existing_data.get('reference_image'):
                        return {
                            'success': False,
                            'error': f'角色 "{item_name}" 已存在参考图像，如需更新请设置 force_update_exist_image=True',
                            'existing_image': existing_data.get('reference_image'),
                            'skip_reason': 'already_has_image'
                        }
                elif item_type == 2:
                    existing_data = file_manager.get_location_json(item_name, user_id, world_id)
                    if existing_data and existing_data.get('reference_image'):
                        return {
                            'success': False,
                            'error': f'地点 "{item_name}" 已存在参考图像，如需更新请设置 force_update_exist_image=True',
                            'existing_image': existing_data.get('reference_image'),
                            'skip_reason': 'already_has_image'
                        }
                elif item_type == 3:
                    existing_data = file_manager.get_prop_json(item_name, user_id, world_id)
                    if existing_data and existing_data.get('reference_image'):
                        return {
                            'success': False,
                            'error': f'道具 "{item_name}" 已存在参考图像，如需更新请设置 force_update_exist_image=True',
                            'existing_image': existing_data.get('reference_image'),
                            'skip_reason': 'already_has_image'
                        }
                elif item_type == 7:
                    char_name = item_name.split('|')[0] if '|' in item_name else item_name
                    variant_label = item_name.split('|')[1] if '|' in item_name else ''
                    existing_data = file_manager.get_character_json(char_name, user_id, world_id)
                    if existing_data and variant_label:
                        existing_variants = existing_data.get('reference_images', [])
                        if any(v.get('label') == variant_label for v in existing_variants if isinstance(v, dict)):
                            return {
                                'success': False,
                                'error': f'角色 "{char_name}" 已存在标签为 "{variant_label}" 的变体图，如需更新请设置 force_update_exist_image=True',
                                'skip_reason': 'already_has_variant'
                            }

        server_config = get_config().get("server", {})
        comfyui_base_url = server_config.get("comfyui_base_url_inner") or server_config.get("host", "")

        if not comfyui_base_url:
            return {'success': False, 'error': '配置文件中未找到comfyui_base_url_inner或host配置'}

        # 强制应用系统注入：任务 snapshot（故事板 workflow_ratio）> 世界偏好 > 参数默认
        generation_snapshot = _image_generation_snapshot_override.get() or locked_snapshot
        aspect_ratio, image_size, image_size_source = _resolve_image_ratio_and_size_from_prefs(
            user_id=user_id,
            world_id=world_id,
            aspect_ratio=aspect_ratio,
            image_size=image_size,
            generation_snapshot=generation_snapshot,
        )

        # 确定 image_size
        config = UnifiedConfigRegistry.get_by_id(text_to_image_task_id)
        if (
            image_size
            and image_size_source in ("preference", "snapshot")
            and config
            and config.supported_sizes
            and image_size.lower() not in [s.lower() for s in config.supported_sizes]
        ):
            logger.warning(
                f"忽略不兼容的图片分辨率偏好: {image_size}, "
                f"当前模型支持: {config.supported_sizes}"
            )
            image_size = None
        if image_size:
            if config and config.supported_sizes:
                supported_lower = [s.lower() for s in config.supported_sizes]
                if image_size.lower() not in supported_lower:
                    return {
                        'success': False,
                        'error': f'不支持的图片尺寸: {image_size}，当前模型支持: {config.supported_sizes}'
                    }
        elif config:
            image_size = _get_lowest_supported_image_size(config)

        # 计算预估算力
        from utils.computing_power import get_computing_power_for_task
        context_for_power = {}
        if image_size:
            context_for_power['resolution'] = image_size
        elif config and config.default_size:
            context_for_power['resolution'] = config.default_size
        computing_power_per_image = get_computing_power_for_task(
            text_to_image_task_id, context=context_for_power or None
        )
        computing_power_total = computing_power_per_image * count

        # 调用图片编辑 API
        api_url = f"{comfyui_base_url.rstrip('/')}/api/image-edit"

        request_data = {
            'prompt': prompt,
            'task_id': text_to_image_task_id,
            'ratio': aspect_ratio,
            'count': count,
            'user_id': user_id,
            'auth_token': auth_token,
            'ref_image_urls': ','.join(parsed_urls),
        }
        if generation_snapshot:
            request_data['generation_snapshot'] = json.dumps(
                generation_snapshot, ensure_ascii=False
            )
        if image_size:
            request_data['image_size'] = image_size

        try:
            # 使用 httpx 替代 requests，避免同步阻塞事件循环
            # ===== E2E Mock 短路：仅替换 project_ids 获取，保留后续 grid_image_tasks 创建逻辑 =====
            from task.mock_interceptor import is_mock_enabled, generate_mock_project_id
            if is_mock_enabled():
                result_data = {'project_ids': [generate_mock_project_id()]}
                logger.info(f"[MOCK] mcp_tool image_edit short-circuit pid={result_data['project_ids'][0]}")
            else:
                # ⚠️ verify=False 禁用 SSL 证书验证，因为 ComfyUI 可能使用自签名证书
                response = httpx.post(api_url, data=request_data, timeout=30, verify=False, trust_env=False)
                response.raise_for_status()
                result_data = response.json()
            # ==============================================================================

            project_ids = result_data.get('project_ids', [])

            if not project_ids:
                return {
                    'success': False,
                    'error': '图片编辑请求成功但未返回project_ids'
                }

            # 读取自动重试配置
            max_retries = 0
            try:
                max_retries = get_config().get("image", {}).get("max_retry_count", 0) or 0
            except Exception:
                pass

            task_id = None
            bound_item_type = 0
            bound_item_name = project_ids[0]

            if item_type is not None and item_name:
                # 绑定到具体角色/场景/道具/变体的任务（必须成功，否则无法回写 JSON）
                # 图生图源图写入 reference_images，供失败重试时走 image-edit
                source_refs = [{'url': u, 'role_description': 'source'} for u in parsed_urls]
                try:
                    task_manager = get_task_manager()
                    task_id = task_manager.create_image_task(
                        project_id=project_ids[0],
                        item_type=item_type,
                        item_name=item_name,
                        comfyui_base_url=comfyui_base_url,
                        auth_token=auth_token,
                        user_id=user_id,
                        world_id=world_id,
                        prompt=prompt,
                        task_config_id=str(text_to_image_task_id) if text_to_image_task_id is not None else None,
                        aspect_ratio=aspect_ratio,
                        image_size=image_size,
                        is_grid=False,
                        max_retries=max_retries,
                        reference_images=source_refs,
                    )
                    bound_item_type = item_type
                    bound_item_name = item_name
                    logger.info(
                        f"创建图片编辑绑定任务: item_type={item_type}, item_name={item_name}, "
                        f"project_id={project_ids[0]}, task_key={task_id}"
                    )
                except ValueError as e:
                    return {'success': False, 'error': str(e), 'project_ids': project_ids}
                except Exception as e:
                    # 绑定失败则无法自动写回 reference_images，必须对调用方报失败
                    logger.error(
                        f"图片编辑绑定任务创建失败: item_type={item_type}, item_name={item_name}, "
                        f"project_id={project_ids[0]}, err={e}",
                        exc_info=True,
                    )
                    return {
                        'success': False,
                        'error': f'图片编辑请求已提交，但后台绑定任务创建失败（结果无法写回资产）: {str(e)}',
                        'project_ids': project_ids,
                        'comfyui_base_url': comfyui_base_url,
                        'model_used': model_name,
                    }
            else:
                # 通用后台任务记录（复用 item_type=0 机制）
                try:
                    from model import GridImageTasksModel, GridImageTaskStatus
                    general_task_key = f"{user_id}_0_{project_ids[0]}"
                    existing = GridImageTasksModel.get_by_task_key(general_task_key)
                    if existing and existing.status not in [GridImageTaskStatus.QUEUED, GridImageTaskStatus.PROCESSING]:
                        GridImageTasksModel.delete_by_task_key(general_task_key)
                    GridImageTasksModel.create(
                        task_key=general_task_key,
                        project_id=project_ids[0],
                        item_type=0,
                        item_name=project_ids[0],
                        user_id=user_id,
                        world_id=world_id,
                        comfyui_base_url=comfyui_base_url,
                        auth_token=auth_token,
                        prompt=prompt,
                        task_config_id=text_to_image_task_id,
                        aspect_ratio=aspect_ratio,
                        image_size=image_size,
                        is_grid=False,
                        max_retries=max_retries,
                        grid_size=GridConfig.SIZE_2X2,
                        grid_layout='2x2',
                    )
                    task_id = general_task_key
                    logger.info(f"创建图片编辑后台任务: {general_task_key}, project_id: {project_ids[0]}")
                except Exception as e:
                    logger.warning(f"图片编辑后台任务创建失败（不影响编辑请求）: {e}")

            result = {
                'success': True,
                'project_ids': project_ids,
                'status': 'submitted',
                'comfyui_base_url': comfyui_base_url,
                'model_used': model_name,
                # 统一模型对账字段：调用方用它校验实际模型与批任务快照一致
                'model_task_id': text_to_image_task_id,
                'image_size_used': image_size,
                'computing_power_required': computing_power_per_image,
                'computing_power_total': computing_power_total,
                'item_type': bound_item_type,
                'item_name': bound_item_name,
            }

            if task_id:
                result.update({
                    'task_id': task_id,
                    'message': f'图片编辑请求已提交（使用模型: {model_name}），后台任务已创建。project_ids: {project_ids}, task_id: {task_id}'
                })
            else:
                result['message'] = f'图片编辑请求已提交（使用模型: {model_name}），project_ids: {project_ids}'

            return result

        except httpx.HTTPStatusError as e:
            error_detail = f'图片编辑请求失败: {str(e)}'
            try:
                resp_data = e.response.json()
                detail = resp_data.get('detail', '')
                if detail:
                    error_detail = detail
            except Exception:
                pass
            return {
                'success': False,
                'error': error_detail,
                'model_used': model_name
            }

    except Exception as e:
        logger.error(f"edit_image error: {e}", exc_info=True)
        return {'success': False, 'error': f'图片编辑失败: {str(e)}'}


def validate_name_for_filename(name: str, field_name: str = "名称", language: str = "zh-CN") -> Dict[str, Any]:
    """
    验证名称是否只包含允许的字符，确保可以用作文件名

    根据语言设置验证名称：
    - language="en": 只允许英文字母、数字、点号、下划线
    - language="zh-CN" 或其他: 允许中文、英文、数字、点号、下划线

    Args:
        name: 要验证的名称
        field_name: 字段名称，用于错误提示
        language: 语言设置，默认 "zh-CN"，"en" 表示英文模式

    Returns:
        dict: 包含验证结果和清理后的名称
    """
    if not name or not name.strip():
        return {
            'valid': False,
            'error': f'{field_name}不能为空',
            'cleaned_name': ''
        }

    import re

    # 根据语言设置选择验证模式
    if language == "en":
        # 英文模式：只允许英文字母、数字、点号、下划线
        valid_pattern = re.compile(r'^[a-zA-Z0-9._]+$')
        # 清理名称：只保留英文、数字、点号、下划线
        cleaned_name = re.sub(r'[^a-zA-Z0-9._]', '', name.strip())
        lang_error_hint = "英文字母、数字、点号(.)、下划线(_)"
    else:
        # 中文模式（默认）：允许中文、英文、数字、点号、下划线
        valid_pattern = re.compile(r'^[\u4e00-\u9fff\w._]+$')
        # 清理名称：只保留中文、英文、数字、点号、下划线
        cleaned_name = re.sub(r'[^\u4e00-\u9fff\w._]', '', name.strip())
        lang_error_hint = "中文、英文字母、数字、点号(.)、下划线(_)"

    if not cleaned_name:
        return {
            'valid': False,
            'error': f'{field_name}必须包含至少一个{lang_error_hint}字符',
            'cleaned_name': ''
        }

    # 检查原始名称是否包含非法字符
    if not valid_pattern.match(name.strip()):
        return {
            'valid': False,
            'error': f'{field_name}只能包含{lang_error_hint}，不能包含其他特殊字符、空格或符号。建议使用: "{cleaned_name}"',
            'cleaned_name': cleaned_name
        }

    return {
        'valid': True,
        'error': None,
        'cleaned_name': cleaned_name
    }

def validate_image_url(url: str, field_name: str = "reference_image") -> Dict[str, Any]:
    """
    验证图片URL是否为合法的HTTP/HTTPS地址

    Args:
        url: 要验证的URL
        field_name: 字段名称，用于错误提示

    Returns:
        dict: 包含验证结果
    """
    if not url or not isinstance(url, str):
        return {
            'valid': False,
            'error': f'{field_name}必须是字符串类型'
        }

    url = url.strip()

    # 使用标准库 urllib.parse 解析URL，判断协议与主机是否合法。
    # 不使用严格正则，以兼容主机名含下划线的内部域名（如 zjt_dev.xxx.cn）。
    from urllib.parse import urlparse
    try:
        parsed = urlparse(url)
    except Exception:
        return {
            'valid': False,
            'error': f'{field_name}的URL格式不正确。请提供合法的HTTP图片地址，不要传入非URL内容。'
        }

    # 检查是否以http://或https://开头
    if parsed.scheme not in ('http', 'https'):
        return {
            'valid': False,
            'error': f'{field_name}必须是合法的HTTP图片地址（以http://或https://开头）。请不要传入非URL内容，该字段只能传入图片URL地址。'
        }

    # 检查主机部分(netloc)是否存在
    if not parsed.netloc:
        return {
            'valid': False,
            'error': f'{field_name}的URL格式不正确。请提供合法的HTTP图片地址，不要传入非URL内容。'
        }

    return {
        'valid': True,
        'error': None
    }


def create_character_json(user_id: str, world_id: str, auth_token: str, name: str, age: str = None, identity: str = None,
                         appearance: str = None, personality: str = None, behavior: str = None,
                         other_info: str = None, reference_image: str = None, default_voice: str = None,
                         _temp_filename: str = None, language: str = "zh-CN",
                         _skip_image_validation: bool = False, **additional_fields) -> Dict[str, Any]:
    """
    创建标准格式的角色JSON文件 - MCP工具函数
    ⚠️ _temp_filename 参数名以下划线开头，但它是公开参数（可由调用方传入）
    命名约定：下划线前缀表示"内部使用"，但 MCP 工具函数的参数会暴露给 LLM，所以用下划线隐藏此参数
    
    Args:
        user_id: 用户ID（必填）
        world_id: 世界ID（必填）
        auth_token: 认证令牌（必填）
        name: 角色名称（必填，只能包含中文、英文、数字）
        age: 角色年龄（可选，字符串）
        identity: 身份（可选）
        appearance: 外貌（可选）
        personality: 性格（可选）
        behavior: 行为（可选）
        other_info: 其他信息（可选）
        reference_image: 参考图片（可选）
        **additional_fields: 额外字段（可选）
    
    Returns:
        dict: 操作结果，包含success状态和相关信息
    """
    try:
        # 验证必填字段
        if not name or not isinstance(name, str):
            return {
                'success': False,
                'error': '角色名称不能为空且必须是字符串'
            }
        
        # 验证名称
        validation_result = validate_name_for_filename(name, "角色名称", language)
        if not validation_result['valid']:
            return {
                'success': False,
                'error': validation_result['error']
            }
        validated_name = validation_result['cleaned_name']
        
        # 验证reference_image（如果提供）
        # _skip_image_validation=True 时跳过：用于数据库同步等系统内部场景，
        # 此时 reference_image 是从自家 DB 读出的数据（可能是 /upload/... 相对路径），属于合法存储格式，无需校验。
        if reference_image is not None and not _skip_image_validation:
            url_validation = validate_image_url(reference_image, "reference_image")
            if not url_validation['valid']:
                return {
                    'success': False,
                    'error': url_validation['error']
                }

        # 创建角色数据
        character_data = {
            'name': validated_name,
            'user_id': int(user_id),
            'world_id': int(world_id),
            'created_at': datetime.now().isoformat()
        }
        
        # 添加可选字段
        if age is not None:
            character_data['age'] = age
        if identity is not None:
            character_data['identity'] = identity
        if appearance is not None:
            character_data['appearance'] = appearance
        if personality is not None:
            character_data['personality'] = personality
        if behavior is not None:
            character_data['behavior'] = behavior
        if other_info is not None:
            character_data['other_info'] = other_info
        if reference_image is not None:
            character_data['reference_image'] = reference_image
        if default_voice is not None:
            character_data['default_voice'] = default_voice

        # 添加额外字段
        for key, value in additional_fields.items():
            if key not in character_data:  # 避免覆盖核心字段
                character_data[key] = value
        
        # 生成安全的文件名（支持临时文件名用于比较）
        filename = _temp_filename if _temp_filename else f"character_{validated_name}.json"
        
        # 使用FileManager统一路径管理
        file_manager = get_file_manager()
        success = file_manager.save_json_content(user_id, world_id, "characters", filename, character_data)
        
        if not success:
            return {
                'success': False,
                'error': '保存角色JSON文件失败'
            }
        
        file_path = file_manager.get_content_file_path(user_id, world_id, "characters", filename)
        
        return {
            'success': True,
            'filename': filename,
            'file_path': file_path,
            'character_data': character_data,
            'message': f'角色 "{name}" 的JSON文件已创建: {filename}'
        }
        
    except Exception as e:
        return {
            'success': False,
            'error': f'创建角色JSON失败: {str(e)}'
        }


def create_script_json(user_id: str, world_id: str, auth_token: str, title: str, episode_number: int, content: str = None, language: str = "zh-CN", **additional_fields) -> Dict[str, Any]:
    """
    创建标准格式的剧本JSON文件 - MCP工具函数

    Args:
        user_id: 用户ID（必填）
        world_id: 世界ID（必填）
        auth_token: 认证令牌（必填）
        title: 剧本标题（必填，只能包含中文、英文、数字）
               推荐格式："剧本名_第N集"  
               例如："神话擂台_第1集" 或 "神话擂台_诸仙听令"
        episode_number: 计划第几集（可选）
        content: 剧本内容（可选）
        **additional_fields: 额外字段（可选）
    
    Returns:
        dict: 操作结果，包含success状态和相关信息
              如果文件已存在，将返回错误信息
    """
    try:
        # 验证必填字段
        if not title or not isinstance(title, str):
            return {
                'success': False,
                'error': '剧本标题不能为空且必须是字符串'
            }

        # 验证 episode_number 为必填正整数
        if episode_number is None or not isinstance(episode_number, int) or episode_number < 1:
            return {
                'success': False,
                'error': '集数(episode_number)为必填字段，且必须为正整数'
            }

        # 验证名称
        validation_result = validate_name_for_filename(title, "剧本标题", language)
        if not validation_result['valid']:
            return {
                'success': False,
                'error': validation_result['error']
            }
        validated_title = validation_result['cleaned_name']

        # 生成文件名：使用 episode_number
        filename = f"{episode_number}.json"

        # 使用FileManager统一路径管理
        file_manager = get_file_manager()

        # 检查集数是否已存在（检查 {episode_number}.json 文件）
        file_path = file_manager.get_content_file_path(user_id, world_id, "scripts", filename)
        if os.path.exists(file_path):
            # 读取已有文件获取标题信息
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    existing_script = json.load(f)
                    existing_title = existing_script.get('title', '未知')
                return {
                    'success': False,
                    'error': f'集数冲突：第 {episode_number} 集已存在（标题："{existing_title}"）。同一世界下不允许创建相同集数的剧本。',
                    'existing_file': file_path,
                    'existing_title': existing_title,
                    'conflicting_episode_number': episode_number
                }
            except Exception:
                return {
                    'success': False,
                    'error': f'集数冲突：第 {episode_number} 集已存在。',
                    'conflicting_episode_number': episode_number
                }

        # 构建剧本数据结构（匹配数据库表结构）
        script_data = {
            'title': validated_title,
            'episode_number': episode_number,
            'content': content or "",
            'user_id': user_id,
            'world_id': world_id,
            'create_time': datetime.now().isoformat(),
            'update_time': datetime.now().isoformat()
        }

        # 添加额外字段
        for key, value in additional_fields.items():
            if key not in script_data and value is not None:
                script_data[key] = value

        success = file_manager.save_json_content(user_id, world_id, "scripts", filename, script_data)

        if not success:
            return {
                'success': False,
                'error': '保存剧本JSON文件失败'
            }

        return {
            'success': True,
            'filename': filename,
            'file_path': file_path,
            'script_data': script_data,
            'message': f'剧本第{episode_number}集 "{title}" 已创建: {filename}'
        }

    except Exception as e:
        return {
            'success': False,
            'error': f'创建剧本JSON失败: {str(e)}'
        }


def create_world_json(user_id: str, world_id: str, auth_token: str, name: str, description: str = None, **additional_fields) -> Dict[str, Any]:
    """
    创建标准格式的世界JSON文件 - MCP工具函数
    
    Args:
        user_id: 用户ID（必填）
        world_id: 世界ID（必填）
        auth_token: 认证令牌（必填）
        name: 世界名称（必填，只能包含中文、英文、数字）
        description: 世界描述（可选）
        **additional_fields: 额外字段（可选）
    
    Returns:
        dict: 操作结果，包含success状态和相关信息
    """
    try:
        # 验证必填字段
        if not name or not isinstance(name, str):
            return {
                'success': False,
                'error': '世界名称不能为空且必须是字符串'
            }
        
        # 验证名称
        validation_result = validate_name_for_filename(name, "世界名称")
        if not validation_result['valid']:
            return {
                'success': False,
                'error': validation_result['error']
            }
        validated_name = validation_result['cleaned_name']
        
        # 创建世界数据
        world_data = {
            'name': validated_name,
            'user_id': user_id,
            'story_type': StoryType.normalize(additional_fields.pop('story_type', None)),
            'created_at': datetime.now().isoformat()
        }
        
        # 添加可选字段
        if description is not None:
            world_data['description'] = description
        
        # 添加额外字段
        for key, value in additional_fields.items():
            if key not in world_data:
                world_data[key] = value
        
        # 生成安全的文件名
        filename = f"world_{validated_name}.json"
        
        # 使用FileManager统一路径管理 (世界文件保存在用户根目录下的worlds文件夹)
        file_manager = get_file_manager()
        # 对于世界文件，使用world_id="0"因为世界本身不属于特定世界
        success = file_manager.save_json_content(user_id, "0", "worlds", filename, world_data)
        
        if not success:
            return {
                'success': False,
                'error': '保存世界JSON文件失败'
            }
        
        file_path = file_manager.get_content_file_path(user_id, "0", "worlds", filename)
        
        return {
            'success': True,
            'filename': filename,
            'file_path': file_path,
            'world_data': world_data,
            'message': f'世界 "{name}" 的JSON文件已创建: {filename}'
        }
        
    except Exception as e:
        return {
            'success': False,
            'error': f'创建世界JSON失败: {str(e)}'
        }


def _truncate_content(content: str, limit: Optional[int] = None) -> str:
    """
    根据limit参数截断内容
    
    Args:
        content: 要截断的内容
        limit: 字符数限制，None表示不限制
    
    Returns:
        str: 截断后的内容
    """
    if limit is None or limit <= 0:
        return content
    
    if len(content) <= limit:
        return content
    
    return content[:limit] + "...(已截断)"


def read_world(user_id: str, world_id: str, auth_token: str, limit: Optional[int] = None) -> Dict[str, Any]:
    """
    读取当前世界的完整信息 - MCP工具函数
    
    Args:
        user_id: 用户ID（必填）
        world_id: 世界ID（必填）
        auth_token: 认证令牌（必填）
        limit: 字符数限制（可选），不填则输出所有内容
    
    Returns:
        dict: 操作结果，包含success状态和世界所有字段（story_outline, visual_style, era_environment, color_language, composition_preference）
    """
    try:
        # 验证上下文
        if not user_id or not world_id:
            return {
                'success': False,
                'error': '无法获取用户或世界信息，请确保会话已正确初始化'
            }
        
        # 使用FileManager读取世界信息
        file_manager = get_file_manager()
        world_data = file_manager.get_world_json(user_id, world_id)
        
        if not world_data:
            return {
                'success': False,
                'error': '未找到世界信息文件'
            }
        
        return {
            'success': True,
            'world_id': world_id,
            'world_name': world_data.get('name', ''),
            'story_type': StoryType.normalize(world_data.get('story_type')),
            'story_outline': _truncate_content(world_data.get('story_outline', ''), limit),
            'visual_style': _truncate_content(world_data.get('visual_style', ''), limit),
            'era_environment': _truncate_content(world_data.get('era_environment', ''), limit),
            'color_language': _truncate_content(world_data.get('color_language', ''), limit),
            'composition_preference': _truncate_content(world_data.get('composition_preference', ''), limit),
            'message': f'成功读取世界 "{world_data.get("name", "")}" 的完整信息'
        }
        
    except Exception as e:
        return {
            'success': False,
            'error': f'读取世界信息失败: {str(e)}'
        }


def update_world(
    user_id: str, world_id: str, auth_token: str,
    story_outline: str = None,
    story_type: str = None,
    visual_style: str = None,
    era_environment: str = None,
    color_language: str = None,
    composition_preference: str = None
) -> Dict[str, Any]:
    """
    更新当前世界的信息 - MCP工具函数
    
    Args:
        user_id: 用户ID（必填）
        world_id: 世界ID（必填）
        auth_token: 认证令牌（必填）
        story_outline: 故事大纲内容（可选）
        visual_style: 画面风格（可选）
        era_environment: 时代环境（可选）
        color_language: 色彩语言（可选）
        composition_preference: 构图倾向（可选）
    
    Returns:
        dict: 操作结果，包含success状态和相关信息
    """
    try:
        # 验证至少有一个字段需要更新
        if all(v is None for v in [story_outline, story_type, visual_style, era_environment, color_language, composition_preference]):
            return {
                'success': False,
                'error': '至少需要提供一个字段进行更新'
            }
        
        # 使用FileManager读取现有世界信息
        file_manager = get_file_manager()
        world_data = file_manager.get_world_json(user_id, world_id)
        
        if not world_data:
            # 如果世界信息文件不存在，创建一个新的
            world_data = {
                'id': int(world_id),
                'name': f'World_{world_id}',
                'user_id': int(user_id)
            }
        
        # 更新提供的字段
        if story_outline is not None:
            world_data['story_outline'] = story_outline
        if story_type is not None:
            world_data['story_type'] = StoryType.normalize(story_type)
        if visual_style is not None:
            world_data['visual_style'] = visual_style
        if era_environment is not None:
            world_data['era_environment'] = era_environment
        if color_language is not None:
            world_data['color_language'] = color_language
        if composition_preference is not None:
            world_data['composition_preference'] = composition_preference
        
        # 保存更新后的世界信息
        success = file_manager.save_world(world_data, user_id, world_id)
        
        if not success:
            return {
                'success': False,
                'error': '保存世界信息失败'
            }
        
        updated_fields = []
        if story_outline is not None:
            updated_fields.append('story_outline')
        if story_type is not None:
            updated_fields.append('story_type')
        if visual_style is not None:
            updated_fields.append('visual_style')
        if era_environment is not None:
            updated_fields.append('era_environment')
        if color_language is not None:
            updated_fields.append('color_language')
        if composition_preference is not None:
            updated_fields.append('composition_preference')
        
        return {
            'success': True,
            'world_id': world_id,
            'world_name': world_data.get('name', ''),
            'updated_fields': updated_fields,
            'message': f'成功更新世界 "{world_data.get("name", "")}" 的信息: {", ".join(updated_fields)}'
        }
        
    except Exception as e:
        return {
            'success': False,
            'error': f'更新世界信息失败: {str(e)}'
        }


def create_location_json(user_id: str, world_id: str, auth_token: str, name: str, description: str = None,
                        reference_image: str = None, parent_id=None, parent_name: str = None,
                        _temp_filename: str = None, language: str = "zh-CN",
                        _skip_image_validation: bool = False, **additional_fields) -> Dict[str, Any]:
    """
    创建标准格式的地点JSON文件 - MCP工具函数
    
    Args:
        user_id: 用户ID（必填）
        world_id: 世界ID（必填）
        auth_token: 认证令牌（必填）
        name: 地点名称（必填，只能包含中文、英文、数字）
        description: 地点描述（可选）
        reference_image: 参考图片（可选）
        parent_id: 父级地点 ID 或兼容字段（可选；文件层优先用 parent_name）
        parent_name: 父级地点名称（可选；未落库稳定键，父须为顶级场景名）
        **additional_fields: 额外字段（可选）
    
    Returns:
        dict: 操作结果，包含success状态和相关信息
    """
    try:
        # 验证必填字段
        if not name or not isinstance(name, str):
            return {
                'success': False,
                'error': '地点名称不能为空且必须是字符串'
            }
        
        # 验证名称
        validation_result = validate_name_for_filename(name, "地点名称", language)
        if not validation_result['valid']:
            return {
                'success': False,
                'error': validation_result['error']
            }
        validated_name = validation_result['cleaned_name']

        # 验证reference_image（如果提供）
        # _skip_image_validation=True 时跳过：用于数据库同步等系统内部场景，
        # 此时 reference_image 是从自家 DB 读出的数据（可能是 /upload/... 相对路径），属于合法存储格式，无需校验。
        if reference_image is not None and not _skip_image_validation:
            url_validation = validate_image_url(reference_image, "reference_image")
            if not url_validation['valid']:
                return {
                    'success': False,
                    'error': url_validation['error']
                }

        # 创建地点数据
        location_data = {
            'name': validated_name,
            'world_id': int(world_id),
            'user_id': int(user_id),
            'created_at': datetime.now().isoformat()
        }
        
        # 父级：支持 parent_name（文件层主字段）与 parent_id（DB id 或兼容）
        pn = (str(parent_name).strip() if parent_name is not None else '') or None
        # additional_fields 里也可能带 parent_name / parent_id
        if pn is None and additional_fields.get('parent_name') is not None:
            pn = (str(additional_fields.get('parent_name')).strip() or None)
        pid = parent_id if parent_id is not None else additional_fields.get('parent_id')
        if pid is not None and pid != '':
            location_data['parent_id'] = pid
        else:
            location_data['parent_id'] = pn  # 过渡：无数字 id 时与 parent_name 双写
        location_data['parent_name'] = pn
        if reference_image is not None:
            location_data['reference_image'] = reference_image
        if description is not None:
            location_data['description'] = description
        
        # 添加额外字段（不覆盖已规范化的 parent_*）
        for key, value in additional_fields.items():
            if key in ('parent_id', 'parent_name'):
                continue
            if key not in location_data:
                location_data[key] = value
        
        # 生成安全的文件名（支持临时文件名用于比较）
        filename = _temp_filename if _temp_filename else f"location_{validated_name}.json"
        
        # 使用FileManager统一路径管理
        file_manager = get_file_manager()
        success = file_manager.save_json_content(user_id, world_id, "locations", filename, location_data)
        
        if not success:
            return {
                'success': False,
                'error': '保存地点JSON文件失败'
            }
        
        file_path = file_manager.get_content_file_path(user_id, world_id, "locations", filename)
        
        return {
            'success': True,
            'filename': filename,
            'file_path': file_path,
            'location_data': location_data,
            'message': f'地点 "{name}" 的JSON文件已创建: {filename}'
        }
        
    except Exception as e:
        return {
            'success': False,
            'error': f'创建地点JSON失败: {str(e)}'
        }


def create_prop_json(user_id: str, world_id: str, auth_token: str, name: str, prop_type: str = None, description: str = None, reference_image: str = None, _temp_filename: str = None, language: str = "zh-CN", _skip_image_validation: bool = False, **additional_fields) -> Dict[str, Any]:
    """
    创建标准格式的道具JSON文件 - MCP工具函数
    
    Args:
        user_id: 用户ID（必填）
        world_id: 世界ID（必填）
        auth_token: 认证令牌（必填）
        name: 道具名称（必填，只能包含中文、英文、数字）
        prop_type: 道具类型（可选）
        description: 道具描述（可选）
        reference_image: 参考图片（可选）
        **additional_fields: 额外字段（可选）
    
    Returns:
        dict: 操作结果，包含success状态和相关信息
    """
    try:
        # 验证必填字段
        if not name or not isinstance(name, str):
            return {
                'success': False,
                'error': '道具名称不能为空且必须是字符串'
            }
        
        # 验证名称
        validation_result = validate_name_for_filename(name, "道具名称", language)
        if not validation_result['valid']:
            return {
                'success': False,
                'error': validation_result['error']
            }
        validated_name = validation_result['cleaned_name']

        # 验证reference_image（如果提供）
        # _skip_image_validation=True 时跳过：用于数据库同步等系统内部场景，
        # 此时 reference_image 是从自家 DB 读出的数据（可能是 /upload/... 相对路径），属于合法存储格式，无需校验。
        if reference_image is not None and not _skip_image_validation:
            url_validation = validate_image_url(reference_image, "reference_image")
            if not url_validation['valid']:
                return {
                    'success': False,
                    'error': url_validation['error']
                }

        # 创建道具数据
        prop_data = {
            'name': validated_name,
            'world_id': int(world_id),
            'user_id': int(user_id),
            'created_at': datetime.now().isoformat()
        }
        
        # 添加可选字段
        if prop_type is not None:
            prop_data['type'] = prop_type
        if description is not None:
            prop_data['description'] = description
        if reference_image is not None:
            prop_data['reference_image'] = reference_image
        
        # 添加额外字段
        for key, value in additional_fields.items():
            if key not in prop_data:
                prop_data[key] = value
        
        # 生成安全的文件名（支持临时文件名用于比较）
        if _temp_filename:
            filename = _temp_filename
        else:
            safe_name = _sanitize_filename(name)
            filename = f"prop_{safe_name}.json"
        
        # 使用FileManager统一路径管理
        file_manager = get_file_manager()
        success = file_manager.save_json_content(user_id, world_id, "props", filename, prop_data)
        
        if not success:
            return {
                'success': False,
                'error': '保存道具JSON文件失败'
            }
        
        file_path = file_manager.get_content_file_path(user_id, world_id, "props", filename)
        
        return {
            'success': True,
            'filename': filename,
            'file_path': file_path,
            'prop_data': prop_data,
            'message': f'道具 "{name}" 的JSON文件已创建: {filename}'
        }
        
    except Exception as e:
        return {
            'success': False,
            'error': f'创建道具JSON失败: {str(e)}'
        }


def read_character_json(user_id: str, world_id: str, auth_token: str, name: str, limit: Optional[int] = None) -> Dict[str, Any]:
    """
    读取角色JSON文件 - MCP工具函数
    
    Args:
        user_id: 用户ID（必填）
        world_id: 世界ID（必填）
        auth_token: 认证令牌（必填）
        name: 角色名称
        limit: 输出字符数限制（可选），不填则输出所有内容
    
    Returns:
        dict: 操作结果，包含success状态和角色数据
    """
    try:
        # 验证必填字段
        if not name or not isinstance(name, str):
            return {
                'success': False,
                'error': '角色名称不能为空且必须是字符串'
            }
        
        # 使用FileManager读取文件
        file_manager = get_file_manager()
        character_data = file_manager.get_character_json(name, user_id, world_id)

        if character_data is None:
            return {
                'success': False,
                'error': f'角色 "{name}" 不存在或读取失败'
            }
        
        # 对文本字段应用limit
        if limit is not None and limit > 0:
            for key in ['appearance', 'personality', 'behavior', 'other_info', 'identity']:
                if key in character_data and isinstance(character_data[key], str):
                    character_data[key] = _truncate_content(character_data[key], limit)
        
        return {
            'success': True,
            'data': character_data,
            'message': f'成功读取角色 "{name}"'
        }
        
    except Exception as e:
        return {
            'success': False,
            'error': f'读取角色JSON失败: {str(e)}'
        }


def read_script_json(user_id: str, world_id: str, auth_token: str, title: str, limit: Optional[int] = None) -> Dict[str, Any]:
    """
    读取剧本JSON文件 - MCP工具函数
    
    Args:
        user_id: 用户ID（必填）
        world_id: 世界ID（必填）
        auth_token: 认证令牌（必填）
        title: 剧本标题
        limit: 输出字符数限制（可选），不填则输出所有内容
    
    Returns:
        dict: 操作结果，包含success状态和剧本数据
    """
    try:
        # 验证必填字段
        if not title or not isinstance(title, str):
            return {
                'success': False,
                'error': '剧本标题不能为空且必须是字符串'
            }
        
        # 使用FileManager读取文件（支持按集数或标题查找）
        file_manager = get_file_manager()

        # 如果 title 是数字，优先按集数查找
        if title.strip().isdigit():
            script_data = file_manager.get_script(title.strip(), user_id, world_id)
        else:
            safe_title = _sanitize_filename(title)
            script_data = file_manager.get_script(safe_title, user_id, world_id)
        
        if script_data is None:
            return {
                'success': False,
                'error': f'剧本 "{title}" 不存在或读取失败'
            }
        
        # 对content字段应用limit
        if limit is not None and limit > 0:
            if 'content' in script_data and isinstance(script_data['content'], str):
                script_data['content'] = _truncate_content(script_data['content'], limit)
        
        return {
            'success': True,
            'data': script_data,
            'message': f'成功读取剧本 "{title}"'
        }
        
    except Exception as e:
        return {
            'success': False,
            'error': f'读取剧本JSON失败: {str(e)}'
        }



def read_location_json(user_id: str, world_id: str, auth_token: str, name: str, limit: Optional[int] = None) -> Dict[str, Any]:
    """
    读取地点JSON文件 - MCP工具函数
    
    Args:
        user_id: 用户ID（必填）
        world_id: 世界ID（必填）
        auth_token: 认证令牌（必填）
        name: 地点名称
        limit: 输出字符数限制（可选），不填则输出所有内容
    
    Returns:
        dict: 包含success状态和数据的结果
    """
    try:
        # 验证必填字段
        if not name or not isinstance(name, str):
            return {
                'success': False,
                'error': '地点名称不能为空且必须是字符串'
            }
        
        safe_name = _sanitize_filename(name)
        filename = f"location_{safe_name}.json"
        
        # 使用FileManager统一路径管理
        file_manager = get_file_manager()
        file_path = file_manager.get_content_file_path(user_id, world_id, "locations", filename)
        
        if os.path.exists(file_path):
            with open(file_path, 'r', encoding='utf-8') as f:
                location_data = json.load(f)
            
            # 对description字段应用limit
            if limit is not None and limit > 0:
                if 'description' in location_data and isinstance(location_data['description'], str):
                    location_data['description'] = _truncate_content(location_data['description'], limit)
            
            return {
                'success': True,
                'data': location_data,
                'message': f'成功读取地点 "{name}" 的信息'
            }
        else:
            return {
                'success': False,
                'error': f'地点 "{name}" 不存在'
            }
        
    except Exception as e:
        return {
            'success': False,
            'error': f'读取地点JSON失败: {str(e)}'
        }


def read_prop_json(user_id: str, world_id: str, auth_token: str, name: str, limit: Optional[int] = None) -> Dict[str, Any]:
    """
    读取道具JSON文件 - MCP工具函数
    
    Args:
        user_id: 用户ID（必填）
        world_id: 世界ID（必填）
        auth_token: 认证令牌（必填）
        name: 道具名称
        limit: 输出字符数限制（可选），不填则输出所有内容
    
    Returns:
        dict: 包含success状态和数据的结果
    """
    try:
        # 验证必填字段
        if not name or not isinstance(name, str):
            return {
                'success': False,
                'error': '道具名称不能为空且必须是字符串'
            }
        
        safe_name = _sanitize_filename(name)
        filename = f"prop_{safe_name}.json"
        
        # 使用FileManager统一路径管理
        file_manager = get_file_manager()
        file_path = file_manager.get_content_file_path(user_id, world_id, "props", filename)
        
        if os.path.exists(file_path):
            with open(file_path, 'r', encoding='utf-8') as f:
                prop_data = json.load(f)
            
            # 对description字段应用limit
            if limit is not None and limit > 0:
                if 'description' in prop_data and isinstance(prop_data['description'], str):
                    prop_data['description'] = _truncate_content(prop_data['description'], limit)
            
            return {
                'success': True,
                'data': prop_data,
                'message': f'成功读取道具 "{name}" 的信息'
            }
        else:
            return {
                'success': False,
                'error': f'道具 "{name}" 不存在'
            }
        
    except Exception as e:
        return {
            'success': False,
            'error': f'读取道具JSON失败: {str(e)}'
        }



def list_location_jsons(user_id: str, world_id: str, auth_token: str) -> Dict[str, Any]:
    """
    列出所有地点JSON文件 - MCP工具函数
    
    Args:
        user_id: 用户ID（必填）
        world_id: 世界ID（必填）
        auth_token: 认证令牌（必填）
    
    Returns:
        dict: 包含success状态和地点文件列表的结果
    """
    try:
        # 使用FileManager统一路径管理
        file_manager = get_file_manager()
        locations_dir = file_manager.get_content_dir_path(user_id, world_id, "locations")
        
        if not os.path.exists(locations_dir):
            return {
                'success': True,
                'data': [],
                'message': '地点目录不存在，返回空列表'
            }
        
        files = []
        for filename in os.listdir(locations_dir):
            if filename.startswith("location_") and filename.endswith(".json"):
                files.append(filename)
        
        return {
            'success': True,
            'data': sorted(files),
            'message': f'成功获取 {len(files)} 个地点文件'
        }
        
    except Exception as e:
        return {
            'success': False,
            'error': f'列出地点文件失败: {str(e)}',
            'data': []
        }


def list_prop_jsons(user_id: str, world_id: str, auth_token: str) -> Dict[str, Any]:
    """
    列出所有道具JSON文件 - MCP工具函数
    
    Args:
        user_id: 用户ID（必填）
        world_id: 世界ID（必填）
        auth_token: 认证令牌（必填）
    
    Returns:
        dict: 包含success状态和道具文件列表的结果
    """
    try:
        # 使用FileManager统一路径管理
        file_manager = get_file_manager()
        props_dir = file_manager.get_content_dir_path(user_id, world_id, "props")
        
        if not os.path.exists(props_dir):
            return {
                'success': True,
                'data': [],
                'message': '道具目录不存在，返回空列表'
            }
        
        files = []
        for filename in os.listdir(props_dir):
            if filename.startswith("prop_") and filename.endswith(".json"):
                files.append(filename)
        
        return {
            'success': True,
            'data': sorted(files),
            'message': f'成功获取 {len(files)} 个道具文件'
        }
        
    except Exception as e:
        return {
            'success': False,
            'error': f'列出道具文件失败: {str(e)}',
            'data': []
        }


def list_character_jsons(user_id: str, world_id: str, auth_token: str) -> Dict[str, Any]:
    """
    列出所有角色JSON文件 - MCP工具函数
    
    Args:
        user_id: 用户ID（必填）
        world_id: 世界ID（必填）
        auth_token: 认证令牌（必填）
    
    Returns:
        dict: 包含success状态和角色文件列表的结果
    """
    try:
        # 使用FileManager统一路径管理
        file_manager = get_file_manager()
        characters_dir = file_manager.get_content_dir_path(user_id, world_id, "characters")
        
        if not os.path.exists(characters_dir):
            return {
                'success': True,
                'data': [],
                'message': '角色目录不存在，返回空列表'
            }
        
        files = []
        for filename in os.listdir(characters_dir):
            if filename.startswith("character_") and filename.endswith(".json"):
                files.append(filename)
        
        return {
            'success': True,
            'data': sorted(files),
            'message': f'成功获取 {len(files)} 个角色文件'
        }
        
    except Exception as e:
        return {
            'success': False,
            'error': f'列出角色文件失败: {str(e)}',
            'data': []
        }


def update_character_json(user_id: str, world_id: str, auth_token: str, name: str, age: str = None, identity: str = None, 
                         appearance: str = None, personality: str = None, behavior: str = None, 
                         other_info: str = None, reference_image: str = None, **additional_fields) -> Dict[str, Any]:
    """
    更新角色JSON文件 - MCP工具函数
    
    Args:
        user_id: 用户ID（必填）
        world_id: 世界ID（必填）
        auth_token: 认证令牌（必填）
        name: 角色名称（必填，用于定位文件）
        age: 角色年龄（可选）
        identity: 身份（可选）
        appearance: 外貌（可选）
        personality: 性格（可选）
        behavior: 行为（可选）
        other_info: 其他信息（可选）
        reference_image: 参考图片（可选）
        **additional_fields: 额外字段（可选）
    
    Returns:
        dict: 操作结果，包含success状态和相关信息
    """
    try:
        # 验证必填字段
        if not name or not isinstance(name, str):
            return {
                'success': False,
                'error': '角色名称不能为空且必须是字符串'
            }
        
        # 使用FileManager统一路径管理，按 name 解析真实文件路径
        # （兼容 character_中文名.json / sanitize 名 / 拼音临时文件名）
        file_manager = get_file_manager()
        resolved_path = file_manager.resolve_character_file_path(name, user_id, world_id)
        if not resolved_path or not resolved_path.exists():
            return {
                'success': False,
                'error': f'角色 "{name}" 不存在，无法更新'
            }
        file_path = str(resolved_path)
        filename = resolved_path.name
        
        # 读取现有数据
        with open(file_path, 'r', encoding='utf-8') as f:
            existing_data = json.load(f)
        
        # 验证reference_image（如果提供）
        if reference_image is not None:
            url_validation = validate_image_url(reference_image, "reference_image")
            if not url_validation['valid']:
                return {
                    'success': False,
                    'error': url_validation['error']
                }

        # 更新字段（只更新提供的非None字段）
        if age is not None:
            existing_data['age'] = age
        if identity is not None:
            existing_data['identity'] = identity
        if appearance is not None:
            existing_data['appearance'] = appearance
        if personality is not None:
            existing_data['personality'] = personality
        if behavior is not None:
            existing_data['behavior'] = behavior
        if other_info is not None:
            existing_data['other_info'] = other_info
        if reference_image is not None:
            existing_data['reference_image'] = reference_image
        
        # 添加额外字段
        for key, value in additional_fields.items():
            if key not in ['name', 'user_id', 'world_id', 'created_at']:  # 保护核心字段
                existing_data[key] = value
        
        # 更新修改时间
        existing_data['updated_at'] = datetime.now().isoformat()
        
        # 直接写回已解析到的真实文件路径，避免 sanitize 后写到另一个新文件
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(existing_data, f, ensure_ascii=False, indent=2)
            success = True
        except Exception as e:
            logger.error(f"保存角色JSON失败 {file_path}: {e}")
            success = False

        if not success:
            return {
                'success': False,
                'error': '保存角色JSON文件失败'
            }

        # 保存成功后，确保主图 CDN mapping
        try:
            ref_img = existing_data.get('reference_image')
            if ref_img:
                from utils.media_mapping_util import ensure_character_image_mapping
                ensure_character_image_mapping(user_id, world_id, name, ref_img)
        except Exception as e:
            logger.warning(f"CDN mapping for character {name} failed (non-blocking): {e}")

        return {
            'success': True,
            'filename': filename,
            'file_path': file_path,
            'character_data': existing_data,
            'message': f'角色 "{name}" 已成功更新'
        }
        
    except Exception as e:
        return {
            'success': False,
            'error': f'更新角色JSON失败: {str(e)}'
        }


def update_location_json(user_id: str, world_id: str, auth_token: str, name: str, parent_id: str = None,
                        parent_name: str = None,
                        reference_image: str = None, description: str = None, **additional_fields) -> Dict[str, Any]:
    """
    更新地点JSON文件 - MCP工具函数
    
    Args:
        user_id: 用户ID（必填）
        world_id: 世界ID（必填）
        auth_token: 认证令牌（必填）
        name: 地点名称（必填，用于定位文件）
        parent_id: 父级地点 ID 或兼容字段（可选）
        parent_name: 父级地点名称（可选；文件层主字段）
        reference_image: 参考图片（可选）
        description: 地点描述（可选）
        **additional_fields: 额外字段（可选）
    
    Returns:
        dict: 操作结果，包含success状态和相关信息
    """
    try:
        # 验证必填字段
        if not name or not isinstance(name, str):
            return {
                'success': False,
                'error': '地点名称不能为空且必须是字符串'
            }
        
        # 生成安全的文件名
        safe_name = _sanitize_filename(name)
        filename = f"location_{safe_name}.json"
        
        # 使用FileManager统一路径管理
        file_manager = get_file_manager()
        file_path = file_manager.get_content_file_path(user_id, world_id, "locations", filename)
        
        # 检查文件是否存在
        if not os.path.exists(file_path):
            return {
                'success': False,
                'error': f'地点 "{name}" 不存在，无法更新'
            }
        
        # 读取现有数据
        with open(file_path, 'r', encoding='utf-8') as f:
            existing_data = json.load(f)
        
        # 验证reference_image（如果提供）
        if reference_image is not None:
            url_validation = validate_image_url(reference_image, "reference_image")
            if not url_validation['valid']:
                return {
                    'success': False,
                    'error': url_validation['error']
                }

        # 更新字段（只更新提供的非None字段）
        if parent_name is not None or additional_fields.get('parent_name') is not None:
            pn = parent_name if parent_name is not None else additional_fields.get('parent_name')
            pn = (str(pn).strip() if pn is not None and pn != '' else None)
            existing_data['parent_name'] = pn
            # 过渡双写：无显式 parent_id 时用名称
            if parent_id is None:
                existing_data['parent_id'] = pn
        if parent_id is not None:
            existing_data['parent_id'] = parent_id if parent_id != '' else None
        if reference_image is not None:
            existing_data['reference_image'] = reference_image
        if description is not None:
            existing_data['description'] = description
        
        # 添加额外字段
        for key, value in additional_fields.items():
            if key in ('parent_id', 'parent_name'):
                continue
            if key not in ['name', 'user_id', 'world_id', 'created_at']:  # 保护核心字段
                existing_data[key] = value
        
        # 更新修改时间
        existing_data['updated_at'] = datetime.now().isoformat()
        
        # 保存更新后的数据
        success = file_manager.save_json_content(user_id, world_id, "locations", filename, existing_data)

        if not success:
            return {
                'success': False,
                'error': '保存地点JSON文件失败'
            }

        # 保存成功后，确保 CDN mapping
        try:
            ref_img = existing_data.get('reference_image')
            if ref_img:
                from utils.media_mapping_util import ensure_location_image_mapping
                ensure_location_image_mapping(user_id, world_id, name, ref_img)
        except Exception as e:
            logger.warning(f"CDN mapping for location {name} failed (non-blocking): {e}")

        return {
            'success': True,
            'filename': filename,
            'file_path': file_path,
            'location_data': existing_data,
            'message': f'地点 "{name}" 已成功更新'
        }
        
    except Exception as e:
        return {
            'success': False,
            'error': f'更新地点JSON失败: {str(e)}'
        }


def update_prop_json(user_id: str, world_id: str, auth_token: str, name: str, prop_type: str = None, 
                    description: str = None, reference_image: str = None, **additional_fields) -> Dict[str, Any]:
    """
    更新道具JSON文件 - MCP工具函数
    
    Args:
        user_id: 用户ID（必填）
        world_id: 世界ID（必填）
        auth_token: 认证令牌（必填）
        name: 道具名称（必填，用于定位文件）
        prop_type: 道具类型（可选）
        description: 道具描述（可选）
        reference_image: 参考图片（可选）
        **additional_fields: 额外字段（可选）
    
    Returns:
        dict: 操作结果，包含success状态和相关信息
    """
    try:
        # 验证必填字段
        if not name or not isinstance(name, str):
            return {
                'success': False,
                'error': '道具名称不能为空且必须是字符串'
            }
        
        # 生成安全的文件名
        safe_name = _sanitize_filename(name)
        filename = f"prop_{safe_name}.json"
        
        # 使用FileManager统一路径管理
        file_manager = get_file_manager()
        file_path = file_manager.get_content_file_path(user_id, world_id, "props", filename)
        
        # 检查文件是否存在
        if not os.path.exists(file_path):
            return {
                'success': False,
                'error': f'道具 "{name}" 不存在，无法更新'
            }
        
        # 读取现有数据
        with open(file_path, 'r', encoding='utf-8') as f:
            existing_data = json.load(f)
        
        # 验证reference_image（如果提供）
        if reference_image is not None:
            url_validation = validate_image_url(reference_image, "reference_image")
            if not url_validation['valid']:
                return {
                    'success': False,
                    'error': url_validation['error']
                }

        # 更新字段（只更新提供的非None字段）
        if prop_type is not None:
            existing_data['type'] = prop_type
        if description is not None:
            existing_data['description'] = description
        if reference_image is not None:
            existing_data['reference_image'] = reference_image
        
        # 添加额外字段
        for key, value in additional_fields.items():
            if key not in ['name', 'user_id', 'world_id', 'created_at']:  # 保护核心字段
                existing_data[key] = value
        
        # 更新修改时间
        existing_data['updated_at'] = datetime.now().isoformat()
        
        # 保存更新后的数据
        success = file_manager.save_json_content(user_id, world_id, "props", filename, existing_data)

        if not success:
            return {
                'success': False,
                'error': '保存道具JSON文件失败'
            }

        # 保存成功后，确保主图 CDN mapping
        try:
            ref_img = existing_data.get('reference_image')
            if ref_img:
                from utils.media_mapping_util import ensure_prop_image_mapping
                ensure_prop_image_mapping(user_id, world_id, name, ref_img)
        except Exception as e:
            logger.warning(f"CDN mapping for prop {name} failed (non-blocking): {e}")

        return {
            'success': True,
            'filename': filename,
            'file_path': file_path,
            'prop_data': existing_data,
            'message': f'道具 "{name}" 已成功更新'
        }
        
    except Exception as e:
        return {
            'success': False,
            'error': f'更新道具JSON失败: {str(e)}'
        }


def update_script_json(user_id: str, world_id: str, auth_token: str, title: str, episode_number: int = None, content: str = None, **additional_fields) -> Dict[str, Any]:
    """
    更新剧本JSON文件 - MCP工具函数
    
    Args:
        user_id: 用户ID（必填）
        world_id: 世界ID（必填）
        auth_token: 认证令牌（必填）
        title: 剧本标题（必填，用于定位文件）
        episode_number: 计划第几集（可选）
        content: 剧本内容（可选）
        **additional_fields: 额外字段（可选）
    
    Returns:
        dict: 操作结果，包含success状态和相关信息
    """
    try:
        # 验证必填字段
        if not title or not isinstance(title, str):
            return {
                'success': False,
                'error': '剧本标题不能为空且必须是字符串'
            }

        # 使用FileManager查找现有文件（支持新旧文件名格式）
        file_manager = get_file_manager()
        existing_data = file_manager.get_script(title, user_id, world_id)

        if existing_data is None:
            return {
                'success': False,
                'error': f'剧本 "{title}" 不存在，无法更新'
            }

        # 确定文件名：使用已有的或新的 episode_number
        current_episode = existing_data.get('episode_number')
        target_episode = episode_number if episode_number is not None else current_episode

        if target_episode is not None:
            filename = f"{target_episode}.json"
        else:
            safe_title = _sanitize_filename(title)
            filename = f"script_{safe_title}.json"

        file_path = file_manager.get_content_file_path(user_id, world_id, "scripts", filename)

        # 如果集数变更，需要重命名文件（删除旧文件）
        if episode_number is not None and current_episode is not None and episode_number != current_episode:
            old_filename = f"{current_episode}.json"
            old_file_path = file_manager.get_content_file_path(user_id, world_id, "scripts", old_filename)
            if os.path.exists(old_file_path) and old_file_path != file_path:
                # 检查新集数文件是否已存在
                if os.path.exists(file_path):
                    return {
                        'success': False,
                        'error': f'集数冲突：第 {episode_number} 集已存在，无法重命名'
                    }
                try:
                    os.remove(old_file_path)
                    logger.info(f"集数变更，删除旧文件: {old_file_path}")
                except Exception as e:
                    logger.warning(f"删除旧文件失败: {e}")

            # 同时清理旧格式文件
            safe_title = _sanitize_filename(title)
            old_script_file = file_manager.get_content_file_path(user_id, world_id, "scripts", f"script_{safe_title}.json")
            if os.path.exists(old_script_file) and old_script_file != file_path:
                try:
                    os.remove(old_script_file)
                except Exception:
                    pass

        # 更新字段（只更新提供的非None字段）
        if episode_number is not None:
            existing_data['episode_number'] = episode_number
        if content is not None:
            existing_data['content'] = content

        # 添加额外字段
        for key, value in additional_fields.items():
            if key not in ['title', 'user_id', 'world_id', 'create_time']:  # 保护核心字段
                existing_data[key] = value

        # 更新修改时间
        existing_data['update_time'] = datetime.now().isoformat()

        # 保存更新后的数据
        success = file_manager.save_json_content(user_id, world_id, "scripts", filename, existing_data)

        if not success:
            return {
                'success': False,
                'error': '保存剧本JSON文件失败'
            }

        return {
            'success': True,
            'filename': filename,
            'file_path': file_path,
            'script_data': existing_data,
            'message': f'剧本第{target_episode}集 "{title}" 已成功更新'
        }

    except Exception as e:
        return {
            'success': False,
            'error': f'更新剧本JSON失败: {str(e)}'
        }


def _sanitize_filename(name: str) -> str:
    """
    清理文件名，移除不安全字符
    
    Args:
        name: 原始名称
    
    Returns:
        str: 安全的文件名
    """
    # 移除或替换不安全字符
    safe_name = re.sub(r'[<>:"/\\|?*]', '_', name)
    safe_name = re.sub(r'\s+', '_', safe_name)  # 空格替换为下划线
    safe_name = safe_name.strip('._')  # 移除开头结尾的点和下划线
    
    # 限制长度
    if len(safe_name) > 50:
        safe_name = safe_name[:50]
    
    # 确保不为空
    if not safe_name:
        safe_name = "unnamed"
    
    return safe_name


def get_script_problem(user_id: str, world_id: str, auth_token: str, limit: Optional[int] = None) -> Dict[str, Any]:
    """
    获取剧本问题文件内容 - MCP工具函数
    
    Args:
        user_id: 用户ID（必填）
        world_id: 世界ID（必填）
        auth_token: 认证令牌（必填）
        limit: 字符数限制（可选），不填则输出所有内容
    
    Returns:
        dict: 操作结果，包含success状态和文件内容
    """
    try:
        
        # 验证上下文
        if not user_id or not world_id:
            return {
                'success': False,
                'error': '无法获取用户和世界信息，请确保会话已正确初始化',
                'verdict': True,
                'problem': ''
            }
        
        # 使用FileManager读取剧本问题
        file_manager = get_file_manager()
        problem_data = file_manager.get_script_problem(user_id, world_id)
        
        verdict = problem_data.get('verdict', True)
        problem = problem_data.get('problem', '')
        
        # 对problem字段应用limit
        if limit is not None and limit > 0:
            problem = _truncate_content(problem, limit)
        
        return {
            'success': True,
            'verdict': verdict,
            'problem': problem,
            'message': f'成功获取剧本问题 (verdict: {verdict})'
        }
        
    except Exception as e:
        return {
            'success': False,
            'error': f'获取剧本问题失败: {str(e)}',
            'verdict': True,
            'problem': ''
        }


def set_script_problem(user_id: str, world_id: str, auth_token: str, verdict: bool, problem: str) -> Dict[str, Any]:
    """
    设置剧本问题文件内容 - MCP工具函数
    
    Args:
        user_id: 用户ID（必填）
        world_id: 世界ID（必填）
        auth_token: 认证令牌（必填）
        verdict: 判定结果，True表示有问题，False表示无问题
        problem: 问题描述（当verdict为True时必填）
    
    Returns:
        dict: 操作结果，包含success状态和相关信息
    """
    try:
        # 验证问题内容
        if problem is None:
            problem = ''  # 允许空字符串，用于清空问题
        
        # 使用FileManager保存剧本问题
        file_manager = get_file_manager()
        success = file_manager.set_script_problem(verdict, problem, user_id, world_id)
        
        if not success:
            return {
                'success': False,
                'error': '保存剧本问题失败'
            }
        
        return {
            'success': True,
            'message': f'剧本问题已成功保存 (verdict: {verdict}, {len(problem)} 字符)'
        }
        
    except Exception as e:
        return {
            'success': False,
            'error': f'设置剧本问题失败: {str(e)}'
        }


# MCP工具定义（供MCP服务器使用）
MCP_TOOLS = [
    {
        "name": "create_character_json",
        "description": "创建或者更新标准格式的角色JSON文件，确保数据格式一致性。名称语言必须与剧本原文一致（英文剧本用英文名，中文剧本用中文名）",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "角色名称（必须与剧本原文语言一致：英文剧本用英文名，中文剧本用中文名；允许中文、英文、数字、点号、下划线）"
                },
                "age": {
                    "type": "string",
                    "description": "角色年龄（可选）"
                },
                "identity": {
                    "type": "string",
                    "description": "身份（可选）"
                },
                "appearance": {
                    "type": "string",
                    "description": "外貌（可选）"
                },
                "personality": {
                    "type": "string",
                    "description": "性格（可选）"
                },
                "behavior": {
                    "type": "string",
                    "description": "行为（可选）"
                },
                "other_info": {
                    "type": "string",
                    "description": "其他信息（可选）"
                },
                "reference_image": {
                    "type": "string",
                    "description": "参考图片（可选）"
                }
            },
            "required": ["name"]
        }
    },
    {
        "name": "create_script_json",
        "description": "创建或者更新标准格式的剧本JSON文件。标题语言必须与剧本原文一致",
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "剧本标题（必须与剧本原文语言一致；允许中文、英文、数字、点号、下划线）"
                },
                "episode_number": {
                    "type": "integer",
                    "description": "计划第几集（可选）"
                },
                "content": {
                    "type": "string",
                    "description": "剧本内容（可选）"
                }
            },
            "required": ["title"]
        }
    },
    {
        "name": "create_location_json",
        "description": "创建或者更新标准格式的地点JSON文件。名称语言必须与剧本原文一致（英文剧本用英文名，中文剧本用中文名）",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "地点名称（必须与剧本原文语言一致：英文剧本用英文名，中文剧本用中文名；允许中文、英文、数字、点号、下划线）"
                },
                "parent_name": {
                    "type": "string",
                    "description": "父级场景名称（可选；须为已有顶级场景名）"
                },
                "parent_id": {
                    "type": "string",
                    "description": "父级地点ID或兼容字段（可选；优先使用 parent_name）"
                },
                "reference_image": {
                    "type": "string",
                    "description": "参考图片（可选）"
                },
                "description": {
                    "type": "string",
                    "description": "地点描述（可选）"
                }
            },
            "required": ["name"]
        }
    },
    {
        "name": "create_prop_json",
        "description": "创建或者更新标准格式的道具JSON文件。名称语言必须与剧本原文一致（英文剧本用英文名，中文剧本用中文名）",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "道具名称（必须与剧本原文语言一致：英文剧本用英文名，中文剧本用中文名；允许中文、英文、数字、点号、下划线）"
                },
                "prop_type": {
                    "type": "string",
                    "description": "道具类型（可选）"
                },
                "description": {
                    "type": "string",
                    "description": "道具描述（可选）"
                },
                "reference_image": {
                    "type": "string",
                    "description": "参考图片（可选）"
                }
            },
            "required": ["name"]
        }
    },
    {
        "name": "read_character_json",
        "description": "读取指定角色的JSON数据",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "角色名称（允许中文、英文、数字、点号、下划线）"
                },
                "limit": {
                    "type": "integer",
                    "description": "输出字符数限制（可选），不填则输出所有内容"
                }
            },
            "required": ["name"]
        }
    },
    {
        "name": "read_script_json",
        "description": "读取指定剧本的JSON数据",
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "剧本标题（允许中文、英文、数字、点号、下划线）"
                },
                "limit": {
                    "type": "integer",
                    "description": "输出字符数限制（可选），不填则输出所有内容"
                }
            },
            "required": ["title"]
        }
    },
    {
        "name": "read_location_json",
        "description": "读取指定地点的JSON数据",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "地点名称（允许中文、英文、数字、点号、下划线）"
                },
                "limit": {
                    "type": "integer",
                    "description": "输出字符数限制（可选），不填则输出所有内容"
                }
            },
            "required": ["name"]
        }
    },
    {
        "name": "read_prop_json",
        "description": "读取指定道具的JSON数据",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "道具名称（允许中文、英文、数字、点号、下划线）"
                },
                "limit": {
                    "type": "integer",
                    "description": "输出字符数限制（可选），不填则输出所有内容"
                }
            },
            "required": ["name"]
        }
    },
    {
        "name": "list_location_jsons",
        "description": "列出当前世界的所有地点JSON文件",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "list_prop_jsons",
        "description": "列出当前世界的所有道具JSON文件",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "list_character_jsons",
        "description": "列出当前世界的所有角色JSON文件",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "update_character_json",
        "description": "更新角色JSON文件的指定字段",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "角色名称（用于定位文件）"
                },
                "age": {
                    "type": "string",
                    "description": "角色年龄（可选）"
                },
                "identity": {
                    "type": "string",
                    "description": "身份（可选）"
                },
                "appearance": {
                    "type": "string",
                    "description": "外貌（可选）"
                },
                "personality": {
                    "type": "string",
                    "description": "性格（可选）"
                },
                "behavior": {
                    "type": "string",
                    "description": "行为（可选）"
                },
                "other_info": {
                    "type": "string",
                    "description": "其他信息（可选）"
                },
                "reference_image": {
                    "type": "string",
                    "description": "参考图片（可选）"
                }
            },
            "required": ["name"]
        }
    },
    {
        "name": "update_location_json",
        "description": "更新地点JSON文件的指定字段",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "地点名称（用于定位文件）"
                },
                "parent_name": {
                    "type": "string",
                    "description": "父级场景名称（可选；须为已有顶级场景名）"
                },
                "parent_id": {
                    "type": "string",
                    "description": "父级地点ID或兼容字段（可选；优先使用 parent_name）"
                },
                "reference_image": {
                    "type": "string",
                    "description": "参考图片（可选）"
                },
                "description": {
                    "type": "string",
                    "description": "地点描述（可选）"
                }
            },
            "required": ["name"]
        }
    },
    {
        "name": "update_prop_json",
        "description": "更新道具JSON文件的指定字段",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "道具名称（用于定位文件）"
                },
                "prop_type": {
                    "type": "string",
                    "description": "道具类型（可选）"
                },
                "description": {
                    "type": "string",
                    "description": "道具描述（可选）"
                },
                "reference_image": {
                    "type": "string",
                    "description": "参考图片（可选）"
                }
            },
            "required": ["name"]
        }
    },
    {
        "name": "update_script_json",
        "description": "更新剧本JSON文件的指定字段",
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "剧本标题（用于定位文件）"
                },
                "episode_number": {
                    "type": "integer",
                    "description": "计划第几集（可选）"
                },
                "content": {
                    "type": "string",
                    "description": "剧本内容（可选）"
                }
            },
            "required": ["title"]
        }
    },
    {
        "name": "read_world",
        "description": "读取当前世界的完整信息，包括故事大纲、画面风格、时代环境、色彩语言、构图倾向等",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "输出字符数限制（可选），不填则输出所有内容"
                }
            },
            "required": []
        }
    },
    {
        "name": "update_world",
        "description": "更新当前世界的信息，可以更新故事大纲、画面风格、时代环境、色彩语言、构图倾向等字段",
        "inputSchema": {
            "type": "object",
            "properties": {
                "story_outline": {
                    "type": "string",
                    "description": "故事大纲内容（可选）"
                },
                "story_type": {
                    "type": "string",
                    "enum": ["dialogue", "narration", "music_mv"],
                    "description": "故事类型：dialogue=对话剧情，narration=旁白解说，music_mv=音乐MV"
                },
                "visual_style": {
                    "type": "string",
                    "description": "画面风格（可选）"
                },
                "era_environment": {
                    "type": "string",
                    "description": "时代环境（可选）"
                },
                "color_language": {
                    "type": "string",
                    "description": "色彩语言（可选）"
                },
                "composition_preference": {
                    "type": "string",
                    "description": "构图倾向（可选）"
                }
            },
            "required": []
        }
    },
    {
        "name": "list_script_jsons",
        "description": "列出当前世界的所有剧本JSON文件",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "create_world_json",
        "description": "创建标准格式的世界JSON文件",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "世界名称（允许中文、英文、数字、点号、下划线）"
                },
                "description": {
                    "type": "string",
                    "description": "世界描述（可选）"
                }
            },
            "required": ["name"]
        }
    },
    {
        "name": "skill",
        "description": "🚨 MANDATORY: 获取专业技能的完整指导内容。在执行剧本创作、角色设计、场景构建等任务前必须先调用此工具。系统采用渐进式披露架构，所有专业知识存储在外部技能系统中，不调用此工具将无法获得正确的工作指导。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "SkillName": {
                    "type": "string",
                    "description": "要调用的技能名称。必须是可用技能列表中的一个。"
                }
            },
            "required": ["SkillName"]
        }
    },
    {
        "name": "get_script_problem",
        "description": "获取剧本问题文件内容（由content-compliance-checker审核后记录的问题）",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "输出字符数限制（可选），不填则输出所有内容"
                }
            },
            "required": []
        }
    },
    {
        "name": "set_script_problem",
        "description": "设置剧本问题文件内容（用于记录审核报告和发现的问题）",
        "inputSchema": {
            "type": "object",
            "properties": {
                "verdict": {
                    "type": "boolean",
                    "description": "审核结果，true表示通过，false表示不通过"
                },
                "problem": {
                    "type": "string",
                    "description": "剧本问题文本，通常是审核报告的完整内容"
                }
            },
            "required": ["verdict", "problem"]
        }
    },
    {
        "name": "get_long_user_input",
        "description": "读取用户长文本输入的完整内容。当用户输入超过5000字时，系统会自动保存完整内容到文件，并在消息中提示文件名。使用此工具可以读取完整内容。如果文件不存在，会返回可用文件列表供纠错。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "长文本文件名。请使用用户消息中系统提示给出的文件名（形如 - 文件名：xxx.txt）。注意：不要凭空编造文件名，必须使用上下文中实际出现的文件名；若文件不存在，工具会返回可用文件列表供纠错。"
                },
                "limit": {
                    "type": "integer",
                    "description": "可选，限制返回字符数，避免token消耗过大。不填则返回完整内容。"
                }
            },
            "required": ["name"]
        }
    },
    {
        "name": "get_text_to_image_model_info",
        "description": "获取当前用户选中的生图模型信息，包括模型名称、算力价格、支持的尺寸和比例、是否支持4宫格等。在生成图片前调用此工具可以了解模型能力和成本。",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "get_user_computing_power",
        "description": "查询当前用户的剩余算力余额。在批量生成图片前调用此工具，可以预估是否有足够算力完成任务，避免提交后因算力不足而失败。",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "list_video_models",
        "description": "查询当前可用的视频模型列表（含 task_id、算力、支持的时长/比例/图模式）。视频生成工具（image_to_video / generate_text_to_video）要求显式传入 task_type 参数，因此在调用视频生成工具之前，必须先调用本工具获取可用模型的 task_id，再选取一个合适的模型将其 task_id 作为 task_type 传入。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "description": "模型类别（可选，默认 image_to_video）：image_to_video（图生视频，基于图片生成视频）或 text_to_video（文生视频，纯文本生成视频）",
                    "default": "image_to_video"
                }
            },
            "required": []
        }
    },
    {
        "name": "list_llm_models",
        "description": "查询当前可用的大语言模型（LLM）列表及费用（含 input/output/cache_read 三档算力阈值与换算单价）。调用 split-from-script / create-storyboard-from-script 等需要 LLM 的命令前，可先用本工具查询模型并对比费用，选取后将 name 作为 model、model_id 作为 model_id、vendor_id 作为 vendor_id 传入对应命令。",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "generate_text_to_image",
        "description": "文本生图（非阻塞）。发起图片生成请求，立即返回project_ids。返回结果包含 model_used、image_size_used、computing_power_required 等算力信息。注意：生图模型由用户在前端界面选择，不同模型算力价格不同，请先调用 get_text_to_image_model_info 了解当前模型。覆盖已有 reference_image 时必须传 force_update_exist_image=true，且仅限本单图工具；4宫格工具不支持强制覆盖。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "图片描述提示词（必填），例如：'一个女孩，漫画风格'"
                },
                "aspect_ratio": {
                    "type": "string",
                    "description": "【已由系统注入，无需传入】图片宽高比。用户在界面上已选择，系统会自动应用。"
                },
                "count": {
                    "type": "integer",
                    "description": "生成图片数量（可选，默认：1）"
                },
                "image_size": {
                    "type": "string",
                    "description": "【已由系统注入，无需传入】图片分辨率。用户在界面上已选择，系统会自动应用。"
                },
                "item_type": {
                    "type": "integer",
                    "description": "物品类型（可选）：1=角色(character), 2=地点(location), 3=道具(props)。指定后会创建后台任务自动处理"
                },
                "item_name": {
                    "type": "string",
                    "description": "物品名称（可选），当指定item_type时必填，会自动更新对应物品的reference_image字段"
                },
                "force_update_exist_image": {
                    "type": "boolean",
                    "description": "是否强制覆盖已有参考图像（默认：false）。仅本单图工具支持；4宫格工具不支持。false：若角色/场景/道具已有 reference_image 则跳过；true：覆盖现有图像。仅在用户明确确认覆盖后才能设为 true",
                    "default": False
                }
            },
            "required": ["prompt"]
        }
    },
    {
        "name": "generate_4grid_character_images",
        "description": "生成4宫格角色图像并自动切分更新到各个角色（一站式解决方案）。自动构建4宫格JSON格式，使用模型支持的最大分辨率生成图像（如4K/3K/2K，取决于所选模型），轮询等待生成完成，自动下载并切分4宫格图像为4个独立图像，自动更新每个角色的reference_image字段。注意：不同生图模型算力价格不同，请先调用 get_text_to_image_model_info 了解当前模型。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "character_names": {
                    "type": "array",
                    "items": {
                        "type": "string"
                    },
                    "description": "4个角色的名称列表（必须是4个），例如：['角色1', '角色2', '角色3', '角色4']"
                },
                "prompts": {
                    "type": "array",
                    "items": {
                        "type": "string"
                    },
                    "description": "4个角色的完整提示词列表（必须是4个），每个提示词对应一个角色的详细描述"
                }
            },
            "required": ["character_names", "prompts"]
        }
    },
    {
        "name": "generate_4grid_location_images",
        "description": "生成4宫格场景图像并自动切分更新到各个场景（一站式解决方案）。自动构建4宫格JSON格式，使用模型支持的最大分辨率生成图像（如4K/3K/2K，取决于所选模型），轮询等待生成完成，自动下载并切分4宫格图像为4个独立图像，自动更新每个场景的reference_image字段。注意：不同生图模型算力价格不同，请先调用 get_text_to_image_model_info 了解当前模型。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "location_names": {
                    "type": "array",
                    "items": {
                        "type": "string"
                    },
                    "description": "4个场景的名称列表（必须是4个），例如：['场景1', '场景2', '场景3', '场景4']。如果实际场景少于4个，用'placeholder'补齐"
                },
                "prompts": {
                    "type": "array",
                    "items": {
                        "type": "string"
                    },
                    "description": "4个场景的完整提示词列表（必须是4个），每个提示词对应一个场景的详细描述。如果实际场景少于4个，用'pure black background'补齐"
                }
            },
            "required": ["location_names", "prompts"]
        }
    },
    {
        "name": "generate_4grid_prop_images",
        "description": "生成4宫格道具图像并自动切分更新到各个道具（一站式解决方案）。自动构建4宫格JSON格式，使用模型支持的最大分辨率生成图像（如4K/3K/2K，取决于所选模型），轮询等待生成完成，自动下载并切分4宫格图像为4个独立图像，自动更新每个道具的reference_image字段。注意：不同生图模型算力价格不同，请先调用 get_text_to_image_model_info 了解当前模型。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "prop_names": {
                    "type": "array",
                    "items": {
                        "type": "string"
                    },
                    "description": "4个道具的名称列表（必须是4个），例如：['道具1', '道具2', '道具3', '道具4']。如果实际道具少于4个，用'placeholder'补齐"
                },
                "prompts": {
                    "type": "array",
                    "items": {
                        "type": "string"
                    },
                    "description": "4个道具的完整提示词列表（必须是4个），每个提示词对应一个道具的详细描述。如果实际道具少于4个，用'pure black background'补齐"
                }
            },
            "required": ["prop_names", "prompts"]
        }
    },
    {
        "name": "get_task_status",
        "description": "查询指定项目的图片生成任务状态，从文件系统中读取状态信息。**重要**: 仅支持单个图片生成任务（generate_text_to_image），不支持多宫格生成任务（generate_4grid_character_images、generate_4grid_location_images、generate_4grid_prop_images），请勿对多宫格任务调用此工具",
        "inputSchema": {
            "type": "object",
            "properties": {
                "item_type": {
                    "type": "integer",
                    "description": "项目类型: 1=角色, 2=场景, 3=道具"
                },
                "item_name": {
                    "type": "string",
                    "description": "项目对应名称，比如角色名，场景名，道具名等"
                }
            },
            "required": ["item_type", "item_name"]
        }
    },
    {
        "name": "check_image_status",
        "description": "通过 project_id 查询图片生成结果（一次性查询）。后台会自动跟踪生图进度，调用此函数直接从数据库读取最终状态和图片URL。适用于不绑定item的通用生图场景（如营销图片）。建议在 generate_text_to_image 或 edit_image 返回后等待一段时间再调用，给后台留出处理时间。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {
                    "type": "string",
                    "description": "generate_text_to_image 或 edit_image 返回的 project_ids 数组中的第一个元素"
                }
            },
            "required": ["project_id"]
        }
    },
    {
        "name": "edit_image",
        "description": "图片编辑（图生图）。根据用户提供的原始图片URL和编辑指令，调用图片编辑API生成新图片。非阻塞，立即返回project_ids。后台会自动跟踪进度，通过 check_image_status 查询结果。注意：图片编辑模型由用户在前端界面选择，不同模型算力价格不同，请先调用 get_text_to_image_model_info 了解当前模型。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "图片编辑指令（必填），例如：'将背景替换为海滩'、'转为水彩画风格'、'添加圣诞装饰'"
                },
                "image_url": {
                    "type": "string",
                    "description": "原始图片URL（必填），仅支持 http/https URL；支持多张图片用英文逗号分隔。对话中每张图片都有 [图片N]（URL: ...） 标签，请将所有需要编辑的图片 URL 用逗号拼接后传入。例如：'http://xxx/a.jpg,http://xxx/b.jpg'。不要传入 /upload/...、upload/... 或本地文件路径。"
                },
                "aspect_ratio": {
                    "type": "string",
                    "description": "【已由系统注入，无需传入】图片宽高比。用户在界面上已选择，系统会自动应用。"
                },
                "count": {
                    "type": "integer",
                    "description": "生成图片数量（可选，默认：1）"
                },
                "image_size": {
                    "type": "string",
                    "description": "【已由系统注入，无需传入】图片分辨率。用户在界面上已选择，系统会自动应用。"
                }
            },
            "required": ["prompt", "image_url"]
        }
    },
    {
        "name": "generate_text_to_video",
        "description": "文本生成视频（非阻塞）。发起视频生成请求，立即返回 project_ids。非阻塞，后台自动跟踪进度。视频模型由系统自动选择（用户偏好/默认），请先调用 get_user_computing_power 确认算力是否充足。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "视频描述提示词（必填），详细描述画面内容、运动方式、风格、镜头运动等。使用英文编写效果最佳。"
                },
                "ratio": {
                    "type": "string",
                    "description": "【已由系统注入，无需传入】视频宽高比。用户在界面上已选择，系统会自动应用。"
                },
                "duration_seconds": {
                    "type": "integer",
                    "description": "【已由系统注入，无需传入】视频时长（秒）。用户在界面上已选择，系统会自动应用。"
                },
                "count": {
                    "type": "integer",
                    "description": "生成视频数量（可选，默认：1）"
                }
            },
            "required": ["prompt"]
        }
    },
    {
        "name": "image_to_video",
        "description": "图片生成视频（图生视频，非阻塞）。基于参考图片和/或参考视频和/或参考音频生成视频，立即返回 project_ids。非阻塞，后台自动跟踪进度。⚠️ 严禁捏造图片/视频URL，必须是对话中真实存在的地址。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "视频描述/运动指令（必填），描述希望视频中出现的运动效果、镜头变化等。"
                },
                "image_urls": {
                    "type": "string",
                    "description": "参考图片URL（可选），多张用英文逗号分隔。对话中每张图片都有 [图片N]（URL: ...） 标签，请将所有图片 URL 用逗号拼接后传入。例如：'http://xxx/a.jpg,http://xxx/b.jpg'。视频克隆场景中可只传 video_urls 不传此参数。"
                },
                "ratio": {
                    "type": "string",
                    "description": "【已由系统注入，无需传入】视频宽高比。用户在界面上已选择，系统会自动应用。"
                },
                "duration_seconds": {
                    "type": "integer",
                    "description": "【已由系统注入，无需传入】视频时长（秒）。用户在界面上已选择，系统会自动应用。"
                },
                "count": {
                    "type": "integer",
                    "description": "生成视频数量（可选，默认：1）"
                },
                "image_mode": {
                    "type": "string",
                    "description": "图片模式（可选，默认 first_last_frame）：first_last_frame（首尾帧）或 multi_reference（全能参考）"
                },
                "video_urls": {
                    "type": "string",
                    "description": "参考视频URL（可选），多个用英文逗号分隔。仅部分模型支持（如 Seedance 2.0）。用于提供驱动视频，让生成的视频模仿参考视频的运动风格。"
                },
                "audio_urls": {
                    "type": "string",
                    "description": "参考音频URL（可选），多个用英文逗号分隔。仅部分模型支持。用于提供驱动音频，让生成的视频配合音频节奏。"
                }
            },
            "required": ["prompt"]
        }
    },
    {
        "name": "fetch_image_as_base64",
        "description": "下载图片并获取其 base64 数据。当你看到对话中 [图片N] 标签显示「该图片加载失败」时，立即调用此工具传入对应的图片 URL 来重新获取图片数据。调用成功后图片将自动注入到你的对话中，你就能看到并分析图片了。也可用于获取对话中任何图片 URL 对应的图片数据。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "image_url": {
                    "type": "string",
                    "description": "图片 URL（必填），对话中 [图片N]（URL: ...）标签里的 URL 地址"
                },
                "max_size_mb": {
                    "type": "number",
                    "description": "最大文件大小（MB），可选，默认 2.0。如果图片较大可适当调高。"
                }
            },
            "required": ["image_url"]
        }
    },
    {
        "name": "generate_character_reference_audio",
        "description": "为角色生成参考音频（异步非阻塞）。根据角色设定自动构建提示词，提交音频生成任务。返回 task_id（async_tasks 表主键），可通过 check_reference_audio_status 查询生成状态。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "character_name": {
                    "type": "string",
                    "description": "角色名称（必填）"
                },
                "style_prompt": {
                    "type": "string",
                    "description": "自定义风格提示词（可选），不填则根据角色设定自动生成，强调平静、自然的语气"
                },
                "text": {
                    "type": "string",
                    "description": "自定义文本内容（可选），不填则根据角色设定自动生成自我介绍"
                }
            },
            "required": ["character_name"]
        }
    },
    {
        "name": "generate_reference_audio",
        "description": "生成通用参考音频（异步非阻塞）。不依赖角色卡，直接根据文本和声音风格提示词提交音频生成任务。返回 task_id，可通过 check_reference_audio_status 查询生成状态并获取 audio_url。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "要朗读的文本内容（必填），例如数字人口播文案"
                },
                "style_prompt": {
                    "type": "string",
                    "description": "声音风格提示词（可选），例如：自然、平静、年轻女性声音、语速适中。不填则使用默认自然声音"
                }
            },
            "required": ["text"]
        }
    },
    {
        "name": "check_reference_audio_status",
        "description": "查询角色参考音频生成任务状态。后台 scheduler 会自动轮询 RunningHub 状态并更新数据库。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "任务ID（必填），即 async_tasks 表主键，由 generate_character_reference_audio 返回"
                },
                "character_name": {
                    "type": "string",
                    "description": "角色名称（可选），仅用于返回信息"
                }
            },
            "required": ["task_id"]
        }
    },
    {
        "name": "generate_digital_human",
        "description": "生成数字人视频（非阻塞）。根据人物图片、口播文本和参考音频 URL 立即提交数字人生成任务，返回 project_ids。必须传入真实 audio_url；如果用户没有提供音频，请先调用 generate_reference_audio 生成并查询到 audio_url。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "image_url": {
                    "type": "string",
                    "description": "人物图片 URL（必填），必须来自对话中的真实图片 URL"
                },
                "text": {
                    "type": "string",
                    "description": "数字人需要说的文本（必填）"
                },
                "audio_url": {
                    "type": "string",
                    "description": "参考音频 URL（必填），必须是对话中用户上传的音频 URL，或 generate_reference_audio 完成后返回的 audio_url"
                },
                "aspect_ratio": {
                    "type": "string",
                    "description": "视频比例，可选，默认 9:16"
                }
            },
            "required": ["image_url", "text", "audio_url"]
        }
    },
    {
        "name": "generate_character_variant_image",
        "description": "为角色生成造型变体图（服装/造型三视角参考图）。基于角色已有主参考图(reference_image)做图片编辑（图生图），保证五官/身份一致，仅改变服装/造型。禁止用文生图生成额外形象。生成完成后自动写入角色的 reference_images 数组。注意：角色必须已存在且已有主参考图，才能生成变体图。请先调用 get_text_to_image_model_info 了解当前模型。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "character_name": {
                    "type": "string",
                    "description": "角色名称（必填），如\"豆包\""
                },
                "variant_label": {
                    "type": "string",
                    "description": "变体标签（必填），如\"晚礼服\"、\"战斗装\"、\"黑化形态\"，用于在 reference_images 中标识该变体"
                },
                "variant_prompt": {
                    "type": "string",
                    "description": "三视角编辑提示词（必填）。必须强调保持参考图中同一人物的五官/体型/身份一致，仅改变服装/造型；必须包含三视角（正面、侧面、背面）描述，末尾必须包含反文字声明"
                },
                "aspect_ratio": {
                    "type": "string",
                    "description": "图片宽高比（默认：16:9）",
                    "default": "16:9"
                },
                "force_update": {
                    "type": "boolean",
                    "description": "是否覆盖已有同标签变体图（默认：False）",
                    "default": False
                }
            },
            "required": ["character_name", "variant_label", "variant_prompt"]
        }
    }
]


def list_script_jsons(user_id: str, world_id: str, auth_token: str) -> Dict[str, Any]:
    """
    列出所有剧本JSON文件 - MCP工具函数
    
    Args:
        user_id: 用户ID（必填）
        world_id: 世界ID（必填）
        auth_token: 认证令牌（必填）
    
    Returns:
        dict: 包含success状态和剧本文件列表的结果
    """
    try:
        # 获取上下文信息
        # context = get_context()
        # user_id = context.get('user_id')
        # world_id = context.get('world_id')
        
        # 验证上下文
        if not user_id or not world_id:
            return {
                'success': False,
                'error': '无法获取用户和世界信息，请确保会话已正确初始化',
                'data': []
            }
        
        # 使用FileManager统一路径管理
        file_manager = get_file_manager()
        scripts_dir = file_manager.get_content_dir_path(user_id, world_id, "scripts")
        
        if not os.path.exists(scripts_dir):
            return {
                'success': True,
                'data': [],
                'message': '剧本目录不存在，返回空列表'
            }
        
        files = []
        for filename in os.listdir(scripts_dir):
            if filename.endswith(".json"):
                # 读取文件获取结构化数据
                try:
                    file_path = os.path.join(scripts_dir, filename)
                    with open(file_path, 'r', encoding='utf-8') as f:
                        script_data = json.load(f)
                    ep = script_data.get('episode_number')
                    title = script_data.get('title', filename.replace('.json', ''))
                    display_name = f"第{ep}集：{title}" if ep is not None else title
                    files.append({
                        'filename': filename,
                        'title': title,
                        'episode_number': ep,
                        'display_name': display_name
                    })
                except Exception:
                    files.append({
                        'filename': filename,
                        'title': filename.replace('.json', ''),
                        'episode_number': None,
                        'display_name': filename.replace('.json', '')
                    })

        # 按集数排序
        files.sort(key=lambda x: (x['episode_number'] is None, x['episode_number'] or 0))

        return {
            'success': True,
            'data': files,
            'message': f'成功获取 {len(files)} 个剧本文件'
        }
        
    except Exception as e:
        return {
            'success': False,
            'error': f'列出剧本文件失败: {str(e)}',
            'data': []
        }


def skill(SkillName: str) -> Dict[str, Any]:
    """
    调用指定技能获取详细指导和提示词 - MCP工具函数
    ⚠️ 参数名 SkillName 使用大写开头，因为这是 MCP 工具函数，参数名会暴露给 LLM，大写更易读
    ⚠️ 此函数签名与其他 mcp_tool 函数不同（无 user_id/world_id/auth_token），因为它不依赖用户上下文

    Args:
        SkillName: 技能名称
        
    Returns:
        dict: 包含技能详细内容的字典
    """
    try:
        log_skill_interaction(f"[技能调用] 开始调用技能: {SkillName}", {"skill_name": SkillName})
        skill_loader = get_skill_loader()
        
        # 检查技能是否存在
        available_skills = skill_loader.list_skills()
        log_skill_interaction(f"[技能调用] 可用技能列表: {available_skills}", {"available_skills": available_skills})
        
        if SkillName not in available_skills:
            error_msg = f'技能 "{SkillName}" 不存在。可用技能: {", ".join(available_skills)}'
            log_skill_interaction(f"[技能调用错误] {error_msg}", {"skill_name": SkillName, "error": error_msg})
            return {
                'success': False,
                'error': error_msg,
                'content': ''
            }
        
        # 获取技能的完整内容
        log_skill_interaction(f"[技能调用] 开始加载技能内容: {SkillName}", {"skill_name": SkillName})
        skill_data = skill_loader.get_skill_full_content(SkillName)
        if not skill_data:
            error_msg = f'无法加载技能 "{SkillName}" 的内容'
            log_skill_interaction(f"[技能调用错误] {error_msg}", {"skill_name": SkillName, "error": error_msg})
            return {
                'success': False,
                'error': error_msg,
                'content': ''
            }
        
        # 构建技能内容响应
        skill_content = f"# {skill_data.get('name', SkillName)} 技能\n\n"
        
        if skill_data.get('description'):
            skill_content += f"**描述**: {skill_data['description']}\n\n"
        
        skill_content += skill_data.get('prompt', '')
        
        log_skill_interaction(f"[技能调用] 成功加载技能: {SkillName}, 内容长度: {len(skill_content)}", {
            "skill_name": SkillName, 
            "content_length": len(skill_content)
        })
        
        result = {
            'success': True,
            'message': f'成功加载技能 "{SkillName}"',
            'content': skill_content,
            'skill_name': SkillName,
            'metadata': skill_loader.get_skill_metadata(SkillName)
        }
        
        log_skill_interaction(f"[技能调用] 返回结果: success={result['success']}, message={result['message']}", {
            "skill_name": SkillName,
            "success": result['success'],
            "message": result['message']
        })
        return result
        
    except Exception as e:
        error_msg = f'调用技能失败: {str(e)}'
        log_skill_interaction(f"[技能调用异常] {error_msg}", {
            "skill_name": SkillName,
            "error": str(e)
        })
        import traceback
        log_skill_interaction(f"[技能调用异常] 堆栈跟踪", {
            "skill_name": SkillName,
            "traceback": traceback.format_exc()
        })
        return {
            'success': False,
            'error': error_msg,
            'content': ''
        }


# ============ 音色相关 MCP 工具函数 ============

def _create_reference_audio_task(
    user_id: str,
    world_id: str,
    text: str,
    style_prompt: Optional[str] = None,
    character_name: Optional[str] = None,
) -> int:
    """Create a RunningHub reference-audio async task."""
    try:
        normalized_user_id = int(user_id)
    except (ValueError, TypeError):
        raise ValueError(f'无效的 user_id: {user_id}')

    final_style_prompt = (
        style_prompt
        or '声音自然清晰，语气平稳，语速适中，适合数字人口播'
    )
    final_text = (text or '').strip()
    if not final_text:
        raise ValueError('音频文本不能为空')

    from model import AsyncTasksModel
    from config.unified_config import AsyncTaskImplementationId

    params = {
        'style_prompt': final_style_prompt,
        'text': final_text,
        'world_id': world_id
    }
    if character_name:
        params['character_name'] = character_name

    return AsyncTasksModel.create_and_schedule(
        implementation=AsyncTaskImplementationId.RUNNINGHUB_AUDIO,
        user_id=normalized_user_id,
        params=params,
        max_attempts=25
    )


def generate_reference_audio(
    user_id: str,
    world_id: str,
    auth_token: str,
    text: str,
    style_prompt: Optional[str] = None,
) -> Dict[str, Any]:
    """
    生成通用参考音频 - MCP工具函数（异步非阻塞）。

    不依赖角色卡，适用于数字人口播等营销场景。返回 async_tasks 主键，
    后续通过 check_reference_audio_status 查询完成后的 audio_url。
    """
    try:
        from config.config_util import get_dynamic_config_value
        runninghub_api_key = get_dynamic_config_value("runninghub", "api_key", default="")
        if not runninghub_api_key:
            return {
                'success': False,
                'error': '参考音频生成功能依赖 RunningHub 服务，但尚未配置 RunningHub API Key。'
            }

        task_id = _create_reference_audio_task(
            user_id=user_id,
            world_id=world_id,
            text=text,
            style_prompt=style_prompt,
        )

        return {
            'success': True,
            'task_id': task_id,
            'message': f'已提交参考音频生成任务 (task_id={task_id})，请使用 check_reference_audio_status 查询生成状态'
        }
    except Exception as e:
        logger.error(f"generate_reference_audio error: {e}", exc_info=True)
        return {
            'success': False,
            'error': f'生成参考音频失败: {str(e)}'
        }


def generate_character_reference_audio(user_id: str, world_id: str, auth_token: str,
                                       character_name: str,
                                       style_prompt: Optional[str] = None,
                                       text: Optional[str] = None,
                                       model: Optional[str] = None,
                                       vendor_id: Optional[int] = None) -> Dict[str, Any]:
    """
    为角色生成参考音频 - MCP工具函数（同步非阻塞）

    创建异步任务记录，由 scheduler 后台统一处理提交到 RunningHub 和状态轮询。

    Args:
        user_id: 用户ID（必填）
        world_id: 世界ID（必填）
        auth_token: 认证令牌（必填）
        character_name: 角色名称（必填）
        style_prompt: 自定义风格提示词（可选），不填则根据角色设定自动生成
        text: 自定义文本内容（可选），不填则根据角色设定自动生成

    Returns:
        dict: 包含 task_id 的结果，可用于 check_reference_audio_status 查询
    """
    try:
        # 检查 RunningHub API Key 是否已配置
        from config.config_util import get_dynamic_config_value
        runninghub_api_key = get_dynamic_config_value("runninghub", "api_key", default="")
        if not runninghub_api_key:
            return {
                'success': False,
                'error': '参考音频生成功能依赖 RunningHub 服务，但尚未配置 RunningHub API Key。请在系统设置的快速配置中填写 runninghub.api_key 后重试。'
            }

        # 验证必填字段
        if not character_name or not isinstance(character_name, str):
            return {
                'success': False,
                'error': '角色名称不能为空且必须是字符串'
            }

        # 从角色JSON中获取角色数据
        file_manager = get_file_manager()
        character_data = file_manager.get_character_json(character_name, user_id, world_id)

        if not character_data:
            return {
                'success': False,
                'error': f'角色 "{character_name}" 不存在'
            }

        # 构建提示词（复用 task/audio_task.py 中的函数）
        from task.audio_task import build_character_audio_text, build_character_audio_style_prompt
        import asyncio
        
        # 在同步函数中调用异步函数
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        
        # 使用 LLM 智能判断角色发声类型并生成文本和风格提示词
        final_text = loop.run_until_complete(
            build_character_audio_text(character_data, text, model=model, vendor_id=vendor_id)
        )
        final_style_prompt = loop.run_until_complete(
            build_character_audio_style_prompt(character_data, style_prompt, model=model, vendor_id=vendor_id)
        )

        task_id = _create_reference_audio_task(
            user_id=user_id,
            world_id=world_id,
            text=final_text,
            style_prompt=final_style_prompt,
            character_name=character_name,
        )

        return {
            'success': True,
            'task_id': task_id,
            'character_name': character_name,
            'message': f'已为角色 "{character_name}" 提交参考音频生成任务 (task_id={task_id})，请使用 check_reference_audio_status 查询生成状态'
        }

    except Exception as e:
        logger.error(f"generate_character_reference_audio error: {e}", exc_info=True)
        return {
            'success': False,
            'error': f'生成参考音频失败: {str(e)}'
        }


def check_reference_audio_status(user_id: str, world_id: str, auth_token: str,
                                   task_id: str,
                                   character_name: Optional[str] = None) -> Dict[str, Any]:
    """
    查询角色参考音频生成任务状态 - MCP工具函数（同步，直接查数据库）

    后台 scheduler 会自动轮询 RunningHub 状态并更新数据库，本函数直接读取数据库中的任务状态。
    task_id 为 create_and_schedule 返回的 async_tasks 表主键。

    Args:
        user_id: 用户ID（必填）
        world_id: 世界ID（必填）
        auth_token: 认证令牌（必填）
        task_id: 任务ID（必填），即 async_tasks 表主键
        character_name: 角色名称（可选，仅用于返回信息）

    Returns:
        dict: 包含任务状态和结果URL的结果
    """
    try:
        from model import AsyncTasksModel, AsyncTaskStatus

        # task_id 可能是 async_tasks 主键，也可能是 external_task_id（RunningHub project_id）
        # 优先按主键（数字）查询，失败则按 external_task_id 查询
        task = None
        if task_id.isdigit():
            task = AsyncTasksModel.get_by_id(int(task_id))

        if not task:
            task = AsyncTasksModel.get_by_external_task_id(task_id)
        if not task:
            return {
                'success': True,
                'status': 'not_found',
                'task_id': task_id,
                'message': f'未找到 task_id={task_id} 对应的任务记录'
            }

        # 状态映射
        status_map = {
            AsyncTaskStatus.QUEUED: 'queued',
            AsyncTaskStatus.PROCESSING: 'processing',
            AsyncTaskStatus.COMPLETED: 'completed',
            AsyncTaskStatus.FAILED: 'failed',
            AsyncTaskStatus.TIMEOUT: 'timeout',
        }
        readable_status = status_map.get(task.status, 'unknown')

        result = {
            'success': True,
            'status': readable_status,
            'task_id': task_id,
            'message': f'任务状态: {readable_status}'
        }

        if task.external_task_id:
            result['runninghub_task_id'] = task.external_task_id

        if task.status == AsyncTaskStatus.COMPLETED and task.result_url:
            result['audio_url'] = task.result_url
            result['message'] = f'音频生成完成，音频URL: {task.result_url}'

        if task.status in (AsyncTaskStatus.FAILED, AsyncTaskStatus.TIMEOUT):
            result['success'] = False
            result['error'] = task.error_message or '音频生成失败'
            result['message'] = f'音频生成失败: {result["error"]}'

        return result

    except Exception as e:
        logger.error(f"check_reference_audio_status error: {e}", exc_info=True)
        return {
            'success': False,
            'error': f'查询音频状态失败: {str(e)}'
        }


def generate_digital_human(
    user_id: str,
    world_id: str,
    auth_token: str,
    image_url: str,
    text: str,
    audio_url: str = None,
    aspect_ratio: str = "9:16"
) -> Dict[str, Any]:
    """
    生成数字人视频 - MCP工具函数（非阻塞版本）

    根据参考图片、参考音频和文本内容生成数字人视频。立即返回 project_ids。
    非阻塞，后台自动跟踪进度。

    注意：如果没有提供 audio_url，需要先调用 generate_character_reference_audio 生成参考音频，
    获取音频URL后再传入此参数。

    Args:
        user_id: 用户ID（必填）
        world_id: 世界ID（必填）
        auth_token: 认证令牌（必填）
        image_url: 数字人参考图片URL（必填）
        text: 数字人要说的文本内容（必填），不超过1000字
        audio_url: 参考音频URL（可选），用于生成数字人的语音
        aspect_ratio: 视频宽高比（默认 9:16），支持 9:16、16:9、1:1、3:2、4:3、2:3、3:4

    Returns:
        dict: 操作结果，包含 success、project_ids、status 等
    """
    try:
        # 验证参数
        if not image_url or not isinstance(image_url, str):
            return {'success': False, 'error': '图片URL不能为空且必须是字符串'}

        # 校验 image_url 格式：必须是有效路径或URL
        image_url = image_url.strip()
        _is_valid_image_path = (
            image_url.startswith('/') or
            image_url.startswith('upload/') or
            image_url.startswith('http://') or
            image_url.startswith('https://') or
            (len(image_url) > 2 and image_url[1] == ':')
        )
        if not _is_valid_image_path:
            # 尝试从中提取 project_id 并查数据库获取真实图片 URL
            _match = re.search(r'(\d+)', image_url)
            _resolved = False
            if _match:
                try:
                    from model.ai_tools import AIToolsModel
                    _project_id_num = int(_match.group(1))
                    _ai_tool_record = AIToolsModel.get_by_id(_project_id_num)
                    if _ai_tool_record and _ai_tool_record.result_url:
                        logger.info(f"generate_digital_human: 自动解析 '{image_url}' -> project {_project_id_num} -> {_ai_tool_record.result_url}")
                        image_url = _ai_tool_record.result_url
                        _resolved = True
                except Exception as e:
                    logger.warning(f"generate_digital_human: 尝试解析 project_id 失败: {e}")
            if not _resolved:
                return {
                    'success': False,
                    'error': f'image_url "{image_url}" 不是有效的图片路径。'
                             f'请传入真实的图片URL（如 /upload/generated/image/774.png），'
                             f'而不是引用描述。可调用 check_image_status 获取真实图片URL。'
                }

        if not text or not isinstance(text, str):
            return {'success': False, 'error': '文本内容不能为空且必须是字符串'}

        if len(text) > 1000:
            return {'success': False, 'error': '文本内容不能超过1000个字'}

        if not audio_url:
            return {
                'success': False,
                'error': '未提供参考音频URL。请先调用 generate_character_reference_audio 生成参考音频，获取音频URL后再调用此工具。'
            }

        # 获取服务器配置
        server_config = get_config().get("server", {})
        base_url = server_config.get("comfyui_base_url_inner") or server_config.get("host", "")

        if not base_url:
            return {'success': False, 'error': '配置文件中未找到服务器地址'}

        # 获取数字人模型配置（digital_human 分类）
        from config.unified_config import UnifiedConfigRegistry, TaskCategory
        configs = UnifiedConfigRegistry.get_by_category(TaskCategory.DIGITAL_HUMAN)
        if not configs:
            return {'success': False, 'error': '未找到可用的数字人模型配置'}

        # 获取第一个启用的模型
        enabled_configs = [c for c in configs if c.enabled and not c.hidden]
        if not enabled_configs:
            return {'success': False, 'error': '未找到启用的数字人模型配置'}

        task_config = enabled_configs[0]
        task_id = task_config.id
        model_name = task_config.name

        # 计算预估算力
        computing_power = task_config.get_computing_power() if task_config else 0

        # 构建请求数据
        request_data = {
            'image_url': image_url,
            'text': text,
            'audio_url': audio_url,
            'aspect_ratio': aspect_ratio,
            'user_id': str(user_id),
            'auth_token': auth_token
        }
        # 调用后端数字人生成API
        api_url = f"{base_url.rstrip('/')}/api/digital-human"

        try:
            response = httpx.post(api_url, data=request_data, timeout=30, verify=False, trust_env=False)
            response.raise_for_status()

            result_data = response.json()

            if not result_data.get('success'):
                return {
                    'success': False,
                    'error': result_data.get('error', '数字人生成请求失败')
                }

            project_id = result_data.get('project_id')
            if not project_id:
                return {'success': False, 'error': '数字人生成请求成功但未返回 project_id'}

            return {
                'success': True,
                'project_ids': [str(project_id)],
                'status': 'submitted',
                'model_used': model_name,
                'computing_power_required': computing_power,
                'message': f'数字人生成请求已提交（使用模型: {model_name}），project_id: {project_id}'
            }

        except httpx.HTTPStatusError as e:
            error_detail = ''
            try:
                error_body = e.response.json()
                error_detail = error_body.get('detail', str(e))
            except Exception:
                error_detail = str(e)
            logger.error(f"数字人生成 API 错误: {error_detail}")
            return {'success': False, 'error': f'数字人生成请求失败: {error_detail}'}

    except Exception as e:
        logger.error(f"generate_digital_human error: {e}", exc_info=True)
        return {'success': False, 'error': f'数字人生成请求异常: {str(e)}'}


def generate_text_to_image(user_id: str, world_id: str, auth_token: str, prompt: str,
                           aspect_ratio: str = "16:9", count: int = 1,
                          image_size: Optional[str] = None,
                          item_type: int = None, item_name: str = None,
                          force_update_exist_image: bool = False,
                          is_grid: bool = False,
                          grid_size: Optional[int] = None,
                          grid_layout: Optional[str] = None,
                          grid_item_names: Optional[List[str]] = None,
                           target_entity_ids: Optional[List[int]] = None,
                           task_type: Optional[int] = None) -> Dict[str, Any]:
    """
    文本生成图片 - MCP工具函数（非阻塞版本，支持后台任务处理）

    注意：生图模型由用户在前端界面选择，不同模型算力价格不同，请先调用 get_text_to_image_model_info 了解当前模型。

    Args:
        user_id: 用户ID（必填）
        world_id: 世界ID（必填）
        auth_token: 认证令牌（必填）
        prompt: 图片描述提示词（必填）
        aspect_ratio: 图片宽高比（默认：16:9）
        count: 生成图片数量（默认：1）
        image_size: 图片分辨率（可选），如 1K/2K/3K/4K，不填则使用模型默认值。
                    4宫格生成时自动使用模型支持的最大尺寸，无需手动指定。
        item_type: 物品类型（可选）：1=角色(character), 2=地点(location), 3=道具(props)
        item_name: 物品名称（可选），当指定item_type时必填，会自动更新对应物品的reference_image字段
        force_update_exist_image: 是否强制更新已存在的图像（默认：False）
                                 - False: 如果角色/场景/道具已有参考图像，则跳过生成
                                 - True: 强制生成并更新，覆盖现有图像
        is_grid: 是否为4宫格批量生成（默认：False）
                - True: 自动使用模型支持的最大尺寸，用于4宫格高分辨率生成

    Returns:
        dict: 操作结果，包含success状态、project_ids、使用的模型信息、算力消耗等
    """
    # 获取用户配置的生图模型 task_id
    locked_snapshot = get_media_generation_snapshot('image', 'text_to_image')
    if locked_snapshot:
        task_type = locked_snapshot.get('task_id')
    text_to_image_task_id = (
        int(task_type)
        if task_type not in (None, '')
        else _get_text_to_image_task_id(user_id, world_id)
    )
    from config.unified_config import UnifiedConfigRegistry, TaskCategory
    selected_config = UnifiedConfigRegistry.get_by_id(text_to_image_task_id)
    if not selected_config:
        return {'success': False, 'error': f'文生图模型（id={text_to_image_task_id}）不存在'}
    if not selected_config.enabled or (selected_config.hidden and not locked_snapshot):
        return {'success': False, 'error': f'文生图模型 {selected_config.name} 已禁用或不可用'}
    selected_categories = {selected_config.category, *(selected_config.categories or [])}
    if TaskCategory.TEXT_TO_IMAGE not in selected_categories:
        return {
            'success': False,
            'error': f'当前选中的模型（id={text_to_image_task_id}）不支持文生图'
        }
    model_name = _get_model_name_by_task_id(text_to_image_task_id)

    try:
        # 验证 auth_token
        if not auth_token:
            return {
                'success': False,
                'error': '认证令牌不能为空'
            }

        # 验证必填字段
        if not prompt or not isinstance(prompt, str):
            return {
                'success': False,
                'error': '图片描述提示词不能为空且必须是字符串'
            }

        # 验证item_type和item_name参数
        if item_type is not None:
            # 检测是否应该使用4宫格生成
            if not isinstance(item_type, int) or item_type not in [1, 2, 3, 4, 5, 6, 7]:
                return {
                    'success': False,
                    'error': 'item_type参数错误。正确值：1=角色, 2=地点, 3=道具, 4=角色四宫格, 5=场景四宫格, 6=道具四宫格, 7=角色变体图'
                }

            # 如果是单个角色/场景/道具类型(1/2/3)，但没有设置is_grid=True，给出提示
            if item_type in ItemType.SINGLE_TYPES and not is_grid:
                logger.warning(f"[提示] 正在为单个项目生成图像 (item_type={item_type}, item_name={item_name})。如果需要批量生成4个或更多项目，建议使用 generate_4grid_character_images() / generate_4grid_images() 函数以提高效率。")
            
            # 如果提供了item_type，必须同时提供item_name
            if not item_name or not isinstance(item_name, str):
                return {
                    'success': False,
                    'error': '当指定item_type时，必须同时提供item_name参数'
                }
            
            # 检查是否已有相同任务正在进行
            task_manager = get_task_manager()
            if task_manager.is_item_generating(item_type, item_name, user_id):
                return {
                    'success': False,
                    'error': f'该项目正在生成图片中，请等待完成后再试。可以调用相关API查询任务状态。'
                }
            
            # 检查是否已存在参考图像（除非强制更新）
            if not force_update_exist_image:
                file_manager = get_file_manager()

                # 根据item_type检查对应的JSON文件
                existing_data = None
                if item_type == 1:  # 角色
                    existing_data = file_manager.get_character_json(item_name, user_id, world_id)
                elif item_type == 2:  # 地点
                    existing_data = file_manager.get_location_json(item_name, user_id, world_id)
                elif item_type == 3:  # 道具
                    existing_data = file_manager.get_prop_json(item_name, user_id, world_id)
                elif item_type == 7:  # 角色变体图 - item_name 格式为 "角色名|变体标签"
                    char_name = item_name.split('|')[0] if '|' in item_name else item_name
                    variant_label = item_name.split('|')[1] if '|' in item_name else ''
                    existing_data = file_manager.get_character_json(char_name, user_id, world_id)
                    # 变体图不检查 reference_image，只检查 reference_images 中是否已有同标签的条目
                    if existing_data and variant_label:
                        existing_variants = existing_data.get('reference_images', [])
                        if any(v.get('label') == variant_label for v in existing_variants if isinstance(v, dict)):
                            return {
                                'success': False,
                                'error': f'角色 "{char_name}" 已存在标签为 "{variant_label}" 的变体图，如需更新请设置 force_update_exist_image=True',
                                'skip_reason': 'already_has_variant'
                            }
                    # 变体图不需要检查 reference_image，跳过后续检查
                    existing_data = None

                # 如果找到数据且已有参考图像，则跳过生成（仅对1/2/3类型）
                if existing_data and existing_data.get('reference_image'):
                    item_type_name = {1: '角色', 2: '地点', 3: '道具'}.get(item_type, '项目')
                    return {
                        'success': False,
                        'error': f'{item_type_name} "{item_name}" 已存在参考图像，如需更新请设置 force_update_exist_image=True',
                        'existing_image': existing_data.get('reference_image'),
                        'skip_reason': 'already_has_image'
                    }
    
        # 需要读取内网，避免ssh.perseids.cn 内网无法访问的问题
        server_config = get_config().get("server", {})
        comfyui_base_url = server_config.get("comfyui_base_url_inner") or server_config.get("host", "")
        
        if not comfyui_base_url:
            return {
                'success': False,
                'error': '配置文件中未找到comfyui_base_url_inner或host配置'
            }
        
        # 强制应用系统注入：任务 snapshot（故事板 workflow_ratio）> 世界偏好 > 参数默认
        # 4宫格模式(is_grid=True)跳过偏好覆盖，因为4宫格布局必须使用16:9横屏比例和最大分辨率
        generation_snapshot = _image_generation_snapshot_override.get() or locked_snapshot
        if not is_grid:
            aspect_ratio, image_size, image_size_source = _resolve_image_ratio_and_size_from_prefs(
                user_id=user_id,
                world_id=world_id,
                aspect_ratio=aspect_ratio,
                image_size=image_size,
                generation_snapshot=generation_snapshot,
            )
        else:
            image_size_source = "argument" if image_size else "default"

        # 准备请求数据
        request_data = {
            'prompt': prompt,
            'task_id': text_to_image_task_id,
            'aspect_ratio': aspect_ratio,
            'count': count,
            'user_id': user_id,
            'auth_token': auth_token
        }
        if generation_snapshot:
            request_data['generation_snapshot'] = json.dumps(
                generation_snapshot, ensure_ascii=False
            )

        # 确定 image_size
        from config.unified_config import UnifiedConfigRegistry
        config = UnifiedConfigRegistry.get_by_id(text_to_image_task_id)
        if not is_grid:
            # snapshot 与 preference 同等对待：不兼容时降级到模型最低档
            resolve_source = (
                "preference"
                if image_size_source in ("preference", "snapshot")
                else image_size_source
            )
            image_size, image_size_error = _resolve_image_size_for_model(
                config, image_size, resolve_source
            )
            if image_size_error:
                return {'success': False, 'error': image_size_error}
        if is_grid:
            # 4宫格生成：自动使用模型支持的最大尺寸
            if config and config.supported_sizes:
                max_size = config.supported_sizes[-1]
                request_data['image_size'] = max_size
            else:
                request_data['image_size'] = '4k'
        elif image_size:
            # Agent 指定了 image_size，校验是否在支持列表中
            if config and config.supported_sizes:
                supported_lower = [s.lower() for s in config.supported_sizes]
                if image_size.lower() not in supported_lower:
                    return {
                        'success': False,
                        'error': f'不支持的图片尺寸: {image_size}，当前模型支持: {config.supported_sizes}'
                    }
            request_data['image_size'] = image_size
        # 否则不设置 image_size，让后端使用模型默认尺寸

        # 计算预估算力
        from utils.computing_power import get_computing_power_for_task
        context_for_power = {}
        if 'image_size' in request_data:
            context_for_power['resolution'] = request_data['image_size']
        elif config and config.default_size:
            context_for_power['resolution'] = config.default_size
        computing_power_per_image = get_computing_power_for_task(
            text_to_image_task_id, context=context_for_power or None
        )
        computing_power_total = computing_power_per_image * count

        # 发起文本生成图片请求
        api_url = f"{comfyui_base_url.rstrip('/')}/api/text-to-image"
        
        try:
            # 接口使用 Form 参数，需要使用 data 而不是 json 来发送表单数据
            # 使用 httpx 替代 requests，避免同步阻塞事件循环
            # ===== E2E Mock 短路：仅替换 project_ids 获取，保留后续 grid_image_tasks 创建逻辑 =====
            from task.mock_interceptor import is_mock_enabled, generate_mock_project_id
            if is_mock_enabled():
                result_data = {'project_ids': [generate_mock_project_id()]}
                logger.info(f"[MOCK] mcp_tool text_to_image short-circuit pid={result_data['project_ids'][0]}")
            else:
                response = httpx.post(api_url, data=request_data, timeout=30, verify=False, trust_env=False)
                response.raise_for_status()
                result_data = response.json()
            # ==============================================================================

            project_ids = result_data.get('project_ids', [])

            if not project_ids:
                return {
                    'success': False,
                    'error': '图片生成请求成功但未返回project_ids'
                }
            
            # 创建后台任务跟踪记录
            task_id = None
            
            # 读取自动重试配置
            max_retries = 0
            try:
                max_retries = get_config().get("image", {}).get("max_retry_count", 0) or 0
            except Exception:
                pass
            
            if item_type is not None and item_name:
                # 绑定到具体角色/场景/道具的任务
                try:
                    task_manager = get_task_manager()
                    task_id = task_manager.create_image_task(
                        project_id=project_ids[0],
                        item_type=item_type,
                        item_name=item_name,
                        comfyui_base_url=comfyui_base_url,
                        auth_token=auth_token,
                        user_id=user_id,
                        world_id=world_id,
                        prompt=prompt,
                        task_config_id=text_to_image_task_id,
                        aspect_ratio=aspect_ratio,
                        image_size=request_data.get('image_size'),
                        is_grid=is_grid,
                        max_retries=max_retries,
                        grid_size=grid_size or GridConfig.SIZE_2X2,
                        grid_layout=grid_layout or '2x2',
                        item_names=grid_item_names,
                        target_entity_ids=target_entity_ids,
                    )
                except ValueError as e:
                    # 任务冲突
                    return {
                        'success': False,
                        'error': str(e)
                    }
                except Exception as e:
                    # 任务创建失败，但图片生成请求已提交
                    return {
                        'success': True,
                        'project_ids': project_ids,
                        'status': 'submitted',
                        'message': f'图片生成请求已提交，但后台任务创建失败: {str(e)}',
                        'warning': f'后台任务创建失败: {str(e)}',
                        'comfyui_base_url': comfyui_base_url
                    }
            else:
                # 通用生图任务（营销等场景，不绑定item），直接创建数据库记录
                # 后台 scheduler 会自动轮询 ComfyUI 状态并更新 result_url
                try:
                    from model import GridImageTasksModel, GridImageTaskStatus
                    general_task_key = f"{user_id}_0_{project_ids[0]}"
                    # 清理同 key 的终态旧记录
                    existing = GridImageTasksModel.get_by_task_key(general_task_key)
                    if existing and existing.status not in [GridImageTaskStatus.QUEUED, GridImageTaskStatus.PROCESSING]:
                        GridImageTasksModel.delete_by_task_key(general_task_key)
                    GridImageTasksModel.create(
                        task_key=general_task_key,
                        project_id=project_ids[0],
                        item_type=0,
                        item_name=project_ids[0],
                        user_id=user_id,
                        world_id=world_id,
                        comfyui_base_url=comfyui_base_url,
                        auth_token=auth_token,
                        prompt=prompt,
                        task_config_id=text_to_image_task_id,
                        aspect_ratio=aspect_ratio,
                        image_size=request_data.get('image_size'),
                        is_grid=is_grid,
                        max_retries=max_retries,
                        grid_size=grid_size or GridConfig.SIZE_2X2,
                        grid_layout=grid_layout or '2x2',
                    )
                    task_id = general_task_key
                    logger.info(f"创建通用生图后台任务: {general_task_key}, project_id: {project_ids[0]}")
                except Exception as e:
                    logger.warning(f"通用生图后台任务创建失败（不影响生图请求）: {e}")
            
            result = {
                'success': True,
                'project_ids': project_ids,
                'status': 'submitted',
                'comfyui_base_url': comfyui_base_url,
                'model_used': model_name,
                'text_to_image_task_id': text_to_image_task_id,
                'image_size_used': request_data.get('image_size'),
                'computing_power_required': computing_power_per_image,
                'computing_power_total': computing_power_total,
            }

            if task_id:
                result.update({
                    'task_id': task_id,
                    'item_type': item_type if item_type is not None else 0,
                    'item_name': item_name if item_name else project_ids[0],
                    'message': f'图片生成请求已提交（使用模型: {model_name}），后台任务已创建。project_ids: {project_ids}, task_id: {task_id}'
                })
            else:
                result['message'] = f'图片生成请求已提交（使用模型: {model_name}），project_ids: {project_ids}'

            return result
            
        except httpx.HTTPStatusError as e:
            # 尝试解析结构化错误（如算力不足）
            error_detail = f'图片生成请求失败: {str(e)}'
            try:
                resp_data = e.response.json()
                detail = resp_data.get('detail', '')
                if detail:
                    error_detail = detail
                    # 解析算力不足信息：格式如 "需要 X 算力，当前仅有 Y 算力"
                    import re
                    match = re.search(r'需要\s*(\d+)\s*算力.*当前仅有\s*(\d+)\s*算力', detail)
                    if match:
                        return {
                            'success': False,
                            'error': '算力不足',
                            'detail': detail,
                            'computing_power_required': int(match.group(1)),
                            'computing_power_available': int(match.group(2)),
                            'shortage': int(match.group(1)) - int(match.group(2)),
                            'model_used': model_name,
                        }
            except (ValueError, KeyError):
                pass
            return {
                'success': False,
                'error': error_detail,
                'model_used': model_name,
                'computing_power_required': computing_power_total,
            }
        
    except Exception as e:
        return {
            'success': False,
            'error': f'图片生成过程中发生错误: {str(e)}'
        }


def generate_4grid_images(user_id: str, world_id: str, auth_token: str,
                         item_names: List[str], prompts: List[str],
                         item_type: int) -> Dict[str, Any]:
    """
    生成4宫格图像并自动切分更新到各个项目（角色/场景/道具）

    注意：不同生图模型算力价格不同，请先调用 get_text_to_image_model_info 了解当前模型。

    Args:
        user_id: 用户ID（必填）
        world_id: 世界ID（必填）
        auth_token: 认证令牌（必填）
        item_names: 4个项目的名称列表（必须是4个）
        prompts: 4个项目的提示词列表（必须是4个）
        item_type: 项目类型（4=角色四宫格, 5=场景四宫格, 6=道具四宫格）

    Returns:
        dict: 操作结果，包含每个项目的更新状态、算力消耗等
    """
    import logging
    logger = logging.getLogger(__name__)

    # 使用常量中的宫格类型映射
    item_type_map = ItemType.GRID_MAP

    try:
        if item_type not in item_type_map:
            return {
                'success': False,
                'error': f'无效的item_type: {item_type}，必须是4(角色四宫格)、5(场景四宫格)或6(道具四宫格)'
            }

        item_info = item_type_map[item_type]
        logger.info(f"[4GRID] 开始执行 generate_4grid_images，类型={item_info['name_cn']}")
        logger.info(f"[4GRID] user_id={user_id}, world_id={world_id}")
        logger.info(f"[4GRID] item_names={item_names}, count={len(item_names) if isinstance(item_names, list) else 'NOT_LIST'}")
        logger.info(f"[4GRID] prompts count={len(prompts) if isinstance(prompts, list) else 'NOT_LIST'}")
        
        # 验证参数
        if len(item_names) != 4:
            return {
                'success': False,
                'error': f'item_names必须包含4个{item_info["name_cn"]}名称，当前提供了{len(item_names)}个'
            }
        
        if len(prompts) != 4:
            return {
                'success': False,
                'error': f'prompts必须包含4个提示词，当前提供了{len(prompts)}个'
            }
        
        # 检查是否已存在参考图像
        file_manager = get_file_manager()
        base_type = item_info['base_type']
        
        for name in item_names:
            # 跳过占位符
            if name.lower() in ['placeholder', 'pure black background']:
                continue
                
            existing_data = None
            if base_type == 1:
                existing_data = file_manager.get_character_json(name, user_id, world_id)
            elif base_type == 2:
                existing_data = file_manager.get_location_json(name, user_id, world_id)
            elif base_type == 3:
                existing_data = file_manager.get_prop_json(name, user_id, world_id)
            
            if existing_data and existing_data.get('reference_image'):
                return {
                    'success': False,
                    'error': f'已经存在的 {name} 不允许更新，必须在人工确认会导致 已有的形象被覆盖 后，再调用 generate_text_to_image 函数(force_update_exist_image 为true）去更新。'
                }
        
        # 构建4宫格JSON格式的prompt
        grid_prompt = {
            "grid_layout": "2x2",
            "grid_aspect_ratio": "16:9",
            "global_watermark": "",
            "grid_output_constraints": GridConfig.GRID_OUTPUT_CONSTRAINTS_NO_TEXT,
            "shots": [
                {"shot_number": "", "prompt_text": prompt}
                for prompt in prompts
            ]
        }

        # 构建item_name（将4个名称用逗号连接）
        combined_item_name = ','.join(item_names)

        # 调用图像生成API（使用is_grid=True）
        logger.info(f"[4GRID] 准备调用 generate_text_to_image")
        logger.info(f"[4GRID] grid_prompt: {json.dumps(grid_prompt, ensure_ascii=False)[:200]}...")
        logger.info(f"[4GRID] item_type={item_type}, item_name={combined_item_name}")

        result = generate_text_to_image(
            user_id=user_id,
            world_id=world_id,
            auth_token=auth_token,
            prompt=json.dumps(grid_prompt),
            aspect_ratio="16:9",
            count=1,
            item_type=item_type,  # 传递4宫格类型（4/5/6）
            item_name=combined_item_name,  # 传递组合的名称
            force_update_exist_image=False,
            is_grid=True,  # 关键：启用4k参数
            # 修复 grid_size=NULL 报错：grid_size/grid_layout 列均为 NOT NULL，
            # 漏传会导致 None 穿透到 INSERT，绕过 DB DEFAULT 与模型默认值（详见 _generate_grid_images_generic 写法）
            grid_size=GridConfig.SIZE_2X2,  # 4=2x2 四宫格
            grid_layout="2x2",              # 与 grid_layout NOT NULL DEFAULT '2x2' 列对齐
            grid_item_names=item_names,     # 结构化名称，下游切图回写优先读 item_names_json
        )
        
        logger.info(f"[4GRID] generate_text_to_image 返回: success={result.get('success')}")
        
        # 直接返回结果，后续的轮询、下载、切分、更新操作由 cron_task_manager.py 处理
        if result.get('success'):
            result['item_type_name'] = item_info['name_cn']
            result['base_item_type'] = item_info['base_type']  # 基础类型（1/2/3）用于后续更新
            result['item_names'] = item_names
            logger.info(f"[4GRID] {item_info['name_cn']}图像生成请求已提交，后续处理由后台任务管理器完成")
        
        return result
        
    except Exception as e:
        return {
            'success': False,
            'error': f'4宫格图像生成过程中发生错误: {str(e)}'
        }


def _resolve_image_edit_task_id(
    user_id: str,
    world_id: str,
    task_type: Optional[int] = None,
) -> Optional[int]:
    """
    解析图片编辑所需的 task_id（模型配置 id）。

    严格复用 edit_image() 的模型选择逻辑，不兼容时返回 None，禁止 fallback。
    """
    from config.unified_config import UnifiedConfigRegistry, TaskCategory
    task_id = (
        int(task_type)
        if task_type not in (None, '')
        else _get_text_to_image_task_id(user_id, world_id)
    )
    config = UnifiedConfigRegistry.get_by_id(task_id)
    if config and (
        config.category == TaskCategory.IMAGE_EDIT
        or TaskCategory.IMAGE_EDIT in getattr(config, 'categories', [])
    ):
        return task_id
    return None


def _to_public_http_url(url: str, comfyui_base_url: str) -> Optional[str]:
    """
    将本地 /upload/... 路径转为可被 /api/image-edit 接受的公开 http(s) URL。

    edit_image() 仅接受 http/https 协议（防 SSRF），本地相对路径必须先转换。
    已是 http/https 的原样返回；无法识别的返回 None。
    """
    if not url or not isinstance(url, str):
        return None
    url = url.strip()
    if url.lower().startswith(('http://', 'https://')):
        return url
    # 本地相对路径：以 / 开头则拼到 host 根，否则补 /
    if url.startswith('/'):
        return f"{comfyui_base_url.rstrip('/')}{url}"
    return f"{comfyui_base_url.rstrip('/')}/{url}"


def submit_grid_image_task(
    user_id: str,
    world_id: str,
    auth_token: str,
    item_names: List[str],
    prompts: List[str],
    item_type: int,
    grid_size: int,
    mode: str = "text_to_image",
    reference_images: Optional[List[Dict[str, str]]] = None,
    target_entity_ids: Optional[List[Optional[int]]] = None,
    aspect_ratio: Optional[str] = None,
    image_size: Optional[str] = None,
    grid_cells: Optional[List[Dict[str, Any]]] = None,
    global_visual_guidance: Optional[Dict[str, str]] = None,
    task_type: Optional[int] = None,
) -> Dict[str, Any]:
    """
    通用宫格图像提交入口（支持 2x2 四宫格 / 3x3 九宫格，支持 t2i / i2i 两种模式）。

    两个干净分支，互不污染：
      - mode="text_to_image"：复用 generate_text_to_image（/api/text-to-image，
        aspect_ratio，is_grid=True 强制最大分辨率），内部自动创建 grid_image_tasks。
      - mode="image_edit"：以参考图为输入走图生图（/api/image-edit，ref_image_urls，
        ratio，IMAGE_EDIT 模型），显式创建带 grid_type 的 grid_image_tasks 记录，
        使后台轮询器能按 item_type 触发宫格切图。

    Args:
        user_id / world_id / auth_token: 用户/世界/认证。
        item_names: 各格子名称（placeholder 占位项会被切图时跳过）。
        prompts: 各格子提示词。
        item_type: ItemType 宫格类型（4=角色四宫格, 5=场景四宫格, 6=道具四宫格, 8=分镜首帧宫格）。
        grid_size: GridConfig.SIZE_2X2(4) 或 GridConfig.SIZE_3X3(9)。
        mode: "text_to_image" 或 "image_edit"。
        reference_images: i2i 模式下的参考图列表，每项 {"url": str, "role_description": str}。
            url 为参考图地址（本地路径或 http URL）；role_description 说明这张图的角色
            （如"父场景的完整俯瞰图"、"分镜首帧"），会被拼进 prompt 全局说明区，对所有格子生效。
            支持多张参考图（如父场景图 + 角色图），适配不同宫格生图场景。
        target_entity_ids: 各格子对应的切图回写目标 DB id（与 item_names 等长，按索引对齐；
            placeholder 格子传 None）。仅 item_type=5(location_grid) 时用于按 id 回写
            location.reference_image；为 None 时回退按 item_name 回写。
        aspect_ratio: 宫格整体画幅，缺省回退 16:9。
        image_size: 可选图片尺寸，写入任务记录供重试复原。
        grid_cells: 可选的格子绑定元数据，分镜首帧宫格用来驱动后续拆图写回。
        global_visual_guidance: 可选的宫格级画风、构图倾向及应用规则，仅在根节点出现一次。
        task_type: 显式生图模型 task_id（统一配置 id）。来自上层批任务创建时锁定的
            模型快照，传入后原样使用（类别不兼容时明确报错，禁止静默换模型）；
            未传入时回退到用户偏好/默认模型解析，并打 warning 让隐式解析点在日志中现形。

    Returns:
        dict: 与 generate_4grid_images 结构一致的结果。
    """
    import logging as _logging
    _logger = _logging.getLogger(__name__)

    if grid_size not in GridConfig.VALID_SIZES:
        return {'success': False, 'error': f'不支持的 grid_size={grid_size}，允许: {GridConfig.VALID_SIZES}'}
    if item_type not in ItemType.GRID_MAP:
        return {'success': False, 'error': f'无效的 item_type={item_type}，必须为宫格类型({sorted(ItemType.GRID_MAP.keys())})'}
    if mode not in ("text_to_image", "image_edit"):
        return {'success': False, 'error': f'无效的 mode={mode}，必须为 text_to_image 或 image_edit'}

    item_info = ItemType.GRID_MAP[item_type]
    resolved_aspect_ratio = str(aspect_ratio or "16:9").strip() or "16:9"

    # 数量校验：placeholder 不计入有效项，但总长度需等于 grid_size
    if len(item_names) != grid_size:
        return {'success': False, 'error': f'item_names 必须包含 {grid_size} 个名称（含 placeholder），当前 {len(item_names)}'}
    if len(prompts) != grid_size:
        return {'success': False, 'error': f'prompts 必须包含 {grid_size} 个提示词，当前 {len(prompts)}'}
    # target_entity_ids 长度校验（提供时必须与 item_names 对齐）
    if target_entity_ids is not None and len(target_entity_ids) != grid_size:
        return {'success': False, 'error': f'target_entity_ids 长度({len(target_entity_ids)})必须等于 grid_size({grid_size})'}

    grid_layout = "2x2" if grid_size == GridConfig.SIZE_2X2 else "3x3"

    # i2i 模式必须有参考图
    if mode == "image_edit" and not reference_images:
        return {'success': False, 'error': 'image_edit 模式必须提供 reference_images（至少一张参考图）'}

    _logger.info(
        "[GRID] submit_grid_image_task mode=%s layout=%s type=%s names=%s target_ids=%s ref_imgs=%s",
        mode, grid_layout, item_info['name_cn'], item_names, target_entity_ids,
        [(r.get('url'), r.get('role_description', '')[:30]) for r in (reference_images or [])],
    )

    # 构造参考图角色说明（拼进 prompt 全局说明区，对所有格子生效）
    reference_images_legend = ""
    if reference_images:
        legend_parts = []
        for idx, ref in enumerate(reference_images, 1):
            role = (ref.get('role_description') or '').strip()
            if role:
                legend_parts.append(f"图{idx}是{role}")
        if legend_parts:
            reference_images_legend = "参考图说明：" + "；".join(legend_parts) + "。各格内容需与参考图保持视觉连续性。"

    # 构造宫格 prompt JSON（shots 列表天然支持任意长度）
    grid_prompt = {
        "grid_layout": grid_layout,
        "grid_aspect_ratio": resolved_aspect_ratio,
        "global_watermark": "",
        "grid_output_constraints": GridConfig.GRID_OUTPUT_CONSTRAINTS_NO_TEXT,
        "shots": [
            {"shot_number": "", "prompt_text": p}
            for p in prompts
        ],
    }
    if isinstance(global_visual_guidance, dict):
        normalized_global_guidance = {
            key: str(global_visual_guidance.get(key) or "").strip()
            for key in ("image_style", "composition_preference", "application_rule")
            if str(global_visual_guidance.get(key) or "").strip()
        }
        if normalized_global_guidance:
            grid_prompt["global_visual_guidance"] = normalized_global_guidance
    if reference_images_legend:
        grid_prompt["reference_images_legend"] = reference_images_legend
    prompt_json_str = json.dumps(grid_prompt, ensure_ascii=False)

    # item_name 列只存「展示短 key」（避免 9 个中文名逗号拼接超 varchar(255)）。
    # 真实名称与回写目标 id 分别落 item_names_json / target_entity_ids_json，
    # 切图与回写统一通过 GridImageTask.get_item_names_list() / get_target_entity_ids_list() 读取。
    if target_entity_ids is not None:
        # 用真实 id 列表生成稳定短 key（如 "loc#100,101,#"），placeholder 位用 # 占位
        display_key = "loc#" + ",".join(
            (str(tid) if tid is not None else "#") for tid in target_entity_ids
        )
    else:
        # 无 target_entity_ids（如四宫格 t2i）：退化为名称首字符拼接，保持兼容
        display_key = ",".join(n[:8] for n in item_names)
    combined_item_name = display_key

    # ---------- 分支 A：纯文生图 ----------
    if mode == "text_to_image":
        target_ids_for_db = [
            target_id for target_id in (target_entity_ids or [])
            if target_id is not None
        ]
        result = generate_text_to_image(
            user_id=user_id,
            world_id=world_id,
            auth_token=auth_token,
            prompt=prompt_json_str,
            aspect_ratio=resolved_aspect_ratio,
            count=1,
            item_type=item_type,
            item_name=combined_item_name,
            force_update_exist_image=False,
            is_grid=True,
            grid_size=grid_size,
            grid_layout=grid_layout,
            grid_item_names=item_names,
            target_entity_ids=target_ids_for_db,
            task_type=task_type,
        )
        if result.get('success'):
            result['item_type_name'] = item_info['name_cn']
            result['base_item_type'] = item_info.get('base_type')
            result['item_names'] = item_names
            # 统一模型对账字段：调用方用它校验实际模型与批任务快照一致
            result['model_task_id'] = result.get('text_to_image_task_id')
        return result

    # ---------- 分支 B：图生图（参考图作为输入）----------
    # 复用 edit_image() 的模型选择 + URL 校验 + 请求构造，但显式创建带 grid_type 的 task。
    server_config = get_config().get("server", {})
    comfyui_base_url = server_config.get("comfyui_base_url_inner") or server_config.get("host", "")
    if not comfyui_base_url:
        return {'success': False, 'error': '配置文件中未找到 comfyui_base_url_inner 或 host 配置'}

    # 参考图 url 转公开 http URL（edit_image 仅接受 http/https，防 SSRF）
    public_ref_urls = []
    for ref in reference_images:
        raw_url = ref.get('url') if isinstance(ref, dict) else ref
        if not raw_url:
            continue
        public_url = _to_public_http_url(raw_url, comfyui_base_url)
        if public_url:
            public_ref_urls.append(public_url)
    if not public_ref_urls:
        return {'success': False, 'error': 'reference_images 无法转为有效 http URL（全部为空或非法）'}

    # 解析模型 task_id（IMAGE_EDIT 类别，含 fallback）。
    # 显式 task_type 来自上层批任务创建时锁定的模型快照：必须原样使用，禁止静默换模型；
    # 未显式指定时才回退到偏好/默认解析，并打 warning 让隐式解析点在日志中现形。
    edit_task_id = _resolve_image_edit_task_id(user_id, world_id, task_type=task_type)
    if edit_task_id is None:
        if task_type not in (None, ''):
            requested_name = _get_model_name_by_task_id(int(task_type))
            return {
                'success': False,
                'error': (
                    f'所选生图模型（id={task_type}，{requested_name}）不支持图片编辑'
                    f'（参考图模式），无法执行宫格 i2i；请更换为支持图片编辑的生图模型'
                ),
            }
        return {'success': False, 'error': '无可用图片编辑模型，无法执行宫格 i2i'}
    if task_type in (None, ''):
        _logger.warning(
            "[GRID] submit_grid_image_task(mode=image_edit) 未显式指定生图模型 task_type，"
            "回退到用户偏好/默认模型解析: user_id=%s world_id=%s item_type=%s resolved_task_id=%s",
            user_id, world_id, item_type, edit_task_id,
        )
    model_name = _get_model_name_by_task_id(edit_task_id)

    if not auth_token:
        return {'success': False, 'error': '认证令牌不能为空'}

    # 按 IMAGE_EDIT 模型 supported_sizes 解析目标分辨率（不支持时自动降级到最接近档位）
    from config.unified_config import UnifiedConfigRegistry
    edit_config = UnifiedConfigRegistry.get_by_id(edit_task_id)
    resolved_image_size = _pick_grid_image_size(edit_config, image_size)
    _logger.info(
        "[GRID] i2i image_size: requested=%s resolved=%s model=%s supported=%s",
        image_size, resolved_image_size, model_name,
        getattr(edit_config, 'supported_sizes', None),
    )

    # 发起图生图请求（参照 edit_image L632-658）
    api_url = f"{comfyui_base_url.rstrip('/')}/api/image-edit"
    request_data = {
        'prompt': prompt_json_str,
        'task_id': edit_task_id,
        'ratio': resolved_aspect_ratio,  # i2i 端点字段名是 ratio，不是 aspect_ratio
        'count': 1,
        'user_id': user_id,
            'auth_token': auth_token,
        'ref_image_urls': ','.join(public_ref_urls),  # 逗号分隔的参考图 URL 列表
    }
    generation_snapshot = (
        _image_generation_snapshot_override.get()
        or get_media_generation_snapshot('image', 'image_edit')
    )
    if generation_snapshot:
        request_data['generation_snapshot'] = json.dumps(
            generation_snapshot, ensure_ascii=False
        )
    if resolved_image_size:
        request_data['image_size'] = resolved_image_size
    try:
        from task.mock_interceptor import is_mock_enabled, generate_mock_project_id
        if is_mock_enabled():
            result_data = {'project_ids': [generate_mock_project_id()]}
            _logger.info(f"[MOCK] submit_grid_image_task i2i short-circuit pid={result_data['project_ids'][0]}")
        else:
            response = httpx.post(api_url, data=request_data, timeout=30, verify=False, trust_env=False)
            response.raise_for_status()
            result_data = response.json()
    except httpx.HTTPStatusError as e:
        error_detail = f'宫格图生图请求失败: {str(e)}'
        try:
            resp_json = e.response.json()
            detail = resp_json.get('detail', '')
            if detail:
                error_detail = detail
        except Exception:
            detail = ''
        _logger.error(
            "[GRID] i2i 请求失败 status=%s detail=%s url=%s",
            e.response.status_code, error_detail, api_url,
        )
        return {'success': False, 'error': error_detail, 'model_used': model_name}
    except Exception as e:
        _logger.error("[GRID] i2i 请求异常: %s", e, exc_info=True)
        return {'success': False, 'error': f'宫格图生图请求异常: {str(e)}'}

    project_ids = result_data.get('project_ids', [])
    if not project_ids:
        return {'success': False, 'error': '宫格图生图请求成功但未返回 project_ids'}

    # 显式创建带 grid_type 的 grid_image_tasks 记录（绕过 create_image_task 的长名 task_key）
    # 用 project_id 短键，避免 9 名拼接超长/撞键
    task_key = f"grid:{user_id}:{world_id}:{project_ids[0]}"
    # target_entity_ids 中的 None（placeholder 位）过滤为纯 id 列表写入 JSON，
    # 使 JSON_CONTAINS 查询与回写对齐语义清晰。
    target_ids_for_db = [tid for tid in (target_entity_ids or []) if tid is not None]
    pipeline_step_id = None
    try:
        from model import GridImageTasksModel, GridImageTaskStatus
        existing = GridImageTasksModel.get_by_task_key(task_key)
        if existing and existing.status not in [GridImageTaskStatus.QUEUED, GridImageTaskStatus.PROCESSING]:
            GridImageTasksModel.delete_by_task_key(task_key)
        grid_task_id = GridImageTasksModel.create(
            task_key=task_key,
            project_id=project_ids[0],
            item_type=item_type,
            item_name=combined_item_name,
            user_id=user_id,
            world_id=world_id,
            comfyui_base_url=comfyui_base_url,
            auth_token=auth_token,
            prompt=prompt_json_str,
            task_config_id=str(edit_task_id),
            aspect_ratio=resolved_aspect_ratio,
            image_size=resolved_image_size or image_size,
            is_grid=True,
            max_retries=(
                GridConfig.STORYBOARD_FIRST_FRAME_VALIDATION_MAX_RETRIES
                if item_type == ItemType.STORYBOARD_FIRST_FRAME_GRID
                else (
                    GridConfig.LOCATION_REFERENCE_VALIDATION_MAX_RETRIES
                    if item_type == ItemType.LOCATION_GRID
                    else 0
                )
            ),
            grid_size=grid_size,
            grid_layout=grid_layout,
            item_names=item_names,
            target_entity_ids=target_ids_for_db,
            reference_images=reference_images,
        )
        if item_type == ItemType.STORYBOARD_FIRST_FRAME_GRID:
            from model.ai_tool_pipeline_steps import PipelineStage, PipelineStepModel, PipelineStepType

            cells = grid_cells
            if not cells:
                cells = []
                target_ids_by_index = target_entity_ids or []
                for index in range(grid_size):
                    scene_id = target_ids_by_index[index] if index < len(target_ids_by_index) else None
                    cells.append(
                        {
                            "grid_index": index,
                            "scene_id": scene_id,
                            "batch_item_id": None,
                            "placeholder": scene_id is None or GridConfig.is_placeholder(item_names[index]),
                        }
                    )

            try:
                ai_tool_id_for_step = int(project_ids[0])
            except (TypeError, ValueError):
                ai_tool_id_for_step = None
                _logger.warning(
                    "[GRID] 分镜首帧宫格 project_id 不是 ai_tools.id，跳过预建 pipeline step: %s",
                    project_ids[0],
                )
            if ai_tool_id_for_step is not None:
                try:
                    pipeline_step_id = PipelineStepModel.create(
                        ai_tool_id=ai_tool_id_for_step,
                        stage=PipelineStage.BEFORE_FINISH,
                        step_type=PipelineStepType.STORYBOARD_FIRST_FRAME_GRID_SPLIT,
                        step_order=0,
                        params={
                            "grid_task_id": grid_task_id,
                            "grid_size": grid_size,
                            "grid_layout": grid_layout,
                            "asset_type": "first_frame",
                            "output_dir": "upload/storyboard/first_frame",
                            "output_url_path": "upload/storyboard/first_frame",
                            "cells": cells,
                        },
                        target=task_key,
                    )
                except Exception as step_err:
                    _logger.error(
                        "[GRID] 分镜首帧宫格 pipeline step 预创建失败，将在轮询成功时 fallback 创建: %s",
                        step_err,
                        exc_info=True,
                    )
        _logger.info(f"[GRID] 宫格 i2i 任务已创建: {task_key}, project_id={project_ids[0]}, target_ids={target_ids_for_db}")
    except Exception as e:
        # 入库失败必须返回失败：否则上层误认为已提交，但后台无任务可轮询/切图/回写。
        # ComfyUI 侧的图生图请求虽已提交，但没有任务记录就无法走切图回写，等于无效提交。
        _logger.error(f"[GRID] 宫格 i2i 后台任务记录创建失败（请求已提交但无任务记录）: {e}", exc_info=True)
        return {
            'success': False,
            'error': f'宫格 i2i 请求已提交但后台任务记录创建失败: {e}',
            'project_ids': project_ids,
            'task_key': task_key,
            'model_used': model_name,
        }
    return {
        'success': True,
        'project_ids': project_ids,
        'grid_task_id': grid_task_id,
        'pipeline_step_id': pipeline_step_id,
        'status': 'submitted',
        'mode': 'image_edit',
        'grid_layout': grid_layout,
        'item_type_name': item_info['name_cn'],
        'base_item_type': item_info.get('base_type'),
        'item_names': item_names,
        'target_entity_ids': target_ids_for_db,
        'model_used': model_name,
        # 统一模型对账字段：调用方用它校验实际模型与批任务快照一致
        'model_task_id': edit_task_id,
        'task_key': task_key,
        'message': f'宫格 i2i 请求已提交（父图作为输入），project_ids={project_ids}',
    }


def generate_9grid_location_images(
    user_id: str,
    world_id: str,
    auth_token: str,
    sub_location_names: List[str],
    prompts: List[str],
    reference_images: Optional[List[Dict[str, str]]] = None,
    target_entity_ids: Optional[List[Optional[int]]] = None,
) -> Dict[str, Any]:
    """
    生成 3x3 九宫格子场景参考图（以参考图为输入，走图生图）。

    用于分镜首帧生成前，先用父场景图等参考图作为 i2i 输入，一次合成 9 个子场景参考图，
    切图后按子场景 location.id 回写 reference_image。

    不足 9 个子场景时，调用方应补 placeholder 占位（不回写、不建 location）。
    超过 9 个时，调用方应拆成多个 3x3 批次分别调用。

    Args:
        user_id / world_id / auth_token: 用户/世界/认证。
        sub_location_names: 9 个子场景名称（含 placeholder 占位）。
        prompts: 9 个子场景提示词。
        reference_images: 参考图列表，每项 {"url": str, "role_description": str}。
            通常含父场景图（role_description 说明是父场景全景）；也可含角色图等其他参考。
            url 为本地路径或 http URL；role_description 拼进 prompt 全局说明区。
        target_entity_ids: 9 个子场景对应的 location DB id（与 sub_location_names 对齐；
            placeholder 位传 None）。切图后按此 id 回写 location.reference_image，
            并使 has_running_grid_for_entity 能查到运行中任务。

    Returns:
        dict: submit_grid_image_task 的结果。
    """
    return submit_grid_image_task(
        user_id=user_id,
        world_id=world_id,
        auth_token=auth_token,
        item_names=sub_location_names,
        prompts=prompts,
        item_type=ItemType.LOCATION_GRID,
        grid_size=GridConfig.SIZE_3X3,
        mode="image_edit",
        reference_images=reference_images,
        target_entity_ids=target_entity_ids,
    )


def generate_4grid_location_images_i2i(
    user_id: str,
    world_id: str,
    auth_token: str,
    sub_location_names: List[str],
    prompts: List[str],
    reference_images: Optional[List[Dict[str, str]]] = None,
    target_entity_ids: Optional[List[Optional[int]]] = None,
) -> Dict[str, Any]:
    """
    生成 2x2 四宫格子场景参考图（以参考图为输入，走图生图）。

    与 generate_9grid_location_images 对称，区别仅在于 grid_size=4。用于子场景数量较少
    （≤4）时避免凑大量黑色占位格：9 宫格只有 1 个真实子场景时要凑 8 个占位，占位占比
    过高既浪费算力又易触发宫格几何校验误判。≤4 个子场景改走 2x2 更经济、校验更稳。

    不足 4 个子场景时，调用方应补 placeholder 占位（不回写、不建 location）。

    Args:
        user_id / world_id / auth_token: 用户/世界/认证。
        sub_location_names: 4 个子场景名称（含 placeholder 占位）。
        prompts: 4 个子场景提示词。
        reference_images: 参考图列表，每项 {"url": str, "role_description": str}。
            通常含父场景图；与 9grid 版语义完全一致。
        target_entity_ids: 4 个子场景对应的 location DB id（与名称对齐；placeholder 位传 None）。

    Returns:
        dict: submit_grid_image_task 的结果。
    """
    return submit_grid_image_task(
        user_id=user_id,
        world_id=world_id,
        auth_token=auth_token,
        item_names=sub_location_names,
        prompts=prompts,
        item_type=ItemType.LOCATION_GRID,
        grid_size=GridConfig.SIZE_2X2,
        mode="image_edit",
        reference_images=reference_images,
        target_entity_ids=target_entity_ids,
    )


def generate_4grid_character_images(user_id: str, world_id: str, auth_token: str,
                                    character_names: List[str], prompts: List[str]) -> Dict[str, Any]:
    """
    生成4宫格角色图像并自动切分更新到各个角色（向后兼容的包装函数）

    注意：不同生图模型算力价格不同，请先调用 get_text_to_image_model_info 了解当前模型。

    Args:
        user_id: 用户ID（必填）
        world_id: 世界ID（必填）
        auth_token: 认证令牌（必填）
        character_names: 4个角色的名称列表（必须是4个）
        prompts: 4个角色的提示词列表（必须是4个）

    Returns:
        dict: 操作结果，包含每个角色的更新状态、算力消耗等
    """
    result = generate_4grid_images(
        user_id=user_id,
        world_id=world_id,
        auth_token=auth_token,
        item_names=character_names,
        prompts=prompts,
        item_type=4  # 角色四宫格类型
    )

    # 转换返回格式以保持向后兼容
    if result.get('success') and 'items' in result:
        result['characters'] = result['items']

    return result


def generate_character_variant_image(user_id: str, world_id: str, auth_token: str,
                                      character_name: str, variant_label: str,
                                      variant_prompt: str, aspect_ratio: str = "16:9",
                                      force_update: bool = False) -> Dict[str, Any]:
    """
    生成角色造型变体图 - 基于已有主参考图做图片编辑（图生图），写入 reference_images 数组

    变体图与主图（reference_image）格式相同，都是三视角参考图（正面、侧面、背面），但服装/造型不同。
    为保持五官/身份一致，内部走 edit_image（基于 reference_image），而不是文生图。
    生成的图片完成后会自动追加到角色 JSON 的 reference_images 数组中。

    注意：图片编辑模型由用户在前端界面选择，请先调用 get_text_to_image_model_info 了解当前模型。

    Args:
        user_id: 用户ID（必填）
        world_id: 世界ID（必填）
        auth_token: 认证令牌（必填）
        character_name: 角色名称（必填），如"豆包"
        variant_label: 变体标签（必填），如"晚礼服"、"战斗装"，用于在 reference_images 中标识该变体
        variant_prompt: 三视角提示词（必填），强调保持参考图人物身份一致，仅改变服装/造型
        aspect_ratio: 图片宽高比（默认：16:9）
        force_update: 是否覆盖已有同标签变体图（默认：False）

    Returns:
        dict: 操作结果，包含 success 状态、project_ids、角色名、变体标签等
    """
    # 检查角色是否存在
    file_manager = get_file_manager()
    character_data = file_manager.get_character_json(character_name, user_id, world_id)
    if not character_data:
        return {
            'success': False,
            'error': f'角色 "{character_name}" 不存在，请先创建角色'
        }

    # 检查是否已有同标签的变体图（除非 force_update=True）
    if not force_update:
        existing_variants = character_data.get('reference_images', [])
        if any(v.get('label') == variant_label for v in existing_variants if isinstance(v, dict)):
            return {
                'success': False,
                'error': f'角色 "{character_name}" 已存在标签为 "{variant_label}" 的变体图，如需更新请设置 force_update=True',
                'existing_variant': [v for v in existing_variants if v.get('label') == variant_label][0],
                'skip_reason': 'already_has_variant'
            }

    # 检查角色是否已有主参考图（变体图必须基于主图做图片编辑）
    main_image_url = (character_data.get('reference_image') or '').strip()
    if not main_image_url:
        return {
            'success': False,
            'error': f'角色 "{character_name}" 尚未生成主参考图(reference_image)，请先生成主图后再生成变体图',
            'skip_reason': 'no_main_image'
        }

    # 主图必须是 http/https，否则 edit_image 无法引用
    from urllib.parse import urlparse
    parsed_main = urlparse(main_image_url)
    if parsed_main.scheme not in ('http', 'https'):
        return {
            'success': False,
            'error': f'角色 "{character_name}" 的主参考图URL无效（仅支持 http/https）: {main_image_url[:100]}',
            'skip_reason': 'invalid_main_image_url'
        }

    # 构造复合 item_name：角色名|变体标签，用于任务追踪和回调时区分
    composite_item_name = f"{character_name}|{variant_label}"

    # 基于主参考图做图片编辑（图生图），item_type=7 表示角色变体图
    result = edit_image(
        user_id=user_id,
        world_id=world_id,
        auth_token=auth_token,
        prompt=variant_prompt,
        image_url=main_image_url,
        aspect_ratio=aspect_ratio,
        item_type=7,
        item_name=composite_item_name,
        force_update_exist_image=force_update,
    )

    # 添加角色名和变体标签到返回结果中
    if result.get('success'):
        result['character_name'] = character_name
        result['variant_label'] = variant_label
        result['composite_item_name'] = composite_item_name
        result['source_image_url'] = main_image_url

    return result


def generate_4grid_location_images(user_id: str, world_id: str, auth_token: str,
                                    location_names: List[str], prompts: List[str],
                                    target_entity_ids: Optional[List[Optional[int]]] = None) -> Dict[str, Any]:
    """
    生成4宫格场景图像并自动切分更新到各个场景（向后兼容的包装函数）

    注意：不同生图模型算力价格不同，请先调用 get_text_to_image_model_info 了解当前模型。

    Args:
        user_id: 用户ID（必填）
        world_id: 世界ID（必填）
        auth_token: 认证令牌（必填）
        location_names: 4个场景的名称列表（必须是4个）
        prompts: 4个场景的提示词列表（必须是4个）
        target_entity_ids: 可选的场景数据库 ID 列表。提供时走统一 t2i 宫格入口，
            使切图结果按 ID 回写 location.reference_image。

    Returns:
        dict: 操作结果，包含每个场景的更新状态、算力消耗等
    """
    if target_entity_ids is not None:
        result = submit_grid_image_task(
            user_id=user_id,
            world_id=world_id,
            auth_token=auth_token,
            item_names=location_names,
            prompts=prompts,
            item_type=ItemType.LOCATION_GRID,
            grid_size=GridConfig.SIZE_2X2,
            mode="text_to_image",
            target_entity_ids=target_entity_ids,
        )
    else:
        result = generate_4grid_images(
            user_id=user_id,
            world_id=world_id,
            auth_token=auth_token,
            item_names=location_names,
            prompts=prompts,
            item_type=ItemType.LOCATION_GRID,
        )

    # 转换返回格式以保持向后兼容
    if result.get('success') and 'items' in result:
        result['locations'] = result['items']

    return result


def generate_4grid_prop_images(user_id: str, world_id: str, auth_token: str,
                                prop_names: List[str], prompts: List[str]) -> Dict[str, Any]:
    """
    生成4宫格道具图像并自动切分更新到各个道具（向后兼容的包装函数）

    注意：不同生图模型算力价格不同，请先调用 get_text_to_image_model_info 了解当前模型。

    Args:
        user_id: 用户ID（必填）
        world_id: 世界ID（必填）
        auth_token: 认证令牌（必填）
        prop_names: 4个道具的名称列表（必须是4个）
        prompts: 4个道具的提示词列表（必须是4个）

    Returns:
        dict: 操作结果，包含每个道具的更新状态、算力消耗等
    """
    result = generate_4grid_images(
        user_id=user_id,
        world_id=world_id,
        auth_token=auth_token,
        item_names=prop_names,
        prompts=prompts,
        item_type=6  # 道具四宫格类型
    )

    # 转换返回格式以保持向后兼容
    if result.get('success') and 'items' in result:
        result['props'] = result['items']

    return result


def get_long_user_input(user_id: str, world_id: str, auth_token: str, name: str, limit: Optional[int] = None) -> str:
    """
    读取用户长文本输入的完整内容
    
    Args:
        user_id: 用户ID（必填）
        world_id: 世界ID（必填）
        auth_token: 认证令牌（必填）
        name: 文件名（例如：2026_01_22_14_01_12_abc123.txt）
        limit: 可选，限制返回字符数，避免token消耗过大
    
    Returns:
        文件完整内容或限制长度的内容
    
    Raises:
        ValueError: 文件不存在时抛出
    """
    if not user_id or not world_id:
        return json.dumps({
            'success': False,
            'error': '用户ID和世界ID不能为空'
        }, ensure_ascii=False)
    
    file_dir = os.path.join(FilePathConstants._SCRIPT_WRITER_USER_DATA_SUBDIR, str(user_id), str(world_id), "user_long_input")
    file_path = os.path.join(file_dir, name)
    
    if not os.path.exists(file_path):
        # 文件不存在时，列出目录中的所有文件供纠错
        available_files = []
        if os.path.exists(file_dir):
            try:
                available_files = [f for f in os.listdir(file_dir) if f.endswith('.txt')]
                available_files.sort(reverse=True)  # 按时间倒序排列
            except Exception as e:
                logger.error(f"列出user_long_input目录失败: {e}")
        
        return json.dumps({
            'success': False,
            'error': f'文件不存在：{name}',
            'available_files': available_files,
            'suggestion': f'可用的文件列表（共{len(available_files)}个）：{", ".join(available_files[:10])}' if available_files else '目录中没有可用文件'
        }, ensure_ascii=False)
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        if limit and len(content) > limit:
            truncated_content = content[:limit]
            return json.dumps({
                'success': True,
                'content': truncated_content,
                'truncated': True,
                'total_length': len(content),
                'message': f'内容已截断，完整内容共 {len(content)} 字，返回前 {limit} 字'
            }, ensure_ascii=False)
        
        return json.dumps({
            'success': True,
            'content': content,
            'truncated': False,
            'total_length': len(content)
        }, ensure_ascii=False)
        
    except Exception as e:
        return json.dumps({
            'success': False,
            'error': f'读取文件失败：{str(e)}'
        }, ensure_ascii=False)
