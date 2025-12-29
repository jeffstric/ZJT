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
from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel
from runninghub_request import RunningHubClient, create_image_edit_nodes, TaskStatus, run_image_edit_task, run_ai_app_task_sync, run_ai_app_task
from config_util import get_config_path, is_dev_environment
from perseids_client import make_perseids_request, call_external_auth_server, get_device_uuid
from model import AIToolsModel, TasksModel, AIAudioModel, PaymentOrdersModel
import uuid
from duomi_api_requset import create_video_remix, create_character, get_character_task_result
from PIL import Image
from baidu import call_ernie_vl_api
from task.scheduler import init_scheduler
from config.constant import TASK_COMPUTING_POWER, TASK_TYPE_GENERATE_VIDEO, TASK_TYPE_GENERATE_AUDIO, RECHARGE_PACKAGES, AUTHENTICATION_ID
from utils.wechat_pay_util import WechatPayUtil

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

# 初始化微信支付工具
wechat_pay_config = config.get("pay", {}).get("wxpay", {})
wechat_pay_util = WechatPayUtil(
    app_id=wechat_pay_config.get("appId"),
    mch_id=wechat_pay_config.get("mchId"),
    api_key=wechat_pay_config.get("api_key"),
    APIv3_key=wechat_pay_config.get("APIv3_key")
)

# Default ComfyUI server address; can be overridden by request field
DEFAULT_COMFYUI_SERVER = os.environ.get("COMFYUI_SERVER", "http://127.0.0.1:8188/")

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


def _save_uploaded_audio(upload_file: UploadFile) -> str:
    """
    Save uploaded audio to /nas/comfyui_upload/tts/tmp_ref_audio directory and return the file path
    """
    # Ensure audio upload directory exists
    audio_dir = "/nas/comfyui_upload/tts/tmp_ref_audio"
    os.makedirs(audio_dir, exist_ok=True)
    
    # Generate unique filename
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    unique_id = str(uuid.uuid4())[:8]
    file_extension = os.path.splitext(upload_file.filename or "audio.wav")[1]
    filename = f"ref_audio_{timestamp}_{unique_id}{file_extension}"
    
    # Save file
    file_path = os.path.join(audio_dir, filename)
    with open(file_path, "wb") as f:
        content = upload_file.file.read()
        f.write(content)
    
    # Return relative path from upload directory
    return file_path

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
    model: str = Form("gemini-2.5-pro-image-preview", description="Model type: gemini-2.5-pro-image-preview, gemini-3-pro-image-preview")
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

        # Handle multiple images
        image_urls = [_save_uploaded_image(img) for img in image]
        
        # Submit tasks according to generation count
        project_ids = []
        for _ in range(count):
            #用uuid生成交易id
            transaction_id = str(uuid.uuid4())

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
                    id = AIToolsModel.create(
                        prompt=prompt,
                        user_id=user_id,
                        type=image_edit_type,  # 1-图片编辑
                        image_path=image_path_str,
                        ratio=ratio,
                        transaction_id=transaction_id,
                        status=0
                    )
                    TasksModel.create(
                        task_type=TASK_TYPE_GENERATE_VIDEO,
                        task_id=id,
                        status=0
                    )
                    project_ids.append(id)
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
            task_record = AIToolsModel.get_by_id(pid)
            
            if task_record and task_record.create_time:
                # Calculate time difference in seconds
                from datetime import datetime
                current_time = datetime.now()
                time_diff = current_time - task_record.create_time
                task_cost_time = int(time_diff.total_seconds())
            status = task_record.status
            reason = task_record.message
            status_str = "RUNNING"
            results_payload = []
            reason_payload = None

            # Update database based on status
            if status == 2:  # Success
                status_str = "SUCCESS"
                media_url = task_record.result_url
                if media_url:
                    results_payload = [{
                        "file_url": media_url,
                        "task_cost_time": task_cost_time
                    }]

            elif status == -1:  # Failed
                status_str = "FAILED"
                reason_payload = reason

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
                    id = AIToolsModel.create(
                        prompt=prompt,
                        user_id=user_id,
                        type=2,  # 2-AI视频生成
                        ratio=ratio,
                        transaction_id=transaction_id,
                        duration=duration_seconds,
                        status=0
                    )
                    TasksModel.create(
                        task_type=TASK_TYPE_GENERATE_VIDEO,
                        task_id=id,
                        status=0
                    )
                    project_ids.append(id)
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
                        id = AIToolsModel.create(
                            prompt=prompt,
                            user_id=user_id,
                            type=3,  # 3-图片生成视频
                            image_path=image_url,
                            ratio=ratio,
                            duration=duration_seconds,
                            transaction_id=transaction_id,
                            status=0
                        )
                        TasksModel.create(
                            task_type=TASK_TYPE_GENERATE_VIDEO,
                            task_id=id,
                            status=0
                        )
                        project_ids.append(id)
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
        response = create_character(
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


@app.post("/api/audio-generate")
async def audio_generate(
    text: str = Form(..., description="Text to generate audio from"),
    ref_audio: Optional[UploadFile] = File(None, description="Reference audio file for voice cloning"),
    emo_ref_audio: Optional[UploadFile] = File(None, description="Emotion reference audio file"),
    ref_audio_url: Optional[str] = Form(None, description="Reference audio URL (alternative to file upload)"),
    emo_ref_audio_url: Optional[str] = Form(None, description="Emotion reference audio URL (alternative to file upload)"),
    emo_text: Optional[str] = Form(None, description="Emotion description text"),
    emo_weight: Optional[float] = Form(None, description="Emotion weight (0.0-1.6)"),
    emo_vec: Optional[str] = Form(None, description="Emotion vector control"),
    emo_control_method: Optional[int] = Form(0, description="Emotion control method: 0-same as voice ref, 1-use emotion ref, 2-use emotion vector, 3-use emotion text"),
    user_id: int = Form(None, description="User ID"),
    auth_token: str = Form(None, description="Authentication token")
):
    """
    Submit audio generation task
    Supports voice cloning with reference audio and emotion control
    """
    try:
        if CHECK_AUTH_TOKEN and auth_token is None:
            raise HTTPException(
                status_code=400,
                detail="Authentication token is required"
            )
        
        # Calculate computing power cost
        ref_path = None
        if ref_audio:
            ref_path = _save_uploaded_audio(ref_audio)  # Reuse upload function for audio
        elif ref_audio_url:
            ref_path = ref_audio_url
        
        # Handle emotion reference audio upload
        emo_ref_path = None
        if emo_ref_audio:
            emo_ref_path = _save_uploaded_audio(emo_ref_audio)
        elif emo_ref_audio_url:
            emo_ref_path = emo_ref_audio_url
        
        # Generate transaction ID
        transaction_id = str(uuid.uuid4())
        
        # Create database record for audio generation task
        audio_id = None
        if user_id:
            try:
                audio_id = AIAudioModel.create(
                    text=text,
                    user_id=user_id,
                    ref_path=ref_path,
                    emo_ref_path=emo_ref_path,
                    transaction_id=transaction_id,
                    emo_text=emo_text,
                    emo_weight=emo_weight,
                    emo_vec=emo_vec,
                    emo_control_method=emo_control_method,
                    status=0
                )
                TasksModel.create(
                    task_type=TASK_TYPE_GENERATE_AUDIO,
                    task_id=audio_id,
                    status=0
                )
            except Exception as db_error:
                logger.error(f"Failed to create audio database record: {db_error}")
                raise HTTPException(status_code=500, detail=f"创建音频记录失败: {str(db_error)}")
        
        return JSONResponse({
            "audio_id": audio_id,
            "status": "submitted",
            "message": "Successfully submitted audio generation task"
        })
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Audio generation failed: {str(e)}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"音频生成失败: {str(e)}")


@app.get("/api/audio-status/{audio_id}")
async def audio_status(audio_id: int):
    """
    查询音频生成任务状态。
    
    根据 ai_audio 表记录判断：
    - status == 2 且 result_url 有值：SUCCESS
    - status == -1：FAILED
    - 其他：RUNNING
    """
    try:
        record = AIAudioModel.get_by_id(audio_id)
        if not record:
            raise HTTPException(status_code=404, detail=f"未找到音频任务 {audio_id}")
        
        if record.status == 2 and record.result_url:
            return JSONResponse({
                "audio_id": record.id,
                "status": "SUCCESS",
                "result_url": record.result_url,
                "message": record.message or "音频生成成功"
            })
        elif record.status == -1:
            return JSONResponse({
                "audio_id": record.id,
                "status": "FAILED",
                "reason": record.message or "音频生成失败"
            })
        else:
            return JSONResponse({
                "audio_id": record.id,
                "status": "RUNNING",
                "message": record.message or "音频生成中，请稍候"
            })
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Audio status check failed: {str(e)}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"查询音频状态失败: {str(e)}")


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


class RechargePackage(BaseModel):
    """算力充值套餐"""
    package_id: int
    computing_power: int
    price: float
    description: Optional[str] = None


class WechatPayRequest(BaseModel):
    """微信支付请求"""
    package_id: int
    user_id: int
    auth_token: str
    is_wechat_browser: bool = False
    openid: Optional[str] = None
    payment_ip: Optional[str] = None


@app.get("/api/wechat/get-openid")
async def get_wechat_openid(code: str):
    """
    通过微信授权code获取用户openid
    
    Args:
        code: 微信授权返回的code
    
    Returns:
        包含openid的响应
    """
    try:
        import requests
        
        # 从配置文件读取微信配置
        wechat_config = config.get("pay", {}).get("wxpay", {})
        app_id = wechat_config.get("appId")
        app_secret = wechat_config.get("appSecret")
        
        if not app_id or not app_secret:
            raise HTTPException(status_code=500, detail="微信配置不完整")
        
        # 调用微信接口获取openid
        url = "https://api.weixin.qq.com/sns/oauth2/access_token"
        params = {
            "appid": app_id,
            "secret": app_secret,
            "code": code,
            "grant_type": "authorization_code"
        }
        
        response = requests.get(url, params=params)
        result = response.json()
        
        if "openid" in result:
            return JSONResponse({
                "success": True,
                "openid": result["openid"],
                "access_token": result.get("access_token"),
                "expires_in": result.get("expires_in")
            })
        else:
            error_msg = result.get("errmsg", "获取openid失败")
            logger.error(f"Failed to get openid: {result}")
            return JSONResponse({
                "success": False,
                "message": error_msg
            }, status_code=400)
            
    except Exception as e:
        logger.error(f"Get openid failed: {str(e)}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"获取openid失败: {str(e)}")


@app.get("/api/recharge/packages")
async def get_recharge_packages(auth_token: str):
    """
    获取算力充值套餐列表
    
    Args:
        auth_token: 用户认证token
    
    Returns:
        List of recharge packages with computing power and pricing
        If user has already recharged before, the first package (首充福利) will be filtered out
    """
    try:
        # 验证token并获取用户信息
        success, message, response_data = make_perseids_request(
            endpoint='check_first_recharge',
            method='POST',
            headers={'Authorization': f'Bearer {auth_token}'}
        )
        
        if not success:
            logger.error(f"Token verification failed: {message}")
            raise HTTPException(status_code=401, detail="Invalid token")
        
        first_recharges = response_data.get('first_recharges')
        if not first_recharges:
            raise HTTPException(status_code=401, detail="Invalid user information")
        
        # 如果用户已经充值过，过滤掉首充福利套餐（第一个套餐）
        packages = RECHARGE_PACKAGES.copy()
        if first_recharges == 1:
            packages = [pkg for pkg in packages if pkg.get("package_id") != 1]
            logger.info(f"User {user_id} has {payment_count} payment records, filtering out first-time package")
        else:
            logger.info(f"User {user_id} is a first-time recharger, showing all packages")
        
        return JSONResponse({
            "success": True,
            "packages": packages
        })
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get recharge packages: {str(e)}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"获取充值套餐失败: {str(e)}")


@app.post("/api/recharge/wechat-pay")
async def create_wechat_payment(request: WechatPayRequest):
    """
    创建微信支付订单
    
    Args:
        request: 包含套餐ID、用户ID、认证token和浏览器类型的请求
    
    Returns:
        微信支付二维码URL/JSAPI支付参数和订单信息
    
    TODO: 实现具体的微信支付逻辑
    - 调用微信支付API创建订单
    - 根据is_wechat_browser参数选择支付方式：
      * True: 使用JSAPI支付（微信内浏览器）
      * False: 使用H5支付或Native支付（外部浏览器）
    - 保存订单记录到数据库
    - 实现支付回调处理
    - 支付成功后增加用户算力
    """
    try:
        # 验证用户token
        if not request.auth_token:
            raise HTTPException(
                status_code=400,
                detail="Authentication token is required"
            )
        
        # 验证用户登录状态：通过查询算力判断token是否有效
        try:
            computing_power_response = make_perseids_request(
                method="GET",
                endpoint="/api/v1/user/check_computing_power",
                params={
                    "user_id": request.user_id,
                    "auth_token": request.auth_token
                }
            )
            
            if not computing_power_response or not computing_power_response.get("success"):
                logger.warning(f"User {request.user_id} authentication failed or expired")
                raise HTTPException(
                    status_code=401,
                    detail="登录已过期，请重新登录"
                )
            
            logger.info(f"User {request.user_id} authentication verified, computing power: {computing_power_response.get('computing_power')}")
            
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Failed to verify user authentication: {str(e)}")
            raise HTTPException(
                status_code=401,
                detail="登录过期，请重新登录"
            )
        
        # 验证套餐ID
        package_info = None
        for package in RECHARGE_PACKAGES:
            if package["package_id"] == request.package_id:
                package_info = package
                break
        
        if not package_info:
            raise HTTPException(
                status_code=400,
                detail="Invalid package ID"
            )
        
        # 生成订单ID
        order_id = wechat_pay_util.generate_order_id()
        
        # 计算支付金额（单位：分）
        total_fee = int(package_info["price"] * 100)
        body = f"算力充值-{package_info['computing_power']}算力"
        
        # TODO: 配置回调URL
        notify_url = f"{SERVER_HOST}/api/recharge/wechat-callback"
        
        # 根据浏览器类型选择支付方式
        payment_result = {}
        payment_type = ""
        
        if request.is_wechat_browser:
            # 微信内浏览器使用JSAPI支付
            payment_type = "JSAPI"
            
            # 获取用户的openid
            if not request.openid:
                raise HTTPException(
                    status_code=400,
                    detail="微信支付需要用户openid，请先进行微信授权"
                )
            
            payment_result = wechat_pay_util.create_jsapi_payment(
                order_id=order_id,
                total_fee=total_fee,
                body=body,
                openid=request.openid,
                notify_url=notify_url,
                payer_client_ip=request.payment_ip or "127.0.0.1"
            )
        else:
            # 外部浏览器使用H5支付
            payment_type = "H5"
            
            payment_result = wechat_pay_util.create_h5_payment(
                order_id=order_id,
                total_fee=total_fee,
                body=body,
                notify_url=notify_url,
                payer_client_ip=request.payment_ip or "127.0.0.1"
            )
        
        # 保存订单记录到数据库
        try:
            record_id = PaymentOrdersModel.create(
                order_id=order_id,
                user_id=request.user_id,
                package_id=request.package_id,
                computing_power=package_info["computing_power"],
                price=package_info["price"],
                payment_type=payment_type,
                status=0,  # 0-待支付
                payment_ip=request.payment_ip
            )
            logger.info(f"Saved payment order {record_id} to database")
        except Exception as e:
            logger.error(f"Failed to save payment order to database: {e}")
            # 继续执行，不影响支付流程
        
        logger.info(f"Created {payment_type} payment order {record_id} for user {request.user_id}, package {request.package_id}")
        
        # 返回支付信息
        response_data = {
            "success": True,
            "order_id": record_id,
            "package_id": request.package_id,
            "computing_power": package_info["computing_power"],
            "price": package_info["price"],
            "payment_type": payment_type
        }
        
        # 根据支付类型返回不同的数据
        if payment_type == "JSAPI":
            # JSAPI支付返回支付参数，前端调用微信JSAPI
            response_data["jsapi_params"] = payment_result
            response_data["message"] = "订单创建成功，请在微信中完成支付"
        else:
            # H5支付返回跳转URL
            response_data["h5_url"] = payment_result.get("h5_url")
            response_data["message"] = "订单创建成功，即将跳转到支付页面"
        
        return JSONResponse(response_data)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to create wechat payment: {str(e)}")
        logger.error(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"创建支付订单失败: {str(e)}")


@app.post("/api/recharge/wechat-callback")
async def wechat_payment_callback(request: Request):
    """
    微信支付回调接口（V3 API）
    
    接收微信支付成功后的异步通知
    
    回调数据格式：
    {
        "id": "事件ID",
        "create_time": "创建时间",
        "resource_type": "encrypt-resource",
        "event_type": "TRANSACTION.SUCCESS",
        "summary": "支付成功",
        "resource": {
            "original_type": "transaction",
            "algorithm": "AEAD_AES_256_GCM",
            "ciphertext": "加密数据",
            "associated_data": "附加数据",
            "nonce": "随机串"
        }
    }
    """
    try:
        # 获取回调数据
        body = await request.body()
        callback_data = json.loads(body.decode('utf-8'))
        
        logger.info(f"Received wechat payment callback: {callback_data.get('id')}")
        logger.info(f"Event type: {callback_data.get('event_type')}")
        
        # TODO: 验证回调签名
        # 从请求头获取签名信息
        timestamp = request.headers.get("Wechatpay-Timestamp")
        nonce = request.headers.get("Wechatpay-Nonce")
        signature = request.headers.get("Wechatpay-Signature")
        serial = request.headers.get("Wechatpay-Serial")
        
        if not wechat_pay_util.verify_callback_signature(timestamp, nonce, body, signature):
            logger.error("Invalid callback signature")
            return JSONResponse({"code": "FAIL", "message": "签名验证失败"}, status_code=400)
        
        # 检查事件类型
        event_type = callback_data.get("event_type")
        if event_type != "TRANSACTION.SUCCESS":
            logger.warning(f"Unsupported event type: {event_type}")
            return JSONResponse({"code": "SUCCESS", "message": "OK"})
        
        # 解密资源数据
        resource = callback_data.get("resource", {})
        ciphertext = resource.get("ciphertext")
        associated_data = resource.get("associated_data")
        resource_nonce = resource.get("nonce")
        
        if not ciphertext or not associated_data or not resource_nonce:
            logger.error("Missing encryption parameters in callback")
            return JSONResponse({"code": "FAIL", "message": "缺少加密参数"}, status_code=400)
        
        # 使用APIv3密钥解密
        try:
            decrypted_data = wechat_pay_util.decrypt_callback_resource(
                nonce=resource_nonce,
                ciphertext=ciphertext,
                associated_data=associated_data
            )
        except Exception as e:
            logger.error(f"Failed to decrypt callback data: {str(e)}")
            return JSONResponse({"code": "FAIL", "message": "解密失败"}, status_code=400)
        
        # 解析交易数据
        transaction_data = json.loads(decrypted_data)
        order_id = transaction_data.get("out_trade_no")
        transaction_id = transaction_data.get("transaction_id")
        trade_state = transaction_data.get("trade_state")
        
        logger.info(f"Decrypted transaction: order_id={order_id}, transaction_id={transaction_id}, state={trade_state}")
        
        # 如果支付成功，处理订单
        if trade_state == "SUCCESS":
            # 查询订单
            order = PaymentOrdersModel.get_by_order_id(order_id)
            
            if not order:
                logger.error(f"Order not found: {order_id}")
                return JSONResponse({"code": "FAIL", "message": "订单不存在"}, status_code=400)
            
            # 检查订单状态，避免重复处理
            if order.status == 1:
                logger.info(f"Order already paid: {order_id}")
                return JSONResponse({"code": "SUCCESS", "message": "OK"})
            
            # 更新订单状态为已支付
            PaymentOrdersModel.update_paid(order_id, transaction_id)
            user_id = order.user_id
            # TODO: 增加用户算力
            logger.info(f"Refunding {user_id} , {AUTHENTICATION_ID}")
            success, message, response_data = make_perseids_request(
                endpoint='get_auth_token_by_user_id',
                method='POST',
                data={
                    "user_id": user_id,
                    "authentication_id": AUTHENTICATION_ID
                }
            )

            if not success:
                logger.error(f"Failed to get auth token for user {user_id}: {message}")
                return False
                
            auth_token = response_data['token']
            headers = {'Authorization': f'Bearer {auth_token}'}
                        
            # 发起请求，增加算力
            success, message, response_data = make_perseids_request(
                endpoint='user/calculate_computing_power',
                method='POST',
                headers=headers,
                data={
                    "computing_power": order.computing_power,
                    "behavior": "increase",
                    "transaction_id": transaction_id
                }
            )
            
            logger.info(f"Payment processed successfully: order_id={order_id}, user_id={order.user_id}, computing_power={order.computing_power}")
        
        # 返回成功响应（V3 API使用JSON格式）
        return JSONResponse({"code": "SUCCESS", "message": "OK"})
        
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse callback data: {str(e)}")
        return JSONResponse({"code": "FAIL", "message": "数据格式错误"}, status_code=400)
    except Exception as e:
        logger.error(f"Wechat payment callback failed: {str(e)}")
        logger.error(traceback.format_exc())
        return JSONResponse({"code": "FAIL", "message": str(e)}, status_code=500)


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
        
        init_scheduler(app)
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
        init_scheduler(app)
        uvicorn.run("server:app", host="0.0.0.0", port=port, reload=False)
