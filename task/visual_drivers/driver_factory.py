"""
视频驱动工厂类
根据驱动类型或驱动名称创建相应的驱动实例
"""
from typing import Optional, Tuple, Dict, Any, Union
import logging
from .base_video_driver import BaseVideoDriver
from .exceptions import DriverConfigError
from config.unified_config import UnifiedConfigRegistry, DriverImplementation

logger = logging.getLogger(__name__)


class VideoDriverFactory:
    """
    视频驱动工厂类
    负责创建和管理所有视频生成驱动实例
    
    架构说明：
    1. 任务类型（type） -> 业务驱动名称（business_driver_name）
       例如：3 -> "sora2_image_to_video"
       配置在 VIDEO_DRIVER_MAPPING 中
    
    2. 业务驱动名称 -> 具体实现驱动（implementation_driver_name）
       例如："sora2_image_to_video" -> "sora2_duomi_v1"
       配置在 DRIVER_IMPLEMENTATION_MAPPING 中
    
    3. 具体实现驱动 -> 驱动类实例
       例如："sora2_duomi_v1" -> Sora2VideoDriver()
       通过 register_driver 注册
    
    这样的三层架构允许灵活切换供应商和驱动版本，只需修改配置文件即可
    """
    
    # 已注册的驱动类（实现驱动名称 -> 驱动类）
    _registered_drivers = {}
    
    @classmethod
    def register_driver(cls, driver_name: str, driver_class: type):
        """
        注册驱动类
        
        Args:
            driver_name: 驱动名称
            driver_class: 驱动类（必须继承自 BaseVideoDriver）
        """
        if not issubclass(driver_class, BaseVideoDriver):
            raise ValueError(f"Driver class {driver_class} must inherit from BaseVideoDriver")
        
        cls._registered_drivers[driver_name] = driver_class
        logger.debug(f"Registered video driver: {driver_name} -> {driver_class.__name__}")
    
    # 存储最近一次创建驱动失败的原因（用于返回更友好的错误信息）
    _last_create_error: Optional[Dict[str, Any]] = None

    @classmethod
    def create_driver_by_type(cls, driver_type: int, user_id: Optional[int] = None) -> Optional[BaseVideoDriver]:
        """
        根据驱动类型创建驱动实例（支持用户偏好）

        Args:
            driver_type: 驱动类型（对应 ai_tools 表的 type 字段）
            user_id: 用户ID（可选），用于获取用户偏好

        Returns:
            BaseVideoDriver: 驱动实例，如果类型不支持或驱动未注册则返回 None

        流程：
            1. 任务类型 -> 业务驱动名称（通过 VIDEO_DRIVER_MAPPING）
            2. 业务驱动名称 -> 实现驱动名称（通过 DRIVER_IMPLEMENTATION_MAPPING 或用户偏好）
            3. 实现驱动名称 -> 驱动类实例（通过 _registered_drivers）
        """
        # 清除上次错误
        cls._last_create_error = None

        # 从统一配置获取任务配置
        config = UnifiedConfigRegistry.get_by_id(driver_type)
        if not config:
            logger.error(f"Unsupported driver type: {driver_type}")
            logger.info(f"Supported types: {[c.id for c in UnifiedConfigRegistry.get_all()]}")
            cls._last_create_error = {
                "reason": "UNSUPPORTED_TYPE",
                "message": f"不支持的任务类型: {driver_type}"
            }
            return None

        business_driver_name = config.driver_name
        if not business_driver_name:
            logger.error(f"No driver configured for task type: {driver_type}")
            cls._last_create_error = {
                "reason": "NO_DRIVER",
                "message": f"任务类型 {driver_type} 未配置驱动"
            }
            return None

        # 获取实现驱动名称（考虑用户偏好）和驱动参数
        implementation_driver_name, driver_params = cls._get_implementation_for_user(driver_type, user_id, config)
        if not implementation_driver_name:
            logger.error(f"No implementation configured for business driver: {business_driver_name}")
            cls._last_create_error = {
                "reason": "NO_IMPLEMENTATION",
                "message": f"驱动 {business_driver_name} 未配置实现方"
            }
            return None

        # 第三层：根据实现驱动名称获取驱动类
        driver_class = cls._registered_drivers.get(implementation_driver_name)
        if not driver_class:
            logger.error(f"Driver implementation not registered: {implementation_driver_name}")
            logger.info(f"Registered implementations: {list(cls._registered_drivers.keys())}")
            cls._last_create_error = {
                "reason": "NOT_REGISTERED",
                "message": f"驱动 {implementation_driver_name} 未注册"
            }
            return None

        # 创建驱动实例
        try:
            logger.info(f"Creating driver: type={driver_type} -> business={business_driver_name} -> implementation={implementation_driver_name}")
            # 使用 driver_params 动态创建驱动实例
            return driver_class(**driver_params)
        except DriverConfigError as e:
            logger.warning(f"Driver {implementation_driver_name} 配置不完整: {e.message}")
            logger.info(f"缺少配置: {', '.join(e.missing_configs)}")
            cls._last_create_error = {
                "reason": "CONFIG_MISSING",
                "message": f"驱动配置不完整，缺少: {', '.join(e.missing_configs)}",
                "missing_configs": e.missing_configs
            }
            return None
        except Exception as e:
            logger.error(f"Failed to create driver instance for {implementation_driver_name}: {str(e)}")
            cls._last_create_error = {
                "reason": "CREATE_FAILED",
                "message": f"驱动创建失败: {str(e)}"
            }
            return None

    @classmethod
    def create_driver_by_implementation(cls, implementation_name: str) -> Optional[BaseVideoDriver]:
        """
        根据实现方名称直接创建驱动实例
        用于状态查询时，确保使用任务提交时的相同实现方

        Args:
            implementation_name: 实现方名称（如 'grok_duomi_v1'）

        Returns:
            BaseVideoDriver: 驱动实例，如果未注册则返回 None
        """
        cls._last_create_error = None

        driver_class = cls._registered_drivers.get(implementation_name)
        if not driver_class:
            logger.error(f"Driver implementation not registered: {implementation_name}")
            cls._last_create_error = {
                "reason": "NOT_REGISTERED",
                "message": f"驱动 {implementation_name} 未注册"
            }
            return None

        # 获取驱动参数
        driver_params = {}
        impl_config = UnifiedConfigRegistry.get_implementation(implementation_name)
        if impl_config and impl_config.driver_params:
            driver_params = impl_config.driver_params.copy()

        try:
            logger.info(f"Creating driver by implementation: {implementation_name}")
            return driver_class(**driver_params)
        except DriverConfigError as e:
            logger.warning(f"Driver {implementation_name} 配置不完整: {e.message}")
            cls._last_create_error = {
                "reason": "CONFIG_MISSING",
                "message": f"驱动配置不完整，缺少: {', '.join(e.missing_configs)}",
                "missing_configs": e.missing_configs
            }
            return None
        except Exception as e:
            logger.error(f"Failed to create driver instance for {implementation_name}: {str(e)}")
            cls._last_create_error = {
                "reason": "CREATE_FAILED",
                "message": f"驱动创建失败: {str(e)}"
            }
            return None

    @classmethod
    def get_last_create_error(cls) -> Optional[Dict[str, Any]]:
        """
        获取最近一次创建驱动失败的详细原因

        Returns:
            Dict 包含:
                - reason: 错误类型 (UNSUPPORTED_TYPE, NO_DRIVER, NO_IMPLEMENTATION, NOT_REGISTERED, CONFIG_MISSING, CREATE_FAILED)
                - message: 用户友好的错误信息
                - missing_configs: 缺少的配置项列表（仅 CONFIG_MISSING 时存在）
            如果没有错误则返回 None
        """
        return cls._last_create_error

    @classmethod
    def get_implementation_for_user(cls, task_type: int, user_id: Optional[int] = None) -> Optional[str]:
        """
        获取实现方名称（公开方法，供外部调用）

        Args:
            task_type: 任务类型
            user_id: 用户ID（可选）

        Returns:
            实现方名称，如果不存在返回 None
        """
        config = UnifiedConfigRegistry.get_by_id(task_type)
        if not config:
            return None

        impl_name, _ = cls._get_implementation_for_user(task_type, user_id, config)
        return impl_name

    @classmethod
    def get_agent_hint_for_task(cls, task_id: int, user_id: Optional[int] = None) -> Optional[Dict[str, str]]:
        """
        获取特定任务类型在特定用户下的第一个顺位实现方的 agent_hint。
        走与 create_driver_by_type 相同的实现方选择逻辑（用户偏好 → 排序 → 可用性）。

        Args:
            task_id: 任务类型 ID
            user_id: 用户ID（可选），用于获取用户偏好

        Returns:
            dict or None: {"impl_name": ..., "display_name": ..., "hint": ...}，无 hint 时返回 None
        """
        config = UnifiedConfigRegistry.get_by_id(task_id)
        if not config:
            return None

        impl_name, _ = cls._get_implementation_for_user(task_id, user_id, config)
        if not impl_name:
            return None

        driver_class = cls._registered_drivers.get(impl_name)
        if not driver_class:
            return None

        hint = getattr(driver_class, 'agent_hint', '')
        if not hint:
            return None

        display_name = cls._get_display_name_for_impl(impl_name)
        return {
            "impl_name": impl_name,
            "display_name": display_name,
            "hint": hint
        }

    @classmethod
    def _get_display_name_for_impl(cls, impl_name: str) -> str:
        """从统一配置获取实现方的显示名称"""
        impl_config = UnifiedConfigRegistry.get_implementation(impl_name)
        if impl_config:
            return impl_config.display_name or impl_name
        return impl_name

    @classmethod
    def _get_implementation_for_user(cls, task_type: int, user_id: Optional[int], config) -> Tuple[Optional[str], Dict[str, Any]]:
        """
        获取实现方名称和驱动参数（考虑用户偏好）

        Args:
            task_type: 任务类型
            user_id: 用户ID
            config: 任务配置

        Returns:
            (implementation_name, driver_params) 元组
            - implementation_name: 实现方名称
            - driver_params: 创建驱动实例需要的额外参数，如 {'site_id': 'site_1'}
        """
        impl_name = None

        # 1. 检查用户偏好
        if user_id:
            try:
                from model.users import UsersModel
                task_key = config.key
                user_pref = UsersModel.get_implementation_preference(user_id, task_key)
                if user_pref:
                    # 验证用户偏好：配置就绪 且 已启用（admin 禁用的实现方不能被偏好绕过）
                    if cls._is_driver_available(user_pref) and cls._is_impl_enabled(user_pref, config.driver_name):
                        logger.debug(f"Using user preference for task {task_key}: {user_pref}")
                        impl_name = user_pref
                    else:
                        logger.warning(f"User preference {user_pref} unavailable or disabled, will auto-select")
            except Exception as e:
                logger.warning(f"Failed to get user preference: {e}")

        # 2. 如果没有用户偏好或偏好不可用，根据排序选择排序最靠前的可用实现方
        if not impl_name:
            available_impls = config._get_implementations_info()
            for impl in available_impls:
                if cls._is_driver_available(impl['name']):
                    impl_name = impl['name']
                    logger.debug(f"Auto-selected implementation for task {config.key}: {impl_name}")
                    break

            # 回退到默认实现方
            if not impl_name:
                impl_name = config.implementation
                logger.warning(f"All implementations unavailable for task {config.key}, falling back to default: {impl_name}")

        # 3. 获取驱动参数
        driver_params = {}
        if impl_name:
            impl_config = UnifiedConfigRegistry.get_implementation(impl_name)
            if impl_config and impl_config.driver_params:
                driver_params = impl_config.driver_params.copy()

        return impl_name, driver_params

    @classmethod
    def _is_driver_available(cls, impl_name: str) -> bool:
        """
        检查实现方驱动是否可用（配置已就绪）

        仅校验驱动能否实例化（必需配置键是否有值），**不检查 enabled**。
        若需同时尊重 admin 禁用，请配合 `_is_impl_enabled` 使用（偏好采纳路径必须二者都过）。

        Args:
            impl_name: 实现方名称

        Returns:
            bool: 驱动是否可用
        """
        driver_class = cls._registered_drivers.get(impl_name)
        if not driver_class:
            return False
        try:
            driver_class()
            return True
        except Exception:
            return False

    @classmethod
    def _is_impl_enabled(cls, impl_name: str, driver_key: Optional[str]) -> bool:
        """
        检查实现方是否启用（尊重 admin 在 implementation_power_config 的 enabled 设置）

        用于偏好采纳路径：被 admin 禁用的实现方，即便配置就绪、即便用户偏好指向它，
        也不应被选中。复用 ImplementationConfig.is_enabled（unified_config.py）的 DB 读取。

        Args:
            impl_name: 实现方名称
            driver_key: 业务驱动名（任务配置的 driver_name），用于 DB 查询

        Returns:
            bool: 启用返回 True；未注册/异常/被禁用返回 False（保守，避免禁用失效）
        """
        try:
            impl_config = UnifiedConfigRegistry.get_implementation(impl_name)
            if not impl_config:
                return False
            return impl_config.is_enabled(driver_key)
        except Exception:
            return False
    
    @classmethod
    def get_supported_types(cls) -> list:
        """
        获取所有支持的驱动类型
        
        Returns:
            list: 支持的驱动类型列表
        """
        return [c.id for c in UnifiedConfigRegistry.get_all() if c.driver_name]
    
    @classmethod
    def get_supported_drivers(cls) -> list:
        """
        获取所有已注册的驱动名称
        
        Returns:
            list: 已注册的驱动名称列表
        """
        return list(cls._registered_drivers.keys())
    
    @classmethod
    def is_type_supported(cls, driver_type: int) -> bool:
        """
        检查驱动类型是否支持
        
        Args:
            driver_type: 驱动类型
        
        Returns:
            bool: 是否支持
        """
        config = UnifiedConfigRegistry.get_by_id(driver_type)
        return config is not None and config.driver_name is not None
    
    @classmethod
    def is_driver_registered(cls, driver_name: str) -> bool:
        """
        检查驱动是否已注册
        
        Args:
            driver_name: 驱动名称
        
        Returns:
            bool: 是否已注册
        """
        return driver_name in cls._registered_drivers
    
    @classmethod
    def get_driver_availability(cls) -> dict:
        """
        获取所有 driver 的可用状态
        
        Returns:
            dict: 任务类型 -> 可用状态
                {
                    "3": {"available": True, "missing_configs": []},
                    "10": {"available": False, "missing_configs": ["RunningHub API Key"]},
                    ...
                }
        """
        result = {}
        for config in UnifiedConfigRegistry.get_all():
            if not config.driver_name:
                continue

            task_type = config.id

            # 收集所有需要检查的实现方（默认 + 可选）
            impl_list = list(config.implementations) if config.implementations else []
            if config.implementation and config.implementation not in impl_list:
                impl_list.insert(0, config.implementation)

            if not impl_list:
                result[str(task_type)] = {
                    "available": False,
                    "missing_configs": ["未配置实现驱动"]
                }
                continue

            # 遍历所有实现方，只要有任意一个可用就标记为可用
            available_impl = None
            last_error_configs = ["未配置实现驱动"]

            for impl_name in impl_list:
                driver_class = cls._registered_drivers.get(impl_name)
                if not driver_class:
                    continue
                try:
                    driver_class()  # 尝试创建实例验证配置
                    available_impl = impl_name
                    break
                except DriverConfigError as e:
                    last_error_configs = e.missing_configs
                except Exception as e:
                    logger.warning(f"检查 driver {impl_name} 可用性时出错: {e}")
                    last_error_configs = [str(e)]

            if available_impl:
                result[str(task_type)] = {
                    "available": True,
                    "missing_configs": []
                }
            else:
                result[str(task_type)] = {
                    "available": False,
                    "missing_configs": last_error_configs
                }

        return result


def register_all_drivers():
    """
    注册所有视频驱动
    此函数应在应用启动时调用

    注意：这里注册的是具体实现驱动（implementation_driver_name），
    而不是业务驱动名称（business_driver_name）
    """
    # 导入所有驱动类并注册
    # 注册格式：实现驱动名称 -> 驱动类
    
    try:
        from .sora2_duomi_v1_driver import Sora2DuomiV1Driver
        # 注册 Sora2 多米供应商 v1 版本
        VideoDriverFactory.register_driver(DriverImplementation.SORA2_DUOMI_V1, Sora2DuomiV1Driver)
    except ImportError as e:
        logger.warning(f"Failed to import Sora2DuomiV1Driver: {e}")

    try:
        from .grok_duomi_v1_driver import GrokDuomiV1Driver
        # 注册 Grok 多米供应商 v1 版本
        VideoDriverFactory.register_driver(DriverImplementation.GROK_DUOMI_V1, GrokDuomiV1Driver)
    except ImportError as e:
        logger.warning(f"Failed to import GrokDuomiV1Driver: {e}")

    try:
        from .kling_duomi_v1_driver import KlingDuomiV1Driver
        # 注册 Kling 多米供应商 v1 版本
        VideoDriverFactory.register_driver(DriverImplementation.KLING_DUOMI_V1, KlingDuomiV1Driver)
    except ImportError as e:
        logger.warning(f"Failed to import KlingDuomiV1Driver: {e}")

    # Kling 通用聚合站点驱动注册（无条件注册，配置检查在运行时 _get_implementations_info 中进行）
    try:
        from .kling_common_v1_driver import (
            KlingCommonSite0V1Driver,
            KlingCommonSite1V1Driver,
            KlingCommonSite2V1Driver,
            KlingCommonSite3V1Driver,
            KlingCommonSite4V1Driver,
            KlingCommonSite5V1Driver,
        )
        for impl_name, driver_class in [
            (DriverImplementation.KLING_COMMON_SITE0_V1, KlingCommonSite0V1Driver),
            (DriverImplementation.KLING_COMMON_SITE1_V1, KlingCommonSite1V1Driver),
            (DriverImplementation.KLING_COMMON_SITE2_V1, KlingCommonSite2V1Driver),
            (DriverImplementation.KLING_COMMON_SITE3_V1, KlingCommonSite3V1Driver),
            (DriverImplementation.KLING_COMMON_SITE4_V1, KlingCommonSite4V1Driver),
            (DriverImplementation.KLING_COMMON_SITE5_V1, KlingCommonSite5V1Driver),
        ]:
            VideoDriverFactory.register_driver(impl_name, driver_class)
    except ImportError as e:
        logger.warning(f"Failed to import KlingCommon site drivers: {e}")
    
    try:
        from .gemini_duomi_v1_driver import GeminiDuomiV1Driver
        # 注册 Gemini 多米供应商 v1 版本（标准版）
        VideoDriverFactory.register_driver(DriverImplementation.GEMINI_DUOMI_V1, GeminiDuomiV1Driver)
    except ImportError as e:
        logger.warning(f"Failed to import GeminiDuomiV1Driver: {e}")

    try:
        from .gpt_image_duomi_v1_driver import GptImageDuomiV1Driver
        # 注册 GPT Image 多米供应商 v1 版本
        VideoDriverFactory.register_driver(DriverImplementation.DUOMI_GPT_IMAGE_V1, GptImageDuomiV1Driver)
    except ImportError as e:
        logger.warning(f"Failed to import GptImageDuomiV1Driver: {e}")

    # GPT Image 2 通用聚合站点驱动注册（无条件注册，配置检查在运行时进行）
    try:
        from .gpt_image_common_v1_driver import (
            GptImageCommonSite0V1Driver,
            GptImageCommonSite1V1Driver,
            GptImageCommonSite2V1Driver,
            GptImageCommonSite3V1Driver,
            GptImageCommonSite4V1Driver,
            GptImageCommonSite5V1Driver,
        )
        for impl_name, driver_class in [
            (DriverImplementation.GPT_IMAGE_COMMON_SITE0_V1, GptImageCommonSite0V1Driver),
            (DriverImplementation.GPT_IMAGE_COMMON_SITE1_V1, GptImageCommonSite1V1Driver),
            (DriverImplementation.GPT_IMAGE_COMMON_SITE2_V1, GptImageCommonSite2V1Driver),
            (DriverImplementation.GPT_IMAGE_COMMON_SITE3_V1, GptImageCommonSite3V1Driver),
            (DriverImplementation.GPT_IMAGE_COMMON_SITE4_V1, GptImageCommonSite4V1Driver),
            (DriverImplementation.GPT_IMAGE_COMMON_SITE5_V1, GptImageCommonSite5V1Driver),
        ]:
            VideoDriverFactory.register_driver(impl_name, driver_class)
    except ImportError as e:
        logger.warning(f"Failed to import GPT Image Common site drivers: {e}")

    try:
        from .veo3_duomi_v1_driver import Veo3DuomiV1Driver
        # 注册 VEO3 多米供应商 v1 版本
        VideoDriverFactory.register_driver(DriverImplementation.VEO3_DUOMI_V1, Veo3DuomiV1Driver)
    except ImportError as e:
        logger.warning(f"Failed to import Veo3DuomiV1Driver: {e}")

    # VEO3 通用聚合站点驱动注册（无条件注册，配置检查在运行时进行）
    try:
        from .veo3_common_v1_driver import (
            Veo3CommonSite0V1Driver,
            Veo3CommonSite1V1Driver,
            Veo3CommonSite2V1Driver,
            Veo3CommonSite3V1Driver,
            Veo3CommonSite4V1Driver,
            Veo3CommonSite5V1Driver
        )
        for impl_name, driver_class in [
            (DriverImplementation.VEO3_COMMON_SITE0_V1, Veo3CommonSite0V1Driver),
            (DriverImplementation.VEO3_COMMON_SITE1_V1, Veo3CommonSite1V1Driver),
            (DriverImplementation.VEO3_COMMON_SITE2_V1, Veo3CommonSite2V1Driver),
            (DriverImplementation.VEO3_COMMON_SITE3_V1, Veo3CommonSite3V1Driver),
            (DriverImplementation.VEO3_COMMON_SITE4_V1, Veo3CommonSite4V1Driver),
            (DriverImplementation.VEO3_COMMON_SITE5_V1, Veo3CommonSite5V1Driver),
        ]:
            VideoDriverFactory.register_driver(impl_name, driver_class)
    except ImportError as e:
        logger.warning(f"Failed to import Veo3Common site drivers: {e}")
    
    # Gemini API 聚合器站点驱动注册（无条件注册，配置检查在运行时进行）
    try:
        from .gemini_image_preview_common_v1_driver import (
            GeminiImagePreviewSite0V1Driver,
            GeminiImagePreviewSite1V1Driver,
            GeminiImagePreviewSite2V1Driver,
            GeminiImagePreviewSite3V1Driver,
            GeminiImagePreviewSite4V1Driver,
            GeminiImagePreviewSite5V1Driver
        )
        for impl_name, driver_class in [
            (DriverImplementation.GEMINI_IMAGE_PREVIEW_SITE0_V1, GeminiImagePreviewSite0V1Driver),
            (DriverImplementation.GEMINI_IMAGE_PREVIEW_SITE1_V1, GeminiImagePreviewSite1V1Driver),
            (DriverImplementation.GEMINI_IMAGE_PREVIEW_SITE2_V1, GeminiImagePreviewSite2V1Driver),
            (DriverImplementation.GEMINI_IMAGE_PREVIEW_SITE3_V1, GeminiImagePreviewSite3V1Driver),
            (DriverImplementation.GEMINI_IMAGE_PREVIEW_SITE4_V1, GeminiImagePreviewSite4V1Driver),
            (DriverImplementation.GEMINI_IMAGE_PREVIEW_SITE5_V1, GeminiImagePreviewSite5V1Driver),
        ]:
            VideoDriverFactory.register_driver(impl_name, driver_class)
    except ImportError as e:
        logger.warning(f"Failed to import Gemini Image Preview Site drivers: {e}")
    
    try:
        from .ltx2_runninghub_v1_driver import Ltx2RunninghubV1Driver
        # 注册 LTX2 RunningHub v1 版本
        VideoDriverFactory.register_driver(DriverImplementation.LTX2_RUNNINGHUB_V1, Ltx2RunninghubV1Driver)
    except ImportError as e:
        logger.warning(f"Failed to import Ltx2RunninghubV1Driver: {e}")

    try:
        from .ltx2_3_runninghub_v1_driver import Ltx2Dot3RunninghubV1Driver
        # 注册 LTX2.3 RunningHub v1 版本
        VideoDriverFactory.register_driver(DriverImplementation.LTX2_3_RUNNINGHUB_V1, Ltx2Dot3RunninghubV1Driver)
    except ImportError as e:
        logger.warning(f"Failed to import Ltx2Dot3RunninghubV1Driver: {e}")

    try:
        from .wan22_runninghub_v1_driver import Wan22RunninghubV1Driver
        # 注册 Wan22 RunningHub v1 版本
        VideoDriverFactory.register_driver(DriverImplementation.WAN22_RUNNINGHUB_V1, Wan22RunninghubV1Driver)
    except ImportError as e:
        logger.warning(f"Failed to import Wan22RunninghubV1Driver: {e}")
    
    try:
        from .digital_human_runninghub_v1_driver import DigitalHumanRunninghubV1Driver
        # 注册 Digital Human RunningHub v1 版本
        VideoDriverFactory.register_driver(DriverImplementation.DIGITAL_HUMAN_RUNNINGHUB_V1, DigitalHumanRunninghubV1Driver)
    except ImportError as e:
        logger.warning(f"Failed to import DigitalHumanRunninghubV1Driver: {e}")

    try:
        from .digital_human_ltx2_3_voice_runninghub_v1_driver import Ltx23WithVoiceRunninghubV1Driver
        # 注册 LTX2.3 With Voice RunningHub v1 版本
        VideoDriverFactory.register_driver(DriverImplementation.LTX2_3_WITH_VOICE_RUNNINGHUB_V1, Ltx23WithVoiceRunninghubV1Driver)
    except ImportError as e:
        logger.warning(f"Failed to import Ltx23WithVoiceRunninghubV1Driver: {e}")
    
    try:
        from .vidu_default_driver import ViduDefaultDriver
        # 注册 Vidu 默认驱动
        VideoDriverFactory.register_driver(DriverImplementation.VIDU_DEFAULT, ViduDefaultDriver)
    except ImportError as e:
        logger.warning(f"Failed to import ViduDefaultDriver: {e}")

    try:
        from .vidu_q2_driver import ViduQ2Driver
        # 注册 Vidu Q2 驱动
        VideoDriverFactory.register_driver(DriverImplementation.VIDU_Q2, ViduQ2Driver)
    except ImportError as e:
        logger.warning(f"Failed to import ViduQ2Driver: {e}")

    try:
        from .seedream_volcengine_v1_driver import Seedream5VolcengineV1Driver
        # 注册 Seedream 5.0 火山引擎 v1 版本
        VideoDriverFactory.register_driver(DriverImplementation.SEEDREAM5_VOLCENGINE_V1, Seedream5VolcengineV1Driver)
    except ImportError as e:
        logger.warning(f"Failed to import Seedream5VolcengineV1Driver: {e}")

    try:
        from .seedance_volcengine_v1_driver import (
            Seedance15ProVolcengineV1Driver,
            Seedance20FastVolcengineV1Driver,
            Seedance20VolcengineV1Driver,
            Seedance20MiniVolcengineV1Driver
        )
        # 注册 Seedance 火山引擎 v1 版本（4 个模型）
        VideoDriverFactory.register_driver(DriverImplementation.SEEDANCE_1_5_PRO_VOLCENGINE_V1, Seedance15ProVolcengineV1Driver)
        VideoDriverFactory.register_driver(DriverImplementation.SEEDANCE_2_0_FAST_VOLCENGINE_V1, Seedance20FastVolcengineV1Driver)
        VideoDriverFactory.register_driver(DriverImplementation.SEEDANCE_2_0_VOLCENGINE_V1, Seedance20VolcengineV1Driver)
        VideoDriverFactory.register_driver(DriverImplementation.SEEDANCE_2_0_MINI_VOLCENGINE_V1, Seedance20MiniVolcengineV1Driver)
    except ImportError as e:
        logger.warning(f"Failed to import Seedance drivers: {e}")

    # Seedream 火山引擎海外版驱动注册
    try:
        from .seedream_volcengine_oversea_v1_driver import Seedream5VolcengineOverseaV1Driver
        VideoDriverFactory.register_driver(DriverImplementation.SEEDREAM5_VOLCENGINE_OVERSEA_V1, Seedream5VolcengineOverseaV1Driver)
    except ImportError as e:
        logger.warning(f"Failed to import Seedream5VolcengineOverseaV1Driver: {e}")

    # Seedance 火山引擎海外版驱动注册
    try:
        from .seedance_volcengine_oversea_v1_driver import (
            Seedance20FastVolcengineOverseaV1Driver,
            Seedance20VolcengineOverseaV1Driver,
            Seedance20MiniVolcengineOverseaV1Driver
        )
        VideoDriverFactory.register_driver(DriverImplementation.SEEDANCE_2_0_FAST_VOLCENGINE_OVERSEA_V1, Seedance20FastVolcengineOverseaV1Driver)
        VideoDriverFactory.register_driver(DriverImplementation.SEEDANCE_2_0_VOLCENGINE_OVERSEA_V1, Seedance20VolcengineOverseaV1Driver)
        VideoDriverFactory.register_driver(DriverImplementation.SEEDANCE_2_0_MINI_VOLCENGINE_OVERSEA_V1, Seedance20MiniVolcengineOverseaV1Driver)
    except ImportError as e:
        logger.warning(f"Failed to import Seedance Oversea drivers: {e}")

    try:
        from .qwen_multi_angle_runninghub_v1_driver import QwenMultiAngleRunninghubV1Driver
        # 注册 Qwen Multi-Angle RunningHub v1 版本
        VideoDriverFactory.register_driver(DriverImplementation.QWEN_MULTI_ANGLE_RUNNINGHUB_V1, QwenMultiAngleRunninghubV1Driver)
    except ImportError as e:
        logger.warning(f"Failed to import QwenMultiAngleRunninghubV1Driver: {e}")

    # Grok 通用聚合站点驱动注册（无条件注册，配置检查在运行时进行）
    try:
        from .grok_common_v1_driver import (
            GrokCommonSite0V1Driver,
            GrokCommonSite1V1Driver,
            GrokCommonSite2V1Driver,
            GrokCommonSite3V1Driver,
            GrokCommonSite4V1Driver,
            GrokCommonSite5V1Driver,
        )
        for impl_name, driver_class in [
            (DriverImplementation.GROK_COMMON_SITE0_V1, GrokCommonSite0V1Driver),
            (DriverImplementation.GROK_COMMON_SITE1_V1, GrokCommonSite1V1Driver),
            (DriverImplementation.GROK_COMMON_SITE2_V1, GrokCommonSite2V1Driver),
            (DriverImplementation.GROK_COMMON_SITE3_V1, GrokCommonSite3V1Driver),
            (DriverImplementation.GROK_COMMON_SITE4_V1, GrokCommonSite4V1Driver),
            (DriverImplementation.GROK_COMMON_SITE5_V1, GrokCommonSite5V1Driver),
        ]:
            VideoDriverFactory.register_driver(impl_name, driver_class)
    except ImportError as e:
        logger.warning(f"Failed to import GrokCommon site drivers: {e}")

    try:
        from .happy_horse_dashscope_v1_driver import HappyHorseDashscopeV1Driver
        VideoDriverFactory.register_driver(
            DriverImplementation.HAPPY_HORSE_DASHSCOPE_V1,
            HappyHorseDashscopeV1Driver
        )
    except ImportError as e:
        logger.warning(f"Failed to import HappyHorseDashscopeV1Driver: {e}")

    try:
        from .happy_horse_dashscope_v1_driver import HappyHorseDashscopeR2VV1Driver
        VideoDriverFactory.register_driver(
            DriverImplementation.HAPPY_HORSE_DASHSCOPE_R2V_V1,
            HappyHorseDashscopeR2VV1Driver
        )
    except ImportError as e:
        logger.warning(f"Failed to import HappyHorseDashscopeR2VV1Driver: {e}")

    try:
        from .happy_horse_dashscope_v1_driver import HappyHorseDashscopeT2VV1Driver
        VideoDriverFactory.register_driver(
            DriverImplementation.HAPPY_HORSE_DASHSCOPE_T2V_V1,
            HappyHorseDashscopeT2VV1Driver
        )
    except ImportError as e:
        logger.warning(f"Failed to import HappyHorseDashscopeT2VV1Driver: {e}")

    logger.info(f"Registered {len(VideoDriverFactory.get_supported_drivers())} video drivers")
