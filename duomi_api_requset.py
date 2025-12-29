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

def create_ai_image(model="gemini-2.5-pro-image-preview", prompt="", ratio="9:16", image_urls=None, image_size="1K"):
    """
    Generate AI image using NanoBanana API
    
    Args:
        model: Model type (default: "gemini-2.5-pro-image-preview")
        prompt: Text prompt for image generation
        ratio: Image aspect ratio (default: "9:16")
        image_urls: Optional image URLs
        image_size: Image resolution (default: "1K", options: "1K", "2K", "4K")
    
    Returns:
        Response from the API
    """
    url = "https://duomiapi.com/api/gemini/nano-banana-edit"
    
    payload = {
        "model": model,
        "prompt": prompt,
        "aspect_ratio": ratio,
        "image_urls": image_urls,
        "image_size": image_size,
    }

    headers = {
        "Content-Type": "application/json",
        "Authorization": token
    }
    
    response = requests.post(url, json=payload, headers=headers)
    return response.json()

def create_video_remix(video_id, prompt, aspect_ratio="16:9", duration=15):
    """
    Remix/re-edit an existing video using Sora2 API
    
    Args:
        video_id: ID of the video to remix
        prompt: Text prompt for video remix
        aspect_ratio: Video aspect ratio (default: "16:9")
        duration: Video duration in seconds (default: 15)
    
    Returns:
        Response from the API
    """
    url = f"https://duomiapi.com/v1/videos/{video_id}/remix"
    
    payload = {
        "model": "sora-2",
        "prompt": prompt,
        "aspect_ratio": aspect_ratio,
        "duration": duration
    }
    
    headers = {
        "Content-Type": "application/json",
        "Authorization": token
    }
    
    response = requests.post(url, json=payload, headers=headers)
    
    # Log response for debugging
    print(f"Remix API response status: {response.status_code}")
    print(f"Remix API response text: {response.text[:500]}")  # First 500 chars
    
    # Check if response is successful
    if response.status_code != 200:
        raise Exception(f"API returned status {response.status_code}: {response.text}")
    
    try:
        return response.json()
    except Exception as e:
        raise Exception(f"Failed to parse JSON response: {response.text[:200]}")

def create_character(timestamps, url=None, from_task=None, callback_url=None):
    """
    Create character generation task using SORA API
    
    Args:
        timestamps: Time range when character appears (format: "start,end", 1-3 seconds range)
        url: Video URL containing the character (not for real people)
        from_task: Task ID of a generated video (supports real people)
        callback_url: Optional callback URL
    
    Returns:
        Response from the API
    """
    api_url = "https://duomiapi.com/v1/characters"
    
    payload = {
        "timestamps": timestamps
    }
    
    if url:
        payload["url"] = url
    if from_task:
        payload["from_task"] = from_task
    if callback_url:
        payload["callback_url"] = callback_url
    
    headers = {
        "Content-Type": "application/json",
        "Authorization": token
    }
    
    response = requests.post(api_url, json=payload, headers=headers)
    
    # Log response for debugging
    print(f"Create character API response status: {response.status_code}")
    print(f"Create character API response text: {response.text[:1000] if response.text else 'EMPTY'}")
    
    try:
        return response.json()
    except Exception as e:
        print(f"Failed to parse create character response: {e}")
        return {"error": str(e), "raw_text": response.text[:500] if response.text else None}


def get_character_task_result(task_id):
    """
    Query character generation task result
    Uses the same endpoint as video tasks: /v1/videos/tasks/{task_id}
    
    Args:
        task_id: Character task ID
    
    Returns:
        Response format:
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
    api_url = f"https://duomiapi.com/v1/videos/tasks/{task_id}"
    
    headers = {
        "Authorization": token
    }
    
    response = requests.get(api_url, headers=headers)
    
    # Log response for debugging
    print(f"Character status API response status: {response.status_code}")
    print(f"Character status API response text: {response.text[:500] if response.text else 'EMPTY'}")
    
    try:
        return response.json()
    except Exception as e:
        print(f"Failed to parse character status response: {e}")
        return {
            "state": "processing",
            "message": "任务处理中..."
        }


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



