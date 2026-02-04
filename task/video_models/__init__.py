"""
视频生成模型模块

此模块包含所有视频生成模型的实现，每个模型都继承自 BaseVideoModel 抽象基类

使用方式:
    from task.video_models import VideoModelFactory, register_all_models
    
    # 在应用启动时注册所有模型
    register_all_models()
    
    # 根据模型类型创建模型实例
    model = VideoModelFactory.create_model_by_type(ai_tool.type)
    if model:
        result = model.submit_task(ai_tool)
"""
from .base_video_model import BaseVideoModel
from .model_factory import VideoModelFactory, register_all_models

__all__ = ['BaseVideoModel', 'VideoModelFactory', 'register_all_models']
