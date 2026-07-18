"""效果模式首帧调度策略门面。"""
import importlib

def get_storyboard_quality_sequence_strategy():
    """延迟加载 Enterprise 严格按幕策略。

    该门面只从已通过 edition gate 的 quality 宫格路径调用；这里不重复读取
    配置，避免通用模块导入时触发环境配置加载。
    """
    module = importlib.import_module(
        "enterprise.services.storyboard_quality_sequence"
    )
    return module.QualityActSequenceStrategy()


def get_storyboard_quality_location_reference_coordinator():
    """延迟加载 Enterprise 场景参考图依赖协调器。"""
    module = importlib.import_module(
        "enterprise.services.storyboard_quality_sequence"
    )
    return module.QualityLocationReferenceCoordinator()


__all__ = [
    "get_storyboard_quality_location_reference_coordinator",
    "get_storyboard_quality_sequence_strategy",
]
