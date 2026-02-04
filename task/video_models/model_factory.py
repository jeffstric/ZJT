"""
视频模型工厂类
根据模型类型或模型名称创建相应的模型实例
"""
from typing import Optional
import logging
from .base_video_model import BaseVideoModel

logger = logging.getLogger(__name__)


class VideoModelFactory:
    """
    视频模型工厂类
    负责创建和管理所有视频生成模型实例
    """
    
    # 模型类型到模型名称的映射
    TYPE_TO_MODEL = {
        1: "gemini_image_edit",      # 图片编辑（标准版）
        2: "sora2_text_to_video",     # Sora2 文生视频
        3: "sora2_image_to_video",    # Sora2 图生视频
        7: "gemini_image_edit_pro",   # 图片编辑（加强版）
        10: "ltx2",                   # LTX2.0 图生视频
        11: "wan22",                  # Wan2.2 图生视频
        12: "kling",                  # 可灵图生视频
        13: "digital_human",          # 数字人生成
        14: "vidu",                   # Vidu 图生视频
        15: "veo3",                   # VEO3 图生视频
    }
    
    # 模型名称到模型类型的映射
    MODEL_TO_TYPE = {v: k for k, v in TYPE_TO_MODEL.items()}
    
    # 已注册的模型类
    _registered_models = {}
    
    @classmethod
    def register_model(cls, model_name: str, model_class: type):
        """
        注册模型类
        
        Args:
            model_name: 模型名称
            model_class: 模型类（必须继承自 BaseVideoModel）
        """
        if not issubclass(model_class, BaseVideoModel):
            raise ValueError(f"Model class {model_class} must inherit from BaseVideoModel")
        
        cls._registered_models[model_name] = model_class
        logger.info(f"Registered video model: {model_name} -> {model_class.__name__}")
    
    @classmethod
    def create_model_by_type(cls, model_type: int) -> Optional[BaseVideoModel]:
        """
        根据模型类型创建模型实例
        
        Args:
            model_type: 模型类型（对应 ai_tools 表的 type 字段）
        
        Returns:
            BaseVideoModel: 模型实例，如果类型不支持则返回 None
        """
        model_name = cls.TYPE_TO_MODEL.get(model_type)
        if not model_name:
            logger.error(f"Unsupported model type: {model_type}")
            return None
        
        return cls.create_model_by_name(model_name)
    
    @classmethod
    def create_model_by_name(cls, model_name: str) -> Optional[BaseVideoModel]:
        """
        根据模型名称创建模型实例
        
        Args:
            model_name: 模型名称
        
        Returns:
            BaseVideoModel: 模型实例，如果模型未注册则返回 None
        """
        model_class = cls._registered_models.get(model_name)
        if not model_class:
            logger.error(f"Model not registered: {model_name}")
            logger.info(f"Available models: {list(cls._registered_models.keys())}")
            return None
        
        try:
            return model_class()
        except Exception as e:
            logger.error(f"Failed to create model instance for {model_name}: {str(e)}")
            return None
    
    @classmethod
    def get_supported_types(cls) -> list:
        """
        获取所有支持的模型类型
        
        Returns:
            list: 支持的模型类型列表
        """
        return list(cls.TYPE_TO_MODEL.keys())
    
    @classmethod
    def get_supported_models(cls) -> list:
        """
        获取所有已注册的模型名称
        
        Returns:
            list: 已注册的模型名称列表
        """
        return list(cls._registered_models.keys())
    
    @classmethod
    def is_type_supported(cls, model_type: int) -> bool:
        """
        检查模型类型是否支持
        
        Args:
            model_type: 模型类型
        
        Returns:
            bool: 是否支持
        """
        return model_type in cls.TYPE_TO_MODEL
    
    @classmethod
    def is_model_registered(cls, model_name: str) -> bool:
        """
        检查模型是否已注册
        
        Args:
            model_name: 模型名称
        
        Returns:
            bool: 是否已注册
        """
        return model_name in cls._registered_models


def register_all_models():
    """
    注册所有视频模型
    此函数应在应用启动时调用
    """
    # 导入所有模型类并注册
    # 注意：这里需要在实现具体模型类后逐步添加
    
    try:
        from .sora2_model import Sora2VideoModel
        VideoModelFactory.register_model("sora2_text_to_video", Sora2VideoModel)
        VideoModelFactory.register_model("sora2_image_to_video", Sora2VideoModel)
    except ImportError as e:
        logger.warning(f"Failed to import Sora2VideoModel: {e}")
    
    # TODO: 逐步添加其他模型的注册
    # from .ltx2_model import LTX2VideoModel
    # VideoModelFactory.register_model("ltx2", LTX2VideoModel)
    
    # from .wan22_model import Wan22VideoModel
    # VideoModelFactory.register_model("wan22", Wan22VideoModel)
    
    # from .kling_model import KlingVideoModel
    # VideoModelFactory.register_model("kling", KlingVideoModel)
    
    # from .vidu_model import ViduVideoModel
    # VideoModelFactory.register_model("vidu", ViduVideoModel)
    
    # from .veo3_model import VEO3VideoModel
    # VideoModelFactory.register_model("veo3", VEO3VideoModel)
    
    # from .digital_human_model import DigitalHumanModel
    # VideoModelFactory.register_model("digital_human", DigitalHumanModel)
    
    # from .gemini_image_edit_model import GeminiImageEditModel
    # VideoModelFactory.register_model("gemini_image_edit", GeminiImageEditModel)
    # VideoModelFactory.register_model("gemini_image_edit_pro", GeminiImageEditModel)
    
    logger.info(f"Registered {len(VideoModelFactory.get_supported_models())} video models")
