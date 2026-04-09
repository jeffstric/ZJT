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
                    # 验证用户偏好在可选列表中（使用 _get_implementations_info 获取动态实现方）
                    available_impls = [impl['name'] for impl in config._get_implementations_info()]
                    if user_pref in available_impls:
                        logger.debug(f"Using user preference for task {task_key}: {user_pref}")
                        impl_name = user_pref
                    else:
                        logger.warning(f"User preference {user_pref} not in available implementations {available_impls}")
            except Exception as e:
                logger.warning(f"Failed to get user preference: {e}")

        # 2. 如果没有用户偏好，根据排序选择排序最靠前的启用实现方
        if not impl_name:
            # 获取所有可用的实现方（已启用且已注册）
            available_impls = config._get_implementations_info()
            if available_impls:
                # _get_implementations_info 已经按 sort_order 排序，取第一个
                impl_name = available_impls[0]['name']
                logger.debug(f"Auto-selected implementation by sort_order for task {config.key}: {impl_name}")
            else:
                # 回退到默认实现方
                impl_name = config.implementation

        # 3. 获取驱动参数
        driver_params = {}
        if impl_name:
            impl_config = UnifiedConfigRegistry.get_implementation(impl_name)
            if impl_config and impl_config.driver_params:
                driver_params = impl_config.driver_params.copy()

        return impl_name, driver_params
    
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
            impl_name = config.implementation
            
            if not impl_name:
                result[str(task_type)] = {
                    "available": False,
                    "missing_configs": ["未配置实现驱动"]
                }
                continue
            
            driver_class = cls._registered_drivers.get(impl_name)
            if not driver_class:
                result[str(task_type)] = {
                    "available": False,
                    "missing_configs": ["驱动未注册"]
                }
                continue
            
            try:
                driver_class()  # 尝试创建实例验证配置
                result[str(task_type)] = {
                    "available": True,
                    "missing_configs": []
                }
            except DriverConfigError as e:
                result[str(task_type)] = {
                    "available": False,
                    "missing_configs": e.missing_configs
                }
            except Exception as e:
                logger.warning(f"检查 driver {impl_name} 可用性时出错: {e}")
                result[str(task_type)] = {
                    "available": False,
                    "missing_configs": [str(e)]
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
        from .kling_duomi_v1_driver import KlingDuomiV1Driver
        # 注册 Kling 多米供应商 v1 版本
        VideoDriverFactory.register_driver(DriverImplementation.KLING_DUOMI_V1, KlingDuomiV1Driver)
    except ImportError as e:
        logger.warning(f"Failed to import KlingDuomiV1Driver: {e}")
    
    try:
        from .gemini_duomi_v1_driver import GeminiDuomiV1Driver
        # 注册 Gemini 多米供应商 v1 版本（标准版）
        VideoDriverFactory.register_driver(DriverImplementation.GEMINI_DUOMI_V1, GeminiDuomiV1Driver)
    except ImportError as e:
        logger.warning(f"Failed to import GeminiDuomiV1Driver: {e}")

    try:
        from .veo3_duomi_v1_driver import Veo3DuomiV1Driver
        # 注册 VEO3 多米供应商 v1 版本
        VideoDriverFactory.register_driver(DriverImplementation.VEO3_DUOMI_V1, Veo3DuomiV1Driver)
    except ImportError as e:
        logger.warning(f"Failed to import Veo3DuomiV1Driver: {e}")
    
    # 注册 API 聚合器站点驱动（仅在配置存在时注册）
    try:
        from utils.config_checker import check_api_aggregator_config_exists
    except ImportError:
        logger.warning("无法导入配置检查工具，跳过API聚合器驱动注册")
        check_api_aggregator_config_exists = lambda site_id: False
    
    aggregator_sites = [
        ('site_1', DriverImplementation.GEMINI_IMAGE_PREVIEW_SITE1_V1, 'GeminiImagePreviewSite1V1Driver'),
        ('site_2', DriverImplementation.GEMINI_IMAGE_PREVIEW_SITE2_V1, 'GeminiImagePreviewSite2V1Driver'),
        ('site_3', DriverImplementation.GEMINI_IMAGE_PREVIEW_SITE3_V1, 'GeminiImagePreviewSite3V1Driver'),
        ('site_4', DriverImplementation.GEMINI_IMAGE_PREVIEW_SITE4_V1, 'GeminiImagePreviewSite4V1Driver'),
        ('site_5', DriverImplementation.GEMINI_IMAGE_PREVIEW_SITE5_V1, 'GeminiImagePreviewSite5V1Driver'),
    ]
    
    # 先导入所有站点驱动类
    try:
        from .gemini_image_preview_common_v1_driver import (
            GeminiImagePreviewSite1V1Driver,
            GeminiImagePreviewSite2V1Driver,
            GeminiImagePreviewSite3V1Driver,
            GeminiImagePreviewSite4V1Driver,
            GeminiImagePreviewSite5V1Driver
        )
        
        site_driver_classes = {
            'site_1': GeminiImagePreviewSite1V1Driver,
            'site_2': GeminiImagePreviewSite2V1Driver,
            'site_3': GeminiImagePreviewSite3V1Driver,
            'site_4': GeminiImagePreviewSite4V1Driver,
            'site_5': GeminiImagePreviewSite5V1Driver,
        }
    except ImportError as e:
        logger.warning(f"Failed to import Gemini Image Preview Site drivers: {e}")
        site_driver_classes = {}
    
    # 只为有配置的站点注册驱动
    for site_id, impl_name, driver_class_name in aggregator_sites:
        if check_api_aggregator_config_exists(site_id):
            driver_class = site_driver_classes.get(site_id)
            if driver_class:
                VideoDriverFactory.register_driver(impl_name, driver_class)
                logger.info(f"已注册 {site_id} 驱动: {impl_name}")
            else:
                logger.warning(f"{site_id} 驱动类未找到，跳过注册")
        else:
            logger.info(f"{site_id} 配置不存在或不完整，跳过驱动注册")
    
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
            Seedance20VolcengineV1Driver
        )
        # 注册 Seedance 火山引擎 v1 版本（3 个模型）
        VideoDriverFactory.register_driver(DriverImplementation.SEEDANCE_1_5_PRO_VOLCENGINE_V1, Seedance15ProVolcengineV1Driver)
        VideoDriverFactory.register_driver(DriverImplementation.SEEDANCE_2_0_FAST_VOLCENGINE_V1, Seedance20FastVolcengineV1Driver)
        VideoDriverFactory.register_driver(DriverImplementation.SEEDANCE_2_0_VOLCENGINE_V1, Seedance20VolcengineV1Driver)
    except ImportError as e:
        logger.warning(f"Failed to import Seedance drivers: {e}")

    try:
        from .qwen_multi_angle_runninghub_v1_driver import QwenMultiAngleRunninghubV1Driver
        # 注册 Qwen Multi-Angle RunningHub v1 版本
        VideoDriverFactory.register_driver(DriverImplementation.QWEN_MULTI_ANGLE_RUNNINGHUB_V1, QwenMultiAngleRunninghubV1Driver)
    except ImportError as e:
        logger.warning(f"Failed to import QwenMultiAngleRunninghubV1Driver: {e}")

    logger.info(f"Registered {len(VideoDriverFactory.get_supported_drivers())} video drivers")
