"""
Pipeline 驱动工厂
根据 step_type 创建对应的 pipeline 驱动实例。
"""
import json
import logging
from typing import Optional, List, Dict, Any

from model import PipelineStepType, PipelineStepModel, PipelineStage, AIToolsModel
from config.config_util import get_dynamic_config_value
from config.unified_config import (
    UnifiedConfigRegistry,
    get_implementation_id,
    get_implementation_name,
    DriverKey,
    SEEDANCE_FACE_MASK_DRIVER_KEYS,
)

from .base_pipeline_driver import BasePipelineDriver
from .face_mask_driver import FaceMaskPipelineDriver
from .image_face_mask_driver import ImageFaceMaskPipelineDriver
from .implementation_retry_driver import ImplementationRetryPipelineDriver
from .storyboard_grid_split_driver import StoryboardGridSplitPipelineDriver
from .h3_prompt_optimize_driver import H3PromptOptimizePipelineDriver
from .h3_prompt_optimize_util import resolve_h3_prompt_variant

logger = logging.getLogger(__name__)

# 驱动注册表
_DRIVER_MAP = {
    PipelineStepType.FACE_MASK: FaceMaskPipelineDriver,
    PipelineStepType.IMAGE_FACE_MASK: ImageFaceMaskPipelineDriver,
    PipelineStepType.IMPLEMENTATION_RETRY: ImplementationRetryPipelineDriver,
    PipelineStepType.STORYBOARD_FIRST_FRAME_GRID_SPLIT: StoryboardGridSplitPipelineDriver,
    PipelineStepType.H3_PROMPT_OPTIMIZE: H3PromptOptimizePipelineDriver,
}


class PipelineDriverFactory:
    """Pipeline 驱动工厂"""

    # 走人脸遮盖预处理的 Seedance 任务 DriverKey（单一来源：config/unified_config.py）
    _SEEDANCE_FACE_MASK_KEYS = SEEDANCE_FACE_MASK_DRIVER_KEYS

    @staticmethod
    def create_driver(step_type: str) -> Optional[BasePipelineDriver]:
        """
        根据 step_type 创建驱动实例

        Args:
            step_type: 步骤类型（如 'face_mask', 'implementation_retry'）

        Returns:
            驱动实例，未找到返回 None
        """
        driver_class = _DRIVER_MAP.get(step_type)
        if driver_class:
            return driver_class()
        logger.warning(f"Unknown pipeline step type: {step_type}")
        return None

    # ==================== param_prepare 步骤创建规则 ====================

    # 需要人脸遮盖的任务类型（Seedance 2.0 带视频输入）
    # key 为 UnifiedTaskConfig.key，value 为步骤配置
    _PARAM_PREPARE_RULES = {
        DriverKey.SEEDANCE_2_0_IMAGE_TO_VIDEO: {
            'condition': lambda ai_tool: bool(getattr(ai_tool, 'video_path', None)),
            'steps': [
                {
                    'step_type': PipelineStepType.FACE_MASK,
                    'params_fn': lambda ai_tool: {'video_path': ai_tool.video_path}
                }
            ]
        },
        DriverKey.SEEDANCE_2_0_FAST_IMAGE_TO_VIDEO: {
            'condition': lambda ai_tool: bool(getattr(ai_tool, 'video_path', None)),
            'steps': [
                {
                    'step_type': PipelineStepType.FACE_MASK,
                    'params_fn': lambda ai_tool: {'video_path': ai_tool.video_path}
                }
            ]
        },
    }

    @staticmethod
    def _split_paths(value: Any) -> List[str]:
        """解析逗号分隔路径，过滤空值。"""
        if not value:
            return []
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return []

    @classmethod
    def _get_reference_images(cls, ai_tool) -> List[str]:
        """解析 ai_tool.reference_images，兼容 JSON 数组和逗号分隔字符串。"""
        raw_value = getattr(ai_tool, 'reference_images', None)
        if not raw_value:
            return []
        if isinstance(raw_value, list):
            return cls._split_paths(raw_value)
        if isinstance(raw_value, str):
            try:
                parsed = json.loads(raw_value)
                if isinstance(parsed, list):
                    return cls._split_paths(parsed)
            except json.JSONDecodeError:
                return cls._split_paths(raw_value)
        return []

    @classmethod
    def _build_seedance_param_prepare_steps(cls, ai_tool) -> List[Dict[str, Any]]:
        """根据 Seedance 输入构建图片/视频人脸遮盖预处理步骤配置。

        受 pipeline.seedance_face_mask_enabled 总开关控制，关闭后图片和视频遮盖步骤均不创建。
        """
        step_configs: List[Dict[str, Any]] = []

        face_mask_enabled = get_dynamic_config_value(
            'pipeline',
            'seedance_face_mask_enabled',
            default=True
        )
        if not face_mask_enabled:
            return step_configs

        for video_path in cls._split_paths(getattr(ai_tool, 'video_path', None)):
            step_configs.append({
                'step_type': PipelineStepType.FACE_MASK,
                'params': {'video_path': video_path},
                'target': video_path,
            })

        for idx, image_path in enumerate(cls._split_paths(getattr(ai_tool, 'image_path', None))):
            step_configs.append({
                'step_type': PipelineStepType.IMAGE_FACE_MASK,
                'params': {
                    'image_path': image_path,
                    'field': 'image_path',
                    'index': idx,
                },
                'target': image_path,
            })

        for idx, image_path in enumerate(cls._get_reference_images(ai_tool)):
            step_configs.append({
                'step_type': PipelineStepType.IMAGE_FACE_MASK,
                'params': {
                    'image_path': image_path,
                    'field': 'reference_images',
                    'index': idx,
                },
                'target': image_path,
            })

        return step_configs

    @classmethod
    def _build_h3_prompt_optimize_steps(cls, ai_tool) -> List[Dict[str, Any]]:
        """MiniMax H3 图生视频提交前的 I2VA/FL2VA 提示词优化。"""
        enabled = get_dynamic_config_value(
            "pipeline",
            "h3_prompt_optimize_enabled",
            default=True,
        )
        if not enabled:
            return []
        variant = resolve_h3_prompt_variant(ai_tool)
        if not variant:
            return []
        original = getattr(ai_tool, "prompt", None) or ""
        duration = getattr(ai_tool, "duration", None) or 5
        return [{
            "step_type": PipelineStepType.H3_PROMPT_OPTIMIZE,
            "params": {
                "variant": variant,
                "original_prompt": original,
                "duration": duration,
            },
            "target": variant,
        }]

    @classmethod
    def is_seedance_face_mask_type(cls, ai_tool_type: int) -> bool:
        """判断某任务类型（TaskTypeId）是否属于走 param_prepare 人脸遮盖的 Seedance 模型。

        供 server.py 等外部入口查询，避免各处重复维护 Seedance 模型清单。
        """
        task_config = UnifiedConfigRegistry.get_by_id(ai_tool_type)
        return bool(task_config and task_config.key in cls._SEEDANCE_FACE_MASK_KEYS)

    @classmethod
    def create_param_prepare_steps(
        cls,
        ai_tool_id: int,
        ai_tool_type: int
    ) -> List[int]:
        """
        根据任务类型自动创建 param_prepare 步骤

        Args:
            ai_tool_id: ai_tools.id
            ai_tool_type: ai_tools.type（任务类型 ID）

        Returns:
            创建的步骤 ID 列表，无步骤则返回空列表
        """
        task_config = UnifiedConfigRegistry.get_by_id(ai_tool_type)
        if not task_config:
            return []

        rule = cls._PARAM_PREPARE_RULES.get(task_config.key)
        is_seedance_face_mask = task_config.key in cls._SEEDANCE_FACE_MASK_KEYS
        is_h3_prompt_optimize = task_config.key == DriverKey.MINIMAX_H3_IMAGE_TO_VIDEO
        if not rule and not is_seedance_face_mask and not is_h3_prompt_optimize:
            return []

        # 获取 ai_tool 对象用于条件判断
        ai_tool = AIToolsModel.get_by_id(ai_tool_id)
        if not ai_tool:
            return []

        if is_seedance_face_mask:
            step_configs = cls._build_seedance_param_prepare_steps(ai_tool)
        elif is_h3_prompt_optimize:
            step_configs = cls._build_h3_prompt_optimize_steps(ai_tool)
        elif rule and rule['condition'](ai_tool):
            step_configs = [
                {
                    'step_type': step_cfg['step_type'],
                    'params': step_cfg['params_fn'](ai_tool) if step_cfg.get('params_fn') else None,
                    'target': None,
                }
                for step_cfg in rule['steps']
            ]
        else:
            return []

        # 创建步骤
        step_ids = []
        for idx, step_cfg in enumerate(step_configs):
            step_id = PipelineStepModel.create(
                ai_tool_id=ai_tool_id,
                stage=PipelineStage.PARAM_PREPARE,
                step_type=step_cfg['step_type'],
                step_order=idx,
                params=step_cfg.get('params'),
                target=step_cfg.get('target')
            )
            step_ids.append(step_id)

        if step_ids:
            logger.info(
                f"Created {len(step_ids)} param_prepare steps for ai_tool {ai_tool_id} "
                f"(type={task_config.key}): {step_ids}"
            )

        return step_ids

    # ==================== before_finish 步骤创建 ====================

    # 最大重试次数（替代实现方数量上限）
    _MAX_RETRY_IMPLEMENTATIONS = 3

    @classmethod
    def select_before_finish_retry_candidate(
        cls,
        ai_tool_id: int,
        ai_tool_type: int,
        failed_implementation: int,
        failure_reason: str
    ) -> Optional[Dict[str, Any]]:
        """选择唯一备用实现方并返回步骤定义；不写数据库。"""
        task_config = UnifiedConfigRegistry.get_by_id(ai_tool_type)
        if not task_config or not task_config.implementations:
            return None

        failed_impl_name = get_implementation_name(failed_implementation)

        # 收集替代实现方：按 sort_order 优先级从头遍历，跳过已尝试过的（包括当前失败的）
        impl_list = [impl['name'] for impl in task_config._get_implementations_info()]

        # 获取该 ai_tool 历史上已尝试过的所有实现方及已消耗备用额度
        attempted_ids = set()
        retry_count = 0
        try:
            from model.implementation_attempts import ImplementationAttemptModel
            attempted_ids = ImplementationAttemptModel.get_attempted_implementations(ai_tool_id)
            retry_count = ImplementationAttemptModel.get_retry_implementation_count(ai_tool_id)
        except Exception as e:
            logger.warning(f"Failed to get attempted implementations for ai_tool {ai_tool_id}: {e}")

        if retry_count >= cls._MAX_RETRY_IMPLEMENTATIONS:
            logger.info(
                f"Retry implementation budget exhausted for ai_tool {ai_tool_id}: "
                f"used={retry_count}, max={cls._MAX_RETRY_IMPLEMENTATIONS}"
            )
            return None

        attempted_names = {get_implementation_name(i) for i in attempted_ids}
        attempted_names.discard(None)
        attempted_names.discard('unknown')
        if failed_impl_name:
            attempted_names.add(failed_impl_name)  # 确保当前失败的也被跳过

        selected_impl = None
        for impl_name in impl_list:
            if impl_name in attempted_names:
                continue
            # 检查实现方是否启用
            impl_config = UnifiedConfigRegistry.get_implementation(impl_name)
            if impl_config and not impl_config.is_enabled(task_config.driver_name):
                logger.info(f"Skipping disabled implementation {impl_name} for retry")
                continue
            # 检查实现方是否能初始化（是否有关键配置/key）
            try:
                from task.visual_drivers import VideoDriverFactory
                test_driver = VideoDriverFactory.create_driver_by_implementation(impl_name)
                if not test_driver:
                    create_error = VideoDriverFactory.get_last_create_error()
                    skip_reason = create_error.get('message', '未知原因') if create_error else '未知原因'
                    logger.info(f"Skipping implementation {impl_name} for retry: cannot initialize ({skip_reason})")
                    continue
            except Exception as e:
                logger.info(f"Skipping implementation {impl_name} for retry: validation error ({e})")
                continue
            selected_impl = impl_name
            break

        if not selected_impl:
            logger.info(
                f"No alternative implementations for ai_tool {ai_tool_id}: "
                f"all_candidates={impl_list}, attempted={list(attempted_names)}"
            )
            return None

        retry_index = retry_count + 1
        attempt_number = retry_index + 1
        return {
            'step_order': retry_count,
            'params': {
                'retry_mode': 'single_candidate_v1',
                'retry_index': retry_index,
                'attempt_number': attempt_number,
                'target_implementation': selected_impl,
                'original_failure': failure_reason,
                'failed_implementation': failed_impl_name,
            },
        }

    @classmethod
    def create_before_finish_steps(
        cls,
        ai_tool_id: int,
        ai_tool_type: int,
        failed_implementation: int,
        failure_reason: str,
    ) -> List[int]:
        """选择并创建一个 before_finish 实现方重试步骤。"""
        candidate = cls.select_before_finish_retry_candidate(
            ai_tool_id,
            ai_tool_type,
            failed_implementation,
            failure_reason,
        )
        if not candidate:
            return []
        step_id = PipelineStepModel.create(
            ai_tool_id=ai_tool_id,
            stage=PipelineStage.BEFORE_FINISH,
            step_type=PipelineStepType.IMPLEMENTATION_RETRY,
            step_order=candidate['step_order'],
            params=candidate['params'],
        )
        logger.info(
            f"Created single before_finish retry step for ai_tool {ai_tool_id}: "
            f"step_id={step_id}, target={candidate['params']['target_implementation']}, "
            f"failed={candidate['params']['failed_implementation']}, "
            f"retry_index={candidate['params']['retry_index']}"
        )
        return [step_id]
