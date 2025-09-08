from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Query
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import uvicorn
import requests
import uuid
import json
import os
import time
from datetime import datetime
from typing import List

APP_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_PATH = os.path.join(APP_DIR, "qwen_image_edit_api.json")
COMFYUI_OUTPUT_PATH = '/mnt/disk/ComfyUI/server_output'

# Default ComfyUI server address; can be overridden by request field
DEFAULT_COMFYUI_SERVER = os.environ.get("COMFYUI_SERVER", "http://127.0.0.1:8188/")

app = FastAPI(title="ComfyUI Qwen Image Edit Proxy")

# Allow CORS for local dev if needed
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def _normalize_server(server: str) -> str:
    if not server:
        server = DEFAULT_COMFYUI_SERVER
    if not server.endswith("/"):
        server += "/"
    return server


def _upload_image_to_comfyui(server: str, upload_file: UploadFile) -> str:
    """
    Upload the file to ComfyUI's /upload/image endpoint and return the stored filename.
    """
    url = f"{server}upload/image"
    files = {
        "image": (upload_file.filename, upload_file.file, upload_file.content_type or "application/octet-stream")
    }
    try:
        resp = requests.post(url, files=files, timeout=60)
        resp.raise_for_status()
        data = resp.json()
        # ComfyUI commonly returns {"name": "uploaded.png"}
        name = data.get("name") if isinstance(data, dict) else None
        if not name:
            # some forks may return list or different shape
            if isinstance(data, list) and data:
                name = data[0].get("name")
        if not name:
            raise HTTPException(status_code=502, detail=f"Unexpected upload response: {data}")
        return name
    except requests.RequestException as e:
        raise HTTPException(status_code=502, detail=f"Failed to upload image to ComfyUI: {e}")


def _build_prompt_payload(image_name: str, text_prompt: str) -> dict:
    if not os.path.exists(TEMPLATE_PATH):
        raise HTTPException(status_code=500, detail="Template JSON not found")
    try:
        with open(TEMPLATE_PATH, "r", encoding="utf-8") as f:
            workflow = json.load(f)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load template JSON: {e}")

    # Generate date-based output path
    output_dir = os.path.join(COMFYUI_OUTPUT_PATH)
    os.makedirs(output_dir, exist_ok=True)
    
    # Generate unique filename with timestamp
    now = datetime.now()
    timestamp = now.strftime("%H%M%S")
    unique_id = str(uuid.uuid4())[:8]
    output_filename = f"image_{timestamp}_{unique_id}.png"
    full_output_path = os.path.join(output_dir, output_filename)

    # Update nodes as specified by the user
    try:
        # Node 78: LoadImage -> inputs.image = uploaded name
        if "78" in workflow and "inputs" in workflow["78"]:
            workflow["78"]["inputs"]["image"] = image_name
        else:
            raise KeyError("Node 78.inputs.image not found in template")
        # Node 108: TextEncodeQwenImageEdit -> inputs.prompt = text_prompt
        if "108" in workflow and "inputs" in workflow["108"]:
            workflow["108"]["inputs"]["prompt"] = text_prompt
        else:
            raise KeyError("Node 108.inputs.prompt not found in template")
        # Node 113: JWImageSaveToPath -> inputs.path = date-based path
        if "113" in workflow and "inputs" in workflow["113"]:
            workflow["113"]["inputs"]["path"] = full_output_path
        else:
            raise KeyError("Node 113.inputs.path not found in template")
    except KeyError as e:
        raise HTTPException(status_code=500, detail=str(e))

    client_id = str(uuid.uuid4())
    data = {
        "prompt": workflow,
        "client_id": client_id
    }
    return data


def _submit_prompt(server: str, payload: dict) -> str:
    url = f"{server}prompt"
    try:
        resp = requests.post(url, json=payload, timeout=30)
        resp.raise_for_status()
        # Prefer server-assigned prompt_id if present
        try:
            rj = resp.json()
            prompt_id = rj.get("prompt_id") or payload.get("client_id")
        except Exception:
            prompt_id = payload.get("client_id")
        return prompt_id
    except requests.RequestException as e:
        raise HTTPException(status_code=502, detail=f"Failed to submit prompt: {e}")


def _check_queue_status(server: str, prompt_id: str) -> str:
    """Check if prompt is in queue (running or pending)"""
    try:
        queue_url = f"{server}queue"
        r = requests.get(queue_url, timeout=5)
        if r.status_code == 200:
            queue_data = r.json()
            
            # Check running jobs
            if "queue_running" in queue_data:
                running_jobs = queue_data["queue_running"]
                if isinstance(running_jobs, list):
                    for job in running_jobs:
                        if isinstance(job, list) and len(job) >= 2 and job[1] == prompt_id:
                            return "running"
            
            # Check pending jobs
            if "queue_pending" in queue_data:
                pending_jobs = queue_data["queue_pending"]
                if isinstance(pending_jobs, list):
                    for job in pending_jobs:
                        if isinstance(job, list) and len(job) >= 2 and job[1] == prompt_id:
                            return "pending"
        return "not_found"
    except Exception:
        return "error"


def _check_history_for_images(server: str, prompt_id: str) -> List[str]:
    """Check history for completed results"""
    try:
        history_url = f"{server}history/{prompt_id}"
        view_url = f"{server}view?filename="
        
        r = requests.get(history_url, timeout=10)
        if r.status_code == 200:
            data = r.json()
            # ComfyUI history format: {prompt_id: {outputs: {...}, status: {...}, ...}}
            if isinstance(data, dict) and prompt_id in data:
                prompt_data = data[prompt_id]
                outputs = prompt_data.get("outputs") if isinstance(prompt_data, dict) else None
                if outputs:
                    image_urls: List[str] = []
                    for node_id, node_out in outputs.items():
                        if not isinstance(node_out, dict):
                            continue
                        for out_type, out_items in node_out.items():
                            if not isinstance(out_items, list):
                                continue
                            for item in out_items:
                                if not isinstance(item, dict):
                                    continue
                                fname = item.get("filename")
                                if fname:
                                    image_urls.append(view_url + fname)
                    return image_urls
        return []
    except Exception:
        return []


@app.post("/api/qwen-image-edit")
async def qwen_image_edit(
    image: UploadFile = File(...),
    prompt: str = Form(...),
    server: str = Form(None)
):
    """
    Accepts an image and a text prompt, calls ComfyUI with the provided template,
    and returns the prompt_id for status checking.
    """
    srv = _normalize_server(server)

    # Step 1: Upload image to ComfyUI input folder via API
    image_name = _upload_image_to_comfyui(srv, image)

    # Step 2: Build workflow payload with updated nodes
    payload = _build_prompt_payload(image_name, prompt)

    # Step 3: Submit prompt
    prompt_id = _submit_prompt(srv, payload)

    return JSONResponse({
        "prompt_id": prompt_id,
        "status": "submitted"
    })


@app.get("/api/status/{prompt_id}")
async def check_status(
    prompt_id: str,
    server: str = Query(None)
):
    """
    Check the status of a submitted prompt.
    Returns: pending, running, completed, or error
    """
    srv = _normalize_server(server)
    
    # First check if it's completed
    image_urls = _check_history_for_images(srv, prompt_id)
    if image_urls:
        return JSONResponse({
            "status": "completed",
            "image_urls": image_urls
        })
    
    # Check queue status
    queue_status = _check_queue_status(srv, prompt_id)
    
    return JSONResponse({
        "status": queue_status,
        "image_urls": []
    })


# Serve frontend - MUST be after API routes
static_dir = os.path.join(APP_DIR, "web")
if not os.path.exists(static_dir):
    os.makedirs(static_dir, exist_ok=True)
app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")


if __name__ == "__main__":
    uvicorn.run("server:app", host="0.0.0.0", port=5173, reload=False)
