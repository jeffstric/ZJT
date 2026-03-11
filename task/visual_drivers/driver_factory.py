"""
视频驱动工厂类
根据驱动类型或驱动名称创建相应的驱动实例
"""
from typing import Optional
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
    
    @classmethod
    def create_driver_by_type(cls, driver_type: int) -> Optional[BaseVideoDriver]:
        """
        根据驱动类型创建驱动实例
        
        Args:
            driver_type: 驱动类型（对应 ai_tools 表的 type 字段）
        
        Returns:
            BaseVideoDriver: 驱动实例，如果类型不支持或驱动未注册则返回 None
        
        流程：
            1. 任务类型 -> 业务驱动名称（通过 VIDEO_DRIVER_MAPPING）
            2. 业务驱动名称 -> 实现驱动名称（通过 DRIVER_IMPLEMENTATION_MAPPING）
            3. 实现驱动名称 -> 驱动类实例（通过 _registered_drivers）
        """
        # 从统一配置获取任务配置
        config = UnifiedConfigRegistry.get_by_id(driver_type)
        if not config:
            logger.error(f"Unsupported driver type: {driver_type}")
            logger.info(f"Supported types: {[c.id for c in UnifiedConfigRegistry.get_all()]}")
            return None
        
        business_driver_name = config.driver_name
        if not business_driver_name:
            logger.error(f"No driver configured for task type: {driver_type}")
            return None
        
        # 从统一配置获取实现驱动名称
        implementation_driver_name = config.implementation
        if not implementation_driver_name:
            logger.error(f"No implementation configured for business driver: {business_driver_name}")
            return None
        
        # 第三层：根据实现驱动名称获取驱动类
        driver_class = cls._registered_drivers.get(implementation_driver_name)
        if not driver_class:
            logger.error(f"Driver implementation not registered: {implementation_driver_name}")
            logger.info(f"Registered implementations: {list(cls._registered_drivers.keys())}")
            return None
        
        # 创建驱动实例
        try:
            logger.info(f"Creating driver: type={driver_type} -> business={business_driver_name} -> implementation={implementation_driver_name}")
            return driver_class()
        except DriverConfigError as e:
            logger.warning(f"Driver {implementation_driver_name} 配置不完整: {e.message}")
            logger.info(f"缺少配置: {', '.join(e.missing_configs)}")
            return None
        except Exception as e:
            logger.error(f"Failed to create driver instance for {implementation_driver_name}: {str(e)}")
            return None
    
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
    
    try:
        from .ltx2_runninghub_v1_driver import Ltx2RunninghubV1Driver
        # 注册 LTX2 RunningHub v1 版本
        VideoDriverFactory.register_driver(DriverImplementation.LTX2_RUNNINGHUB_V1, Ltx2RunninghubV1Driver)
    except ImportError as e:
        logger.warning(f"Failed to import Ltx2RunninghubV1Driver: {e}")
    
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

    logger.info(f"Registered {len(VideoDriverFactory.get_supported_drivers())} video drivers")
