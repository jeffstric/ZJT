"""剧本分段策略门面。

核心仓库只定义通用执行协议；效果模式实现由 Enterprise 包延迟提供。
"""
import importlib
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from config.constant import Edition
from services.storyboard_spatial.exceptions import StoryboardEnterpriseFeatureRequired


@dataclass(frozen=True)
class ScriptSplitMaterializationResult:
    parsed: Dict[str, Any]
    final_state: Dict[str, Any]
    diagnostics: List[Dict[str, Any]]
    degraded: bool = False


class StandardScriptSplitStrategy:
    """社区版及非效果模式使用的现有串行策略。"""

    parallel_enabled = False

    def __init__(self, mode: str = "speed"):
        self.mode = mode

    def build_planning_prompt(
        self,
        anchors: List[Dict[str, Any]],
        max_output_tokens: int,
        db_locations: Optional[List[Dict[str, Any]]] = None,
    ) -> Optional[str]:
        # 社区版 plan 为 schema v1 纯分段，不产出 location，无需注入已有场景列表。
        return None

    def compile_plan(
        self,
        plan: Dict[str, Any],
        anchors: List[Dict[str, Any]],
        db_locations: Optional[List[Dict[str, Any]]] = None,
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

    def materialize_segment_result(
        self,
        parsed: Dict[str, Any],
        plan: Dict[str, Any],
        segment_id: str,
        segment_context: Dict[str, Any],
    ) -> ScriptSplitMaterializationResult:
        return ScriptSplitMaterializationResult(
            parsed=parsed,
            final_state={},
            diagnostics=[],
        )

    async def write_materialization_logs(
        self,
        task_id: int,
        segment_id: str,
        parsed: Dict[str, Any],
    ) -> None:
        return None

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


__all__ = [
    "ScriptSplitMaterializationResult",
    "StandardScriptSplitStrategy",
    "get_script_split_strategy",
]
