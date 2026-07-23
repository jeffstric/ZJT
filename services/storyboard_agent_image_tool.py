"""Prompt and dimension enforcement for storyboard-agent image generation tools."""

from typing import Any, Dict, List, Optional

from services.storyboard_reference_prompt_service import append_storyboard_visual_suffix


class StoryboardAgentImageToolExecutor:
    """Append storyboard visual settings and force workflow_ratio at the tool boundary."""

    def __init__(
        self,
        delegate,
        *,
        style: str = "",
        composition_preference: str = "",
        generation_snapshot: Optional[Dict[str, Any]] = None,
        workflow_ratio: str = "",
    ):
        self._delegate = delegate
        self._style = style or ""
        self._composition_preference = composition_preference or ""
        self._generation_snapshot = dict(generation_snapshot or {})
        self._workflow_ratio = str(workflow_ratio or "").strip()

    def get_tool_definitions(self, allowed_tools: List[str]) -> List[Dict[str, Any]]:
        return self._delegate.get_tool_definitions(allowed_tools)

    def _resolve_forced_aspect_ratio(self) -> str:
        """Prefer task snapshot ratio, then storyboard.workflow_ratio."""
        snap_ratio = self._generation_snapshot.get("ratio")
        if snap_ratio not in (None, ""):
            text = str(snap_ratio).strip()
            if text and text.lower() != "auto":
                return text
        if self._workflow_ratio and self._workflow_ratio.lower() != "auto":
            return self._workflow_ratio
        return ""

    def execute_tool(
        self,
        tool_name: str,
        tool_args: Dict[str, Any],
        user_id: str,
        world_id: str,
        auth_token: str,
        language: str = "zh-CN",
        model: Optional[str] = None,
        vendor_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        args = dict(tool_args or {})
        snapshot = dict(self._generation_snapshot)
        if tool_name in ("generate_text_to_image", "edit_image"):
            args["prompt"] = append_storyboard_visual_suffix(
                args.get("prompt") or "",
                style=self._style,
                composition_preference=self._composition_preference,
            )
            forced_task_type = snapshot.get("task_id")
            if forced_task_type not in (None, ""):
                args["task_type"] = int(forced_task_type)

            # 与视频路径一致：画幅由故事板 workflow_ratio 强制注入，不信任 LLM 漏传/传错。
            # 工具 schema 写「已由系统注入，无需传入」时，Agent 常省略 aspect_ratio；
            # 若不在此处写入 snapshot/args，mcp_tool 会落到默认 16:9。
            forced_ratio = self._resolve_forced_aspect_ratio()
            if forced_ratio:
                args["aspect_ratio"] = forced_ratio
                snapshot["ratio"] = forced_ratio

        from script_writer_core.mcp_tool import scoped_image_generation_snapshot

        with scoped_image_generation_snapshot(snapshot):
            return self._delegate.execute_tool(
                tool_name,
                args,
                user_id,
                world_id,
                auth_token,
                language=language,
                model=model,
                vendor_id=vendor_id,
            )
