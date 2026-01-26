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
import subprocess
import tempfile
from datetime import datetime
from typing import List, Optional
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode
import mimetypes
from pydantic import BaseModel
from runninghub_request import RunningHubClient, create_image_edit_nodes, TaskStatus, run_image_edit_task, run_ai_app_task_sync, run_ai_app_task
from config_util import get_config_path, is_dev_environment
from perseids_client import make_perseids_request, call_external_auth_server, get_device_uuid
from model import AIToolsModel, VideoWorkflowModel,TasksModel, AIAudioModel, PaymentOrdersModel
from model.world import WorldModel
from model.character import CharacterModel
from model.location import LocationModel
from model.script import ScriptModel
from model.props import PropsModel
import uuid
from duomi_api_requset import create_image_to_video, get_ai_task_result, create_ai_image, create_video_remix, create_character as create_character_task, get_character_task_result, create_text_to_image
from PIL import Image
from llm import call_ernie_vl_api
from task.scheduler import init_scheduler
from config.constant import TASK_COMPUTING_POWER, TASK_TYPE_GENERATE_VIDEO, TASK_TYPE_GENERATE_AUDIO, RECHARGE_PACKAGES, AUTHENTICATION_ID
from utils.wechat_pay_util import WechatPayUtil

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
MP_VERIFY_FILENAME = "MP_verify_lXQewBFqjUipl3B8.txt"
MP_VERIFY_ROUTE = "/MP_verify_lXQewBFqjUipl3B8.txt"


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

SCRIPT_WRITER_URL = config["script_writer"]["url"]

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


def _trim_audio_if_needed(audio_path: str, max_duration: float = 20.0) -> str:
    """
    Check audio duration and trim if it exceeds max_duration.
    
    Args:
        audio_path: Path to the audio file
        max_duration: Maximum duration in seconds (default: 20.0)
        
    Returns:
        Path to the audio file (original or trimmed)
        
    Raises:
        Exception: If audio processing fails
    """
    try:
        ffmpeg_path = config.get("bin", {}).get("ffmpeg", "ffmpeg")
        ffprobe_path = config.get("bin", {}).get("ffprobe", "ffprobe")
        
        # Check audio duration using ffprobe
        duration_cmd = [
            ffprobe_path, '-v', 'error',
            '-show_entries', 'format=duration',
            '-of', 'default=noprint_wrappers=1:nokey=1',
            audio_path
        ]
        
        duration_result = subprocess.run(
            duration_cmd,
            capture_output=True,
            text=True,
            timeout=10
        )
        
        if duration_result.returncode != 0:
            logger.warning(f"Failed to get audio duration: {duration_result.stderr}")
            return audio_path
        
        duration = float(duration_result.stdout.strip())
        logger.info(f"Audio duration: {duration:.2f}s")
        
        # If duration is within limit, return original file
        if duration <= max_duration:
            return audio_path
        
        # Trim audio to max_duration
        logger.info(f"Trimming audio from {duration:.2f}s to {max_duration:.2f}s")
        
        # Generate output filename
        base_name = os.path.splitext(audio_path)[0]
        ext = os.path.splitext(audio_path)[1]
        trimmed_path = f"{base_name}_trimmed{ext}"
        
        # Use ffmpeg to trim audio
        trim_cmd = [
            ffmpeg_path, '-i', audio_path,
            '-t', str(max_duration),
            '-acodec', 'copy',
            '-y',
            trimmed_path
        ]
        
        trim_result = subprocess.run(
            trim_cmd,
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if trim_result.returncode != 0:
            logger.error(f"ffmpeg trim error: {trim_result.stderr}")
            return audio_path
        
        # Remove original file and rename trimmed file
        os.remove(audio_path)
        os.rename(trimmed_path, audio_path)
        
        logger.info(f"Audio trimmed successfully to {max_duration}s")
        return audio_path
        
    except subprocess.TimeoutExpired:
        logger.error("Audio processing timeout")
        return audio_path
    except Exception as e:
        logger.error(f"Error trimming audio: {e}")
        return audio_path


def _download_and_extract_audio_from_video(video_url: str) -> str:
    """
    Download video from URL, validate size and duration, extract audio, and clean up.
    
    Args:
        video_url: URL of the video to download
        
    Returns:
        Path to extracted audio file
        
    Raises:
        HTTPException: If video is too large, too long, or processing fails
    """
    video_path = None
    audio_path = None
    
    try:
        # Create temp directory for video processing
        temp_dir = tempfile.mkdtemp(prefix="video_audio_extract_")
        video_path = os.path.join(temp_dir, "temp_video.mp4")
        
        # Download video with size limit check
        logger.info(f"Downloading video from: {video_url}")
        response = requests.get(video_url, stream=True, timeout=30)
        response.raise_for_status()
        
        # Check Content-Length header if available
        content_length = response.headers.get('Content-Length')
        if content_length:
            size_mb = int(content_length) / (1024 * 1024)
            if size_mb > 40:
                raise HTTPException(
                    status_code=400,
                    detail=f"视频文件过大: {size_mb:.1f}MB，限制为40MB"
                )
        
        # Download video with size check
        downloaded_size = 0
        max_size = 40 * 1024 * 1024  # 40MB in bytes
        
        with open(video_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    downloaded_size += len(chunk)
                    if downloaded_size > max_size:
                        raise HTTPException(
                            status_code=400,
                            detail=f"视频文件超过40MB限制"
                        )
                    f.write(chunk)
        
        logger.info(f"Video downloaded: {downloaded_size / (1024*1024):.2f}MB")
        
        # Check video duration using ffprobe
        try:
            duration_cmd = [
                'ffprobe', '-v', 'error',
                '-show_entries', 'format=duration',
                '-of', 'default=noprint_wrappers=1:nokey=1',
                video_path
            ]
            duration_result = subprocess.run(
                duration_cmd,
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if duration_result.returncode == 0:
                duration = float(duration_result.stdout.strip())
                logger.info(f"Video duration: {duration:.2f}s")
                
                if duration > 20:
                    raise HTTPException(
                        status_code=400,
                        detail=f"视频时长过长: {duration:.1f}秒，限制为20秒"
                    )
            else:
                logger.warning(f"Failed to get video duration: {duration_result.stderr}")
        except subprocess.TimeoutExpired:
            logger.warning("ffprobe timeout when checking duration")
        except Exception as e:
            logger.warning(f"Error checking video duration: {e}")
        
        # Extract audio using ffmpeg
        audio_dir = "/nas/comfyui_upload/tts/tmp_ref_audio"
        os.makedirs(audio_dir, exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        unique_id = str(uuid.uuid4())[:8]
        audio_filename = f"extracted_audio_{timestamp}_{unique_id}.wav"
        audio_path = os.path.join(audio_dir, audio_filename)
        
        logger.info(f"Extracting audio to: {audio_path}")
        
        # Use ffmpeg to extract audio
        ffmpeg_cmd = [
            'ffmpeg', '-i', video_path,
            '-vn',  # No video
            '-acodec', 'pcm_s16le',  # PCM 16-bit
            '-ar', '44100',  # Sample rate 44.1kHz
            '-ac', '2',  # Stereo
            '-y',  # Overwrite output file
            audio_path
        ]
        
        result = subprocess.run(
            ffmpeg_cmd,
            capture_output=True,
            text=True,
            timeout=60
        )
        
        if result.returncode != 0:
            logger.error(f"ffmpeg error: {result.stderr}")
            raise HTTPException(
                status_code=500,
                detail=f"音频提取失败: {result.stderr[:200]}"
            )
        
        if not os.path.exists(audio_path):
            raise HTTPException(
                status_code=500,
                detail="音频提取失败: 输出文件不存在"
            )
        
        logger.info(f"Audio extracted successfully: {audio_path}")
        return audio_path
        
    except HTTPException:
        raise
    except requests.RequestException as e:
        logger.error(f"Failed to download video: {e}")
        raise HTTPException(
            status_code=400,
            detail=f"视频下载失败: {str(e)}"
        )
    except subprocess.TimeoutExpired:
        logger.error("ffmpeg timeout")
        raise HTTPException(
            status_code=500,
            detail="音频提取超时"
        )
    except Exception as e:
        logger.error(f"Error processing video: {e}")
        logger.error(traceback.format_exc())
        raise HTTPException(
            status_code=500,
            detail=f"视频处理失败: {str(e)}"
        )
    finally:
        # Clean up temporary video file
        if video_path and os.path.exists(video_path):
            try:
                os.remove(video_path)
                logger.info(f"Cleaned up temporary video: {video_path}")
            except Exception as e:
                logger.warning(f"Failed to remove temp video: {e}")
        
        # Clean up temp directory
        if video_path:
            temp_dir = os.path.dirname(video_path)
            if os.path.exists(temp_dir):
                try:
                    shutil.rmtree(temp_dir)
                    logger.info(f"Cleaned up temp directory: {temp_dir}")
                except Exception as e:
                    logger.warning(f"Failed to remove temp directory: {e}")


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
            total_computing_power = computing_power * count
            user_id_from_token = response_data.get('user_id')
            if user_computing_power < total_computing_power:
                raise HTTPException(
                    status_code=400, 
                    detail="您的算力不足，无法生成图片"
                )
            if user_id_from_token != user_id:
                raise HTTPException(
                    status_code=400, 
                    detail="用户ID不匹配"
                )

        # Handle multiple images - limit to maximum 5 images
        images_to_process = image[:5] if len(image) > 5 else image
        image_urls = [_save_uploaded_image(img) for img in images_to_process]
        
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

@app.post("/api/text-to-image")
async def text_to_image(
    prompt: str = Form(...),
    model: str = Form("gemini-2.5-pro-image-preview", description="Model type: gemini-3-pro-image-preview, gemini-2.5-pro-image-preview"),
    aspect_ratio: str = Form("9:16", description="Aspect ratio: 1:1, 2:3, 3:2, 3:4, 4:3, 4:5, 5:4, 9:16, 16:9, 21:9"),
    image_size: str = Form(None, description="Image resolution: 1K, 2K, 4K (only for gemini-3-pro-image-preview)"),
    count: int = Form(1, ge=1, le=4, description="Generation count (1-4)"),
    user_id: int = Form(None, description="User ID"),
    auth_token: str = Form(None, description="Authentication token")
):
    """
    Submit text-to-image task to Duomi API (Gemini nano-banana)
    """
    try:
        if CHECK_AUTH_TOKEN and auth_token is None:
            raise HTTPException(
                status_code=400, 
                detail="Authentication token is required"
            )

        # Determine computing power based on model
        text_to_image_type = 1  # gemini-2.5-pro-image-preview: 2算力
        if model == "gemini-3-pro-image-preview":
            text_to_image_type = 7  # gemini-3-pro-image-preview: 6算力
        
        computing_power = TASK_COMPUTING_POWER[text_to_image_type]
        
        if CHECK_AUTH_TOKEN:
            headers = {'Authorization': f'Bearer {auth_token}'}
            # Check computing power
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
            total_computing_power = computing_power * count
            user_id_from_token = response_data.get('user_id')
            if user_computing_power < total_computing_power:
                raise HTTPException(
                    status_code=400, 
                    detail=f"您的算力不足，需要 {total_computing_power} 算力，当前仅有 {user_computing_power} 算力"
                )
            if user_id_from_token != user_id:
                raise HTTPException(
                    status_code=400, 
                    detail="用户ID不匹配"
                )

        # Submit tasks according to generation count
        project_ids = []
        for _ in range(count):
            # Generate transaction ID
            transaction_id = str(uuid.uuid4())

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

            # Create database record (status=0, will be processed by scheduler)
            if user_id:
                try:
                    id = AIToolsModel.create(
                        prompt=prompt,
                        user_id=user_id,
                        type=text_to_image_type,
                        ratio=aspect_ratio,
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
                    raise HTTPException(status_code=500, detail=f"创建数据库记录失败: {str(db_error)}")

        return JSONResponse({
            "project_ids": project_ids,
            "status": "submitted"
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
                #发起请求，获取用户ID
                success, message, response_data = make_perseids_request(
                    endpoint='user/get_user_id_by_auth_token',
                    method='POST',
                    headers=headers
                )
                if not success:
                    raise HTTPException(status_code=400, detail=message)
                user_id_from_token = response_data.get('user_id')
                if user_id_from_token != task_record.user_id:
                    raise HTTPException(status_code=400, detail="用户ID不匹配")
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
            total_computing_power = computing_power * count
            user_id_from_token = response_data.get('user_id')
            if user_computing_power < total_computing_power:
                raise HTTPException(
                    status_code=400, 
                    detail="您的算力不足，无法生成视频"
                )
            if user_id_from_token != user_id:
                raise HTTPException(
                    status_code=400, 
                    detail="用户ID不匹配"
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
    images: List[UploadFile] = File(None, description="Image files for the AI app (1-5 images)"),
    image_urls: str = Form(None, description="Comma-separated image URLs (alternative to uploading files)"),
    video_model: str = Form("sora2", description="Video model: sora2, ltx2, wan22, kling"),
    ratio: str = Form("9:16", description="Ratio type: 9:16, 16:9 (sora2/kling); 9:16, 16:9, 3:4, 1:1, 4:3 (wan22)"),
    duration_seconds: int = Form(15, description="Duration in seconds (sora2: 10/15, ltx2: 5/8/10, wan22: 5/10, kling: 5/10)"),
    count: int = Form(1, ge=1, le=4, description="Generation count (1-4)"),
    user_id: int = Form(None, description="User ID"),
    auth_token: str = Form(None, description="Authentication token")
):
    """
    Submit image to video task.
    Supports four video models:
    1. sora2: Uses Sora2 model with ratio and duration parameters
       - Ratio: 9:16, 16:9
       - Duration: 10秒, 15秒
    2. ltx2: Uses LTX2.0 model with duration parameter
       - Fixed 24fps, auto-calculate frame count
       - Duration: 5秒, 8秒, 10秒 (121帧, 201帧, 241帧)
       - Ratio: matches input image
    3. wan22: Uses Wan2.2 model with ratio and duration parameters
       - Ratio: 9:16, 16:9, 3:4, 1:1, 4:3
       - Duration: 5秒, 10秒
    4. kling: Uses Kling model with ratio and duration parameters
       - Ratio: 9:16, 16:9
       - Duration: 5秒, 10秒
    
    Supports two image input modes:
    1. Upload images: Provide 1-5 images via 'images' parameter (will be concatenated horizontally)
    2. Use image URLs: Provide comma-separated URLs via 'image_urls' parameter
    """
    try:
        if CHECK_AUTH_TOKEN and auth_token is None:
            raise HTTPException(
                status_code=400, 
                detail="Authentication token is required"
            )
        
        # Determine which mode: uploaded images or image URLs
        if image_urls:
            # Mode 1: Use provided image URLs
            url_list = [url.strip() for url in image_urls.split(',') if url.strip()]
            if not url_list:
                raise HTTPException(
                    status_code=400,
                    detail="At least one valid image URL is required"
                )
            if len(url_list) > 5:
                raise HTTPException(
                    status_code=400,
                    detail="Maximum 5 image URLs allowed"
                )
            # Use the first URL directly (or concatenate if multiple URLs provided)
            if len(url_list) == 1:
                image_url = url_list[0]
            else:
                # For multiple URLs, we use the first one for now
                # TODO: Consider downloading and concatenating multiple URLs if needed
                image_url = url_list[0]
        elif images and len(images) > 0:
            # Mode 2: Upload images
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
        else:
            raise HTTPException(
                status_code=400,
                detail="Either 'images' (uploaded files) or 'image_urls' (comma-separated URLs) must be provided"
            )

        # Determine task type and computing power based on video_model
        if video_model == "ltx2":
            task_type = 10  # LTX2.0 图生视频
            computing_power = TASK_COMPUTING_POWER[task_type]
        elif video_model == "wan22":
            task_type = 11  # Wan2.2 图生视频
            # Wan2.2根据时长区分算力：5秒=12，10秒=24
            wan22_power_map = TASK_COMPUTING_POWER[task_type]
            computing_power = wan22_power_map.get(duration_seconds, 12)
        elif video_model == "kling":
            task_type = 12  # 可灵图生视频
            # 可灵根据时长区分算力：5秒=38，10秒=55
            kling_power_map = TASK_COMPUTING_POWER[task_type]
            computing_power = kling_power_map.get(duration_seconds, 38)
        else:
            task_type = 3   # Sora2 图生视频
            computing_power = TASK_COMPUTING_POWER[task_type]
        
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
            user_id_from_token = response_data.get('user_id')
            if user_computing_power < total_computing_power:
                raise HTTPException(
                    status_code=400, 
                    detail=f"您的算力不足，需要 {total_computing_power} 算力，当前仅有 {user_computing_power} 算力"
                )
            if user_id_from_token != user_id:
                raise HTTPException(
                    status_code=400, 
                    detail="用户ID不匹配"
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
                        # Determine type and ratio based on video_model
                        if video_model == "ltx2":
                            # LTX2.0 图生视频: type=10
                            # 现在 LTX2.0 也支持比例选择（横屏/竖屏）
                            task_type = 10  # LTX2.0 图生视频
                            ratio_value = ratio
                            duration_value = duration_seconds
                        elif video_model == "wan22":
                            # Wan2.2 图生视频: type=11
                            task_type = 11
                            ratio_value = ratio
                            duration_value = duration_seconds
                        elif video_model == "kling":
                            # 可灵图生视频: type=12
                            task_type = 12
                            ratio_value = ratio
                            duration_value = duration_seconds
                        else:
                            # Sora2 图生视频: type=3
                            task_type = 3
                            ratio_value = ratio
                            duration_value = duration_seconds
                        
                        id = AIToolsModel.create(
                            prompt=prompt,
                            user_id=user_id,
                            type=task_type,
                            image_path=image_url,
                            ratio=ratio_value,
                            duration=duration_value,
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
    types: Optional[str] = Query(None, description="Multiple tool types filter, comma-separated (e.g., '3,10,11,12')"),
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
                        #发起请求，获取用户ID
                        success, message, response_data = make_perseids_request(
                            endpoint='user/get_user_id_by_auth_token',
                            method='POST',
                            headers=headers
                        )
                        if not success:
                            raise HTTPException(status_code=400, detail=message)
                        user_id_from_token = response_data.get('user_id')
                        if user_id != user_id_from_token:
                            raise HTTPException(status_code=400, detail="用户ID不匹配")
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
        # Parse types parameter if provided
        type_list_param = None
        if types:
            try:
                type_list_param = [int(t.strip()) for t in types.split(',') if t.strip()]
            except ValueError:
                return JSONResponse(
                    status_code=400,
                    content={
                        'success': False,
                        'message': 'Invalid types parameter format'
                    }
                )
        
        type_mapping = {
            1: [1, 4, 7],  # 图片编辑 + 图片高清放大
            2: [2, 5],  # AI视频生成 + 高清修复
            3: [3, 6, 10, 11, 12],  # 图片生成视频（Sora2、LTX2.0、Wan2.2、可灵）+ 高清修复
            4: [5, 6] # 高清修复
        }

        if type_list_param:
            # Use types parameter (comma-separated list)
            result = AIToolsModel.list_by_user(
                user_id=user_id,
                page=page,
                page_size=page_size,
                order_by='create_time',
                order_direction='DESC',
                type_list=type_list_param
            )
        elif type in type_mapping:
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


@app.get('/api/computing-power-config')
async def get_computing_power_config():
    """
    获取算力配置
    返回各个任务类型的算力消耗配置
    """
    try:
        return JSONResponse(
            content={
                'success': True,
                'message': '获取成功',
                'data': {
                    'task_computing_power': TASK_COMPUTING_POWER
                }
            }
        )
    except Exception as e:
        logger.error(f'获取算力配置失败: {str(e)}')
        return JSONResponse(
            status_code=500,
            content={
                'success': False,
                'message': '服务器错误'
            }
        )


@app.get('/api/script-writer-url')
async def get_script_writer_url():
    """
    获取短剧智能体服务地址
    """
    try:
        return JSONResponse(
            content={
                'code': 0,
                'message': '获取成功',
                'data': {
                    'url': SCRIPT_WRITER_URL
                }
            }
        )
    except Exception as e:
        logger.error(f'获取短剧智能体服务地址失败: {str(e)}')
        return JSONResponse(
            status_code=500,
            content={
                'code': -1,
                'message': '服务器错误'
            }
        )


@app.get('/api/ai-tools/detail/{record_id}')
async def get_ai_tool_detail(
    record_id: int,
    user_id: int = Header(None, alias="X-User-Id"),
    auth_token: str = Header(None, alias="Authorization")
):
    """
    获取单个 AI 工具记录的详情
    """
    try:
        # 查询数据库记录
        record = AIToolsModel.get_by_id(record_id)
        
        if not record:
            raise HTTPException(status_code=404, detail="记录不存在")
        
        # 检查权限（可选）
        if user_id and record.user_id != user_id:
            raise HTTPException(status_code=403, detail="无权访问该记录")
        
        return JSONResponse({
            'success': True,
            'data': record.to_dict()
        })
    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f'获取记录详情失败: {str(e)}')
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
            user_id_from_token = response_data.get('user_id')
            if user_computing_power < computing_power:
                raise HTTPException(
                    status_code=400, 
                    detail="您的算力不足，无法进行高清放大"
                )
            if user_id_from_token != user_id:
                raise HTTPException(
                    status_code=400, 
                    detail="用户ID不匹配"
                )
                  
        # 1. Get the original image record from database using project_id
        original_record = AIToolsModel.get_by_id(project_id)
        
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
            user_id_from_token = response_data.get('user_id')
            if user_computing_power < computing_power:
                raise HTTPException(
                    status_code=400,
                    detail="您的算力不足，无法进行视频修复"
                )
            if user_id_from_token != user_id:
                raise HTTPException(
                    status_code=400,
                    detail="用户ID不匹配"
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
                "plus"  # instanceType
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
            user_id_from_token = response_data.get('user_id')
            if user_computing_power < total_computing_power:
                raise HTTPException(
                    status_code=400,
                    detail=f"您的算力不足，需要 {total_computing_power} 算力，当前仅有 {user_computing_power} 算力"
                )
            if user_id_from_token != user_id:
                raise HTTPException(
                    status_code=400, 
                    detail="用户ID不匹配"
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
    from_task: Optional[str] = Form(None, description="Task ID or database record ID (supports real people)"),
    callback_url: Optional[str] = Form(None, description="Callback URL"),
    user_id: Optional[int] = Form(None, description="User ID"),
    auth_token: Optional[str] = Form(None, description="Authentication token")
):
    """
    Create character generation task using SORA API
    Either url or from_task must be provided
    from_task can be either a Duomi API task ID or a database record ID
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
            user_id_from_token = response_data.get('user_id')
            if user_computing_power < computing_power:
                raise HTTPException(
                    status_code=400,
                    detail=f"您的算力不足，需要 {computing_power} 算力，当前仅有 {user_computing_power} 算力"
                )
            if user_id_from_token != user_id:
                raise HTTPException(
                    status_code=400, 
                    detail="用户ID不匹配"
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
        
        # Check for API errors first
        if "error" in response:
            error_info = response.get("error", {})
            error_message = error_info.get("message", "未知错误")
            error_code = error_info.get("code", "unknown")
            raise HTTPException(
                status_code=500, 
                detail=f"创建角色任务失败: [{error_code}] {error_message}"
            )
        
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
    emo_ref_video_url: Optional[str] = Form(None, description="Emotion reference video URL (will extract audio)"),
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
        elif emo_ref_video_url:
            # Download video and extract audio
            emo_ref_path = _download_and_extract_audio_from_video(emo_ref_video_url)
        elif emo_ref_audio_url:
            emo_ref_path = emo_ref_audio_url
        
        logger.info(f"Audio generation - ref_path: {ref_path}, emo_ref_path: {emo_ref_path}")
        
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
            file_path = record.result_url
            if not os.path.isfile(file_path):
                logger.error(f"Audio file not found for task {audio_id}: {file_path}")
                raise HTTPException(status_code=500, detail="音频文件不存在，请稍后重试")
            
            filename = os.path.basename(file_path)
            media_type, _ = mimetypes.guess_type(file_path)
            headers = {
                "X-Audio-Status": "SUCCESS"
            }
            return FileResponse(
                path=file_path,
                filename=filename,
                media_type=media_type or "audio/wav",
                headers=headers
            )
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
                        #发起请求，获取用户ID
                        success, message, response_data = make_perseids_request(
                            endpoint='user/get_user_id_by_auth_token',
                            method='POST',
                            headers=headers
                        )
                        if not success:
                            raise HTTPException(status_code=400, detail=message)
                        user_id_from_token = response_data.get('user_id')
                        if task_record.user_id != user_id_from_token:
                            raise HTTPException(status_code=400, detail="用户ID不匹配")
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


def _has_completed_first_recharge(auth_token: str) -> bool:
    """
    调用认证服务接口，判断用户是否已经完成首充
    
    Args:
        auth_token: 用户认证 token
    
    Returns:
        True 表示已经首充，False 表示仍是首充用户
    """
    success, message, response_data = make_perseids_request(
        endpoint='user/check_first_recharge',
        method='GET',
        headers={'Authorization': f'Bearer {auth_token}'}
    )

    if not success:
        logger.error(f"Token verification failed: {message}")
        raise HTTPException(status_code=401, detail="Invalid token")

    logger.info(f"Token verification successful: {response_data}")
    first_recharge = response_data.get('first_recharge')
    if first_recharge is None:
        raise HTTPException(status_code=401, detail="Invalid user information")

    return first_recharge == 1


def _append_redirect_url(h5_url: Optional[str], redirect_url: str) -> Optional[str]:
    """
    在H5支付链接中追加 redirect_url 参数（若已存在则覆盖）
    """
    if not h5_url:
        return h5_url
    try:
        parsed = urlparse(h5_url)
        query_params = dict(parse_qsl(parsed.query, keep_blank_values=True))
        query_params["redirect_url"] = redirect_url
        new_query = urlencode(query_params, doseq=True)
        return urlunparse(parsed._replace(query=new_query))
    except Exception as e:
        logger.error(f"Failed to append redirect_url to h5_url: {e}")
        return h5_url


def _update_first_recharge_status(auth_token: str) -> None:
    """
    调用认证服务接口，更新用户首充状态
    
    Args:
        auth_token: 用户认证 token
    """
    success, message, response_data = make_perseids_request(
        endpoint='user/update_first_recharge',
        method='POST',
        headers={'Authorization': f'Bearer {auth_token}'}
    )

    if not success:
        logger.error(f"Failed to update first recharge status: {message}")
        raise HTTPException(status_code=400, detail="更新首充状态失败")

    logger.info(f"First recharge status updated successfully: {response_data}")


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
        # 查询用户是否已经首充
        has_completed_first_recharge = _has_completed_first_recharge(auth_token)

        # 如果用户已经充值过，过滤掉首充福利套餐（第一个套餐）
        packages = RECHARGE_PACKAGES.copy()
        if has_completed_first_recharge:
            packages = [pkg for pkg in packages if pkg.get("package_id") != 1]
            logger.info(f"已经首充，过滤掉首充福利套餐")
        else:
            logger.info(f"是首充用户，显示所有套餐")
        
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
            success, message, response_data = make_perseids_request(
                endpoint='user/check_computing_power',
                method='GET',
                headers={'Authorization': f'Bearer {request.auth_token}'}
            )
            
            if not success:
                logger.warning(f"User {request.user_id} authentication failed or expired")
                raise HTTPException(
                    status_code=401,
                    detail="登录已过期，请重新登录"
                )
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

        # 首充套餐校验：如果package_id为1且用户已首充，禁止再次购买
        if request.package_id == 1:
            has_completed_first_recharge = _has_completed_first_recharge(request.auth_token)
            if has_completed_first_recharge:
                logger.warning(f"User {request.user_id} attempted to purchase first-charge package again")
                raise HTTPException(
                    status_code=400,
                    detail="首充福利仅限首次充值，您已领取过该套餐"
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
            # 外部浏览器使用Native扫码支付
            payment_type = "NATIVE"
            
            payment_result = wechat_pay_util.create_native_payment(
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
            # Native支付返回二维码链接
            response_data["code_url"] = payment_result.get("code_url")
            response_data["message"] = "订单创建成功，请使用微信扫码完成支付"
        
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
        logger.info(f"callback_data: {callback_data}")
        # TODO: 验证回调签名
        # 从请求头获取签名信息
        timestamp = request.headers.get("Wechatpay-Timestamp")
        nonce = request.headers.get("Wechatpay-Nonce")
        signature = request.headers.get("Wechatpay-Signature")
        serial = request.headers.get("Wechatpay-Serial")
        
        logger.info(f"Timestamp: {timestamp}")
        logger.info(f"Nonce: {nonce}")
        logger.info(f"Signature: {signature}")
        logger.info(f"Serial: {serial}")
        
        if not wechat_pay_util.verify_callback_signature(timestamp, nonce, body, signature,serial):
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
            computing_power = order.computing_power
            
            # 检查是否为首充福利
            if order.package_id == 1:
                has_completed_first_recharge = _has_completed_first_recharge(auth_token)
                if has_completed_first_recharge:
                    computing_power = 4
                    logger.warning(f"User {order.user_id} attempted to purchase first-charge package again, downgrade computing power to {computing_power}")
                    try:
                        PaymentOrdersModel.update_computing_power(order_id, computing_power)
                    except Exception as e:
                        logger.error(f"Failed to update computing power for repeated first-charge order {order_id}: {e}")
                else:
                    # 更新用户首充状态
                    _update_first_recharge_status(auth_token=auth_token)
            
            # 更新订单状态为已支付
            PaymentOrdersModel.update_paid(order_id, transaction_id)

            headers = {'Authorization': f'Bearer {auth_token}'}
                        
            # 发起请求，增加算力
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
            
            logger.info(f"Payment processed successfully: order_id={order_id}, user_id={order.user_id}, computing_power={computing_power}")
        
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

class VideoWorkflowCreateRequest(BaseModel):
    name: str
    description: Optional[str] = None
    cover_image: Optional[str] = None
    status: Optional[int] = 1
    workflow_data: Optional[dict] = None
    style: Optional[str] = None
    style_reference_image: Optional[str] = None
    default_world_id: Optional[int] = None

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
    file: UploadFile = File(..., description="要上传的图片、视频或音频文件"),
    auth_token: str = Header(None, alias="Authorization"),
    user_id: Optional[int] = Header(None, alias="X-User-Id")
):
    """
    上传工作流素材（图片、视频或音频）
    返回可访问的永久URL
    """
    try:
        user_id = _get_user_id_from_header(user_id)
        
        # 验证文件类型
        content_type = file.content_type or ""
        if not (content_type.startswith("image/") or content_type.startswith("video/") or content_type.startswith("audio/")):
            return JSONResponse(
                status_code=400,
                content={"code": -1, "message": "仅支持图片、视频或音频文件"}
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
        force_medium_shot = body.get('force_medium_shot', False)
        no_bg_music = body.get('no_bg_music', False)
        split_multi_dialogue = body.get('split_multi_dialogue', False)
        
        if not script_content:
            return JSONResponse(
                status_code=400,
                content={"code": -1, "message": "剧本内容不能为空"}
            )

            # 检查算力是否充足
        if auth_token:
            headers = {'Authorization': f'Bearer {auth_token}'}
            success, message, response_data = make_perseids_request(
                endpoint='user/check_computing_power',
                method='GET',
                headers=headers
            )
            if not success:
                return JSONResponse(
                    status_code=400,
                    content={
                        'code': -1,
                        'message': f'算力检查失败: {message}',
                        'data': None
                    }
                )
                    
            # Check if computing power is sufficient
            user_computing_power = response_data.get('computing_power', 0)
            if user_computing_power < 1:
                return JSONResponse(
                    status_code=400,
                    content={
                        'code': -1,
                        'message': '算力不足，请充值',
                        'data': None
                    }
                )
        
        # 导入剧本解析模块
        from llm.script_parser import parse_script_to_shots
        
        # 调用LLM解析剧本
        parsed_data = await parse_script_to_shots(
            script_content=script_content,
            max_group_duration=max_group_duration,
            world_id=world_id,
            model='gemini-3-flash-preview',
            temperature=0.5,
            force_medium_shot=force_medium_shot,
            no_bg_music=no_bg_music,
            split_multi_dialogue=split_multi_dialogue,
            auth_token=auth_token,
            vendor_id=1,
            model_id=1
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
            style_reference_image=request.style_reference_image,
            default_world_id=request.default_world_id
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


class UpdateWorldRequest(BaseModel):
    name: Optional[str] = None
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
        
        cleaned_name = request.name.strip()
        
        existing_world = WorldModel.get_by_name(
            user_id=user_id,
            name=cleaned_name
        )
        if existing_world:
            return JSONResponse(
                status_code=400,
                content={
                    'code': -1,
                    'message': '该世界已经存在，请选择其他名称',
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


@app.put('/api/worlds/{world_id}')
async def update_world(
    world_id: int,
    request: UpdateWorldRequest,
    auth_token: str = Header(None, alias="Authorization"),
    user_id: int = Header(None, alias="X-User-Id")
):
    """
    编辑世界信息
    """
    try:
        user_id = _get_user_id_from_header(user_id)
        world = _ensure_world_owner(world_id, user_id)

        update_fields = {}

        if request.name is not None:
            cleaned_name = request.name.strip()
            if not cleaned_name:
                return JSONResponse(
                    status_code=400,
                    content={
                        'code': -1,
                        'message': '世界名称不能为空',
                        'data': None
                    }
                )
            existing_world = WorldModel.get_by_name(user_id=user_id, name=cleaned_name)
            if existing_world and getattr(existing_world, "id", None) != world_id:
                return JSONResponse(
                    status_code=400,
                    content={
                        'code': -1,
                        'message': '该世界名称已被使用',
                        'data': None
                    }
                )
            update_fields['name'] = cleaned_name

        if request.description is not None:
            update_fields['description'] = request.description.strip() if request.description else None

        if not update_fields:
            return JSONResponse(
                status_code=400,
                content={
                    'code': -1,
                    'message': '没有可更新的字段',
                    'data': None
                }
            )

        WorldModel.update(world_id, **update_fields)
        updated_world = WorldModel.get_by_id(world_id)

        return JSONResponse(
            status_code=200,
            content={
                'code': 0,
                'message': '更新成功',
                'data': updated_world.to_dict() if updated_world else world.to_dict()
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update world {world_id}: {e}")
        return JSONResponse(
            status_code=500,
            content={
                'code': -1,
                'message': str(e),
                'data': None
            }
        )


@app.delete('/api/worlds/{world_id}')
async def delete_world(
    world_id: int,
    auth_token: str = Header(None, alias="Authorization"),
    user_id: int = Header(None, alias="X-User-Id")
):
    """
    删除世界
    """
    try:
        user_id = _get_user_id_from_header(user_id)
        _ensure_world_owner(world_id, user_id)

        character_count = CharacterModel.count_by_world(world_id)
        if character_count > 0:
            return JSONResponse(
                status_code=400,
                content={
                    'code': -1,
                    'message': '该世界下仍存在角色，请先删除所有角色后再尝试删除世界',
                    'data': None
                }
            )

        location_count = LocationModel.count_by_world(world_id)
        if location_count > 0:
            return JSONResponse(
                status_code=400,
                content={
                    'code': -1,
                    'message': '该世界下仍存在场景，请先删除所有场景后再尝试删除世界',
                    'data': None
                }
            )

        WorldModel.delete(world_id)

        return JSONResponse(
            status_code=200,
            content={
                'code': 0,
                'message': '删除成功',
                'data': None
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete world {world_id}: {e}")
        return JSONResponse(
            status_code=500,
            content={
                'code': -1,
                'message': str(e),
                'data': None
            }
        )


@app.get('/api/scripts')
async def get_scripts(
    world_id: int = Query(..., description="世界ID"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    order_by: str = Query('create_time', description="排序字段"),
    order_direction: str = Query('DESC', description="排序方向"),
    auth_token: str = Header(None, alias="Authorization"),
    user_id: int = Header(None, alias="X-User-Id")
):
    """
    根据世界ID获取剧本列表
    """
    try:
        user_id = _get_user_id_from_header(user_id)
        _ensure_world_owner(world_id, user_id)
        
        result = ScriptModel.list_by_world(
            world_id=world_id,
            page=page,
            page_size=page_size,
            order_by=order_by,
            order_direction=order_direction
        )
        
        return JSONResponse(
            status_code=200,
            content={
                'code': 0,
                'message': 'success',
                'data': result
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get scripts for world {world_id}: {e}")
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
            
            # 自动裁剪音频（如果超过20秒）
            file_path = _trim_audio_if_needed(file_path, max_duration=20.0)
            
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
            
            # 自动裁剪音频（如果超过20秒）
            file_path = _trim_audio_if_needed(file_path, max_duration=20.0)
            
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


# ========== 道具相关接口 ==========

@app.get('/api/props')
async def get_props(
    world_id: int = Query(..., description="世界ID"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(100, ge=1, le=100, description="每页数量"),
    keyword: Optional[str] = Query(None, description="搜索关键词"),
    auth_token: str = Header(None, alias="Authorization"),
    user_id: int = Header(None, alias="X-User-Id")
):
    """
    获取道具列表
    """
    try:
        user_id = _get_user_id_from_header(user_id)
        logger.info(f"Getting props list - world_id: {world_id}, page: {page}, page_size: {page_size}, keyword: {keyword}")
        
        result = PropsModel.list_by_world(
            world_id=world_id,
            page=page,
            page_size=page_size,
            keyword=keyword
        )
        
        logger.info(f"Props query result - total: {result.get('total', 0)}, data count: {len(result.get('data', []))}")
        
        return JSONResponse(
            status_code=200,
            content={
                'code': 0,
                'message': 'success',
                'data': result
            }
        )
    except Exception as e:
        logger.error(f"Failed to get props: {e}")
        return JSONResponse(
            status_code=500,
            content={
                'code': -1,
                'message': str(e),
                'data': None
            }
        )


@app.get('/api/props/{props_id}')
async def get_props_by_id(
    props_id: int,
    auth_token: str = Header(None, alias="Authorization"),
    user_id: int = Header(None, alias="X-User-Id")
):
    """
    获取单个道具详情
    """
    try:
        user_id = _get_user_id_from_header(user_id)
        logger.info(f"Getting props detail - props_id: {props_id}")
        
        props = PropsModel.get_by_id(props_id)
        
        if not props:
            return JSONResponse(
                status_code=404,
                content={
                    'code': -1,
                    'message': '道具不存在',
                    'data': None
                }
            )
        
        return JSONResponse(
            status_code=200,
            content={
                'code': 0,
                'message': 'success',
                'data': props.to_dict()
            }
        )
    except Exception as e:
        logger.error(f"Failed to get props detail: {e}")
        return JSONResponse(
            status_code=500,
            content={
                'code': -1,
                'message': str(e),
                'data': None
            }
        )


@app.post('/api/props')
async def create_props(
    world_id: int = Form(..., description="世界ID"),
    name: str = Form(..., description="道具名称"),
    content: Optional[str] = Form(None, description="道具描述"),
    other_info: Optional[str] = Form(None, description="其他信息"),
    reference_image: Optional[UploadFile] = File(None, description="参考图"),
    auth_token: str = Header(None, alias="Authorization"),
    user_id: int = Header(None, alias="X-User-Id")
):
    """
    创建道具
    """
    try:
        user_id = _get_user_id_from_header(user_id)
        
        if not name or not name.strip():
            return JSONResponse(
                status_code=400,
                content={
                    'code': -1,
                    'message': '道具名称不能为空',
                    'data': None
                }
            )
        
        # 处理图片上传
        image_path = None
        if reference_image and reference_image.filename:
            file_ext = os.path.splitext(reference_image.filename)[1]
            filename = f"props_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}{file_ext}"
            
            props_upload_dir = os.path.join(upload_dir, "props")
            os.makedirs(props_upload_dir, exist_ok=True)
            
            file_path = os.path.join(props_upload_dir, filename)
            with open(file_path, "wb") as f:
                content_data = await reference_image.read()
                f.write(content_data)
            
            image_path = f"{SERVER_HOST}/upload/props/{filename}"
        
        props_id = PropsModel.create(
            world_id=world_id,
            name=name.strip(),
            user_id=user_id,
            content=content.strip() if content else None,
            other_info=other_info.strip() if other_info else None,
            reference_image=image_path
        )
        
        props = PropsModel.get_by_id(props_id)
        
        return JSONResponse(
            status_code=200,
            content={
                'code': 0,
                'message': '创建成功',
                'data': props.to_dict() if props else None
            }
        )
    except Exception as e:
        logger.error(f"Failed to create props: {e}")
        return JSONResponse(
            status_code=500,
            content={
                'code': -1,
                'message': str(e),
                'data': None
            }
        )


@app.put('/api/props/{props_id}')
async def update_props(
    props_id: int,
    name: Optional[str] = Form(None, description="道具名称"),
    content: Optional[str] = Form(None, description="道具描述"),
    other_info: Optional[str] = Form(None, description="其他信息"),
    reference_image: Optional[UploadFile] = File(None, description="参考图"),
    auth_token: str = Header(None, alias="Authorization"),
    user_id: int = Header(None, alias="X-User-Id")
):
    """
    更新道具
    """
    try:
        user_id = _get_user_id_from_header(user_id)
        
        # 获取道具信息
        props = PropsModel.get_by_id(props_id)
        if not props:
            return JSONResponse(
                status_code=404,
                content={
                    'code': -1,
                    'message': '道具不存在',
                    'data': None
                }
            )
        
        # 验证权限
        if props.user_id != user_id:
            return JSONResponse(
                status_code=403,
                content={
                    'code': -1,
                    'message': '无权限修改此道具',
                    'data': None
                }
            )
        
        # 处理图片上传
        image_path = props.reference_image
        if reference_image and reference_image.filename:
            file_ext = os.path.splitext(reference_image.filename)[1]
            filename = f"props_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}{file_ext}"
            
            props_upload_dir = os.path.join(upload_dir, "props")
            os.makedirs(props_upload_dir, exist_ok=True)
            
            file_path = os.path.join(props_upload_dir, filename)
            with open(file_path, "wb") as f:
                content_data = await reference_image.read()
                f.write(content_data)
            
            image_path = f"{SERVER_HOST}/upload/props/{filename}"
        
        # 更新道具
        PropsModel.update(
            props_id=props_id,
            name=name.strip() if name else props.name,
            content=content.strip() if content else props.content,
            other_info=other_info.strip() if other_info else props.other_info,
            reference_image=image_path
        )
        
        # 获取更新后的道具
        updated_props = PropsModel.get_by_id(props_id)
        
        return JSONResponse(
            status_code=200,
            content={
                'code': 0,
                'message': '更新成功',
                'data': updated_props.to_dict() if updated_props else None
            }
        )
    except Exception as e:
        logger.error(f"Failed to update props: {e}")
        return JSONResponse(
            status_code=500,
            content={
                'code': -1,
                'message': str(e),
                'data': None
            }
        )


@app.delete('/api/props/{props_id}')
async def delete_props(
    props_id: int,
    auth_token: str = Header(None, alias="Authorization"),
    user_id: int = Header(None, alias="X-User-Id")
):
    """
    删除道具
    """
    try:
        user_id = _get_user_id_from_header(user_id)
        
        # 获取道具信息
        props = PropsModel.get_by_id(props_id)
        if not props:
            return JSONResponse(
                status_code=404,
                content={
                    'code': -1,
                    'message': '道具不存在',
                    'data': None
                }
            )
        
        # 验证权限
        if props.user_id != user_id:
            return JSONResponse(
                status_code=403,
                content={
                    'code': -1,
                    'message': '无权限删除此道具',
                    'data': None
                }
            )
        
        # 删除道具
        PropsModel.delete(props_id)
        
        return JSONResponse(
            status_code=200,
            content={
                'code': 0,
                'message': '删除成功',
                'data': None
            }
        )
    except Exception as e:
        logger.error(f"Failed to delete props: {e}")
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
    video_clips: List[dict] = []
    audio_clips: List[dict] = []
    pillars: List[dict] = []
    workflow_name: Optional[str] = "未命名工作流"
    request_origin: Optional[str] = None
    # 兼容旧版本
    timeline_clips: Optional[List[dict]] = None


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
        
        # 兼容旧版本：如果使用旧的timeline_clips字段，转换为新格式
        if payload.timeline_clips is not None:
            payload.video_clips = payload.timeline_clips
            payload.audio_clips = []
            payload.pillars = []
        
        if not payload.video_clips and not payload.audio_clips:
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
        from jianying_utils import seconds_to_microseconds
        
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
        
        # 下载所有视频和音频
        downloaded_video_files = []
        downloaded_audio_files = []
        asset_cache = {}
        
        # 下载视频文件
        for idx, clip in enumerate(payload.video_clips):
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
                        logger.info(f"正在下载视频 {idx + 1}/{len(payload.video_clips)}: {video_name}")
                        
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
                
                downloaded_video_files.append({
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
        
        # 下载音频文件
        for idx, clip in enumerate(payload.audio_clips):
            audio_url = clip.get('url')
            audio_name = clip.get('name', f'audio_{idx}')
            
            if not audio_url:
                logger.warning(f"跳过没有URL的音频片段: {audio_name}")
                continue
            
            try:
                asset_key = None
                local_asset_path = _get_local_upload_file(audio_url, request_origin)
                if local_asset_path:
                    asset_key = f"local::{os.path.abspath(local_asset_path)}"
                elif audio_url:
                    asset_key = f"url::{audio_url}"

                if asset_key and asset_key in asset_cache:
                    file_path = asset_cache[asset_key]
                    safe_name = os.path.basename(file_path)
                    logger.info(f"复用已下载素材: {audio_name} -> {safe_name}")
                else:
                    if local_asset_path:
                        file_ext = os.path.splitext(local_asset_path)[1] or '.mp3'
                        safe_name = f"audio_{idx:03d}_{uuid.uuid4().hex[:8]}{file_ext}"
                        file_path = os.path.join(temp_download_dir, safe_name)
                        shutil.copy2(local_asset_path, file_path)
                        logger.info(f"已复用本地上传音频文件: {local_asset_path} -> {file_path}")
                    else:
                        logger.info(f"正在下载音频 {idx + 1}/{len(payload.audio_clips)}: {audio_name}")
                        
                        # 下载音频
                        response = requests.get(audio_url, stream=True, timeout=300)
                        response.raise_for_status()
                        
                        # 确定文件扩展名
                        file_ext = '.mp3'
                        if 'content-type' in response.headers:
                            content_type = response.headers['content-type']
                            if 'audio/wav' in content_type or audio_url.endswith('.wav'):
                                file_ext = '.wav'
                            elif 'audio/aac' in content_type or audio_url.endswith('.aac'):
                                file_ext = '.aac'
                            elif 'audio/mpeg' in content_type or audio_url.endswith('.mp3'):
                                file_ext = '.mp3'
                        
                        # 保存文件
                        safe_name = f"audio_{idx:03d}_{uuid.uuid4().hex[:8]}{file_ext}"
                        file_path = os.path.join(temp_download_dir, safe_name)
                        
                        with open(file_path, 'wb') as f:
                            for chunk in response.iter_content(chunk_size=8192):
                                if chunk:
                                    f.write(chunk)
                        
                        logger.info(f"音频下载完成: {safe_name}")
                    
                    if asset_key:
                        asset_cache[asset_key] = file_path
                
                downloaded_audio_files.append({
                    'file_path': file_path,
                    'clip': clip,
                    'filename': safe_name
                })
                
            except Exception as e:
                logger.error(f"处理音频失败 {audio_name}: {e}")
                return JSONResponse(
                    status_code=500,
                    content={
                        'success': False,
                        'error': f'处理音频失败: {audio_name} - {str(e)}'
                    }
                )
        
        if not downloaded_video_files and not downloaded_audio_files:
            return JSONResponse(
                status_code=400,
                content={
                    'success': False,
                    'error': '没有成功下载任何媒体文件'
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
        
        # 创建视频轨道和音频轨道
        video_track = library.create_video_track("主轨道")
        audio_track = library.create_audio_track("音频轨道")
        
        # 如果有柱子数据，使用柱子系统处理（支持不连续的视频）
        if payload.pillars:
            logger.info(f"使用柱子系统处理时间轴，共 {len(payload.pillars)} 个柱子")
            
            # 按柱子顺序处理
            sorted_pillars = sorted(payload.pillars, key=lambda p: (p.get('scriptId', 0), p.get('shotNumber', 0)))
            current_time = 0
            
            for pillar in sorted_pillars:
                pillar_id = pillar.get('id')
                default_duration = pillar.get('defaultDuration', 15)
                video_clip_ids = pillar.get('videoClipIds', [])
                audio_clip_ids = pillar.get('audioClipIds', [])
                
                logger.info(f"处理柱子 {pillar_id}: 默认时长={default_duration}秒, 视频片段={len(video_clip_ids)}个, 音频片段={len(audio_clip_ids)}个")
                
                # 计算该柱子的实际时长
                pillar_duration = default_duration
                
                # 处理该柱子内的视频片段
                pillar_video_duration = 0
                has_video = False
                
                for clip_data in payload.video_clips:
                    if clip_data.get('pillarId') == pillar_id:
                        # 查找对应的下载文件
                        downloaded_item = None
                        for item in downloaded_video_files:
                            if item['clip'].get('url') == clip_data.get('url'):
                                downloaded_item = item
                                break
                        
                        if downloaded_item:
                            has_video = True
                            clip = downloaded_item['clip']
                            file_path = downloaded_item['file_path']
                            
                            # 计算剪切后的时长
                            start_time = clip.get('startTime', 0)
                            end_time = clip.get('endTime', clip.get('duration', 0))
                            clip_duration_sec = end_time - start_time
                            
                            # 转换为微秒
                            source_start = seconds_to_microseconds(start_time)
                            clip_duration = seconds_to_microseconds(clip_duration_sec)
                            
                            # 添加到轨道
                            library.add_video_to_track(
                                track_id=video_track,
                                file_path=file_path,
                                start_time=seconds_to_microseconds(current_time + pillar_video_duration),
                                duration=clip_duration,
                                source_start=source_start
                            )
                            
                            pillar_video_duration += clip_duration_sec
                            logger.info(f"  添加视频片段: {clip.get('name')}, 时长={clip_duration_sec:.2f}秒")
                
                # 如果该柱子没有视频，创建占位符
                if not has_video:
                    # 使用任意一个已下载的视频作为占位符素材（不可见、静音）
                    if downloaded_video_files:
                        placeholder_file = downloaded_video_files[0]['file_path']
                        placeholder_duration = default_duration
                        
                        library.add_video_to_track(
                            track_id=video_track,
                            file_path=placeholder_file,
                            start_time=seconds_to_microseconds(current_time),
                            duration=seconds_to_microseconds(placeholder_duration),
                            source_start=0,
                            is_placeholder=True
                        )
                        
                        pillar_video_duration = placeholder_duration
                        logger.info(f"  添加占位符片段: 时长={placeholder_duration:.2f}秒（柱子无视频）")
                
                # 处理该柱子内的音频片段
                pillar_audio_duration = 0
                for clip_data in payload.audio_clips:
                    if clip_data.get('pillarId') == pillar_id:
                        # 查找对应的下载文件
                        downloaded_item = None
                        for item in downloaded_audio_files:
                            if item['clip'].get('url') == clip_data.get('url'):
                                downloaded_item = item
                                break
                        
                        if downloaded_item:
                            clip = downloaded_item['clip']
                            file_path = downloaded_item['file_path']
                            
                            # 计算剪切后的时长
                            start_time = clip.get('startTime', 0)
                            end_time = clip.get('endTime', clip.get('duration', 0))
                            clip_duration_sec = end_time - start_time
                            
                            # 转换为微秒
                            source_start = seconds_to_microseconds(start_time)
                            clip_duration = seconds_to_microseconds(clip_duration_sec)
                            
                            # 添加到轨道
                            library.add_audio_to_track(
                                track_id=audio_track,
                                file_path=file_path,
                                start_time=seconds_to_microseconds(current_time + pillar_audio_duration),
                                duration=clip_duration,
                                source_start=source_start
                            )
                            
                            pillar_audio_duration += clip_duration_sec
                            logger.info(f"  添加音频片段: {clip.get('name')}, 时长={clip_duration_sec:.2f}秒")
                
                # 使用最大时长作为柱子的实际时长
                pillar_duration = max(default_duration, pillar_video_duration, pillar_audio_duration)
                current_time += pillar_duration
                logger.info(f"柱子 {pillar_id} 实际时长: {pillar_duration:.2f}秒")
        
        else:
            # 经典模式：按顺序添加视频和音频（兼容旧版本）
            logger.info("使用经典模式处理时间轴")
            current_time = 0
            
            # 添加视频片段
            for item in downloaded_video_files:
                clip = item['clip']
                file_path = item['file_path']
                
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
            
            # 添加音频片段
            audio_time = 0
            for item in downloaded_audio_files:
                clip = item['clip']
                file_path = item['file_path']
                
                # 计算剪切后的时长
                start_time = clip.get('startTime', 0)
                end_time = clip.get('endTime', clip.get('duration', 0))
                
                # 转换为微秒
                source_start = seconds_to_microseconds(start_time)
                clip_duration = seconds_to_microseconds(end_time - start_time)
                
                # 添加到轨道
                library.add_audio_to_track(
                    track_id=audio_track,
                    file_path=file_path,
                    start_time=seconds_to_microseconds(audio_time),
                    duration=clip_duration,
                    source_start=source_start
                )
                
                audio_time += (end_time - start_time)
        
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
                'video_count': len(downloaded_video_files),
                'audio_count': len(downloaded_audio_files),
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

@app.get("/image-style-guide")
async def serve_image_style_guide():
    file_path = os.path.join(static_dir, "image_style_guide.html")
    if os.path.isfile(file_path):
        return FileResponse(file_path)
    raise HTTPException(status_code=404, detail="Image style guide page not found")

@app.get(f"{MP_VERIFY_ROUTE}")
async def get_mp_verify_file():
    """
    Serve the WeChat MP verification file at a dedicated root endpoint.
    """
    file_path = os.path.join(APP_DIR, MP_VERIFY_FILENAME)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Verification file not found")
    return FileResponse(file_path, media_type="text/plain")

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
