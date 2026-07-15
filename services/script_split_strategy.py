"""剧本分段策略门面。

核心仓库只定义通用执行协议；效果模式实现由 Enterprise 包延迟提供。
"""
import importlib
from typing import Any, Dict, List, Optional

from config.constant import Edition
from services.storyboard_spatial.exceptions import StoryboardEnterpriseFeatureRequired


class StandardScriptSplitStrategy:
    """社区版及非效果模式使用的现有串行策略。"""

    parallel_enabled = False

    def __init__(self, mode: str = "speed"):
        self.mode = mode

    def build_planning_prompt(
        self,
        anchors: List[Dict[str, Any]],
        max_output_tokens: int,
    ) -> Optional[str]:
        return None

    def compile_plan(
        self,
        plan: Dict[str, Any],
        anchors: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        return plan

    def build_segment_context(
        self,
        plan: Dict[str, Any],
        segment_id: str,
    ) -> Dict[str, Any]:
        return {}

    def validate_segment_result(
        self,
        parsed: Dict[str, Any],
        plan: Dict[str, Any],
        segment_id: str,
    ) -> List[Dict[str, Any]]:
        return []

    def repair_merged_result(
        self,
        merged: Dict[str, Any],
        plan: Dict[str, Any],
    ) -> Dict[str, Any]:
        return merged


def get_script_split_strategy(sequence_mode: str):
    """按模式选择策略；quality 的业务实现不得进入核心仓库。"""
    mode = str(sequence_mode or "speed").strip().lower()
    if mode != "quality":
        return StandardScriptSplitStrategy(mode)
    if Edition.is_community():
        raise StoryboardEnterpriseFeatureRequired()
    module = importlib.import_module("enterprise.services.script_split_quality")
    return module.QualityScriptSplitStrategy()


__all__ = ["StandardScriptSplitStrategy", "get_script_split_strategy"]
