"""本地 ComfyUI HTTP 助手。

用户模块允许 ``from module_runtime.comfyui import ...``。本文件只依赖标准库、
``httpx`` 与 ``protocol``，禁止 import ``os`` / ``subprocess`` / ``config`` / ``model``。
"""

from __future__ import annotations

import copy
import random
import uuid
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set
from urllib.parse import urlparse, urlunparse

import httpx

from module_runtime.protocol import MediaKind


DEFAULT_HTTP_TIMEOUT_SECONDS = 30.0
DEFAULT_STRIP_CLASS_TYPES = ("JWImageSaveToPath",)
LOAD_IMAGE_CLASS_TYPES = frozenset({"LoadImage", "LoadImageMask"})
SAVE_IMAGE_CLASS_TYPES = frozenset({"SaveImage", "PreviewImage"})
SAVE_VIDEO_CLASS_TYPES = frozenset({"SaveVideo", "VHS_VideoCombine", "VHS_FILENAMES"})
SAMPLER_CLASS_TYPES = frozenset({"KSampler", "KSamplerAdvanced", "SamplerCustom", "RandomNoise"})
PROMPT_FIELDS = ("prompt", "text")


class ComfyUIError(RuntimeError):
    """ComfyUI HTTP 或工作流改写失败。"""

    def __init__(self, message: str, *, retryable: bool = False, details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.retryable = retryable
        self.details = details or {}


def normalize_base_url(base_url: str) -> str:
    raw = str(base_url or "").strip()
    if not raw:
        raise ComfyUIError("ComfyUI 地址不能为空")
    parsed = urlparse(raw)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        raise ComfyUIError("ComfyUI 地址必须是完整的 http/https URL")
    path = parsed.path.rstrip("/")
    return urlunparse((parsed.scheme.lower(), parsed.netloc, path, "", "", ""))


def host_port_from_base_url(base_url: str) -> str:
    return urlparse(normalize_base_url(base_url)).netloc


def view_url(
    base_url: str,
    filename: str,
    *,
    subfolder: str = "",
    image_type: str = "output",
) -> str:
    root = normalize_base_url(base_url)
    query = f"filename={filename}&type={image_type}"
    if subfolder:
        query += f"&subfolder={subfolder}"
    return f"{root}/view?{query}"


def _is_link(value: Any) -> bool:
    return isinstance(value, list) and len(value) >= 1


def _scalar_text(value: Any) -> Optional[str]:
    if isinstance(value, str) and not _is_link(value):
        return value
    return None


def infer_mapping(workflow: Mapping[str, Any]) -> Dict[str, Any]:
    """从 API 格式工作流推断节点映射。多候选时保留列表并标 ambiguous。"""

    if not isinstance(workflow, Mapping) or not workflow:
        raise ComfyUIError("工作流 JSON 必须是非空对象")

    load_image_nodes: List[str] = []
    text_nodes: List[Dict[str, str]] = []
    save_image_nodes: List[str] = []
    preview_nodes: List[str] = []
    save_video_nodes: List[str] = []
    seed_nodes: List[str] = []
    strip_class_types: List[str] = []

    for node_id, node in workflow.items():
        if not isinstance(node, Mapping):
            continue
        class_type = str(node.get("class_type") or "")
        inputs = node.get("inputs") if isinstance(node.get("inputs"), Mapping) else {}
        if class_type in DEFAULT_STRIP_CLASS_TYPES and class_type not in strip_class_types:
            strip_class_types.append(class_type)
        if class_type in LOAD_IMAGE_CLASS_TYPES:
            load_image_nodes.append(str(node_id))
        if class_type in SAVE_IMAGE_CLASS_TYPES:
            if class_type == "PreviewImage":
                preview_nodes.append(str(node_id))
            else:
                save_image_nodes.append(str(node_id))
        if class_type in SAVE_VIDEO_CLASS_TYPES:
            save_video_nodes.append(str(node_id))
        if class_type in SAMPLER_CLASS_TYPES and "seed" in inputs and not _is_link(inputs.get("seed")):
            seed_nodes.append(str(node_id))
        for field in PROMPT_FIELDS:
            text = _scalar_text(inputs.get(field))
            if text is not None:
                text_nodes.append({"node": str(node_id), "field": field, "text": text})
                break

    nonempty = [item for item in text_nodes if str(item["text"]).strip()]
    empty = [item for item in text_nodes if not str(item["text"]).strip()]
    output_node = ""
    media_kind = MediaKind.IMAGE.value
    if save_image_nodes:
        output_node = save_image_nodes[0]
    elif save_video_nodes:
        output_node = save_video_nodes[0]
        media_kind = MediaKind.VIDEO.value
    elif preview_nodes:
        output_node = preview_nodes[0]

    mapping: Dict[str, Any] = {
        "load_image_nodes": load_image_nodes,
        "positive_prompt_node": nonempty[0]["node"] if nonempty else "",
        "positive_prompt_field": nonempty[0]["field"] if nonempty else "prompt",
        "negative_prompt_node": empty[0]["node"] if empty else "",
        "negative_prompt_field": empty[0]["field"] if empty else "prompt",
        "seed_node": seed_nodes[0] if seed_nodes else "",
        "seed_field": "seed",
        "output_node": output_node,
        "media_kind": media_kind,
        "strip_class_types": strip_class_types or list(DEFAULT_STRIP_CLASS_TYPES),
        "ambiguous": bool(
            len(load_image_nodes) > 1
            or len(nonempty) > 1
            or len(save_image_nodes) + len(save_video_nodes) + len(preview_nodes) > 1
        ),
    }
    return mapping


def apply_mapping(
    workflow: Mapping[str, Any],
    mapping: Mapping[str, Any],
    *,
    prompt: Optional[str] = None,
    image_names: Optional[Sequence[str]] = None,
    seed: Optional[int] = None,
) -> Dict[str, Any]:
    graph = copy.deepcopy(dict(workflow))
    strip_types = set(mapping.get("strip_class_types") or DEFAULT_STRIP_CLASS_TYPES)
    for node_id in list(graph.keys()):
        node = graph.get(node_id)
        if isinstance(node, Mapping) and node.get("class_type") in strip_types:
            del graph[node_id]

    names = list(image_names or [])
    load_nodes = [str(item) for item in (mapping.get("load_image_nodes") or [])]
    if len(names) < len(load_nodes):
        raise ComfyUIError(
            f"工作流需要 {len(load_nodes)} 张输入图，实际提供 {len(names)} 张"
        )
    for index, node_id in enumerate(load_nodes):
        _set_input(graph, node_id, "image", names[index])

    positive_node = str(mapping.get("positive_prompt_node") or "")
    if positive_node and prompt is not None:
        field = str(mapping.get("positive_prompt_field") or "prompt")
        _set_input(graph, positive_node, field, prompt)

    seed_node = str(mapping.get("seed_node") or "")
    if seed_node:
        field = str(mapping.get("seed_field") or "seed")
        value = int(seed) if seed is not None else random.randint(0, 2**32 - 1)
        _set_input(graph, seed_node, field, value)
    return graph


def _set_input(graph: Dict[str, Any], node_id: str, field: str, value: Any) -> None:
    node = graph.get(node_id)
    if not isinstance(node, Mapping):
        raise ComfyUIError(f"工作流缺少节点 {node_id}")
    inputs = node.setdefault("inputs", {})
    if not isinstance(inputs, dict):
        raise ComfyUIError(f"节点 {node_id} 的 inputs 不是对象")
    inputs[field] = value


def outputs_from_history(history: Mapping[str, Any], mapping: Mapping[str, Any]) -> List[Dict[str, str]]:
    if not isinstance(history, Mapping):
        return []
    payload = history
    if "outputs" not in payload:
        if len(payload) == 1:
            inner = next(iter(payload.values()))
            if isinstance(inner, Mapping):
                payload = inner
    outputs = payload.get("outputs") if isinstance(payload.get("outputs"), Mapping) else {}
    node_id = str(mapping.get("output_node") or "")
    node_out = outputs.get(node_id) if node_id else None
    if not isinstance(node_out, Mapping):
        for value in outputs.values():
            if isinstance(value, Mapping) and (value.get("images") or value.get("gifs")):
                node_out = value
                break
    if not isinstance(node_out, Mapping):
        return []
    items = node_out.get("images") or node_out.get("gifs") or []
    result: List[Dict[str, str]] = []
    for item in items:
        if not isinstance(item, Mapping) or not item.get("filename"):
            continue
        result.append(
            {
                "filename": str(item["filename"]),
                "subfolder": str(item.get("subfolder") or ""),
                "type": str(item.get("type") or "output"),
            }
        )
    return result


def history_failed(history: Mapping[str, Any]) -> Optional[str]:
    payload = history
    if "status" not in payload and len(payload) == 1:
        inner = next(iter(payload.values()))
        if isinstance(inner, Mapping):
            payload = inner
    status = payload.get("status") if isinstance(payload.get("status"), Mapping) else {}
    status_str = str(status.get("status_str") or status.get("status") or "").lower()
    if status_str in {"error", "failed"}:
        messages = status.get("messages") or []
        return str(messages[0] if messages else "ComfyUI 工作流执行失败")
    return None


class LocalComfyUIClient:
    """对一台 ComfyUI 的异步 HTTP 封装。"""

    def __init__(
        self,
        base_url: str,
        *,
        timeout_seconds: float = DEFAULT_HTTP_TIMEOUT_SECONDS,
        allowed_input_urls: Optional[Iterable[str]] = None,
    ):
        self.base_url = normalize_base_url(base_url)
        self.timeout_seconds = float(timeout_seconds)
        self.allowed_input_urls: Set[str] = {str(item) for item in (allowed_input_urls or []) if item}

    def _timeout(self) -> httpx.Timeout:
        return httpx.Timeout(self.timeout_seconds)

    async def download_media(self, url: str) -> bytes:
        if url not in self.allowed_input_urls:
            raise ComfyUIError("只能下载任务附件中的输入媒体 URL")
        async with httpx.AsyncClient(timeout=self._timeout()) as client:
            try:
                response = await client.get(url)
                response.raise_for_status()
            except httpx.HTTPError as exc:
                raise ComfyUIError(f"下载输入媒体失败: {exc}", retryable=True) from exc
            return response.content

    async def upload_image(self, data: bytes, filename: str) -> str:
        files = {"image": (filename or "input.png", data, "application/octet-stream")}
        async with httpx.AsyncClient(timeout=self._timeout()) as client:
            try:
                response = await client.post(f"{self.base_url}/upload/image", files=files)
                response.raise_for_status()
                payload = response.json()
            except httpx.HTTPError as exc:
                raise ComfyUIError(f"上传图片到 ComfyUI 失败: {exc}", retryable=True) from exc
            except ValueError as exc:
                raise ComfyUIError("ComfyUI 上传响应不是 JSON") from exc
        name = str(payload.get("name") or "")
        subfolder = str(payload.get("subfolder") or "")
        if not name:
            raise ComfyUIError("ComfyUI 上传响应缺少 name")
        return f"{subfolder}/{name}" if subfolder else name

    async def submit_prompt(self, graph: Mapping[str, Any], *, client_id: Optional[str] = None) -> str:
        body = {"prompt": dict(graph), "client_id": client_id or uuid.uuid4().hex}
        async with httpx.AsyncClient(timeout=self._timeout()) as client:
            try:
                response = await client.post(f"{self.base_url}/prompt", json=body)
                response.raise_for_status()
                payload = response.json()
            except httpx.HTTPError as exc:
                raise ComfyUIError(f"提交 ComfyUI 工作流失败: {exc}", retryable=True) from exc
            except ValueError as exc:
                raise ComfyUIError("ComfyUI /prompt 响应不是 JSON") from exc
        node_errors = payload.get("node_errors") or {}
        if node_errors:
            raise ComfyUIError(
                f"ComfyUI 节点错误: {node_errors}",
                details={"node_errors": node_errors},
            )
        prompt_id = str(payload.get("prompt_id") or "")
        if not prompt_id:
            raise ComfyUIError("ComfyUI /prompt 响应缺少 prompt_id")
        return prompt_id

    async def get_history(self, prompt_id: str) -> Optional[Dict[str, Any]]:
        async with httpx.AsyncClient(timeout=self._timeout()) as client:
            try:
                response = await client.get(f"{self.base_url}/history/{prompt_id}")
                response.raise_for_status()
                payload = response.json()
            except httpx.HTTPError as exc:
                raise ComfyUIError(f"查询 ComfyUI history 失败: {exc}", retryable=True) from exc
            except ValueError as exc:
                raise ComfyUIError("ComfyUI /history 响应不是 JSON") from exc
        if not payload:
            return None
        if prompt_id in payload and isinstance(payload[prompt_id], Mapping):
            return dict(payload[prompt_id])
        if isinstance(payload, Mapping):
            return dict(payload)
        return None

    async def download_view(
        self,
        filename: str,
        *,
        subfolder: str = "",
        image_type: str = "output",
    ) -> bytes:
        params = {"filename": filename, "type": image_type}
        if subfolder:
            params["subfolder"] = subfolder
        async with httpx.AsyncClient(timeout=self._timeout()) as client:
            try:
                response = await client.get(f"{self.base_url}/view", params=params)
                response.raise_for_status()
            except httpx.HTTPError as exc:
                raise ComfyUIError(f"下载 ComfyUI 输出失败: {exc}", retryable=True) from exc
            return response.content
