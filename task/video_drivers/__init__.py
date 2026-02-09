"""
视频生成驱动模块

此模块包含所有视频生成驱动的实现，每个驱动都继承自 BaseVideoDriver 抽象基类

使用方式:
    from task.video_drivers import VideoDriverFactory, register_all_drivers
    
    # 在应用启动时注册所有驱动
    register_all_drivers()
    
    # 根据驱动类型创建驱动实例
    driver = VideoDriverFactory.create_driver_by_type(ai_tool.type)
    if driver:
        result = driver.submit_task(ai_tool)
"""
from .base_video_driver import BaseVideoDriver
from .driver_factory import VideoDriverFactory, register_all_drivers

__all__ = ['BaseVideoDriver', 'VideoDriverFactory', 'register_all_drivers']
