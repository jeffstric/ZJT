import requests
from config_util import get_config_path
import os
import yaml
import uuid
import time
import json
from logger_config import setup_logger

logger = setup_logger(__name__)

config_path = get_config_path()
    
# Load config to get host
if not os.path.exists(config_path):
    raise FileNotFoundError(f"Configuration file not found: {config_path}")
    
with open(config_path, 'r', encoding='utf-8') as file:
    config = yaml.safe_load(file)
    
vidu_config = config.get("vidu", {})
api_key = vidu_config.get("token", "")
base_url = "https://api.vidu.cn"


def create_vidu_image_to_video(
    image_url: str,
    prompt: str,
    model: str = "viduq2-pro-fast",
    audio: bool = True,
    voice_id: str = "professional_host",
    duration: int = 5,
    seed: int = 0,
    resolution: str = "720p",
    movement_amplitude: str = "auto",
    off_peak: bool = False
):
    """
    Create Vidu image to video task
    
    Args:
        image_url: URL of the input image
        prompt: Text prompt for video generation
        model: Model name (default: "viduq2-pro-fast")
        audio: Whether to generate audio (default: True)
        voice_id: Voice ID for audio generation (default: "professional_host")
        duration: Video duration in seconds (default: 5)
        seed: Random seed (default: 0)
        resolution: Video resolution (default: "720p")
        movement_amplitude: Movement amplitude - "auto", "small", "medium", "large" (default: "auto")
        off_peak: Whether to use off-peak pricing (default: False)
    
    Returns:
        Response from the API with task_id
        Format: {"id": "task_id", "status": "processing", ...}
    """
    url = f"{base_url}/ent/v2/img2video"
    
    headers = {
        "Authorization": f"Token {api_key}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": model,
        "images": [image_url],
        "prompt": prompt,
        "audio": audio,
        "voice_id": voice_id,
        "duration": duration,
        "seed": seed,
        "resolution": resolution,
        "movement_amplitude": movement_amplitude,
        "off_peak": off_peak
    }
    
    logger.info(f"[Vidu API] Request URL: {url}")
    logger.info(f"[Vidu API] Request Payload: {json.dumps(payload, ensure_ascii=False, indent=2)}")
    
    try:
        response = requests.post(url, json=payload, headers=headers)
        response.raise_for_status()
        result = response.json()
        
        logger.info(f"[Vidu API] Response: {json.dumps(result, ensure_ascii=False, indent=2)}")
        
        return result
    except requests.exceptions.RequestException as e:
        logger.error(f"[Vidu API] Error creating image to video task: {e}")
        if hasattr(e, 'response') and e.response is not None:
            logger.error(f"[Vidu API] Response Status Code: {e.response.status_code}")
            logger.error(f"[Vidu API] Response Body: {e.response.text}")
        return {
            "error": str(e),
            "status": "failed"
        }


def create_vidu_text_to_video(
    prompt: str,
    model: str = "viduq2-pro-fast",
    style: str = "general",
    duration: int = 5,
    seed: int = 0,
    aspect_ratio: str = "16:9",
    resolution: str = "720p",
    movement_amplitude: str = "auto"
):
    """
    Create Vidu text to video task
    
    使用文本提示词生成视频。
    
    Args:
        prompt: Text prompt for video generation
        model: Model name (default: "viduq1")
        style: Video style (default: "general")
        duration: Video duration in seconds (default: 5)
        seed: Random seed (default: 0)
        aspect_ratio: Video aspect ratio (default: "16:9")
        resolution: Video resolution (default: "1080p")
        movement_amplitude: Movement amplitude - "auto", "small", "medium", "large" (default: "auto")
    
    Returns:
        Response from the API with task_id
        Format: {"id": "task_id", "status": "processing", ...}
    """
    url = f"{base_url}/ent/v2/text2video"
    
    headers = {
        "Authorization": f"Token {api_key}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": model,
        "style": style,
        "prompt": prompt,
        "duration": str(duration),
        "seed": str(seed),
        "aspect_ratio": aspect_ratio,
        "resolution": resolution,
        "movement_amplitude": movement_amplitude
    }
    
    logger.info(f"[Vidu API] Request URL: {url}")
    logger.info(f"[Vidu API] Request Payload: {json.dumps(payload, ensure_ascii=False, indent=2)}")
    
    try:
        response = requests.post(url, json=payload, headers=headers)
        response.raise_for_status()
        result = response.json()
        
        logger.info(f"[Vidu API] Response: {json.dumps(result, ensure_ascii=False, indent=2)}")
        
        return result
    except requests.exceptions.RequestException as e:
        logger.error(f"[Vidu API] Error creating text to video task: {e}")
        if hasattr(e, 'response') and e.response is not None:
            logger.error(f"[Vidu API] Response Status Code: {e.response.status_code}")
            logger.error(f"[Vidu API] Response Body: {e.response.text}")
        return {
            "error": str(e),
            "status": "failed"
        }


def create_vidu_start_end_to_video(
    start_image_url: str,
    end_image_url: str,
    prompt: str,
    model: str = "viduq2-pro-fast",
    duration: int = 5,
    seed: int = 0,
    resolution: str = "720p",
    movement_amplitude: str = "auto"
):
    """
    Create Vidu start-end image to video task
    
    使用首尾两张图片生成视频，AI 会自动补充中间的过渡帧。
    
    Args:
        start_image_url: URL of the start image (首图)
        end_image_url: URL of the end image (尾图)
        prompt: Text prompt for video generation
        model: Model name (default: "viduq1")
        duration: Video duration in seconds (default: 5)
        seed: Random seed (default: 0)
        resolution: Video resolution (default: "1080p")
        movement_amplitude: Movement amplitude - "auto", "small", "medium", "large" (default: "auto")
    
    Returns:
        Response from the API with task_id
        Format: {"id": "task_id", "status": "processing", ...}
    """
    url = f"{base_url}/ent/v2/start-end2video"
    logger.info(f"[Vidu API] API_KEY: {api_key}")
    headers = {
        "Authorization": f"Token {api_key}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": model,
        "images": [start_image_url, end_image_url],
        "prompt": prompt,
        "duration": str(duration),
        "seed": str(seed),
        "resolution": resolution,
        "movement_amplitude": movement_amplitude
    }
    
    logger.info(f"[Vidu API] Request Payload: {json.dumps(payload, ensure_ascii=False, indent=2)}")
    
    try:
        response = requests.post(url, json=payload, headers=headers)
        response.raise_for_status()
        result = response.json()
        
        return result
    except requests.exceptions.RequestException as e:
        logger.error(f"[Vidu API] Error creating start-end to video task: {e}")
        if hasattr(e, 'response') and e.response is not None:
            logger.error(f"[Vidu API] Response Status Code: {e.response.status_code}")
            logger.error(f"[Vidu API] Response Body: {e.response.text}")
        return {
            "error": str(e),
            "status": "failed"
        }


def get_vidu_task_status(task_id: str):
    """
    Get Vidu task status
    
    Args:
        task_id: Task ID to check
    
    Returns:
        Response from the API with task status and result
        Format: {
            "id": "task_id",
            "status": "processing/completed/failed",
            "video_url": "url" (if completed),
            ...
        }
    """
    url = f"{base_url}/ent/v2/tasks/{task_id}/creations"
    
    headers = {
        "Authorization": f"Token {api_key}",
        "Content-Type": "application/json"
    }
    
    logger.info(f"[Vidu API] Status Check URL: {url}")
    logger.info(f"[Vidu API] Task ID: {task_id}")
    
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        result = response.json()
        
        logger.info(f"[Vidu API] Status Response: {json.dumps(result, ensure_ascii=False, indent=2)}")
        
        return result
    except requests.exceptions.RequestException as e:
        logger.error(f"[Vidu API] Error getting task status: {e}")
        if hasattr(e, 'response') and e.response is not None:
            logger.error(f"[Vidu API] Response Status Code: {e.response.status_code}")
            logger.error(f"[Vidu API] Response Body: {e.response.text}")
        return {
            "id": task_id,
            "status": "failed",
            "error": str(e)
        }
