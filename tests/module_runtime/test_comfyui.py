import asyncio
import json
from pathlib import Path
from typing import Any, Dict

import httpx
import pytest

from module_runtime.comfyui import (
    ComfyUIError,
    LocalComfyUIClient,
    apply_mapping,
    host_port_from_base_url,
    infer_mapping,
    outputs_from_history,
    view_url,
)


FIXTURE = Path(__file__).resolve().parent / "fixtures" / "qwen_image_edit_api_0824.json"


def _workflow() -> Dict[str, Any]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_qwen_0824_infer_mapping_snapshot():
    mapping = infer_mapping(_workflow())
    assert mapping["load_image_nodes"] == ["78"]
    assert mapping["positive_prompt_node"] == "108"
    assert mapping["positive_prompt_field"] == "prompt"
    assert mapping["negative_prompt_node"] == "109"
    assert mapping["seed_node"] == "3"
    assert mapping["output_node"] == "60"
    assert mapping["media_kind"] == "image"
    assert "JWImageSaveToPath" in mapping["strip_class_types"]
    assert mapping["ambiguous"] is False


def test_apply_mapping_rewrites_prompt_image_seed_and_strips_jw_node():
    mapping = infer_mapping(_workflow())
    graph = apply_mapping(
        _workflow(),
        mapping,
        prompt="换成蓝色背景",
        image_names=["uploaded_ref.png"],
        seed=42,
    )
    assert "113" not in graph
    assert graph["78"]["inputs"]["image"] == "uploaded_ref.png"
    assert graph["108"]["inputs"]["prompt"] == "换成蓝色背景"
    assert graph["3"]["inputs"]["seed"] == 42
    assert graph["109"]["inputs"]["prompt"] == ""


def test_apply_mapping_requires_enough_images():
    mapping = infer_mapping(_workflow())
    with pytest.raises(ComfyUIError, match="需要 1 张"):
        apply_mapping(_workflow(), mapping, prompt="x", image_names=[])


def test_outputs_from_history_reads_save_image_node():
    mapping = {"output_node": "60"}
    history = {
        "outputs": {
            "60": {
                "images": [{"filename": "ComfyUI_00001_.png", "subfolder": "", "type": "output"}]
            }
        }
    }
    items = outputs_from_history(history, mapping)
    assert items == [{"filename": "ComfyUI_00001_.png", "subfolder": "", "type": "output"}]


def test_host_port_and_view_url():
    assert host_port_from_base_url("http://192.168.10.187:8188/") == "192.168.10.187:8188"
    assert view_url("http://192.168.10.187:8188/", "a.png") == (
        "http://192.168.10.187:8188/view?filename=a.png&type=output"
    )


def test_client_rejects_undeclared_input_url():
    async def scenario():
        client = LocalComfyUIClient(
            "http://192.168.10.187:8188",
            allowed_input_urls=["https://cdn.example/a.png"],
        )
        with pytest.raises(ComfyUIError, match="任务附件"):
            await client.download_media("http://169.254.169.254/latest")

    asyncio.run(scenario())


async def _run_transport_scenario():
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if request.method == "POST" and url.endswith("/upload/image"):
            return httpx.Response(200, json={"name": "in.png", "subfolder": "", "type": "input"})
        if request.method == "POST" and url.endswith("/prompt"):
            body = json.loads(request.content.decode("utf-8"))
            assert "78" in body["prompt"]
            return httpx.Response(200, json={"prompt_id": "p1", "node_errors": {}})
        if request.method == "GET" and "/history/p1" in url:
            return httpx.Response(
                200,
                json={
                    "p1": {
                        "status": {"completed": True, "status_str": "success"},
                        "outputs": {
                            "60": {
                                "images": [
                                    {"filename": "out.png", "subfolder": "", "type": "output"}
                                ]
                            }
                        },
                    }
                },
            )
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    mapping = infer_mapping(_workflow())
    graph = apply_mapping(
        _workflow(),
        mapping,
        prompt="测试",
        image_names=["in.png"],
        seed=1,
    )

    class TransportClient(httpx.AsyncClient):
        def __init__(self, **kwargs):
            kwargs["transport"] = transport
            super().__init__(**kwargs)

    import module_runtime.comfyui as comfy_mod

    original = httpx.AsyncClient
    httpx.AsyncClient = TransportClient  # type: ignore
    try:
        api = LocalComfyUIClient("http://192.168.10.187:8188", allowed_input_urls=[])
        name = await api.upload_image(b"abc", "a.png")
        assert name == "in.png"
        prompt_id = await api.submit_prompt(graph)
        assert prompt_id == "p1"
        history = await api.get_history(prompt_id)
        assert history is not None
        items = outputs_from_history(history, mapping)
        assert items[0]["filename"] == "out.png"
    finally:
        httpx.AsyncClient = original


def test_client_prompt_history_via_transport():
    asyncio.run(_run_transport_scenario())
