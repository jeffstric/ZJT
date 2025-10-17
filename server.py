from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Query
from fastapi.responses import JSONResponse, StreamingResponse
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
from runninghub_request import RunningHubClient, create_image_edit_nodes, TaskStatus, run_image_edit_task, run_ai_app_task_sync
from config_util import get_config_path, is_dev_environment

APP_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_PATH = os.path.join(APP_DIR, "qwen_image_edit_api.json")
COMFYUI_OUTPUT_PATH = '/mnt/disk/ComfyUI/server_output'
UPLOAD_DIR = os.path.join(APP_DIR, "upload")

# Load server configuration
import yaml
config_file = get_config_path()
with open(os.path.join(APP_DIR, config_file), 'r', encoding='utf-8') as f:
    config = yaml.safe_load(f)
SERVER_HOST = config["server"]["host"]

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


@app.get("/api/download")
async def download_image(
    url: str = Query(..., description="Media URL to download"),
    filename: str = Query(None, description="Custom filename")
):
    """
    Proxy download for media files (images/videos) to handle CORS and provide proper download headers
    """
    try:
        # Fetch the file from remote server
        response = requests.get(url, timeout=30, stream=True)
        response.raise_for_status()
        
        # Determine filename
        if not filename:
            # Extract filename from URL or generate one
            if "filename=" in url:
                filename = url.split("filename=")[-1].split("&")[0]
            else:
                # Try to get extension from URL
                url_path = url.split('?')[0]
                ext = url_path.split('.')[-1] if '.' in url_path else 'bin'
                filename = f"generated_file_{int(time.time())}.{ext}"
        
        # Don't add extension if filename already has a valid one
        valid_extensions = ('.png', '.jpg', '.jpeg', '.gif', '.webp', '.mp4', '.avi', '.mov', '.mkv', '.webm', '.flv')
        if not filename.lower().endswith(valid_extensions):
            # Try to detect from content-type
            content_type = response.headers.get('content-type', '')
            if 'video' in content_type:
                filename += '.mp4'
            elif 'image' in content_type:
                filename += '.png'
        
        # Get content type
        content_type = response.headers.get('content-type', 'application/octet-stream')
        
        def generate():
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    yield chunk
        
        return StreamingResponse(
            generate(),
            media_type=content_type,
            headers={
                "Content-Disposition": f"attachment; filename={filename}",
                "Content-Type": content_type
            }
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Download failed: {str(e)}")


@app.get("/api/proxy-image")
async def proxy_image(url: str = Query(..., description="Image URL to proxy")):
    """
    Proxy image requests to avoid CORS issues in Electron
    """
    try:
        # Fetch the image from the external server
        response = requests.get(url, timeout=30, stream=True)
        response.raise_for_status()
        
        # Get content type
        content_type = response.headers.get('content-type', 'image/png')
        
        def generate():
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    yield chunk
        
        return StreamingResponse(
            generate(),
            media_type=content_type,
            headers={
                "Content-Type": content_type,
                "Cache-Control": "public, max-age=3600"
            }
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Image proxy failed: {str(e)}")


def _save_uploaded_image(upload_file: UploadFile) -> str:
    """
    Save uploaded image to upload directory and return the file URL
    """
    # Ensure upload directory exists
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    
    # Generate unique filename
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    unique_id = str(uuid.uuid4())[:8]
    file_extension = os.path.splitext(upload_file.filename or "image.png")[1]
    filename = f"upload_{timestamp}_{unique_id}{file_extension}"
    
    # Save file
    file_path = os.path.join(UPLOAD_DIR, filename)
    with open(file_path, "wb") as f:
        content = upload_file.file.read()
        f.write(content)
    
    # Return URL that can be accessed via static file serving
    return f"{SERVER_HOST}/upload/{filename}"


@app.post("/api/nanobanana-edit")
async def nanobanana_edit(
    image: UploadFile = File(...),
    prompt: str = Form(...)
):
    """
    Submit image editing task to RunningHub nanobanana service
    """
    try:
        # Save uploaded image to upload directory
        image_url = _save_uploaded_image(image)
        
        # Initialize RunningHub client
        client = RunningHubClient()
        
        # Create nodes for the workflow
        nodes = create_image_edit_nodes(image_url, prompt)
        
        # Submit task
        response = client.run_task(nodes)
        task_id = response["data"]["taskId"]
        
        return JSONResponse({
            "task_id": task_id,
            "status": "submitted",
            "image_url": image_url
        })
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to submit nanobanana task: {str(e)}")


@app.get("/api/nanobanana-status/{task_id}")
async def nanobanana_status(task_id: str):
    """
    Check the status of a nanobanana task
    """
    try:
        client = RunningHubClient()
        status = client.check_status(task_id)
        
        if status == TaskStatus.SUCCESS:
            # Get results
            results = client.get_outputs(task_id)
            return JSONResponse({
                "status": status.value,
                "results": [
                    {
                        "file_url": result.file_url,
                        "file_type": result.file_type,
                        "task_cost_time": result.task_cost_time,
                        "node_id": result.node_id
                    }
                    for result in results
                ]
            })
        else:
            return JSONResponse({
                "status": status.value,
                "results": []
            })
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to check nanobanana status: {str(e)}")


@app.post("/api/runninghub-edit-sync")
async def runninghub_edit_sync(
    image_url: str = Form(..., description="URL of the image to edit"),
    prompt: str = Form(..., description="Text prompt for editing")
):
    """
    Submit image editing task to RunningHub and wait for completion.
    Unlike nanobanana-edit, this endpoint accepts an image URL instead of uploaded file
    and waits for the task to complete before returning results (with 3-minute timeout).
    """
    try:
        print(image_url)
        print(prompt)
        # Run the image editing task and wait for completion (3-minute timeout)
        task_id, results = run_image_edit_task(image_url, prompt, timeout=180)

        return JSONResponse({
            "task_id": task_id,
            "status": "completed",
            "image_url": image_url,
            "results": [
                {
                    "file_url": result.file_url,
                    "file_type": result.file_type,
                    "task_cost_time": result.task_cost_time,
                    "node_id": result.node_id
                }
                for result in results
            ]
        })

    except TimeoutError as e:
        raise HTTPException(status_code=408, detail=f"Task timed out: {str(e)}")
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=f"Task failed: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to process image editing task: {str(e)}")


@app.post("/api/ai-app-run")
async def ai_app_run(
    prompt: str = Form(..., description="Text prompt for the AI app"),
    model: str = Form("portrait", description="Model type: portrait, landscape, portrait-hd, landscape-hd"),
    timeout: int = Form(300, description="Maximum wait time in seconds")
):
    """
    Submit task to RunningHub AI-app/run endpoint and wait for completion.
    Automatically polls task status and returns final video/image URLs.
    """
    try:
        # Validate model parameter
        valid_models = ["portrait", "landscape", "portrait-hd", "landscape-hd"]
        if model not in valid_models:
            raise HTTPException(
                status_code=400, 
                detail=f"Invalid model. Must be one of: {', '.join(valid_models)}"
            )
        
        # Model descriptions mapping
        model_descriptions = {
            "portrait": "竖屏",
            "landscape": "横屏",
            "portrait-hd": "高清竖屏",
            "landscape-hd": "高清横屏"
        }
        
        # Build node info list
        node_info_list = [
            {
                "nodeId": "1",
                "fieldName": "prompt",
                "fieldValue": prompt,
                "description": "Input text"
            },
            {
                "nodeId": "1",
                "fieldName": "model",
                "fieldData": '[{"name":"portrait","index":"portrait","description":"竖屏","fastIndex":1.0,"descriptionEn":"Vertical screen"},{"name":"landscape","index":"landscape","description":"横屏","fastIndex":2.0,"descriptionEn":"Horizontal screen"},{"name":"portrait-hd","index":"portrait-hd","description":"高清竖屏","fastIndex":3.0,"descriptionEn":"High-definition vertical screen"},{"name":"landscape-hd","index":"landscape-hd","description":"高清横屏","fastIndex":4.0,"descriptionEn":"HD horizontal screen"}]',
                "fieldValue": model,
                "description": model_descriptions.get(model, "Horizontal and vertical mode")
            }
        ]
        
        # Get AI-app configuration from config file
        webapp_id = config["runninghub"].get("ai_app_webapp_id", "1973555977595301890")
        api_key = config["runninghub"].get("ai_app_api_key", config["runninghub"]["api_key"])
        
        # Run task and wait for completion
        task_id, results = run_ai_app_task_sync(
            webapp_id=webapp_id,
            api_key=api_key,
            node_info_list=node_info_list,
            timeout=timeout
        )
        
        return JSONResponse({
            "success": True,
            "task_id": task_id,
            "status": "completed",
            "results": [
                {
                    "file_url": result.file_url,
                    "file_type": result.file_type,
                    "task_cost_time": result.task_cost_time,
                    "node_id": result.node_id
                }
                for result in results
            ]
        })
        
    except TimeoutError as e:
        raise HTTPException(status_code=408, detail=f"Task timed out: {str(e)}")
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=f"Task failed: {str(e)}")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to submit AI app task: {str(e)}")


# Serve upload directory for static file access
upload_dir = os.path.join(APP_DIR, "upload")
if not os.path.exists(upload_dir):
    os.makedirs(upload_dir, exist_ok=True)
app.mount("/upload", StaticFiles(directory=upload_dir), name="uploads")

# Serve frontend - MUST be after API routes
static_dir = os.path.join(APP_DIR, "web")
if not os.path.exists(static_dir):
    os.makedirs(static_dir, exist_ok=True)
app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")


if __name__ == "__main__":
    port = 9002 if is_dev_environment() else config["server"].get("port", 5173)
    uvicorn.run("server:app", host="0.0.0.0", port=port, reload=False)
