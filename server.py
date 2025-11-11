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
from model import AIToolsModel
import uuid
from api_requset import create_image_to_video, get_ai_task_result, create_ai_image
from PIL import Image
from baidu import call_ernie_vl_api

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
SERVER_HOST = config["server"]["host"]
API_KEY = config["runninghub"]["api_key"]

# Default ComfyUI server address; can be overridden by request field
DEFAULT_COMFYUI_SERVER = os.environ.get("COMFYUI_SERVER", "http://127.0.0.1:8188/")

# Type to computing power mapping
# 1: 图片编辑, 2: AI视频生成, 3: 图片生成视频, 4: 高清放大
TASK_COMPUTING_POWER = {
    1: 2,
    2: 20,
    3: 20,
    4: 1
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
    image: UploadFile = File(...),
    prompt: str = Form(...),
    ratio: str = Form("9:16", description="Model type: 9:16, 16:9, 1:1 ,3:4, 4:3"),
    user_id: int = Form(None, description="User ID"),
    auth_token: str = Form(None, description="Authentication token")
):
    """
    Submit image editing task to RunningHub nanobanana service
    """
    try:
        if CHECK_AUTH_TOKEN and auth_token is None:
            raise HTTPException(
                status_code=400, 
                detail="Authentication token is required"
            )

        #用uuid生成交易id
        transaction_id = str(uuid.uuid4())
        computing_power = TASK_COMPUTING_POWER[1]
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

        # Save uploaded image to upload directory
        image_url = _save_uploaded_image(image)
        
        # Submit task
        response = create_ai_image(prompt, ratio, image_url)
        project_id = response["data"]["projectId"]
        if project_id and CHECK_AUTH_TOKEN:
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
            
        # Create database record
        if user_id:
            try:
                AIToolsModel.create(
                    prompt=prompt,
                    user_id=user_id,
                    type=1,  # 1-图片编辑
                    image_path=image_url,
                    ratio=ratio,
                    project_id=project_id,
                    transaction_id=transaction_id,
                    status=1
                )
            except Exception as db_error:
                logger.error(f"Failed to create database record: {db_error}")
                # Don't fail the request if database insert fails
        
        return JSONResponse({
            "project_id": project_id,
            "status": "submitted",
            "image_url": image_url
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
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to check runninghub status: {str(e)}")


@app.get("/api/get-status/{project_id}")
async def get_status(
    project_id: str,
    auth_token: Optional[str] = Query(None, description="Auth token for computing power refund")
):
    """
    Check the status of an AI task
    If task fails, will refund computing power
    """
    try:
        # Call get_ai_task_result to check status
        result = get_ai_task_result(project_id)
        
        # Check if API call was successful
        if result.get("code") != 0:
            error_msg = result.get("msg", "Unknown error")
            raise HTTPException(status_code=500, detail=f"Failed to get task result: {error_msg}")
        
        data = result.get("data", {})
        task_status = data.get("status")  # 0-进行中 1-成功 2-失败
        media_url = data.get("mediaUrl")
        reason = data.get("reason")
        
        # Query database to get creation time
        task_record = AIToolsModel.get_by_project_id(project_id)
        task_cost_time = None
        if task_record and task_record.create_time:
            # Calculate time difference in seconds
            from datetime import datetime
            current_time = datetime.now()
            time_diff = current_time - task_record.create_time
            task_cost_time = int(time_diff.total_seconds())
        
        # Update database based on status
        if task_status == 1:  # Success
            try:
                AIToolsModel.update_by_project_id(
                    project_id=project_id,
                    result_url=media_url,
                    status=2  # 2-处理完成
                )
            except Exception as db_error:
                logger.error(f"Failed to update database record: {db_error}")
            
            return JSONResponse({
                "status": "SUCCESS",
                "results": [
                    {
                        "file_url": media_url,
                        "task_cost_time": task_cost_time
                    }
                ] if media_url else []
            })
        elif task_status == 2:  # Failed
            logger.info(f"Task failed: {reason}")
            if reason and "We currently do not support uploads of images containing photorealistic people" in reason:
                reason = "图片包含真人，无法处理"
            elif reason and "This content may violate our guardrails concerning similarity to third-party content. " in reason:
                reason = "此内容可能违反了我们关于与第三方内容相似性的规定"
            try:
                AIToolsModel.update_by_project_id(
                    project_id=project_id,
                    status=-1,  # -1-处理失败
                    message=reason
                )
            except Exception as db_error:
                logger.error(f"Failed to update database record: {db_error}")
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
                "status": "FAILED",
                "reason": reason,
                "results": []
            })
        else:  # task_status == 0, In progress
            return JSONResponse({
                "status": "RUNNING",
                "results": []
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
        #用uuid生成交易id
        transaction_id = str(uuid.uuid4())
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
            
            
        # Submit task (async, return immediately)
        result = create_image_to_video(prompt, ratio, None, duration_seconds)
        # Check if task submission failed
        if result.get("code") != 0:
            error_msg = result.get("msg", "Unknown error")
            raise HTTPException(status_code=500, detail=f"Task submission failed: {error_msg}")
        
        project_id = result.get("data", {}).get("projectId")
        if not project_id:
            raise HTTPException(status_code=500, detail="未获得任务id")
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

        # Create database record
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
            "project_id": project_id,
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

        #用uuid生成交易id
        transaction_id = str(uuid.uuid4())
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
            
            # Check if computing power is sufficient
            user_computing_power = response_data.get('computing_power', 0)
            if user_computing_power < computing_power:
                raise HTTPException(
                    status_code=400, 
                    detail="您的算力不足，无法生成视频"
                )
            
        # Submit task (async, return immediately)
        result = create_image_to_video(prompt, ratio, image_url, duration_seconds)
        
        # Check if task submission failed
        if result.get("code") != 0:
            error_msg = result.get("msg", "Unknown error")
            raise HTTPException(status_code=500, detail=f"Task submission failed: {error_msg}")
        
        project_id = result.get("data", {}).get("projectId")
        if not project_id:
            raise HTTPException(status_code=500, detail="未获得任务id")
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
        # Create database record
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
                logger.error(f"Failed to create database record: {db_error}")
                # Don't fail the request if database insert fails
        
        return JSONResponse({
            "success": True,
            "project_id": project_id,
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
                    # Type 4 (图片高清放大) uses RunningHub, others use get_ai_task_result
                    if task.type == 4:
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
                        # Use get_ai_task_result for other task types
                        result = get_ai_task_result(task.project_id)
                        
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
        # If type=1, also include type=4 (图片高清放大)
        if type == 1:
            result = AIToolsModel.list_by_user(
                user_id=user_id,
                page=page,
                page_size=page_size,
                order_by='create_time',
                order_direction='DESC',
                type_list=[1, 4]  # 1-图片编辑, 4-图片高清放大
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
                detail="Authentication token is required"
            )
        # 保存上传的图片并获取URL
        image_url1 = _save_uploaded_image(image1)
        image_url2 = _save_uploaded_image(image2) if image2 else None
        image_url3 = _save_uploaded_image(image3) if image3 else None
        image_url4 = _save_uploaded_image(image4) if image4 else None
        image_url5 = _save_uploaded_image(image5) if image5 else None
        
        logger.info(f"AI script generation started with images: {image_url1}, {image_url2}, {image_url3}, {image_url4}, {image_url5}")
        
        # 调用百度千帆API
        result = call_ernie_vl_api(
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
        
        logger.info(f"Baidu API response received: {result}")
        
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
                "nodeId": "15",
                "fieldName": "image",
                "fieldValue": result_url,
                "description": "Upload image"
            }
        ]
        result = run_ai_app_task("1950110619129307138", API_KEY, node_info_list, None)
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
    port = 9002 if is_dev_environment() else config["server"].get("port", 5173)
    uvicorn.run("server:app", host="0.0.0.0", port=port, reload=False)
