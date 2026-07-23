"""Prompt enforcement for storyboard-agent image generation tools."""

from typing import Any, Dict, List, Optional

from services.storyboard_reference_prompt_service import append_storyboard_visual_suffix


class StoryboardAgentImageToolExecutor:
    """Append storyboard visual settings at the final image-tool boundary."""

    def __init__(
        self,
        delegate,
        *,
        style: str = "",
        composition_preference: str = "",
        generation_snapshot: Optional[Dict[str, Any]] = None,
    ):
        self._delegate = delegate
        self._style = style or ""
        self._composition_preference = composition_preference or ""
        self._generation_snapshot = dict(generation_snapshot or {})

    def get_tool_definitions(self, allowed_tools: List[str]) -> List[Dict[str, Any]]:
        return self._delegate.get_tool_definitions(allowed_tools)

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
        if tool_name in ("generate_text_to_image", "edit_image"):
            args["prompt"] = append_storyboard_visual_suffix(
                args.get("prompt") or "",
                style=self._style,
                composition_preference=self._composition_preference,
            )
            forced_task_type = self._generation_snapshot.get('task_id')
            if forced_task_type not in (None, ''):
                args['task_type'] = int(forced_task_type)

        from script_writer_core.mcp_tool import scoped_image_generation_snapshot

        with scoped_image_generation_snapshot(self._generation_snapshot):
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
