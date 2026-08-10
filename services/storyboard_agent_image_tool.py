"""Prompt and dimension enforcement for storyboard-agent image generation tools."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Sequence

from services.storyboard_reference_prompt_service import (
    append_reference_legend,
    append_storyboard_visual_suffix,
)

logger = logging.getLogger(__name__)


def _parse_image_urls(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item or "").strip()]
    text = str(value).strip()
    if not text:
        return []
    return [part.strip() for part in text.split(",") if part.strip()]


def merge_forced_reference_urls(
    forced_urls: Sequence[str],
    llm_urls: Sequence[str],
) -> List[str]:
    """Keep all authoritative reference URLs, then append extra LLM URLs (deduped, order-preserving)."""
    seen = set()
    merged: List[str] = []
    for url in list(forced_urls or []) + list(llm_urls or []):
        text = str(url or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        merged.append(text)
    return merged


def strip_trailing_reference_legend(prompt: str) -> str:
    """Remove a trailing 参考图说明 block so it can be rebuilt against final URL order."""
    text = str(prompt or "").rstrip()
    marker = "参考图说明："
    idx = text.rfind(marker)
    if idx < 0:
        return text
    # Only strip when the legend is a trailing section (not mid-body narrative).
    before = text[:idx].rstrip()
    after = text[idx + len(marker):].strip()
    if "\n\n" in after:
        return text
    return before


def build_legend_items_for_urls(
    urls: Sequence[str],
    reference_items: Sequence[Dict[str, Any]],
) -> List[Dict[str, str]]:
    """Align legend entries to the final image_url order."""
    by_url = {}
    for item in reference_items or []:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip()
        if url and url not in by_url:
            by_url[url] = item
    ordered: List[Dict[str, str]] = []
    for url in urls:
        text = str(url or "").strip()
        if not text:
            continue
        item = by_url.get(text) or {}
        ordered.append({
            "type": str(item.get("type") or "参考图"),
            "name": str(item.get("name") or ""),
            "variant_label": str(item.get("variant_label") or ""),
            "url": text,
        })
    return ordered


class StoryboardAgentImageToolExecutor:
    """Append storyboard visual settings, force workflow_ratio, and pin reference URLs."""

    def __init__(
        self,
        delegate,
        *,
        style: str = "",
        composition_preference: str = "",
        generation_snapshot: Optional[Dict[str, Any]] = None,
        workflow_ratio: str = "",
        forced_reference_urls: Optional[Sequence[str]] = None,
        forced_reference_items: Optional[Sequence[Dict[str, Any]]] = None,
    ):
        self._delegate = delegate
        self._style = style or ""
        self._composition_preference = composition_preference or ""
        self._generation_snapshot = dict(generation_snapshot or {})
        self._workflow_ratio = str(workflow_ratio or "").strip()
        self._forced_reference_urls = [
            str(url).strip()
            for url in (forced_reference_urls or [])
            if str(url or "").strip()
        ]
        self._forced_reference_items = [
            dict(item)
            for item in (forced_reference_items or [])
            if isinstance(item, dict) and str(item.get("url") or "").strip()
        ]

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

    def _align_prompt_legend(self, prompt: str, image_urls: Sequence[str]) -> str:
        """Rebuild trailing 参考图说明 so图号 matches the final image_url order."""
        if not image_urls:
            return prompt
        items = build_legend_items_for_urls(image_urls, self._forced_reference_items)
        if not items:
            return prompt
        body = strip_trailing_reference_legend(prompt)
        return append_reference_legend(body, items)

    def _apply_forced_reference_urls(self, tool_name: str, args: Dict[str, Any]) -> str:
        """Ensure edit_image receives the full scene reference list (shot-frame style).

        Aligns with video_workflow collectShotFrameRefImages: once references are resolved,
        all of them are submitted — never trust the LLM to copy every URL.
        """
        if not self._forced_reference_urls:
            return tool_name

        if tool_name == "generate_text_to_image":
            # Reference list non-empty: must image-edit, same as storyboard-image skill.
            args["image_url"] = ",".join(self._forced_reference_urls)
            args["prompt"] = self._align_prompt_legend(
                args.get("prompt") or "",
                self._forced_reference_urls,
            )
            logger.info(
                "[storyboard-agent-image] convert generate_text_to_image -> edit_image "
                "with %s forced reference url(s)",
                len(self._forced_reference_urls),
            )
            return "edit_image"

        if tool_name == "edit_image":
            llm_urls = _parse_image_urls(args.get("image_url"))
            merged = merge_forced_reference_urls(self._forced_reference_urls, llm_urls)
            if merged != llm_urls:
                logger.info(
                    "[storyboard-agent-image] merged forced reference urls: "
                    "forced=%s llm=%s final=%s",
                    len(self._forced_reference_urls),
                    len(llm_urls),
                    len(merged),
                )
            args["image_url"] = ",".join(merged)
            args["prompt"] = self._align_prompt_legend(args.get("prompt") or "", merged)
        return tool_name

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
        effective_tool = tool_name

        if tool_name in ("generate_text_to_image", "edit_image"):
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

            # 先强制参考 URL + 图例，再把画风/构图幂等接到末尾（对齐 generate_image）。
            effective_tool = self._apply_forced_reference_urls(tool_name, args)
            args["prompt"] = append_storyboard_visual_suffix(
                args.get("prompt") or "",
                style=self._style,
                composition_preference=self._composition_preference,
            )

        from script_writer_core.mcp_tool import scoped_image_generation_snapshot

        with scoped_image_generation_snapshot(snapshot):
            return self._delegate.execute_tool(
                effective_tool,
                args,
                user_id,
                world_id,
                auth_token,
                language=language,
                model=model,
                vendor_id=vendor_id,
            )
