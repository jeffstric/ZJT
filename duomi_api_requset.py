import requests
from config_util import get_config_path
import os
import yaml

config_path = get_config_path()
    
# Load config to get host
if not os.path.exists(config_path):
    raise FileNotFoundError(f"Configuration file not found: {config_path}")
    
with open(config_path, 'r', encoding='utf-8') as file:
    config = yaml.safe_load(file)
    
token = config["duomi"]["token"]


def create_image_to_video(prompt, ratio="9:16", img_url=None, duration=15):
    """
    Create video from image using Sora2 API
    
    Args:
        prompt: Text prompt for video generation
        ratio: Video aspect ratio (default: "9:16")
        img_url: Optional image URL
        duration: Video duration in seconds (default: 10)
    
    Returns:
        Response from the API
    """
    url = "https://duomiapi.com/v1/videos/generations"
    
    payload = {
        "model": "sora-2",
        "prompt": prompt,
        "aspect_ratio": ratio,
        "duration": duration,
        "image_urls": [
            img_url
        ]
    }
    
    headers = {
        "Content-Type": "application/json",
        "Authorization": token
    }
    
    response = requests.post(url, json=payload, headers=headers)
    return response.json()

def create_ai_image(model="gemini-2.5-pro-image-preview", prompt="", ratio="9:16", image_urls=None):
    """
    Generate AI image using NanoBanana API
    
    Args:
        model: Model type (default: "gemini-2.5-pro-image-preview")
        prompt: Text prompt for image generation
        ratio: Image aspect ratio (default: "9:16")
        img_url: Optional image URL
    
    Returns:
        Response from the API
    """
    url = "https://duomiapi.com/api/gemini/nano-banana-edit"
    
    payload = {
        "model": model,
        "prompt": prompt,
        "aspect_ratio": ratio,
        "image_urls": image_urls,
    }

    headers = {
        "Content-Type": "application/json",
        "Authorization": token
    }
    
    response = requests.post(url, json=payload, headers=headers)
    return response.json()

def get_ai_task_result(project_id, is_video):
    """
    Query AI task generation result
    
    Args:
        project_id: Project ID (string)
        is_video: Whether the task is a video task (boolean)
    
    Returns:
        Unified response format:
        {
            "code": 0 (success) or non-zero (error),
            "msg": "success" or error message,
            "data": {
                "status": 0 (processing) / 1 (success) / 2 (failed),
                "mediaUrl": "url to media file",
                "reason": "failure reason if failed"
            }
        }
    """
    if is_video:
        url = f"https://duomiapi.com/v1/videos/tasks/{project_id}"
    else:
        url = f"https://duomiapi.com/api/gemini/nano-banana/{project_id}"
    
    headers = {
        "Authorization": token
    }
    
    response = requests.get(url, headers=headers)
    raw_result = response.json()
    # Normalize the response format
    if is_video:
        # Video format: {"id": "...", "state": "succeeded/failed/processing", "data": {"videos": [...]}, ...}
        state = raw_result.get("state", "")
        message = raw_result.get("message", "")
        
        # Map state to status: processing->0, succeeded->1, failed->2
        if state == "succeeded":
            status = 1
            media_url = None
            videos = raw_result.get("data", {}).get("videos", [])
            if videos and len(videos) > 0:
                media_url = videos[0].get("url")
            
            return {
                "code": 0,
                "msg": "success",
                "data": {
                    "status": status,
                    "mediaUrl": media_url,
                    "reason": None
                }
            }
        elif state == "error":
            return {
                "code": 0,
                "msg": "success",
                "data": {
                    "status": 2,
                    "mediaUrl": None,
                    "reason": message or "Task failed"
                }
            }
        else:
            # processing or other states
            return {
                "code": 0,
                "msg": "success",
                "data": {
                    "status": 0,
                    "mediaUrl": None,
                    "reason": None
                }
            }
    else:
        # Image format: {"code": 200, "data": {"state": "succeeded/failed/processing", "data": {"images": [...]}, ...}}
        if raw_result.get("code") != 200:
            return {
                "code": raw_result.get("code", -1),
                "msg": raw_result.get("msg", "Unknown error"),
                "data": {}
            }
        
        data = raw_result.get("data", {})
        state = data.get("state", "")
        msg = data.get("msg", "")
        
        # Map state to status
        if state == "succeeded":
            status = 1
            media_url = None
            images = data.get("data", {}).get("images", [])
            if images and len(images) > 0:
                media_url = images[0].get("url")
            
            return {
                "code": 0,
                "msg": "success",
                "data": {
                    "status": status,
                    "mediaUrl": media_url,
                    "reason": None
                }
            }
        elif state == "error":
            return {
                "code": 0,
                "msg": "success",
                "data": {
                    "status": 2,
                    "mediaUrl": None,
                    "reason": msg or "Task failed"
                }
            }
        else:
            # processing or other states
            return {
                "code": 0,
                "msg": "success",
                "data": {
                    "status": 0,
                    "mediaUrl": None,
                    "reason": None
                }
            }



