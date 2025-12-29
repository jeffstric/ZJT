from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Query, Request, Header
from fastapi.responses import JSONResponse, StreamingResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import uvicorn
import requests
import uuid
import json
import os
import time
import logging
import traceback
import shutil
from datetime import datetime
from typing import List, Optional
from urllib.parse import urlparse
from pydantic import BaseModel
from runninghub_request import RunningHubClient, create_image_edit_nodes, TaskStatus, run_image_edit_task, run_ai_app_task_sync, run_ai_app_task
from config_util import get_config_path, is_dev_environment
from perseids_client import make_perseids_request, call_external_auth_server, get_device_uuid
from model import AIToolsModel, VideoWorkflowModel
from model.world import WorldModel
from model.character import CharacterModel
from model.location import LocationModel
import uuid
from duomi_api_requset import create_image_to_video, get_ai_task_result, create_ai_image, create_video_remix, create_character as create_character_task, get_character_task_result
from PIL import Image
from llm import call_ernie_vl_api


def _get_user_id_from_header(user_id: Optional[int]) -> int:
    if user_id is None:
        raise HTTPException(status_code=400, detail="user_id is required")
    if isinstance(user_id, str) and not user_id.strip():
        raise HTTPException(status_code=400, detail="user_id is required")
    try:
        return int(user_id)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="invalid user_id")


def _ensure_world_owner(world_id: int, user_id: int):
    world = WorldModel.get_by_id(world_id)
    if not world:
        raise HTTPException(status_code=404, detail="世界不存在")
    if getattr(world, 'user_id', None) != user_id:
        raise HTTPException(status_code=403, detail="无权访问该世界")
    return world

APP_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_PATH = os.path.join(APP_DIR, "qwen_image_edit_api.json")
COMFYUI_OUTPUT_PATH = '/mnt/disk/ComfyUI/server_output'
UPLOAD_DIR = os.path.join(APP_DIR, "upload")
CHECK_AUTH_TOKEN = True

# Load server configuration
import yaml
config_file = get_config_path()
with open(os.path.join(APP_DIR, config_file), 'r', encoding='utf-8') as f:
    config = yaml.safe_load(f)
# Choose appropriate host based on HTTPS configuration
https_config = config["server"].get("https", {})
if https_config.get("enabled", False) and "https_host" in config["server"]:
    SERVER_HOST = config["server"]["https_host"]
else:
    SERVER_HOST = config["server"]["host"]
API_KEY = config["runninghub"]["api_key"]

# Default ComfyUI server address; can be overridden by request field
DEFAULT_COMFYUI_SERVER = os.environ.get("COMFYUI_SERVER", "http://127.0.0.1:8188/")

# Type to computing power mapping
# 1: 图片编辑, 2: AI视频生成, 3: 图片生成视频, 4: 高清放大, 5: ai视频高清修复, 6: 图生视频高清修复，7：图片编辑(nano-banana-pro), 8: 创建角色卡
TASK_COMPUTING_POWER = {
    1: 2,
    2: 20,
    3: 20,
    4: 1,
    5: 10,
    6: 10,
    7: 6,
    8: 20
}

app = FastAPI(title="ComfyUI Qwen Image Edit Proxy")

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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


def _save_user_asset(
    upload_file: UploadFile,
    user_id: int,
    category: str = "workflow",
    base_host: Optional[str] = None
) -> str:
    """
    Save a user-specific asset (image/video) under a scoped directory.
    """
    asset_dir = os.path.join(UPLOAD_DIR, category, str(user_id))
    os.makedirs(asset_dir, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    unique_id = uuid.uuid4().hex[:8]
    original_name = upload_file.filename or "asset"
    file_extension = os.path.splitext(original_name)[1] or ".bin"
    filename = f"{category}_{timestamp}_{unique_id}{file_extension}"

    file_path = os.path.join(asset_dir, filename)
    with open(file_path, "wb") as f:
        content = upload_file.file.read()
        f.write(content)

    relative_path = f"{category}/{user_id}/{filename}"
    host = (base_host or SERVER_HOST).rstrip("/")
    return f"{host}/upload/{relative_path}"


def _normalize_origin(origin: Optional[str]) -> Optional[str]:
    if not origin:
        return None
    try:
        trimmed = origin.strip()
        if not trimmed:
            return None
        parsed = urlparse(trimmed)
        if not parsed.scheme or not parsed.netloc:
            parsed = urlparse(f"http://{trimmed.lstrip('/')}")
        if not parsed.scheme or not parsed.netloc:
            return None
        return f"{parsed.scheme}://{parsed.netloc}".rstrip("/")
    except Exception:
        return None


def _get_local_upload_file(asset_url: Optional[str], origin: Optional[str]) -> Optional[str]:
    if not asset_url:
        return None
    normalized_origin = _normalize_origin(origin)
    try:
        # Support relative URLs like /upload/...
        if asset_url.startswith("/upload/"):
            relative_path = asset_url[len("/upload/"):]
            local_path = os.path.join(UPLOAD_DIR, *relative_path.split("/"))
            return local_path if os.path.exists(local_path) else None

        parsed = urlparse(asset_url)
        if not parsed.scheme or not parsed.netloc:
            return None
        asset_origin = f"{parsed.scheme}://{parsed.netloc}".rstrip("/")
        if normalized_origin and asset_origin != normalized_origin:
            return None
        asset_path = parsed.path or ""
        if not asset_path.startswith("/upload/"):
            return None
        relative_path = asset_path[len("/upload/"):]
        if not relative_path:
            return None
        local_path = os.path.join(UPLOAD_DIR, *relative_path.split("/"))
        return local_path if os.path.exists(local_path) else None
    except Exception:
        return None


def _concatenate_images(upload_files: List[UploadFile]) -> str:
    """
    Concatenate multiple images horizontally and save to upload directory.
    All images will be resized to the same height while maintaining aspect ratio.
    Returns the URL of the concatenated image.
    """
    if not upload_files or len(upload_files) == 0:
        raise ValueError("No images provided")
    
    if len(upload_files) > 5:
        raise ValueError("Maximum 5 images allowed")
    
    # Ensure upload directory exists
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    
    # Load all images
    images = []
    for upload_file in upload_files:
        content = upload_file.file.read()
        upload_file.file.seek(0)  # Reset file pointer for potential reuse
        img = Image.open(upload_file.file)
        # Convert to RGB if necessary (handles RGBA, grayscale, etc.)
        if img.mode != 'RGB':
            img = img.convert('RGB')
        images.append(img)
    
    # Calculate target height - use the average height or a reasonable fixed height
    # Using average height to balance between quality and consistency
    avg_height = sum(img.height for img in images) // len(images)
    target_height = avg_height
    
    # Alternatively, you can use a fixed height like 1024 or the minimum height
    # target_height = 1024  # Fixed height option
    # target_height = min(img.height for img in images)  # Minimum height option
    
    # Resize all images to the same height while maintaining aspect ratio
    resized_images = []
    for img in images:
        # Calculate new width to maintain aspect ratio
        aspect_ratio = img.width / img.height
        new_width = int(target_height * aspect_ratio)
        resized_img = img.resize((new_width, target_height), Image.LANCZOS)
        resized_images.append(resized_img)
    
    # Define spacing between images (in pixels)
    spacing = 10  # 10px white space between images
    
    # Calculate total width after resizing (including spacing)
    total_width = sum(img.width for img in resized_images) + spacing * (len(resized_images) - 1)
    
    # Create new image with combined width
    concatenated = Image.new('RGB', (total_width, target_height), (255, 255, 255))
    
    # Paste images horizontally with spacing
    x_offset = 0
    for i, img in enumerate(resized_images):
        concatenated.paste(img, (x_offset, 0))
        x_offset += img.width
        # Add spacing after each image except the last one
        if i < len(resized_images) - 1:
            x_offset += spacing
    
    # Generate unique filename
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    unique_id = str(uuid.uuid4())[:8]
    filename = f"concat_{timestamp}_{unique_id}.jpg"
    file_path = os.path.join(UPLOAD_DIR, filename)
    
    # Save concatenated image
    concatenated.save(file_path, 'JPEG', quality=95)
    
    # Return URL
    return f"{SERVER_HOST}/upload/{filename}"


@app.post("/api/image-edit")
async def image_edit(
    image: List[UploadFile] = File(...),
    prompt: str = Form(...),
    ratio: str = Form("9:16", description="Model type: 9:16, 16:9, 1:1 ,3:4, 4:3"),
    count: int = Form(1, ge=1, le=4, description="Generation count (1-4)"),
    user_id: int = Form(None, description="User ID"),
    auth_token: str = Form(None, description="Authentication token"),
    model: str = Form("gemini-2.5-pro-image-preview", description="Model type: gemini-2.5-pro-image-preview, gemini-3-pro-image-preview"),
    image_size: str = Form("1K", description="Image resolution: 1K, 2K, 4K")
):
    """
    Submit image editing task to RunningHub nanobanana service
    Supports multiple images - will concatenate them horizontally if more than one
    """
    try:
        if CHECK_AUTH_TOKEN and auth_token is None:
            raise HTTPException(
                status_code=400, 
                detail="Authentication token is required"
            )

        #用uuid生成交易id
        image_edit_type = 1
        if model == "gemini-2.5-pro-image-preview":
            image_edit_type = 1
        elif model == "gemini-3-pro-image-preview":
            image_edit_type = 7
        computing_power = TASK_COMPUTING_POWER[image_edit_type]
        if CHECK_AUTH_TOKEN:
            headers = {'Authorization': f'Bearer {auth_token}'}
            #发起请求，检查算力是否充足
            success, message, response_data = make_perseids_request(
                endpoint='user/check_computing_power',
                method='GET',
                headers=headers
            )
            if not success:
                raise HTTPException(
                    status_code=400, 
                    detail=message
                )
            
            # Check if computing power is sufficient
            user_computing_power = response_data.get('computing_power', 0)
            if user_computing_power < computing_power:
                raise HTTPException(
                    status_code=400, 
                    detail="您的算力不足，无法生成视频"
                )

        # Handle multiple images - limit to maximum 5 images
        images_to_process = image[:5] if len(image) > 5 else image
        image_urls = [_save_uploaded_image(img) for img in images_to_process]
        
        # Submit tasks according to generation count
        project_ids = []
        for _ in range(count):
            #用uuid生成交易id
            transaction_id = str(uuid.uuid4())

            response = create_ai_image(model, prompt, ratio, image_urls, image_size)
            logger.info(response)
            project_id = response.get("data", {}).get("task_id")
            if not project_id:
                logger.error("Failed to create project")
                continue
            project_ids.append(project_id)

            if CHECK_AUTH_TOKEN:
                #发起请求，扣除算力
                success, message, response_data = make_perseids_request(
                    endpoint='user/calculate_computing_power',
                    method='POST',
                    headers=headers,
                    data={
                        "computing_power": computing_power,
                        "behavior": "deduct",
                        "transaction_id": transaction_id
                    }
                )
                if not success:
                    raise HTTPException(
                        status_code=400, 
                        detail=message
                    )

            # Create database record for each project
            if user_id:
                try:
                    # Store multiple image URLs as comma-separated string
                    image_path_str = ','.join(image_urls) if isinstance(image_urls, list) else image_urls
                    AIToolsModel.create(
                        prompt=prompt,
                        user_id=user_id,
                        type=image_edit_type,  # 1-图片编辑
                        image_path=image_path_str,
                        ratio=ratio,
                        project_id=project_id,
                        transaction_id=transaction_id,
                        status=1
                    )
                except Exception as db_error:
                    logger.error(f"Failed to create database record: {db_error}")
                    # Don't fail the request if database insert fails

        return JSONResponse({
            "project_ids": project_ids,
            "status": "submitted",
            "image_urls": image_urls
        })
    except HTTPException:
        raise    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/runninghub-status/{project_id}")
async def runninghub_status(
    project_id: str,
    auth_token: Optional[str] = Query(None, description="Auth token for computing power refund")
):
    """
    Check the status of a runninghub task
    If task fails, will refund computing power
    """
    try:
        task_record = AIToolsModel.get_by_project_id(project_id)
        if task_record is None:
            raise HTTPException(status_code=404, detail="未找到对应的图片记录")
        client = RunningHubClient()
        status = client.check_status(project_id)
        
        if status == TaskStatus.SUCCESS:
            # Get results
            results = client.get_outputs(project_id)
            
            # Update database record with result_url
            if results:
                try:
                    result_url = results[0].file_url
                    AIToolsModel.update_by_project_id(
                        project_id=project_id,
                        result_url=result_url,
                        status=2
                    )
                except Exception as db_error:
                    logger.error(f"Failed to update database record: {db_error}")
            
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
        elif status == TaskStatus.FAILED:
            AIToolsModel.update_by_project_id(
                project_id=project_id,
                status=-1
            )
            if CHECK_AUTH_TOKEN and auth_token:
                # 生成交易ID
                transaction_id = str(uuid.uuid4())
                headers = {'Authorization': f'Bearer {auth_token}'}
                #发起请求，增加算力
                type = task_record.type
                computing_power = TASK_COMPUTING_POWER[type]
                success, message, response_data = make_perseids_request(
                    endpoint='user/calculate_computing_power',
                    method='POST',
                    headers=headers,
                    data={
                        "computing_power": computing_power,
                        "behavior": "increase",
                        "transaction_id": transaction_id
                    }
                )
                if success:
                    logger.info(f"Successfully refunded {computing_power} computing power for failed task {project_id}, transaction_id: {transaction_id}")
                else:
                    logger.error(f"Failed to refund computing power for task {project_id}: {message}")
            return JSONResponse({
                "status": status.value,
                "results": []
            })
        else:
            # RUNNING or QUEUED status
            return JSONResponse({
                "status": status.value,
                "results": []
            })
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to check runninghub status: {str(e)}")


@app.get("/api/get-status/{project_id}")
async def get_status(
    project_id: str,
    auth_token: Optional[str] = Query(None, description="Auth token for computing power refund")
):
    """
    Check the status of one or more AI tasks.
    - For a single project_id: returns the original shape {status, results, reason?}
    - For multiple project_ids (comma-separated): returns {tasks: [{project_id, status, results, reason}]}
    If task fails, will refund computing power.
    """
    try:
        project_ids = [pid.strip() for pid in project_id.split(",") if pid.strip()]
        if not project_ids:
            raise HTTPException(status_code=400, detail="project_id is required")

        tasks_response = []

        for pid in project_ids:
            # Query database to get task type
            task_record = AIToolsModel.get_by_project_id(pid)
            
            # Determine if this is a video task (type 2 or 3)
            is_video = task_record and task_record.type in [2, 3]
            
            result = get_ai_task_result(pid, is_video)

            # Check if API call was successful
            if result.get("code") != 0:
                error_msg = result.get("msg", "Unknown error")
                raise HTTPException(status_code=500, detail=f"Failed to get task result: {error_msg}")

            data = result.get("data", {})
            task_status = data.get("status")  # 0-进行中 1-成功 2-失败
            media_url = data.get("mediaUrl")
            reason = data.get("reason")
            # Calculate task cost time
            task_cost_time = None
            if task_record and task_record.create_time:
                # Calculate time difference in seconds
                from datetime import datetime
                current_time = datetime.now()
                time_diff = current_time - task_record.create_time
                task_cost_time = int(time_diff.total_seconds())

            status_str = "RUNNING"
            results_payload = []
            reason_payload = None

            # Update database based on status
            if task_status == 1:  # Success
                status_str = "SUCCESS"
                try:
                    AIToolsModel.update_by_project_id(
                        project_id=pid,
                        result_url=media_url,
                        status=2  # 2-处理完成
                    )
                except Exception as db_error:
                    logger.error(f"Failed to update database record: {db_error}")

                if media_url:
                    results_payload = [{
                        "file_url": media_url,
                        "task_cost_time": task_cost_time
                    }]

            elif task_status == 2:  # Failed
                status_str = "FAILED"
                logger.info(f"Task failed: {reason}")
                if reason and "We currently do not support uploads of images containing photorealistic people" in reason:
                    reason = "图片包含真人，无法处理"
                elif reason and "This content may violate our guardrails concerning similarity to third-party content. " in reason:
                    reason = "此内容可能违反了我们关于与第三方内容相似性的规定"
                
                # Check if task has already been marked as failed
                already_failed = task_record and task_record.status == -1
                
                if not already_failed:
                    # Only update status and refund if not already processed
                    try:
                        AIToolsModel.update_by_project_id(
                            project_id=pid,
                            status=-1,  # -1-处理失败
                            message=reason
                        )
                    except Exception as db_error:
                        logger.error(f"Failed to update database record: {db_error}")
                    
                    if CHECK_AUTH_TOKEN and auth_token and task_record is not None:
                        # 生成交易ID
                        transaction_id = str(uuid.uuid4())
                        headers = {'Authorization': f'Bearer {auth_token}'}
                        #发起请求，增加算力
                        type = task_record.type
                        computing_power = TASK_COMPUTING_POWER[type]
                        success, message, response_data = make_perseids_request(
                            endpoint='user/calculate_computing_power',
                            method='POST',
                            headers=headers,
                            data={
                                "computing_power": computing_power,
                                "behavior": "increase",
                                "transaction_id": transaction_id
                            }
                        )
                        if success:
                            logger.info(f"Successfully refunded {computing_power} computing power for failed task {pid}, transaction_id: {transaction_id}")
                        else:
                            logger.error(f"Failed to refund computing power for task {pid}: {message}")
                else:
                    logger.info(f"Task {pid} already marked as failed (status=-1), skipping status update and refund")

                reason_payload = reason

            # task_status == 0 or unknown -> RUNNING by default

            tasks_response.append({
                "project_id": pid,
                "status": status_str,
                "results": results_payload,
                "reason": reason_payload
            })

        # Backward compatibility: single project_id keeps old shape
        if len(tasks_response) == 1:
            task = tasks_response[0]
            return JSONResponse({
                "status": task["status"],
                "results": task["results"],
                "reason": task["reason"]
            })

        # Multiple project_ids: return list
        return JSONResponse({
            "tasks": tasks_response
        })

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to check task status: {str(e)}")


@app.post("/api/ai-app-run")
async def ai_app_run(
    prompt: str = Form(..., description="Text prompt for the AI app"),
    ratio: str = Form("9:16", description="Model type: 9:16, 16:9"),
    duration_seconds: int = Form(15, description="Duration in seconds"),
    count: int = Form(1, ge=1, le=4, description="Generation count (1-4)"),
    user_id: int = Form(None, description="User ID"),
    auth_token: str = Form(None, description="Authentication token")
):
    """
    Submit task to RunningHub AI-app/run endpoint and wait for completion.
    Automatically polls task status and returns final video/image URLs.
    """
    try:
        if CHECK_AUTH_TOKEN and auth_token is None:
            raise HTTPException(
                status_code=400, 
                detail="Authentication token is required"
            )
        computing_power = TASK_COMPUTING_POWER[2]
        if CHECK_AUTH_TOKEN:
            headers = {'Authorization': f'Bearer {auth_token}'}
            #发起请求，检查算力是否充足
            success, message, response_data = make_perseids_request(
                endpoint='user/check_computing_power',
                method='GET',
                headers=headers
            )
            if not success:
                raise HTTPException(
                    status_code=400, 
                    detail=message
                )
            
            # Check if computing power is sufficient
            user_computing_power = response_data.get('computing_power', 0)
            if user_computing_power < computing_power:
                raise HTTPException(
                    status_code=400, 
                    detail="您的算力不足，无法生成视频"
                )
            
            
        project_ids = []

        # Submit tasks according to generation count
        for _ in range(count):
            # 用uuid生成交易id
            transaction_id = str(uuid.uuid4())

            # Submit task (async, return immediately)
            result = create_image_to_video(prompt, ratio, None, duration_seconds)
            logger.info(f"Submit task result: {result}")
            # Get project_id from new API response format
            project_id = result.get("id")
            if not project_id:
                raise HTTPException(status_code=500, detail="未获得任务id")
            project_ids.append(project_id)

            if CHECK_AUTH_TOKEN:
                #发起请求，增加算力
                success, message, response_data = make_perseids_request(
                    endpoint='user/calculate_computing_power',
                    method='POST',
                    headers=headers,
                    data={
                        "computing_power": computing_power,
                        "behavior": "deduct",
                        "transaction_id": transaction_id
                    }
                )
                if not success:
                    raise HTTPException(
                        status_code=400, 
                        detail=message
                    )

            # Create database record for each project
            if user_id:
                try:
                    AIToolsModel.create(
                        prompt=prompt,
                        user_id=user_id,
                        type=2,  # 2-AI视频生成
                        ratio=ratio,
                        project_id=project_id,
                        transaction_id=transaction_id,
                        status=1
                    )
                except Exception as db_error:
                    logger.error(f"Failed to create database record: {db_error}")
                    # Don't fail the request if database insert fails

        return JSONResponse({
            "success": True,
            "project_ids": project_ids,
            "status": "submitted"
        })
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to submit AI app task: {str(e)}")

@app.post("/api/ai-app-run-image")
async def ai_app_run_image(
    prompt: str = Form(..., description="Text prompt for the AI app"),
    images: List[UploadFile] = File(..., description="Image files for the AI app (1-5 images)"),
    ratio: str = Form("9:16", description="Ratio type: 9:16, 16:9"),
    duration_seconds: int = Form(15, description="Duration in seconds"),
    count: int = Form(1, ge=1, le=4, description="Generation count (1-4)"),
    user_id: int = Form(None, description="User ID"),
    auth_token: str = Form(None, description="Authentication token")
):
    """
    Submit task to RunningHub AI-app/run endpoint and wait for completion.
    Supports uploading 1-5 images which will be concatenated horizontally.
    Automatically polls task status and returns final video/image URLs.
    """
    try:
        if CHECK_AUTH_TOKEN and auth_token is None:
            raise HTTPException(
                status_code=400, 
                detail="Authentication token is required"
            )
        
        # Validate number of images
        if not images or len(images) == 0:
            raise HTTPException(
                status_code=400,
                detail="At least one image is required"
            )
        
        if len(images) > 5:
            raise HTTPException(
                status_code=400,
                detail="Maximum 5 images allowed"
            )
        
        # If single image, save it directly; if multiple, concatenate them
        if len(images) == 1:
            image_url = _save_uploaded_image(images[0])
        else:
            image_url = _concatenate_images(images)

        computing_power = TASK_COMPUTING_POWER[3]
        if CHECK_AUTH_TOKEN:
            headers = {'Authorization': f'Bearer {auth_token}'}
            #发起请求，检查算力是否充足
            success, message, response_data = make_perseids_request(
                endpoint='user/check_computing_power',
                method='GET',
                headers=headers
            )
            if not success:
                raise HTTPException(
                    status_code=400, 
                    detail=message
                )
            
            # Check if computing power is sufficient for all generations
            user_computing_power = response_data.get('computing_power', 0)
            total_computing_power = computing_power * count
            if user_computing_power < total_computing_power:
                raise HTTPException(
                    status_code=400, 
                    detail=f"您的算力不足，需要 {total_computing_power} 算力，当前仅有 {user_computing_power} 算力"
                )
        
        project_ids = []
        
        # Loop to create multiple tasks
        for i in range(count):
            try:
                # Generate unique transaction ID for each task
                transaction_id = str(uuid.uuid4())
                
                # Submit task (async, return immediately)
                result = create_image_to_video(prompt, ratio, image_url, duration_seconds)
                
                # Get project_id from new API response format
                project_id = result.get("id")
                if not project_id:
                    logger.error(f"Task {i+1}: No project ID received")
                    continue  # Continue with next task
                
                project_ids.append(project_id)
                
                # Deduct computing power for each task
                if CHECK_AUTH_TOKEN:
                    success, message, response_data = make_perseids_request(
                        endpoint='user/calculate_computing_power',
                        method='POST',
                        headers=headers,
                        data={
                            "computing_power": computing_power,
                            "behavior": "deduct",
                            "transaction_id": transaction_id
                        }
                    )
                    if not success:
                        logger.error(f"Task {i+1} computing power deduction failed: {message}")
                        # Continue anyway, as task is already submitted
                
                # Create database record for each task
                if user_id:
                    try:
                        AIToolsModel.create(
                            prompt=prompt,
                            user_id=user_id,
                            type=3,  # 3-图片生成视频
                            image_path=image_url,
                            ratio=ratio,
                            duration=duration_seconds,
                            project_id=project_id,
                            transaction_id=transaction_id,
                            status=1
                        )
                    except Exception as db_error:
                        logger.error(f"Failed to create database record for task {i+1}: {db_error}")
                        # Don't fail the request if database insert fails
                        
            except Exception as task_error:
                logger.error(f"Task {i+1} failed: {task_error}")
                continue  # Continue with next task
        
        if not project_ids:
            raise HTTPException(status_code=500, detail="所有任务都提交失败")
        
        return JSONResponse({
            "success": True,
            "project_ids": project_ids,
            "status": "submitted",
            "image_url": image_url
        })
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to submit AI app task: {str(e)}")


@app.post("/api/ai-app-run-image-url")
async def ai_app_run_image_url(
    prompt: str = Form("", description="Text prompt for the AI app"),
    image_url: str = Form(..., description="Image URL (already uploaded to server)"),
    ratio: str = Form("9:16", description="Ratio type: 9:16, 16:9"),
    duration_seconds: int = Form(10, description="Duration in seconds"),
    count: int = Form(1, ge=1, le=4, description="Generation count (1-4)"),
    user_id: int = Form(None, description="User ID"),
    auth_token: str = Form(None, description="Authentication token")
):
    """
    Submit image-to-video task using an already uploaded image URL.
    This is optimized for workflow where images are already on the server.
    """
    try:
        # logger.info(f"ai_app_run_image_url called with image_url: {image_url}")
        # logger.info(f"prompt: {prompt}")
        # logger.info(f"ratio: {ratio}, duration_seconds: {duration_seconds}, count: {count}")

        if CHECK_AUTH_TOKEN and auth_token is None:
            raise HTTPException(
                status_code=400, 
                detail="Authentication token is required"
            )
        
        if not image_url:
            raise HTTPException(
                status_code=400,
                detail="Image URL is required"
            )

        computing_power = TASK_COMPUTING_POWER[3]
        if CHECK_AUTH_TOKEN:
            headers = {'Authorization': f'Bearer {auth_token}'}
            success, message, response_data = make_perseids_request(
                endpoint='user/check_computing_power',
                method='GET',
                headers=headers
            )
            if not success:
                raise HTTPException(
                    status_code=400, 
                    detail=message
                )
            
            user_computing_power = response_data.get('computing_power', 0)
            total_computing_power = computing_power * count
            if user_computing_power < total_computing_power:
                raise HTTPException(
                    status_code=400, 
                    detail=f"您的算力不足，需要 {total_computing_power} 算力，当前仅有 {user_computing_power} 算力"
                )
        
        project_ids = []
        
        for i in range(count):
            try:
                transaction_id = str(uuid.uuid4())
                result = create_image_to_video(prompt, ratio, image_url, duration_seconds)
                
                project_id = result.get("id")
                if not project_id:
                    logger.error(f"Task {i+1}: No project ID received")
                    continue
                
                project_ids.append(project_id)
                logger.info(f"Task {i+1} submitted with project_id: {project_id}")
                
                if CHECK_AUTH_TOKEN:
                    headers = {'Authorization': f'Bearer {auth_token}'}
                    make_perseids_request(
                        endpoint='user/calculate_computing_power',
                        method='POST',
                        headers=headers,
                        data={
                            'computing_power': computing_power,
                            'behavior': 'deduct',
                            'transaction_id': transaction_id
                        }
                    )
                
                if user_id:
                    try:
                        AIToolsModel.create(
                            prompt=prompt,
                            user_id=user_id,
                            type=3,
                            image_path=image_url,
                            ratio=ratio,
                            duration=duration_seconds,
                            project_id=project_id,
                            status=1  # 1-处理中, 2-完成, -1-失败
                        )
                    except Exception as db_err:
                        logger.error(f"Failed to save to database: {str(db_err)}")
                        
            except Exception as task_err:
                logger.error(f"Task {i+1} failed: {str(task_err)}")
                continue
        
        if not project_ids:
            raise HTTPException(status_code=500, detail="所有任务都提交失败")
        
        return JSONResponse({
            "success": True,
            "project_ids": project_ids,
            "status": "submitted",
            "image_url": image_url
        })
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to submit task: {str(e)}")


@app.get('/api/user/computing_power')
async def get_computing_power(auth_token: str = Header(None, alias="Authorization")):
    """
    查询用户算力
    """
    try:
        # 验证 auth_token
        if not auth_token:
            return JSONResponse(
                status_code=401,
                content={
                    'success': False,
                    'message': '未提供认证信息'
                }
            )
        
        # 移除 "Bearer " 前缀（如果存在）
        if auth_token.startswith("Bearer "):
            auth_token = auth_token[7:]
        
        # 调用 perseids_server 的查询算力接口
        headers = {'Authorization': f'Bearer {auth_token}'}
        success, message, response_data = make_perseids_request(
            endpoint='user/check_computing_power',
            method='GET',
            headers=headers
        )
        
        if success:
            return JSONResponse(
                content={
                    'success': True,
                    'message': '查询成功',
                    'data': {
                        'computing_power': response_data.get('computing_power', 0)
                    }
                }
            )
        else:
            return JSONResponse(
                status_code=400,
                content={
                    'success': False,
                    'message': message or '查询算力失败'
                }
            )
    
    except Exception as e:
        logger.error(f'查询算力失败: {str(e)}')
        logger.error(traceback.format_exc())
        return JSONResponse(
            status_code=500,
            content={
                'success': False,
                'message': '服务器错误'
            }
        )


class SendVerifyCodeRequest(BaseModel):
    phone: str
    type: str
    agent: Optional[str] = 'default'

@app.post('/api/auth/send_verify_code')
async def send_verify_code(request: SendVerifyCodeRequest):
    """
    发送验证码
    """
    try:
        phone = request.phone
        verify_type = request.type
        agent = request.agent

        if not phone or not verify_type:
            return JSONResponse(
                status_code=400,
                content={
                    'success': False,
                    'message': '手机号和验证码类型不能为空'
                }
            )

        # 验证手机号格式
        if not phone.isdigit() or len(phone) != 11:
            return JSONResponse(
                status_code=400,
                content={
                    'success': False,
                    'message': '无效的手机号格式'
                }
            )

        # 验证码类型检查
        valid_types = ['register', 'login', 'reset_password', 'get_serial', 'update_serial']
        if verify_type not in valid_types:
            return JSONResponse(
                status_code=400,
                content={
                    'success': False,
                    'message': '无效的验证码类型'
                }
            )

        # 调用 Go 服务器发送验证码
        success, message, response_data = make_perseids_request(
            endpoint='send_verify_code',
            data={
                'phone': phone,
                'type': verify_type,
                'agent': agent
            }
        )

        if success:
            return JSONResponse(
                content={
                    'success': True,
                    'message': '验证码发送成功'
                }
            )
        else:
            return JSONResponse(
                status_code=400,
                content={
                    'success': False,
                    'message': message or '验证码发送失败'
                }
            )

    except Exception as e:
        logger.error(f"发送验证码时发生错误: {str(e)}")
        logger.error(traceback.format_exc())
        return JSONResponse(
            status_code=500,
            content={
                'success': False,
                'message': '服务器内部错误'
            }
        )

class RegisterRequest(BaseModel):
    phone: str
    code: str
    password: str
    agent: Optional[str] = 'default'
    invite_code: Optional[str] = None

@app.post('/api/auth/register')
async def register(request: RegisterRequest):
    """
    用户注册接口
    """
    try:
        phone = request.phone
        password = request.password
        verify_code = request.code
        agent = request.agent
        
        logger.info(f"收到注册请求 - 手机号: {phone}")

        # 验证必填字段
        if not all([phone, password, verify_code]):
            return JSONResponse(
                status_code=400,
                content={
                    'success': False,
                    'message': '手机号、密码和验证码不能为空'
                }
            )

        # 验证手机号格式
        if not phone.isdigit() or len(phone) != 11:
            return JSONResponse(
                status_code=400,
                content={
                    'success': False,
                    'message': '无效的手机号格式'
                }
            )

        # 验证密码长度
        if len(password) < 6:
            return JSONResponse(
                status_code=400,
                content={
                    'success': False,
                    'message': '密码长度不能少于6位'
                }
            )

        # 调用认证服务器注册
        success, message, auth_data = call_external_auth_server(
            phone=phone,
            password=password,
            auth_type='register',
            extra_data={'code': verify_code, 'invite_code': request.invite_code}  # 使用 code 而不是 verify_code
        )
        
        if success:
            logger.info(f"用户注册成功 - 手机号: {phone}")
            return JSONResponse(
                content={
                    'success': True,
                    'message': '注册成功',
                    'data': auth_data
                }
            )
        else:
            return JSONResponse(
                status_code=400,
                content={
                    'success': False,
                    'message': message or '注册失败'
                }
            )
            
    except Exception as e:
        logger.error(f"处理注册请求时发生异常: {str(e)}")
        logger.error(traceback.format_exc())
        return JSONResponse(
            status_code=500,
            content={
                'success': False,
                'message': '系统异常，请稍后重试'
            }
        )

class LoginRequest(BaseModel):
    phone: str
    password: str
    agent: Optional[str] = 'default'
    terms_agreed: Optional[int] = 0

@app.post('/api/auth/login')
async def login(request: LoginRequest):
    """
    用户登录接口
    """
    try:
        phone = request.phone
        password = request.password
        agent = request.agent
        terms_agreed = request.terms_agreed
        
        logger.info(f"收到登录请求 - 手机号: {phone}")

        # 验证必填字段
        if not all([phone, password]):
            return JSONResponse(
                status_code=400,
                content={
                    'success': False,
                    'message': '手机号和密码不能为空'
                }
            )

        # 验证手机号格式
        if not phone.isdigit() or len(phone) != 11:
            return JSONResponse(
                status_code=400,
                content={
                    'success': False,
                    'message': '无效的手机号格式'
                }
            )
        device_uuid = get_device_uuid()
        if device_uuid is None:
            return JSONResponse(
                status_code=400,
                content={
                    'success': False,
                    'message': '无法获取设备UUID'
                }
            )
        # 调用认证服务器登录
        extra_data={'terms_agreed': terms_agreed}
        success, message, auth_data = call_external_auth_server(phone, password, device_uuid,'login', extra_data)
        
        if success:
            logger.info(f"用户登录成功 - 手机号: {phone}")
            return JSONResponse(
                content={
                    'success': True,
                    'message': '登录成功',
                    'data': auth_data
                }
            )
        else:
            return JSONResponse(
                status_code=400,
                content={
                    'success': False,
                    'message': message or '登录失败'
                }
            )

    except Exception as e:
        logger.error(f"处理登录请求时发生异常: {str(e)}")
        logger.error(traceback.format_exc())
        return JSONResponse(
            status_code=500,
            content={
                'success': False,
                'message': '系统异常，请稍后重试'
            }
        )

class LogoutRequest(BaseModel):
    auth_token: str

@app.post('/api/auth/logout')
async def logout(request: LogoutRequest):
    """
    用户登出接口
    """
    try:
        auth_token = request.auth_token

        if not auth_token:
            return JSONResponse(
                status_code=400,
                content={
                    'success': False,
                    'message': '认证信息不存在'
                }
            )

        # 调用 perseids_server 的登出接口
        success, message, response_data = make_perseids_request(
            endpoint='auth/logout',
            method='POST',
            headers={'Authorization': f"Bearer {auth_token}"}
        )

        if success:
            return JSONResponse(
                content={
                    'success': True,
                    'message': '登出成功'
                }
            )
        else:
            return JSONResponse(
                status_code=400,
                content={
                    'success': False,
                    'message': message or '登出失败'
                }
            )

    except Exception as e:
        logger.error(f"登出失败: {str(e)}")
        logger.error(traceback.format_exc())
        return JSONResponse(
            status_code=500,
            content={
                'success': False,
                'message': '登出失败'
            }
        )

class ResetPasswordRequest(BaseModel):
    phone: str
    code: str
    new_password: str

@app.post('/api/auth/reset_password')
async def reset_password(request: ResetPasswordRequest):
    """
    重置密码
    """
    try:
        phone = request.phone
        code = request.code
        new_password = request.new_password

        if not all([phone, code, new_password]):
            return JSONResponse(
                status_code=400,
                content={
                    'success': False,
                    'message': '缺少必要参数'
                }
            )

        # 调用外部认证服务器重置密码
        success, message, response_data = call_external_auth_server(
            phone=phone,
            password=new_password,
            auth_type='reset_password',
            extra_data={
                'code': code,
                'new_password': new_password
            }
        )

        if success:
            return JSONResponse(
                content={
                    'success': True,
                    'message': '密码重置成功',
                    'data': response_data
                }
            )
        else:
            return JSONResponse(
                status_code=400,
                content={
                    'success': False,
                    'message': message
                }
            )

    except Exception as e:
        logger.error(f'重置密码失败: {str(e)}')
        logger.error(traceback.format_exc())
        return JSONResponse(
            status_code=500,
            content={
                'success': False,
                'message': '服务器错误'
            }
        )


@app.get('/api/ai-tools/history')
async def get_ai_tools_history(
    user_id: int = Query(..., description="User ID"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Page size"),
    type: Optional[int] = Query(None, description="Tool type filter (1-图片编辑, 2-AI视频生成, 3-图片生成视频)"),
    auth_token: Optional[str] = Query(None, description="Auth token for computing power refund")
):
    """
    获取用户的 AI 工具历史记录
    在查询前会先检查并更新所有正在处理的任务状态
    如果任务失败，会自动补回算力
    """
    try:
        # First, check and update processing tasks
        processing_tasks = AIToolsModel.list_processing_by_user(user_id)
        
        if processing_tasks:
            updated_count = 0
            total_refund_power = 0  # 累计需要补回的算力
            
            # Check each task's status
            for task in processing_tasks:
                if not task.project_id:
                    continue
                    
                try:
                    if task.type in [4,5,6]:
                        # Use RunningHub client for upscale tasks
                        client = RunningHubClient()
                        status = client.check_status(task.project_id)
                        
                        if status == TaskStatus.SUCCESS:
                            # Get results
                            results = client.get_outputs(task.project_id)
                            
                            if results:
                                result_url = results[0].file_url
                                AIToolsModel.update_by_project_id(
                                    project_id=task.project_id,
                                    result_url=result_url,
                                    status=2  # 处理完成
                                )
                                updated_count += 1
                                logger.info(f"Upscale task {task.project_id} completed successfully")
                        elif status == TaskStatus.FAILED:
                            AIToolsModel.update_by_project_id(
                                project_id=task.project_id,
                                status=-1,  # 处理失败
                                message="高清放大失败"
                            )
                            updated_count += 1
                            # 累计需要补回的算力
                            computing_power = TASK_COMPUTING_POWER[task.type]
                            total_refund_power += computing_power
                            logger.info(f"Upscale task {task.project_id} failed, will refund {computing_power} computing power")
                    else:
                        # Determine if this is a video task (type 2 or 3)
                        is_video = task.type in [2, 3]
                        
                        result = get_ai_task_result(task.project_id, is_video)
                        
                        # Ensure we received a valid response
                        if not result or not isinstance(result, dict):
                            logger.error(f"Failed to get task result for {task.project_id}: invalid response type {type(result).__name__}")
                            continue
                        
                        # Check if API call was successful
                        if result.get("code") != 0:
                            logger.error(f"Failed to get task result for {task.project_id}: {result.get('msg')}")
                            continue
                        
                        data = result.get("data", {})
                        task_status = data.get("status")  # 0-进行中 1-成功 2-失败
                        media_url = data.get("mediaUrl")
                        reason = data.get("reason")
                        
                        if task_status == 1:  # Success
                            AIToolsModel.update_by_project_id(
                                project_id=task.project_id,
                                result_url=media_url,
                                status=2  # 处理完成
                            )
                            updated_count += 1
                            logger.info(f"Task {task.project_id} completed successfully")
                                
                        elif task_status == 2:  # Failed
                            if reason and "We currently do not support uploads of images containing photorealistic people" in reason:
                                reason = "图片包含真人，无法处理"
                            elif reason and "This content may violate our guardrails concerning similarity to third-party content. " in reason:
                                reason = "此内容可能违反了我们关于与第三方内容相似性的规定"
                            # Update status to failed
                            AIToolsModel.update_by_project_id(
                                project_id=task.project_id,
                                status=-1,  # 处理失败
                                message=reason
                            )
                            updated_count += 1
                            # 累计需要补回的算力
                            computing_power = TASK_COMPUTING_POWER[task.type]
                            total_refund_power += computing_power
                            logger.info(f"Task {task.project_id} failed: {reason}, will refund {computing_power} computing power")
                        
                        # If task_status == 0 (in progress), keep status as 1 (processing)
                    
                except Exception as task_error:
                    logger.error(f"Failed to check status for task {task.project_id}: {task_error}")
                    continue
            
            logger.info(f"Checked {len(processing_tasks)} processing tasks, updated {updated_count}")
            
            # 如果有需要补回的算力，统一进行补回
            if total_refund_power > 0 and CHECK_AUTH_TOKEN:
                try:
                    if not auth_token:
                        logger.warning(f"Need to refund {total_refund_power} computing power for user {user_id}, but auth_token is not provided")
                    else:
                        # 生成交易ID
                        transaction_id = str(uuid.uuid4())
                        headers = {'Authorization': f'Bearer {auth_token}'}
                        
                        # 发起请求，增加算力（补回）
                        success, message, response_data = make_perseids_request(
                            endpoint='user/calculate_computing_power',
                            method='POST',
                            headers=headers,
                            data={
                                "computing_power": total_refund_power,
                                "behavior": "increase",
                                "transaction_id": transaction_id
                            }
                        )
                        
                        if success:
                            logger.info(f"Successfully refunded {total_refund_power} computing power for user {user_id}, transaction_id: {transaction_id}")
                        else:
                            logger.error(f"Failed to refund computing power for user {user_id}: {message}")
                    
                except Exception as refund_error:
                    logger.error(f"Failed to refund computing power: {refund_error}")
                    logger.error(traceback.format_exc())
        
        # 查询历史记录
        type_mapping = {
            1: [1, 4, 7],  # 图片编辑 + 图片高清放大
            2: [2, 5],  # AI视频生成 + 高清修复
            3: [3, 6],  # 图片生成视频/图生视频智能体 + 高清修复
            4: [5, 6] # 高清修复
        }

        if type in type_mapping:
            result = AIToolsModel.list_by_user(
                user_id=user_id,
                page=page,
                page_size=page_size,
                order_by='create_time',
                order_direction='DESC',
                type_list=type_mapping[type]
            )
        else:
            result = AIToolsModel.list_by_user(
                user_id=user_id,
                page=page,
                page_size=page_size,
                order_by='create_time',
                order_direction='DESC',
                type=type
            )
        
        return JSONResponse(
            content={
                'success': True,
                'message': '查询成功',
                'data': result
            }
        )
    
    except Exception as e:
        logger.error(f'查询历史记录失败: {str(e)}')
        logger.error(traceback.format_exc())
        return JSONResponse(
            status_code=500,
            content={
                'success': False,
                'message': '服务器错误'
            }
        )


@app.post("/api/ai-script-generate")
async def ai_script_generate(
    image1: UploadFile = File(..., description="第一张图片（必传）"),
    image2: UploadFile = File(None, description="第二张图片（可选）"),
    image3: UploadFile = File(None, description="第三张图片（可选）"),
    image4: UploadFile = File(None, description="第四张图片（可选）"),
    image5: UploadFile = File(None, description="第五张图片（可选）"),
    extra_prompt: str = Form("", description="额外提示词"),
    add_detail: str = Form("否", description="是否添加细节描写"),
    need_narration: str = Form("否", description="是否需要旁白"),
    user_id: int = Form(None, description="User ID"),
    auth_token: str = Form(None, description="Authentication token")
):
    """
    图生视频智能体- 上传1-5张图片，调用百度千帆API生成视频脚本
    """
    try:
        if CHECK_AUTH_TOKEN and auth_token is None:
            raise HTTPException(
                status_code=400, 
                detail="请登录"
            )
        # 保存上传的图片并获取URL
        image_url1 = _save_uploaded_image(image1)
        image_url2 = _save_uploaded_image(image2) if image2 else None
        image_url3 = _save_uploaded_image(image3) if image3 else None
        image_url4 = _save_uploaded_image(image4) if image4 else None
        image_url5 = _save_uploaded_image(image5) if image5 else None
        
        logger.info(f"AI script generation started with images: {image_url1}, {image_url2}, {image_url3}, {image_url4}, {image_url5}")
        
        # 调用百度千帆API
        result = await call_ernie_vl_api(
            image_url1=image_url1,
            image_url2=image_url2,
            image_url3=image_url3,
            image_url4=image_url4,
            image_url5=image_url5,
            prompt="",
            add_detail=add_detail,
            need_narration=need_narration,
            extra_prompt=extra_prompt
        )
        
        # 检查是否有错误
        if "error" in result:
            raise HTTPException(status_code=500, detail=result["error"])
        
        # 解析返回的脚本内容
        try:
            # 百度API返回格式: {"result": "...", "choices": [...]}
            script_content = result.get("result", "")
            if not script_content and "choices" in result:
                script_content = result["choices"][0]["message"]["content"]
            
            logger.info(f"Script content extracted: {script_content[:200]}...")
            
            # 尝试解析JSON脚本
            import re
            json_match = re.search(r'\{.*\}', script_content, re.DOTALL)
            if json_match:
                script_json = json.loads(json_match.group())    
                logger.info(f"Successfully parsed script JSON with {len(script_json.get('ScriptScenes', []))} scenes")
            else:
                script_json = {"raw_content": script_content}
                logger.warning("Could not extract JSON from script content")
                
        except Exception as parse_error:
            logger.warning(f"Failed to parse script JSON: {parse_error}")
            script_json = {"raw_content": script_content if 'script_content' in locals() else str(result)}
        
        return JSONResponse({
            "success": True,
            "script": script_json,
            "raw_response": result,
            "images": {
                "image1": image_url1,
                "image2": image_url2,
                "image3": image_url3,
                "image4": image_url4,
                "image5": image_url5
            }
        })
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"AI script generation failed: {str(e)}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/image-upscale")
async def image_upscale(
    project_id: str = Form(..., description="Project ID of the image to upscale"),
    user_id: int = Form(None, description="User ID"),
    auth_token: str = Form(None, description="Authentication token")
):
    """
    Image upscale endpoint - Upscale an image to higher resolution
    
    Args:
        project_id: The project ID of the existing image record
    
    Returns:
        JSON response with upscale task information
    """
    try:
        logger.info(f"Image upscale request received for project_id: {project_id}")
        
        # Check authentication and computing power
        if CHECK_AUTH_TOKEN and auth_token is None:
            raise HTTPException(
                status_code=400, 
                detail="Authentication token is required"
            )
        
        # Generate transaction ID
        transaction_id = str(uuid.uuid4())
        computing_power = TASK_COMPUTING_POWER[4]
        if CHECK_AUTH_TOKEN:
            headers = {'Authorization': f'Bearer {auth_token}'}
            # Check if computing power is sufficient
            success, message, response_data = make_perseids_request(
                endpoint='user/check_computing_power',
                method='GET',
                headers=headers
            )
            if not success:
                raise HTTPException(
                    status_code=400, 
                    detail=message
                )
            
            user_computing_power = response_data.get('computing_power', 0)
            if user_computing_power < computing_power:
                raise HTTPException(
                    status_code=400, 
                    detail="您的算力不足，无法进行高清放大"
                )
                  
        # 1. Get the original image record from database using project_id
        original_record = AIToolsModel.get_by_project_id(project_id)
        
        if not original_record:
            raise HTTPException(status_code=404, detail="未找到对应的图片记录")
        
        if not original_record.result_url:
            raise HTTPException(status_code=400, detail="原始图片未生成完成，无法进行高清放大")
        result_url = original_record.result_url
        
        logger.info(f"Found original record: type={original_record.type}, result_url={result_url}")
        node_info_list=[
            {
                "nodeId": "8",
                "fieldName": "image",
                "fieldValue": result_url,
                "description": "用户图片"
            }
        ]
        result = run_ai_app_task("1987213919284563970", API_KEY, node_info_list, None)
        if result.get("code") != 0:
            error_msg = result.get("msg", "Unknown error")
            raise RuntimeError(f"Task submission failed: {error_msg}")
        
        task_id = result.get("data", {}).get("taskId")
        if not task_id:
            raise RuntimeError("创建任务失败")
        
        logger.info(f"Upscale task created with task_id: {task_id}")
        if CHECK_AUTH_TOKEN:
            # Deduct computing power
            success, message, response_data = make_perseids_request(
                endpoint='user/calculate_computing_power',
                method='POST',
                headers=headers,
                data={
                    "computing_power": computing_power,
                    "behavior": "deduct",
                    "transaction_id": transaction_id
                }
            )
            if not success:
                raise HTTPException(
                    status_code=400, 
                    detail=message
                )

        # Create new database record for upscale task (type=4)
        new_record_id = AIToolsModel.create(
            prompt=f"高清放大: {original_record.prompt or '原始图片'}",
            user_id=user_id or original_record.user_id,
            type=4,  # 4-图片高清放大
            image_path=result_url,  # Store original image URL
            project_id=task_id,  # Use the new task_id as project_id
            ratio=original_record.ratio,
            transaction_id=transaction_id,  # Store transaction ID
            status=1  # 1-正在处理
        )
        
        logger.info(f"Created upscale record with ID: {new_record_id}, project_id: {task_id}")
        
        return JSONResponse({
            "success": True,
            "message": "图片高清放大任务已创建",
            "data": {
                "project_id": task_id,
                "record_id": new_record_id,
                "status": "processing"
            }
        })
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Image upscale failed: {str(e)}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"图片高清放大失败: {str(e)}")
        
@app.post("/api/video-enhance")
async def video_enhance(
    video: UploadFile = File(None, description="需要修复的视频文件"),
    video_url: str = Form(None, description="视频URL（如果提供则不需要上传文件）"),
    user_id: int = Form(None, description="User ID"),
    auth_token: str = Form(None, description="Authentication token"),
    enhance_type: int = Form(5, description="增强类型：5-视频高清修复，6-从其他任务生成高清视频")
):
    """
    Video enhancement endpoint - Enhance blurry video to higher quality
    Args:
    video: The video file to enhance (optional if video_url provided)
    video_url: Direct video URL to enhance (optional if video file provided)
    user_id: User ID for tracking
    auth_token: Authentication token
    enhance_type: Type for database record (5 for direct upload, 6 for history enhancement)
    Returns:
    JSON response with enhancement task information
    """
    try:
        logger.info(f"Video enhancement request received from user: {user_id}")
        # Check authentication
        if CHECK_AUTH_TOKEN and auth_token is None:
            raise HTTPException(
                status_code=400,
                detail="Authentication token is required"
            )
        # Generate transaction ID
        transaction_id = str(uuid.uuid4())
        computing_power = TASK_COMPUTING_POWER[5]
        if CHECK_AUTH_TOKEN:
            headers = {'Authorization': f'Bearer {auth_token}'}
            # Check if computing power is sufficient
            success, message, response_data = make_perseids_request(
                endpoint='user/check_computing_power',
                method='GET',
                headers=headers
            )
            if not success:
                raise HTTPException(
                    status_code=400,
                    detail=message
                )
            user_computing_power = response_data.get('computing_power', 0)
            if user_computing_power < computing_power:
                raise HTTPException(
                    status_code=400,
                    detail="您的算力不足，无法进行视频修复"
                )
        
        # Determine video URL - either from upload or from parameter
        if video_url:
            # Use provided video URL directly
            final_video_url = video_url
            logger.info(f"Using provided video URL: {video_url}")
        elif video:
            # Save uploaded video and get URL
            file_bytes = await video.read()
            
            # Save video to upload directory
            os.makedirs(UPLOAD_DIR, exist_ok=True)
            video_filename = f"{uuid.uuid4()}_{video.filename}"
            local_video_path = os.path.join(UPLOAD_DIR, video_filename)
            with open(local_video_path, "wb") as f:
                f.write(file_bytes)
            
            # Create accessible URL for frontend
            final_video_url = f"{SERVER_HOST}/upload/{video_filename}"
            logger.info(f"Uploaded video saved to: {final_video_url}")
        else:
            raise HTTPException(
                status_code=400,
                detail="必须提供视频文件或视频URL"
            )
        
        # Submit video enhancement task using runninghub_request module
        try:
            from runninghub_request import run_ai_app_task
            
            node_info_list = [{
                "nodeId": "6",
                "fieldName": "video",
                "fieldValue": final_video_url,
                "description": "video"
            }]
            
            result = run_ai_app_task(
                "1989206149524238338",  # webappId for video enhancement
                "9549532f3c3d435ebe5e1ca78dcac1e8",  # apiKey
                node_info_list,
                None,
            )
            
            if result.get("code") != 0:
                error_msg = result.get("msg", "Unknown error")
                raise RuntimeError(f"Task submission failed: {error_msg}")
            
            project_id = result.get("data", {}).get("taskId")
            if not project_id:
                raise HTTPException(status_code=500, detail="提交任务失败，未返回 taskId")
            
            logger.info(f"Video enhancement task created with project_id: {project_id}")
            
        except Exception as task_error:
            logger.error(f"Failed to submit video enhancement task: {task_error}")
            raise HTTPException(
                status_code=500,
                detail=f"任务提交失败: {str(task_error)}"
            )
        
        # Deduct computing power
        if CHECK_AUTH_TOKEN:
            success, message, response_data = make_perseids_request(
                endpoint='user/calculate_computing_power',
                method='POST',
                headers=headers,
                data={
                    "computing_power": computing_power,
                    "behavior": "deduct",
                    "transaction_id": transaction_id
                }
            )
            if not success:
                logger.error(f"Failed to deduct computing power: {message}")
                # Don't fail the request, just log the error
        
        # Create database record
        if user_id:
            try:
                AIToolsModel.create(
                    prompt="视频高清修复",
                    user_id=user_id,
                    type=enhance_type,  # Use provided enhance_type
                    image_path=final_video_url,
                    project_id=project_id,
                    transaction_id=transaction_id,
                    status=1
                )
            except Exception as db_error:
                logger.error(f"Failed to create database record: {db_error}")
        
        return JSONResponse({
            "project_id": project_id,
            "status": "submitted",
            "video_url": final_video_url
        })
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Video enhancement failed: {str(e)}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"视频高清修复失败: {str(e)}")


@app.post("/api/video-remix")
async def video_remix(
    video_id: str = Form(..., description="视频ID"),
    prompt: str = Form(..., description="重新编辑的提示词"),
    aspect_ratio: str = Form("16:9", description="视频比例: 16:9, 9:16, 1:1"),
    duration: int = Form(15, description="视频时长（秒）"),
    count: int = Form(1, ge=1, le=4, description="生成数量 (1-4)"),
    user_id: int = Form(None, description="用户ID"),
    auth_token: str = Form(None, description="认证令牌")
):
    """
    Sora2 视频重新编辑接口 - 基于现有视频ID进行重新编辑
    
    Args:
        video_id: 要重新编辑的视频ID
        prompt: 重新编辑的提示词
        aspect_ratio: 视频比例 (16:9, 9:16, 1:1)
        duration: 视频时长（秒）
        count: 生成数量 (1-4)
        user_id: 用户ID
        auth_token: 认证令牌
    
    Returns:
        JSON响应，包含任务ID列表
    """
    try:
        logger.info(f"Video remix request received - video_id: {video_id}, prompt: {prompt}")
        
        # 检查认证
        if CHECK_AUTH_TOKEN and auth_token is None:
            raise HTTPException(
                status_code=400,
                detail="请提供认证令牌"
            )
        
        # 计算所需算力（使用视频生成的算力标准）
        computing_power = TASK_COMPUTING_POWER[2]  # 2: AI视频生成
        
        if CHECK_AUTH_TOKEN:
            headers = {'Authorization': f'Bearer {auth_token}'}
            
            # 检查算力是否充足
            success, message, response_data = make_perseids_request(
                endpoint='user/check_computing_power',
                method='GET',
                headers=headers
            )
            if not success:
                raise HTTPException(
                    status_code=400,
                    detail=message
                )
            
            # 检查算力是否足够生成所有视频
            user_computing_power = response_data.get('computing_power', 0)
            total_computing_power = computing_power * count
            if user_computing_power < total_computing_power:
                raise HTTPException(
                    status_code=400,
                    detail=f"您的算力不足，需要 {total_computing_power} 算力，当前仅有 {user_computing_power} 算力"
                )
        
        project_ids = []
        
        # 循环创建多个任务
        for i in range(count):
            try:
                # 为每个任务生成唯一的交易ID
                transaction_id = str(uuid.uuid4())
                
                # 调用remix API
                try:
                    result = create_video_remix(
                        video_id=video_id,
                        prompt=prompt,
                        aspect_ratio=aspect_ratio,
                        duration=duration
                    )
                except Exception as api_error:
                    error_msg = str(api_error)
                    logger.error(f"Task {i+1} API call failed: {error_msg}")
                    # 如果是第一个任务就失败，直接抛出错误
                    if i == 0 and len(project_ids) == 0:
                        raise HTTPException(
                            status_code=500,
                            detail=f"Remix API调用失败: {error_msg}"
                        )
                    continue
                
                logger.info(f"Remix task {i+1} result: {result}")
                
                # 从响应中获取project_id
                project_id = result.get("id")
                if not project_id:
                    logger.error(f"Task {i+1}: No project ID received from remix API. Response: {result}")
                    # 如果是第一个任务就失败，直接抛出错误
                    if i == 0 and len(project_ids) == 0:
                        raise HTTPException(
                            status_code=500,
                            detail=f"API返回格式错误: 未获取到任务ID。响应: {result}"
                        )
                    continue
                
                project_ids.append(project_id)
                
                # 扣除算力
                if CHECK_AUTH_TOKEN:
                    success, message, response_data = make_perseids_request(
                        endpoint='user/calculate_computing_power',
                        method='POST',
                        headers=headers,
                        data={
                            "computing_power": computing_power,
                            "behavior": "deduct",
                            "transaction_id": transaction_id
                        }
                    )
                    if not success:
                        logger.error(f"Task {i+1} computing power deduction failed: {message}")
                        # 继续执行，因为任务已经提交
                
                # 创建数据库记录
                if user_id:
                    try:
                        AIToolsModel.create(
                            prompt=f"Remix: {prompt}",
                            user_id=user_id,
                            type=2,  # 2-AI视频生成
                            ratio=aspect_ratio,
                            duration=duration,
                            project_id=project_id,
                            transaction_id=transaction_id,
                            status=1,  # 1-正在处理
                            message=f"原视频ID: {video_id}"
                        )
                    except Exception as db_error:
                        logger.error(f"Failed to create database record for task {i+1}: {db_error}")
                        # 不因数据库插入失败而中断请求
                
            except Exception as task_error:
                logger.error(f"Task {i+1} failed: {task_error}")
                logger.error(traceback.format_exc())
                continue  # 继续处理下一个任务
        
        if not project_ids:
            raise HTTPException(status_code=500, detail="所有任务都提交失败")
        
        return JSONResponse({
            "success": True,
            "project_ids": project_ids,
            "status": "submitted",
            "video_id": video_id
        })
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Video remix failed: {str(e)}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"视频重新编辑失败: {str(e)}")


@app.post("/api/create-character")
async def api_create_character(
    timestamps: str = Form(..., description="Time range (format: 'start,end', 1-3 seconds)"),
    url: Optional[str] = Form(None, description="Video URL (not for real people)"),
    from_task: Optional[str] = Form(None, description="Task ID (supports real people)"),
    callback_url: Optional[str] = Form(None, description="Callback URL"),
    user_id: Optional[int] = Form(None, description="User ID"),
    auth_token: Optional[str] = Form(None, description="Authentication token")
):
    """
    Create character generation task using SORA API
    Either url or from_task must be provided
    """
    try:
        # 检查认证
        if CHECK_AUTH_TOKEN and auth_token is None:
            raise HTTPException(
                status_code=400,
                detail="请提供认证令牌"
            )
        
        # Validate that either url or from_task is provided
        if not url and not from_task:
            raise HTTPException(
                status_code=400, 
                detail="必须提供 url 或 from_task 其中一个参数"
            )
        
        # Validate timestamps format
        try:
            parts = timestamps.split(",")
            if len(parts) != 2:
                raise ValueError("Invalid format")
            start = float(parts[0])
            end = float(parts[1])
            diff = end - start
            if diff < 1 or diff > 3:
                raise HTTPException(
                    status_code=400, 
                    detail="时间范围差值必须在 1-3 秒之间"
                )
        except ValueError:
            raise HTTPException(
                status_code=400, 
                detail="timestamps 格式错误，应为 '起始秒,结束秒'"
            )
        
        # 计算所需算力
        computing_power = TASK_COMPUTING_POWER[8]  # 8: 创建角色卡
        
        if CHECK_AUTH_TOKEN:
            headers = {'Authorization': f'Bearer {auth_token}'}
            
            # 检查算力是否充足
            success, message, response_data = make_perseids_request(
                endpoint='user/check_computing_power',
                method='GET',
                headers=headers
            )
            if not success:
                raise HTTPException(
                    status_code=400,
                    detail=message
                )
            
            # 检查算力是否足够
            user_computing_power = response_data.get('computing_power', 0)
            if user_computing_power < computing_power:
                raise HTTPException(
                    status_code=400,
                    detail=f"您的算力不足，需要 {computing_power} 算力，当前仅有 {user_computing_power} 算力"
                )
        
        # 生成交易ID
        transaction_id = str(uuid.uuid4())
        
        # Call the character creation API
        response = create_character_task(
            timestamps=timestamps,
            url=url,
            from_task=from_task,
            callback_url=callback_url
        )
        
        logger.info(f"Character creation response: {response}")
        
        # Extract task ID from response
        task_id = response.get("id") or response.get("task_id") or response.get("data", {}).get("id")
        
        if not task_id:
            raise HTTPException(
                status_code=500, 
                detail=f"创建角色任务失败: {response.get('message', '未知错误')}"
            )
        
        # 扣除算力
        if CHECK_AUTH_TOKEN:
            success, message, response_data = make_perseids_request(
                endpoint='user/calculate_computing_power',
                method='POST',
                headers=headers,
                data={
                    "computing_power": computing_power,
                    "behavior": "deduct",
                    "transaction_id": transaction_id
                }
            )
            if not success:
                logger.error(f"Character creation computing power deduction failed: {message}")
        
        # 创建数据库记录
        if user_id:
            try:
                source_info = f"from_task: {from_task}" if from_task else f"url: {url}"
                AIToolsModel.create(
                    prompt=f"创建角色卡 - timestamps: {timestamps}",
                    user_id=user_id,
                    type=8,  # 8-创建角色卡
                    project_id=task_id,
                    transaction_id=transaction_id,
                    status=1,  # 1-正在处理
                    message=source_info
                )
            except Exception as db_error:
                logger.error(f"Failed to create database record for character creation: {db_error}")
        
        return JSONResponse({
            "success": True,
            "task_id": task_id,
            "status": "submitted",
            "message": "角色创建任务已提交"
        })
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Character creation failed: {str(e)}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"创建角色失败: {str(e)}")


@app.get("/api/character-status/{task_id}")
async def api_character_status(
    task_id: str,
    auth_token: Optional[str] = Query(None, description="Auth token for computing power refund")
):
    """
    Check the status of a character generation task
    
    Response format from API:
    {
        "id": "task-id",
        "state": "succeeded/processing/failed",
        "data": {
            "characters": [{"id": "character-username"}]
        },
        "progress": 100,
        "action": "characters"
    }
    """
    try:
        response = get_character_task_result(task_id)
        
        logger.info(f"Character status response: {response}")
        
        # Parse the response
        state = response.get("state", "")
        progress = response.get("progress", 0)
        
        if state == "succeeded":
            # Get characters array from data
            characters = response.get("data", {}).get("characters", [])
            
            # Update database record with character IDs
            try:
                # Build character IDs string like "@id1, @id2"
                character_ids = ", ".join([f"@{c.get('id', '')}" for c in characters if c.get('id')])
                AIToolsModel.update_by_project_id(
                    project_id=task_id,
                    result_url=character_ids,  # Store character IDs in result_url field
                    status=2  # 2-处理完成
                )
            except Exception as db_error:
                logger.error(f"Failed to update character record: {db_error}")
            
            return JSONResponse({
                "status": "SUCCESS",
                "characters": characters,
                "progress": progress,
                "raw_response": response
            })
        elif state in ["failed", "error"]:
            # Update database record as failed
            try:
                task_record = AIToolsModel.get_by_project_id(task_id)
                already_failed = task_record and task_record.status == -1
                
                if not already_failed:
                    AIToolsModel.update_by_project_id(
                        project_id=task_id,
                        status=-1,  # -1-处理失败
                        message=response.get("message", "任务失败")
                    )
                    
                    # Refund computing power
                    if CHECK_AUTH_TOKEN and auth_token and task_record:
                        transaction_id = str(uuid.uuid4())
                        headers = {'Authorization': f'Bearer {auth_token}'}
                        computing_power = TASK_COMPUTING_POWER.get(task_record.type, 0)
                        if computing_power > 0:
                            success, message, _ = make_perseids_request(
                                endpoint='user/calculate_computing_power',
                                method='POST',
                                headers=headers,
                                data={
                                    "computing_power": computing_power,
                                    "behavior": "increase",
                                    "transaction_id": transaction_id
                                }
                            )
                            if success:
                                logger.info(f"Refunded {computing_power} for failed character task {task_id}")
            except Exception as db_error:
                logger.error(f"Failed to update failed character record: {db_error}")
            
            return JSONResponse({
                "status": "FAILED",
                "reason": response.get("message", "任务失败"),
                "raw_response": response
            })
        else:
            # Still processing (state might be "processing" or other)
            return JSONResponse({
                "status": "RUNNING",
                "progress": progress,
                "message": response.get("message", "任务处理中..."),
                "raw_response": response
            })
            
    except Exception as e:
        logger.error(f"Character status check failed: {str(e)}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"查询角色状态失败: {str(e)}")


# ==================== Video Workflow API ====================

class VideoWorkflowCreateRequest(BaseModel):
    name: str
    description: Optional[str] = None
    cover_image: Optional[str] = None
    status: Optional[int] = 1
    workflow_data: Optional[dict] = None
    style: Optional[str] = None
    style_reference_image: Optional[str] = None

class VideoWorkflowUpdateRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    cover_image: Optional[str] = None
    status: Optional[int] = None
    workflow_data: Optional[dict] = None
    style: Optional[str] = None
    style_reference_image: Optional[str] = None
    default_world_id: Optional[int] = None


@app.get('/api/video-workflow/list')
async def get_video_workflow_list(
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(10, ge=1, le=100, description="每页数量"),
    status: Optional[int] = Query(None, description="状态筛选: 0-禁用, 1-启用, 2-草稿"),
    keyword: Optional[str] = Query(None, description="搜索关键词"),
    order_by: str = Query("create_time", description="排序字段"),
    order_direction: str = Query("DESC", description="排序方向: ASC, DESC"),
    auth_token: str = Header(None, alias="Authorization"),
    user_id: Optional[int] = Header(None, alias="X-User-Id")
):
    """
    获取视频工作流列表（分页）
    """
    try:
        user_id = _get_user_id_from_header(user_id)

        result = VideoWorkflowModel.list_by_user(
            user_id=user_id,
            page=page,
            page_size=page_size,
            status=status,
            keyword=keyword,
            order_by=order_by,
            order_direction=order_direction
        )
        
        return JSONResponse({
            "code": 0,
            "message": "success",
            "data": result
        })
    except Exception as e:
        logger.error(f"Failed to get video workflow list: {str(e)}")
        logger.error(traceback.format_exc())
        return JSONResponse(
            status_code=500,
            content={"code": -1, "message": f"获取工作流列表失败: {str(e)}"}
        )


@app.get('/api/video-workflow/{workflow_id}')
async def get_video_workflow(
    workflow_id: int,
    auth_token: str = Header(None, alias="Authorization"),
    user_id: Optional[int] = Header(None, alias="X-User-Id")
):
    """
    获取单个视频工作流详情
    """
    try:
        user_id = _get_user_id_from_header(user_id)
        workflow = VideoWorkflowModel.get_by_id(workflow_id)
        if not workflow:
            return JSONResponse(
                status_code=404,
                content={"code": -1, "message": "工作流不存在"}
            )

        if getattr(workflow, 'user_id', None) != user_id:
            return JSONResponse(
                status_code=403,
                content={"code": -1, "message": "无权限访问该工作流"}
            )
        
        return JSONResponse({
            "code": 0,
            "message": "success",
            "data": workflow.to_dict()
        })
    except Exception as e:
        logger.error(f"Failed to get video workflow {workflow_id}: {str(e)}")
        logger.error(traceback.format_exc())
        return JSONResponse(
            status_code=500,
            content={"code": -1, "message": f"获取工作流详情失败: {str(e)}"}
        )


@app.post('/api/video-workflow/upload')
async def upload_workflow_asset(
    request: Request,
    file: UploadFile = File(..., description="要上传的图片或视频文件"),
    auth_token: str = Header(None, alias="Authorization"),
    user_id: Optional[int] = Header(None, alias="X-User-Id")
):
    """
    上传工作流素材（图片或视频）
    返回可访问的永久URL
    """
    try:
        user_id = _get_user_id_from_header(user_id)
        
        # 验证文件类型
        content_type = file.content_type or ""
        if not (content_type.startswith("image/") or content_type.startswith("video/")):
            return JSONResponse(
                status_code=400,
                content={"code": -1, "message": "仅支持图片或视频文件"}
            )
        
        # 保存文件并获取URL（用户隔离目录）
        request_host = str(request.base_url).rstrip("/")
        file_url = _save_user_asset(file, user_id, category="workflow", base_host=request_host)
        
        return JSONResponse({
            "code": 0,
            "message": "上传成功",
            "data": {"url": file_url}
        })
    except Exception as e:
        logger.error(f"Failed to upload workflow asset: {str(e)}")
        logger.error(traceback.format_exc())
        return JSONResponse(
            status_code=500,
            content={"code": -1, "message": f"上传失败: {str(e)}"}
        )


def _match_location_to_db(location_id: str, locations: list, user_id: int) -> tuple[Optional[int], Optional[str], Optional[str]]:
    """
    匹配场景到数据库
    
    Args:
        location_id: 场景ID (如 "loc_001")
        locations: 大模型返回的locations数组
        user_id: 当前用户ID
    
    Returns:
        (db_location_id, db_location_pic, location_name) 元组，未匹配则返回 (None, None, None)
    """
    # 构建location字典以便快速查找
    location_map = {loc['id']: loc for loc in locations}
    
    # 查找当前location
    current_loc = location_map.get(location_id)
    if not current_loc:
        return (None, None, None)
    
    # 递归向上查找匹配的location_db_id
    def find_matching_db_location(loc):
        if not loc:
            return (None, None, None)
        
        # 检查当前location的location_db_id
        db_id = loc.get('location_db_id')
        if db_id is not None:
            # 验证该location是否属于当前用户
            try:
                db_location = LocationModel.get_by_id(db_id)
                if db_location and db_location.user_id == user_id:
                    # 匹配成功
                    return (db_id, db_location.reference_image, db_location.name)
            except Exception as e:
                logger.warning(f"Failed to get location {db_id}: {e}")
        
        # 如果当前location未匹配，且不是根节点，则查找父节点
        level = loc.get('level', 0)
        if level != 0:
            parent_id = loc.get('parent_id')
            if parent_id:
                parent_loc = location_map.get(parent_id)
                return find_matching_db_location(parent_loc)
        
        # 已到根节点仍未匹配
        return (None, None, None)
    
    return find_matching_db_location(current_loc)


@app.post('/api/parse-script')
async def parse_script(
    request: Request,
    auth_token: str = Header(None, alias="Authorization"),
    user_id: Optional[int] = Header(None, alias="X-User-Id")
):
    """
    解析剧本为分镜组
    """
    try:
        user_id = _get_user_id_from_header(user_id)
        body = await request.json()
        script_content = body.get('script_content', '')
        max_group_duration = body.get('max_group_duration', 15)
        world_id = body.get('world_id')
        
        if not script_content:
            return JSONResponse(
                status_code=400,
                content={"code": -1, "message": "剧本内容不能为空"}
            )
        
        # 导入剧本解析模块
        from llm.script_parser import parse_script_to_shots
        
        # 调用LLM解析剧本
        parsed_data = await parse_script_to_shots(
            script_content=script_content,
            max_group_duration=max_group_duration,
            world_id=world_id,
            model=None,
            temperature=0.7
        )
        
        if not parsed_data:
            return JSONResponse(
                status_code=500,
                content={"code": -1, "message": "剧本解析失败"}
            )
        
        # 为每个shot添加db_location_id、db_location_pic和location_name字段
        locations = parsed_data.get('locations', [])
        shot_groups = parsed_data.get('shot_groups', [])
        
        for group in shot_groups:
            shots = group.get('shots', [])
            for shot in shots:
                location_id = shot.get('location_id')
                if location_id:
                    db_location_id, db_location_pic, location_name = _match_location_to_db(location_id, locations, user_id)
                    shot['db_location_id'] = db_location_id
                    shot['db_location_pic'] = db_location_pic
                    shot['location_name'] = location_name
                else:
                    shot['db_location_id'] = None
                    shot['db_location_pic'] = None
                    shot['location_name'] = None
        
        return JSONResponse({
            "code": 0,
            "message": "解析成功",
            "data": parsed_data
        })
        
    except Exception as e:
        logger.error(f"Failed to parse script: {str(e)}")
        logger.error(traceback.format_exc())
        return JSONResponse(
            status_code=500,
            content={"code": -1, "message": f"剧本解析失败: {str(e)}"}
        )


class ReduceViolationRequest(BaseModel):
    prompt: str

@app.post('/api/reduce-violation')
async def reduce_violation(
    request: ReduceViolationRequest,
    auth_token: str = Header(None, alias="Authorization"),
    user_id: Optional[int] = Header(None, alias="X-User-Id")
):
    """
    降低提示词违规风险
    """
    try:
        from llm.qwen import call_qwen_chat_async
        
        user_prompt = f"""以上提示词中触发了 sora的 This content may violate our content policies. 请你修改以上提示词，避免触发违禁

原提示词：
{request.prompt}

请直接输出修改后的提示词，不要添加任何解释。"""
        
        messages = [
            {"role": "user", "content": user_prompt}
        ]
        
        rewritten_prompt = await call_qwen_chat_async(
            messages=messages,
            temperature=0.7,
            max_tokens=2000
        )
        
        return JSONResponse({
            "code": 0,
            "message": "改写成功",
            "data": {"prompt": rewritten_prompt.strip()}
        })
        
    except Exception as e:
        logger.error(f"Failed to reduce violation: {str(e)}")
        logger.error(traceback.format_exc())
        return JSONResponse(
            status_code=500,
            content={"code": -1, "message": f"改写失败: {str(e)}"}
        )


@app.post('/api/video-workflow/create')
async def create_video_workflow(
    request: VideoWorkflowCreateRequest,
    auth_token: str = Header(None, alias="Authorization"),
    user_id: Optional[int] = Header(None, alias="X-User-Id")
):
    """
    创建视频工作流
    """
    try:
        user_id = _get_user_id_from_header(user_id)
        
        workflow_id = VideoWorkflowModel.create(
            name=request.name,
            user_id=user_id,
            description=request.description,
            cover_image=request.cover_image,
            status=request.status,
            workflow_data=request.workflow_data,
            style=request.style,
            style_reference_image=request.style_reference_image
        )
        
        return JSONResponse({
            "code": 0,
            "message": "创建成功",
            "data": {"id": workflow_id}
        })
    except Exception as e:
        logger.error(f"Failed to create video workflow: {str(e)}")
        logger.error(traceback.format_exc())
        return JSONResponse(
            status_code=500,
            content={"code": -1, "message": f"创建工作流失败: {str(e)}"}
        )


@app.put('/api/video-workflow/{workflow_id}')
async def update_video_workflow(
    workflow_id: int,
    request: VideoWorkflowUpdateRequest,
    auth_token: str = Header(None, alias="Authorization"),
    user_id: Optional[int] = Header(None, alias="X-User-Id")
):
    """
    更新视频工作流
    """
    try:
        user_id = _get_user_id_from_header(user_id)
        # 检查工作流是否存在
        workflow = VideoWorkflowModel.get_by_id(workflow_id)
        if not workflow:
            return JSONResponse(
                status_code=404,
                content={"code": -1, "message": "工作流不存在"}
            )

        if getattr(workflow, 'user_id', None) != user_id:
            return JSONResponse(
                status_code=403,
                content={"code": -1, "message": "无权限修改该工作流"}
            )
        
        # 构建更新字段
        update_fields = {}
        if request.name is not None:
            update_fields['name'] = request.name
        if request.description is not None:
            update_fields['description'] = request.description
        if request.cover_image is not None:
            update_fields['cover_image'] = request.cover_image
        if request.status is not None:
            update_fields['status'] = request.status
        if request.workflow_data is not None:
            update_fields['workflow_data'] = request.workflow_data
        if request.style is not None:
            update_fields['style'] = request.style
        if request.style_reference_image is not None:
            update_fields['style_reference_image'] = request.style_reference_image
        if request.default_world_id is not None:
            update_fields['default_world_id'] = request.default_world_id
        
        if update_fields:
            VideoWorkflowModel.update(workflow_id, **update_fields)
        
        return JSONResponse({
            "code": 0,
            "message": "更新成功"
        })
    except Exception as e:
        logger.error(f"Failed to update video workflow {workflow_id}: {str(e)}")
        logger.error(traceback.format_exc())
        return JSONResponse(
            status_code=500,
            content={"code": -1, "message": f"更新工作流失败: {str(e)}"}
        )


@app.delete('/api/video-workflow/{workflow_id}')
async def delete_video_workflow(
    workflow_id: int,
    auth_token: str = Header(None, alias="Authorization"),
    user_id: Optional[int] = Header(None, alias="X-User-Id")
):
    """
    删除视频工作流
    """
    try:
        user_id = _get_user_id_from_header(user_id)
        # 检查工作流是否存在
        workflow = VideoWorkflowModel.get_by_id(workflow_id)
        if not workflow:
            return JSONResponse(
                status_code=404,
                content={"code": -1, "message": "工作流不存在"}
            )

        if getattr(workflow, 'user_id', None) != user_id:
            return JSONResponse(
                status_code=403,
                content={"code": -1, "message": "无权限删除该工作流"}
            )
        
        VideoWorkflowModel.delete(workflow_id)
        
        return JSONResponse({
            "code": 0,
            "message": "删除成功"
        })
    except Exception as e:
        logger.error(f"Failed to delete video workflow {workflow_id}: {str(e)}")
        logger.error(traceback.format_exc())
        return JSONResponse(
            status_code=500,
            content={"code": -1, "message": f"删除工作流失败: {str(e)}"}
        )


# Serve upload directory for static file access
upload_dir = os.path.join(APP_DIR, "upload")
if not os.path.exists(upload_dir):
    os.makedirs(upload_dir, exist_ok=True)
app.mount("/upload", StaticFiles(directory=upload_dir), name="uploads")

# Serve files directory for static assets (logo, etc.)
files_dir = os.path.join(APP_DIR, "files")
if not os.path.exists(files_dir):
    os.makedirs(files_dir, exist_ok=True)
app.mount("/files", StaticFiles(directory=files_dir), name="files")

# Serve frontend static files
static_dir = os.path.join(APP_DIR, "web")
if not os.path.exists(static_dir):
    os.makedirs(static_dir, exist_ok=True)

@app.get('/api/worlds')
async def get_worlds(
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(100, ge=1, le=100, description="每页数量"),
    auth_token: str = Header(None, alias="Authorization"),
    user_id: int = Header(None, alias="X-User-Id")
):
    """
    获取世界列表
    """
    try:
        user_id = _get_user_id_from_header(user_id)
        result = WorldModel.list_by_user(
            user_id=user_id,
            page=page,
            page_size=page_size
        )
        return JSONResponse(
            status_code=200,
            content={
                'code': 0,
                'message': 'success',
                'data': result
            }
        )
    except Exception as e:
        logger.error(f"Failed to get worlds: {e}")
        return JSONResponse(
            status_code=500,
            content={
                'code': -1,
                'message': str(e),
                'data': None
            }
        )


class CreateWorldRequest(BaseModel):
    name: str
    description: Optional[str] = None


@app.post('/api/worlds')
async def create_world(
    request: CreateWorldRequest,
    auth_token: str = Header(None, alias="Authorization"),
    user_id: int = Header(None, alias="X-User-Id")
):
    """
    创建世界
    """
    try:
        user_id = _get_user_id_from_header(user_id)
        
        if not request.name or not request.name.strip():
            return JSONResponse(
                status_code=400,
                content={
                    'code': -1,
                    'message': '世界名称不能为空',
                    'data': None
                }
            )
        
        world_id = WorldModel.create(
            name=request.name.strip(),
            user_id=user_id,
            description=request.description
        )
        
        world = WorldModel.get_by_id(world_id)
        
        return JSONResponse(
            status_code=200,
            content={
                'code': 0,
                'message': '创建成功',
                'data': world.to_dict() if world else None
            }
        )
    except Exception as e:
        logger.error(f"Failed to create world: {e}")
        return JSONResponse(
            status_code=500,
            content={
                'code': -1,
                'message': str(e),
                'data': None
            }
        )


@app.get('/api/characters')
async def get_characters(
    world_id: int = Query(..., description="世界ID"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(100, ge=1, le=100, description="每页数量"),
    keyword: Optional[str] = Query(None, description="搜索关键词"),
    auth_token: str = Header(None, alias="Authorization"),
    user_id: int = Header(None, alias="X-User-Id")
):
    """
    获取角色列表
    """
    try:
        user_id = _get_user_id_from_header(user_id)
        result = CharacterModel.list_by_world(
            world_id=world_id,
            page=page,
            page_size=page_size,
            keyword=keyword
        )
        return JSONResponse(
            status_code=200,
            content={
                'code': 0,
                'message': 'success',
                'data': result
            }
        )
    except Exception as e:
        logger.error(f"Failed to get characters: {e}")
        return JSONResponse(
            status_code=500,
            content={
                'code': -1,
                'message': str(e),
                'data': None
            }
        )


@app.get('/api/character/search')
async def search_character(
    user_id: int = Query(..., description="用户ID"),
    world_id: int = Query(..., description="世界ID"),
    name: str = Query(..., description="角色名称")
):
    """
    根据角色名称和世界ID搜索角色，返回角色的sora_character字段
    """
    try:
        result = CharacterModel.list_by_world(
            world_id=world_id,
            page=1,
            page_size=1,
            keyword=name
        )
        
        if result and result.get('data') and len(result['data']) > 0:
            character = result['data'][0]
            if character.get('name') == name:
                return JSONResponse(
                    status_code=200,
                    content={
                        'code': 0,
                        'message': 'success',
                        'data': character,
                        'sora_character': character.get('sora_character')
                    }
                )
        
        return JSONResponse(
            status_code=404,
            content={
                'code': -1,
                'message': 'Character not found',
                'data': None
            }
        )
    except Exception as e:
        logger.error(f"Failed to search character: {e}")
        return JSONResponse(
            status_code=500,
            content={
                'code': -1,
                'message': str(e),
                'data': None
            }
        )


@app.post('/api/characters')
async def create_character(
    world_id: int = Form(..., description="世界ID"),
    name: str = Form(..., description="角色名称"),
    age: Optional[str] = Form(None, description="年龄"),
    identity: Optional[str] = Form(None, description="身份/职业"),
    personality: Optional[str] = Form(None, description="性格"),
    behavior: Optional[str] = Form(None, description="行为习惯"),
    other_info: Optional[str] = Form(None, description="其他信息"),
    reference_image: Optional[UploadFile] = File(None, description="参考图"),
    default_voice: Optional[UploadFile] = File(None, description="参考音频"),
    auth_token: str = Header(None, alias="Authorization"),
    user_id: int = Header(None, alias="X-User-Id")
):
    """
    创建角色
    """
    try:
        user_id = _get_user_id_from_header(user_id)
        
        if not name or not name.strip():
            return JSONResponse(
                status_code=400,
                content={
                    'code': -1,
                    'message': '角色名称不能为空',
                    'data': None
                }
            )
        
        # 处理图片上传
        image_path = None
        if reference_image and reference_image.filename:
            file_ext = os.path.splitext(reference_image.filename)[1]
            filename = f"character_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}{file_ext}"
            
            char_upload_dir = os.path.join(upload_dir, "character", "pic")
            os.makedirs(char_upload_dir, exist_ok=True)
            
            file_path = os.path.join(char_upload_dir, filename)
            with open(file_path, "wb") as f:
                content = await reference_image.read()
                f.write(content)
            
            image_path = f"{SERVER_HOST}/upload/character/pic/{filename}"
        
        # 处理音频上传
        voice_path = None
        if default_voice and default_voice.filename:
            file_ext = os.path.splitext(default_voice.filename)[1]
            filename = f"character_voice_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}{file_ext}"
            
            voice_upload_dir = os.path.join(upload_dir, "character", "voice")
            os.makedirs(voice_upload_dir, exist_ok=True)
            
            file_path = os.path.join(voice_upload_dir, filename)
            with open(file_path, "wb") as f:
                content = await default_voice.read()
                f.write(content)
            
            voice_path = f"{SERVER_HOST}/upload/character/voice/{filename}"
        
        character_id = CharacterModel.create(
            world_id=world_id,
            name=name.strip(),
            user_id=user_id,
            age=age.strip() if age else None,
            identity=identity.strip() if identity else None,
            personality=personality.strip() if personality else None,
            behavior=behavior.strip() if behavior else None,
            other_info=other_info.strip() if other_info else None,
            reference_image=image_path,
            default_voice=voice_path
        )
        
        character = CharacterModel.get_by_id(character_id)
        
        return JSONResponse(
            status_code=200,
            content={
                'code': 0,
                'message': '创建成功',
                'data': character.to_dict() if character else None
            }
        )
    except Exception as e:
        logger.error(f"Failed to create character: {e}")
        return JSONResponse(
            status_code=500,
            content={
                'code': -1,
                'message': str(e),
                'data': None
            }
        )


@app.post('/api/characters/update')
async def update_character(
    character_id: int = Form(..., description="角色ID"),
    name: str = Form(..., description="角色名称"),
    age: Optional[str] = Form(None, description="年龄"),
    identity: Optional[str] = Form(None, description="身份/职业"),
    personality: Optional[str] = Form(None, description="性格"),
    behavior: Optional[str] = Form(None, description="行为习惯"),
    other_info: Optional[str] = Form(None, description="其他信息"),
    sora_character: Optional[str] = Form(None, description="Sora角色卡ID"),
    reference_image: Optional[UploadFile] = File(None, description="参考图"),
    default_voice: Optional[UploadFile] = File(None, description="参考音频"),
    auth_token: str = Header(None, alias="Authorization"),
    user_id: int = Header(None, alias="X-User-Id")
):
    """
    更新角色
    """
    try:
        user_id = _get_user_id_from_header(user_id)
        
        if not name or not name.strip():
            return JSONResponse(
                status_code=400,
                content={
                    'code': -1,
                    'message': '角色名称不能为空',
                    'data': None
                }
            )
        
        # 处理图片上传
        image_path = None
        if reference_image and reference_image.filename:
            file_ext = os.path.splitext(reference_image.filename)[1]
            filename = f"character_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}{file_ext}"
            
            char_upload_dir = os.path.join(upload_dir, "character", "pic")
            os.makedirs(char_upload_dir, exist_ok=True)
            
            file_path = os.path.join(char_upload_dir, filename)
            with open(file_path, "wb") as f:
                content = await reference_image.read()
                f.write(content)
            
            image_path = f"{SERVER_HOST}/upload/character/pic/{filename}"
        
        # 处理音频上传
        voice_path = None
        if default_voice and default_voice.filename:
            file_ext = os.path.splitext(default_voice.filename)[1]
            filename = f"character_voice_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}{file_ext}"
            
            voice_upload_dir = os.path.join(upload_dir, "character", "voice")
            os.makedirs(voice_upload_dir, exist_ok=True)
            
            file_path = os.path.join(voice_upload_dir, filename)
            with open(file_path, "wb") as f:
                content = await default_voice.read()
                f.write(content)
            
            voice_path = f"{SERVER_HOST}/upload/character/voice/{filename}"
        
        # 构建更新字段
        update_fields = {
            'name': name.strip(),
            'age': age.strip() if age else None,
            'identity': identity.strip() if identity else None,
            'personality': personality.strip() if personality else None,
            'behavior': behavior.strip() if behavior else None,
            'other_info': other_info.strip() if other_info else None,
            'sora_character': sora_character.strip() if sora_character else None,
        }
        
        if image_path:
            update_fields['reference_image'] = image_path
        if voice_path:
            update_fields['default_voice'] = voice_path
        
        CharacterModel.update(character_id, **update_fields)
        
        character = CharacterModel.get_by_id(character_id)
        
        return JSONResponse(
            status_code=200,
            content={
                'code': 0,
                'message': '更新成功',
                'data': character.to_dict() if character else None
            }
        )
    except Exception as e:
        logger.error(f"Failed to update character: {e}")
        return JSONResponse(
            status_code=500,
            content={
                'code': -1,
                'message': str(e),
                'data': None
            }
        )


@app.get('/api/locations')
async def get_locations(
    world_id: int = Query(..., description="世界ID"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(100, ge=1, le=100, description="每页数量"),
    keyword: Optional[str] = Query(None, description="搜索关键词"),
    auth_token: str = Header(None, alias="Authorization"),
    user_id: int = Header(None, alias="X-User-Id")
):
    """
    获取场景列表
    """
    try:
        user_id = _get_user_id_from_header(user_id)
        result = LocationModel.list_by_world(
            world_id=world_id,
            page=page,
            page_size=page_size,
            keyword=keyword
        )
        return JSONResponse(
            status_code=200,
            content={
                'code': 0,
                'message': 'success',
                'data': result
            }
        )
    except Exception as e:
        logger.error(f"Failed to get locations: {e}")
        return JSONResponse(
            status_code=500,
            content={
                'code': -1,
                'message': str(e),
                'data': None
            }
        )


@app.get('/api/location/{location_id}')
async def get_location_by_id(
    location_id: int,
    auth_token: str = Header(None, alias="Authorization"),
    user_id: int = Header(None, alias="X-User-Id")
):
    """
    根据ID获取场景信息
    """
    try:
        user_id = _get_user_id_from_header(user_id)
        location = LocationModel.get_by_id(location_id)
        
        if not location:
            return JSONResponse(
                status_code=404,
                content={'code': -1, 'message': '场景不存在'}
            )
        
        # 验证权限
        if location.user_id != user_id:
            return JSONResponse(
                status_code=403,
                content={'code': -1, 'message': '无权访问此场景'}
            )
        
        return JSONResponse(
            status_code=200,
            content={
                'code': 0,
                'message': 'success',
                'data': location.to_dict()
            }
        )
    except Exception as e:
        logger.error(f"Failed to get location {location_id}: {e}")
        return JSONResponse(
            status_code=500,
            content={'code': -1, 'message': f'获取场景失败: {str(e)}'}
        )


@app.get('/api/locations/tree')
async def get_locations_tree(
    world_id: int = Query(..., description="世界ID"),
    limit: Optional[int] = Query(None, ge=1, description="最大返回数量，优先保留顶层场景"),
    auth_token: str = Header(None, alias="Authorization"),
    user_id: int = Header(None, alias="X-User-Id")
):
    """
    获取场景树形结构
    返回嵌套的场景树，支持 limit 参数控制返回数量
    当指定 limit 时，优先保留顶层场景（parent_id 为 null），然后是一级子场景，以此类推
    """
    try:
        user_id = _get_user_id_from_header(user_id)
        tree = LocationModel.get_tree_by_world(world_id=world_id, limit=limit)
        return JSONResponse(
            status_code=200,
            content={
                'code': 0,
                'message': 'success',
                'data': tree
            }
        )
    except Exception as e:
        logger.error(f"Failed to get location tree: {e}")
        return JSONResponse(
            status_code=500,
            content={
                'code': -1,
                'message': str(e),
                'data': None
            }
        )


@app.post('/api/locations')
async def create_location(
    world_id: int = Form(..., description="世界ID"),
    name: str = Form(..., description="场景名称"),
    parent_id: Optional[int] = Form(None, description="父场景ID，为空表示顶层场景"),
    description: Optional[str] = Form(None, description="场景描述"),
    reference_image: Optional[UploadFile] = File(None, description="参考图"),
    auth_token: str = Header(None, alias="Authorization"),
    user_id: int = Header(None, alias="X-User-Id")
):
    """
    创建场景
    支持嵌套场景：通过 parent_id 指定父场景，为 null 表示顶层场景
    """
    try:
        user_id = _get_user_id_from_header(user_id)
        
        if not name or not name.strip():
            return JSONResponse(
                status_code=400,
                content={
                    'code': -1,
                    'message': '场景名称不能为空',
                    'data': None
                }
            )
        
        # 处理图片上传
        image_path = None
        if reference_image and reference_image.filename:
            file_ext = os.path.splitext(reference_image.filename)[1]
            filename = f"location_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}{file_ext}"
            
            loc_upload_dir = os.path.join(upload_dir, "location", "pic")
            os.makedirs(loc_upload_dir, exist_ok=True)
            
            file_path = os.path.join(loc_upload_dir, filename)
            with open(file_path, "wb") as f:
                content = await reference_image.read()
                f.write(content)
            
            image_path = f"{SERVER_HOST}/upload/location/pic/{filename}"
        
        location_id = LocationModel.create(
            world_id=world_id,
            name=name.strip(),
            user_id=user_id,
            parent_id=parent_id,
            description=description.strip() if description else None,
            reference_image=image_path
        )
        
        location = LocationModel.get_by_id(location_id)
        
        return JSONResponse(
            status_code=200,
            content={
                'code': 0,
                'message': '创建成功',
                'data': location.to_dict() if location else None
            }
        )
    except Exception as e:
        logger.error(f"Failed to create location: {e}")
        return JSONResponse(
            status_code=500,
            content={
                'code': -1,
                'message': str(e),
                'data': None
            }
        )


@app.put('/api/locations/{location_id}')
async def update_location(
    location_id: int,
    name: Optional[str] = Form(None, description="场景名称"),
    parent_id: Optional[int] = Form(None, description="父场景ID"),
    description: Optional[str] = Form(None, description="场景描述"),
    reference_image: Optional[UploadFile] = File(None, description="参考图"),
    auth_token: str = Header(None, alias="Authorization"),
    user_id: int = Header(None, alias="X-User-Id")
):
    """
    更新场景信息
    """
    try:
        user_id = _get_user_id_from_header(user_id)
        
        # 检查场景是否存在
        location = LocationModel.get_by_id(location_id)
        if not location:
            return JSONResponse(
                status_code=404,
                content={
                    'code': -1,
                    'message': '场景不存在',
                    'data': None
                }
            )
        
        # 准备更新数据
        update_data = {}
        
        if name is not None and name.strip():
            update_data['name'] = name.strip()
        
        if parent_id is not None:
            update_data['parent_id'] = parent_id
        
        if description is not None:
            update_data['description'] = description.strip() if description else None
        
        # 处理图片上传
        if reference_image and reference_image.filename:
            file_ext = os.path.splitext(reference_image.filename)[1]
            filename = f"location_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}{file_ext}"
            
            loc_upload_dir = os.path.join(upload_dir, "location", "pic")
            os.makedirs(loc_upload_dir, exist_ok=True)
            
            file_path = os.path.join(loc_upload_dir, filename)
            with open(file_path, "wb") as f:
                content = await reference_image.read()
                f.write(content)
            
            update_data['reference_image'] = f"{SERVER_HOST}/upload/location/pic/{filename}"
        
        # 更新场景
        if update_data:
            LocationModel.update(location_id, **update_data)
        
        # 获取更新后的场景
        updated_location = LocationModel.get_by_id(location_id)
        
        return JSONResponse(
            status_code=200,
            content={
                'code': 0,
                'message': '更新成功',
                'data': updated_location.to_dict() if updated_location else None
            }
        )
    except Exception as e:
        logger.error(f"Failed to update location: {e}")
        return JSONResponse(
            status_code=500,
            content={
                'code': -1,
                'message': str(e),
                'data': None
            }
        )


class ExportTimelineDraftRequest(BaseModel):
    draft_path: str
    timeline_clips: List[dict]
    workflow_name: Optional[str] = "未命名工作流"
    request_origin: Optional[str] = None


@app.post('/api/export_timeline_draft')
async def export_timeline_draft(
    payload: ExportTimelineDraftRequest,
    http_request: Request,
    user_id: int = Header(None, alias="X-User-Id")
):
    """
    导出时间轴到剪影草稿
    """
    try:
        user_id = _get_user_id_from_header(user_id)
        
        if not payload.timeline_clips or len(payload.timeline_clips) == 0:
            return JSONResponse(
                status_code=400,
                content={
                    'success': False,
                    'error': '时间轴为空，无法导出'
                }
            )
        
        # 导入jianying库
        import sys
        jianying_path = os.path.join(APP_DIR, 'jianying', 'src')
        if jianying_path not in sys.path:
            sys.path.insert(0, jianying_path)
        
        from core import JianyingMultiTrackLibrary
        from draft_generator import DraftGenerator
        from utils import seconds_to_microseconds
        
        # 生成唯一的草稿名称（使用工作流名称作为前缀）
        # 清理工作流名称，移除不适合文件名的字符
        safe_workflow_name = "".join(c for c in payload.workflow_name if c.isalnum() or c in (' ', '-', '_')).strip()
        safe_workflow_name = safe_workflow_name.replace(' ', '_') or 'workflow'
        draft_name = f"{safe_workflow_name}_{uuid.uuid4().hex[:8]}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        # 创建临时目录（使用/tmp目录，按日期分组）
        date_folder = datetime.now().strftime('%Y-%m-%d')
        base_temp_dir = os.path.join('/tmp', 'jianying_export', date_folder, draft_name)
        temp_download_dir = os.path.join(base_temp_dir, 'downloads')
        local_draft_parent = os.path.join(base_temp_dir, 'draft_output')
        os.makedirs(temp_download_dir, exist_ok=True)
        os.makedirs(local_draft_parent, exist_ok=True)
        
        logger.info(f"开始导出草稿: {draft_name}")
        logger.info(f"临时基础目录: {base_temp_dir}")
        logger.info(f"临时下载目录: {temp_download_dir}")
        logger.info(f"草稿路径前缀: {payload.draft_path}")

        request_origin = payload.request_origin or http_request.headers.get("Origin") or http_request.headers.get("Referer")
        
        # 下载所有视频
        downloaded_files = []
        asset_cache = {}
        for idx, clip in enumerate(payload.timeline_clips):
            video_url = clip.get('url')
            video_name = clip.get('name', f'video_{idx}')
            
            if not video_url:
                logger.warning(f"跳过没有URL的片段: {video_name}")
                continue
            
            try:
                asset_key = None
                local_asset_path = _get_local_upload_file(video_url, request_origin)
                if local_asset_path:
                    asset_key = f"local::{os.path.abspath(local_asset_path)}"
                elif video_url:
                    asset_key = f"url::{video_url}"

                if asset_key and asset_key in asset_cache:
                    file_path = asset_cache[asset_key]
                    safe_name = os.path.basename(file_path)
                    logger.info(f"复用已下载素材: {video_name} -> {safe_name}")
                else:
                    if local_asset_path:
                        file_ext = os.path.splitext(local_asset_path)[1] or '.mp4'
                        safe_name = f"video_{idx:03d}_{uuid.uuid4().hex[:8]}{file_ext}"
                        file_path = os.path.join(temp_download_dir, safe_name)
                        shutil.copy2(local_asset_path, file_path)
                        logger.info(f"已复用本地上传文件: {local_asset_path} -> {file_path}")
                    else:
                        logger.info(f"正在下载视频 {idx + 1}/{len(payload.timeline_clips)}: {video_name}")
                        
                        # 下载视频
                        response = requests.get(video_url, stream=True, timeout=300)
                        response.raise_for_status()
                        
                        # 确定文件扩展名
                        file_ext = '.mp4'
                        if 'content-type' in response.headers:
                            content_type = response.headers['content-type']
                            if 'video/quicktime' in content_type or video_url.endswith('.mov'):
                                file_ext = '.mov'
                            elif 'video/x-msvideo' in content_type or video_url.endswith('.avi'):
                                file_ext = '.avi'
                        
                        # 保存文件
                        safe_name = f"video_{idx:03d}_{uuid.uuid4().hex[:8]}{file_ext}"
                        file_path = os.path.join(temp_download_dir, safe_name)
                        
                        with open(file_path, 'wb') as f:
                            for chunk in response.iter_content(chunk_size=8192):
                                if chunk:
                                    f.write(chunk)
                        
                        logger.info(f"视频下载完成: {safe_name}")
                    
                    if asset_key:
                        asset_cache[asset_key] = file_path
                
                downloaded_files.append({
                    'file_path': file_path,
                    'clip': clip,
                    'filename': safe_name
                })
                
            except Exception as e:
                logger.error(f"处理视频失败 {video_name}: {e}")
                return JSONResponse(
                    status_code=500,
                    content={
                        'success': False,
                        'error': f'处理视频失败: {video_name} - {str(e)}'
                    }
                )
        
        if not downloaded_files:
            return JSONResponse(
                status_code=400,
                content={
                    'success': False,
                    'error': '没有成功下载任何视频'
                }
            )
        
        # 创建剪影草稿
        logger.info("开始生成剪影草稿...")
        
        # 创建库实例
        library = JianyingMultiTrackLibrary(
            draft_name=draft_name,
            output_dir=local_draft_parent,
            material_path_prefix=payload.draft_path
        )
        
        # 创建视频轨道
        video_track = library.create_video_track("主轨道")
        
        # 添加视频片段到轨道
        current_time = 0
        for item in downloaded_files:
            clip = item['clip']
            file_path = item['file_path']
            
            # 获取视频时长
            duration = library.get_media_duration(file_path)
            
            # 计算剪切后的时长
            start_time = clip.get('startTime', 0)
            end_time = clip.get('endTime', clip.get('duration', 0))
            
            # 转换为微秒
            source_start = seconds_to_microseconds(start_time)
            clip_duration = seconds_to_microseconds(end_time - start_time)
            
            # 添加到轨道
            library.add_video_to_track(
                track_id=video_track,
                file_path=file_path,
                start_time=seconds_to_microseconds(current_time),
                duration=clip_duration,
                source_start=source_start
            )
            
            current_time += (end_time - start_time)
        
        # 生成草稿
        generator = DraftGenerator(library)
        draft_path = generator.generate_draft(
            copy_media_files=True,
            media_source_dir=temp_download_dir
        )
        
        logger.info(f"草稿生成成功: {draft_path}")
        
        # 创建导入指南HTML文件（从模板读取）
        template_path = os.path.join(APP_DIR, 'templates', 'jianying_import_guide.html')
        with open(template_path, 'r', encoding='utf-8') as f:
            html_guide_content = f.read()
        
        # 将HTML文件写入草稿的父目录（与草稿文件夹同级）
        html_guide_path = os.path.join(os.path.dirname(draft_path), "如何导入到剪影.html")
        with open(html_guide_path, 'w', encoding='utf-8') as f:
            f.write(html_guide_content)
        logger.info(f"已创建导入指南: {html_guide_path}")
        
        # 创建草稿压缩包
        logger.info("开始创建草稿压缩包...")
        # 使用日期分组目录
        draft_upload_dir = os.path.join(UPLOAD_DIR, 'draft', date_folder)
        os.makedirs(draft_upload_dir, exist_ok=True)
        
        zip_filename = f"{draft_name}.zip"
        zip_path = os.path.join(draft_upload_dir, zip_filename)
        
        import zipfile
        
        # 手动创建压缩包，包含HTML指南和草稿文件夹
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            # 添加HTML指南到压缩包根目录
            zipf.write(html_guide_path, "如何导入到剪影.html")
            
            # 添加草稿文件夹及其所有内容
            for root, dirs, files in os.walk(draft_path):
                for file in files:
                    file_path = os.path.join(root, file)
                    arcname = os.path.join(os.path.basename(draft_path), os.path.relpath(file_path, draft_path))
                    zipf.write(file_path, arcname)
        
        logger.info(f"压缩包已创建: {zip_path}")
        
        # 生成下载URL（包含日期路径）
        download_url = f"{SERVER_HOST}/upload/draft/{date_folder}/{zip_filename}"
        logger.info(f"下载地址: {download_url}")
        
        # 清理临时文件
        try:
            shutil.rmtree(temp_download_dir)
            logger.info("临时下载文件已清理")
        except Exception as e:
            logger.warning(f"清理临时文件失败: {e}")
        
        # 清理生成的草稿目录（因为已经打包）
        try:
            shutil.rmtree(draft_path)
            logger.info("草稿临时目录已清理")
        except Exception as e:
            logger.warning(f"清理草稿目录失败: {e}")
        
        return JSONResponse(
            status_code=200,
            content={
                'success': True,
                'draft_name': draft_name,
                'draft_path': draft_path,
                'video_count': len(downloaded_files),
                'download_url': download_url,
                'zip_filename': zip_filename
            }
        )
        
    except Exception as e:
        logger.error(f"导出草稿失败: {e}")
        logger.error(traceback.format_exc())
        return JSONResponse(
            status_code=500,
            content={
                'success': False,
                'error': str(e)
            }
        )


@app.get("/video-workflow-list")
async def serve_video_workflow_list():
    file_path = os.path.join(static_dir, "video_workflow_list.html")
    if os.path.isfile(file_path):
        return FileResponse(file_path)
    raise HTTPException(status_code=404, detail="Video workflow list page not found")

@app.get("/video-workflow")
async def serve_video_workflow():
    file_path = os.path.join(static_dir, "video_workflow.html")
    if os.path.isfile(file_path):
        return FileResponse(file_path)
    raise HTTPException(status_code=404, detail="Video workflow page not found")

# Catch-all route for SPA - returns index.html for all unmatched routes
# This supports Vue Router history mode
@app.get("/{full_path:path}")
async def serve_spa(full_path: str):
    """
    Serve index.html for all routes to support Vue Router history mode.
    This allows refreshing on routes like /nanobanana-edit, /ai-video-gen, etc.
    
    First tries to serve a static file if it exists, otherwise returns index.html.
    """
    # Skip API routes - let them be handled by their specific handlers
    if full_path.startswith("api/"):
        raise HTTPException(status_code=404, detail="API endpoint not found")
    
    # Try to serve static file first
    file_path = os.path.join(static_dir, full_path)
    if os.path.isfile(file_path):
        return FileResponse(file_path)
    
    # Otherwise return index.html for SPA routing
    index_path = os.path.join(static_dir, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    
    raise HTTPException(status_code=404, detail="Frontend not found")


if __name__ == "__main__":
    # Check if HTTPS is enabled
    https_config = config["server"].get("https", {})
    if https_config.get("enabled", False):
        # For HTTPS, prefer https_port, fallback to port, then default
        port = config["server"].get("https_port") or config["server"].get("port")
    else:
        # For HTTP, use port or default
        port = config["server"].get("port")
    
    if https_config.get("enabled", False):
        # HTTPS configuration
        ssl_keyfile = os.path.join(APP_DIR, https_config["keyfile"])
        ssl_certfile = os.path.join(APP_DIR, https_config["certfile"])
        
        # Verify certificate files exist
        if not os.path.exists(ssl_keyfile):
            raise FileNotFoundError(f"SSL key file not found: {ssl_keyfile}")
        if not os.path.exists(ssl_certfile):
            raise FileNotFoundError(f"SSL certificate file not found: {ssl_certfile}")
        
        logger.info(f"Starting HTTPS server on port {port}")
        logger.info(f"Using SSL cert: {ssl_certfile}")
        logger.info(f"Using SSL key: {ssl_keyfile}")
        
        uvicorn.run(
            "server:app", 
            host="0.0.0.0", 
            port=port, 
            reload=False,
            ssl_keyfile=ssl_keyfile,
            ssl_certfile=ssl_certfile
        )
    else:
        # HTTP configuration
        logger.info(f"Starting HTTP server on port {port}")
        uvicorn.run("server:app", host="0.0.0.0", port=port, reload=False)
