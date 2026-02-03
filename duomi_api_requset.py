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
    
token = config["duomi"]["token"]

# Test mode configuration
test_mode_config = config.get("test_mode", {})
TEST_MODE_ENABLED = test_mode_config.get("enabled", False)
MOCK_VIDEOS = test_mode_config.get("mock_videos", {})
MOCK_IMAGES = test_mode_config.get("mock_images", {})


def _generate_mock_task_id():
    """生成测试模式的task_id，带有特殊前缀用于识别"""
    return f"mock_task_{uuid.uuid4().hex[:16]}_{int(time.time())}"


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
    # 测试模式：返回mock task_id
    if TEST_MODE_ENABLED:
        mock_task_id = _generate_mock_task_id()
        print(f"[TEST MODE] create_image_to_video - Generated mock task_id: {mock_task_id}")
        return {
            "id": mock_task_id,
            "state": "processing",
            "message": "Test mode - task created"
        }
    
    url = "https://duomiapi.com/v1/videos/generations"
    
    payload = {
        "model": "sora-2-temporary",
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
    
    logger.info(f"[Duomi Sora API] Request URL: {url}")
    logger.info(f"[Duomi Sora API] Request Payload: {json.dumps(payload, ensure_ascii=False, indent=2)}")
    
    try:
        response = requests.post(url, json=payload, headers=headers)
        response.raise_for_status()
        result = response.json()
        logger.info(f"[Duomi Sora API] Response: {json.dumps(result, ensure_ascii=False, indent=2)}")
        return result
    except requests.exceptions.RequestException as e:
        logger.error(f"[Duomi Sora API] Error creating image to video task: {e}")
        if hasattr(e, 'response') and e.response is not None:
            logger.error(f"[Duomi Sora API] Response Status Code: {e.response.status_code}")
            logger.error(f"[Duomi Sora API] Response Body: {e.response.text}")
        raise

def create_image_to_video_veo(prompt, ratio="9:16", img_url=None, duration=8):
    """
    Create video from image using Veo3.1-fast API
    
    Args:
        prompt: Text prompt for video generation
        ratio: Video aspect ratio (default: "9:16")
        img_url: Optional image URL
        duration: Video duration in seconds (default: 15)
    
    Returns:
        Response from the API
    """
    if TEST_MODE_ENABLED:
        mock_task_id = _generate_mock_task_id()
        print(f"[TEST MODE] create_image_to_video_veo - Generated mock task_id: {mock_task_id}")
        return {
            "id": mock_task_id,
            "state": "processing",
            "message": "Test mode - task created"
        }
    
    url = "https://duomiapi.com/v1/videos/generations"
    
    payload = {
        "model": "veo3.1-fast",
        "prompt": prompt,
        "aspect_ratio": ratio,
        "duration": duration,
        "image_urls": [
            img_url
        ],
        "generation_type":"FIRST&LAST"
    }
    
    headers = {
        "Content-Type": "application/json",
        "Authorization": token
    }
    
    logger.info(f"[Duomi Veo API] Request URL: {url}")
    logger.info(f"[Duomi Veo API] Request Payload: {json.dumps(payload, ensure_ascii=False, indent=2)}")
    
    try:
        response = requests.post(url, json=payload, headers=headers)
        response.raise_for_status()
        result = response.json()
        logger.info(f"[Duomi Veo API] Response: {json.dumps(result, ensure_ascii=False, indent=2)}")
        return result
    except requests.exceptions.RequestException as e:
        logger.error(f"[Duomi Veo API] Error creating image to video task: {e}")
        if hasattr(e, 'response') and e.response is not None:
            logger.error(f"[Duomi Veo API] Response Status Code: {e.response.status_code}")
            logger.error(f"[Duomi Veo API] Response Body: {e.response.text}")
        raise

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
    # 测试模式：返回mock task_id
    if TEST_MODE_ENABLED:
        mock_task_id = _generate_mock_task_id()
        print(f"[TEST MODE] create_ai_image - Generated mock task_id: {mock_task_id}")
        return {
            "code": 200,
            "msg": "success",
            "data": {
                "task_id": mock_task_id,
                "state": "processing",
                "message": "Test mode - task created"
            }
        }
    
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

def create_text_to_image(model="gemini-3-pro-image-preview", prompt="", aspect_ratio="auto", image_size=None):
    """
    Generate AI image from text using NanoBanana API (text-to-image)
    
    Args:
        model: Model type (default: "gemini-3-pro-image-preview")
               Options: "gemini-3-pro-image-preview", "nano-banana-pro", 
                       "gemini-2.5-pro-image-preview", "nano-banana"
        prompt: Text prompt for image generation
        aspect_ratio: Image aspect ratio (default: "auto")
                     Options: "auto", "1:1", "2:3", "3:2", "3:4", "4:3", 
                             "4:5", "5:4", "9:16", "16:9", "21:9"
        image_size: Image resolution (optional, only for gemini-3-pro-image-preview)
                   Format: "1K", "2K", "4K" (K must be uppercase)
    
    Returns:
        Response from the API
    """
    # 测试模式：返回mock task_id
    if TEST_MODE_ENABLED:
        mock_task_id = _generate_mock_task_id()
        print(f"[TEST MODE] create_text_to_image - Generated mock task_id: {mock_task_id}")
        return {
            "code": 200,
            "msg": "success",
            "data": {
                "task_id": mock_task_id,
                "state": "processing",
                "message": "Test mode - task created"
            }
        }
    
    url = "https://duomiapi.com/api/gemini/nano-banana"
    
    payload = {
        "model": model,
        "prompt": prompt,
        "aspect_ratio": aspect_ratio
    }
    
    if image_size and model == "gemini-3-pro-image-preview":
        payload["image_size"] = image_size

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
    
    logger.info(f"[Duomi Sora API] Request URL: {url}")
    logger.info(f"[Duomi Sora API] Request Payload: {json.dumps(payload, ensure_ascii=False, indent=2)}")
    
    try:
        response = requests.post(url, json=payload, headers=headers)
        response.raise_for_status()
        result = response.json()
        logger.info(f"[Duomi Sora API] Response: {json.dumps(result, ensure_ascii=False, indent=2)}")
        return result
    except requests.exceptions.RequestException as e:
        logger.error(f"[Duomi Sora API] Error creating video remix task: {e}")
        if hasattr(e, 'response') and e.response is not None:
            logger.error(f"[Duomi Sora API] Response Status Code: {e.response.status_code}")
            logger.error(f"[Duomi Sora API] Response Body: {e.response.text}")
        raise

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
    # 测试模式：检测mock task_id并返回配置的测试资源
    if TEST_MODE_ENABLED and isinstance(project_id, str) and project_id.startswith("mock_task_"):
        print(f"[TEST MODE] get_ai_task_result - Detected mock task_id: {project_id}")
        
        # 根据任务类型返回对应的mock资源
        if is_video:
            # 视频任务：返回配置的测试视频URL
            mock_video_url = MOCK_VIDEOS.get("image_to_video", "http://example.com/test_video.mp4")
            print(f"[TEST MODE] Returning mock video URL: {mock_video_url}")
        else:
            # 图片任务：返回配置的测试图片URL
            mock_image_url = MOCK_IMAGES.get("image_edit", "http://example.com/test_image.png")
            print(f"[TEST MODE] Returning mock image URL: {mock_image_url}")
        
        return {
            "code": 0,
            "msg": "success",
            "data": {
                "status": 1,  # 成功
                "mediaUrl": mock_video_url if is_video else mock_image_url,
                "reason": None
            }
        }
    
    if is_video:
        url = f"https://duomiapi.com/v1/videos/tasks/{project_id}"
    else:
        url = f"https://duomiapi.com/api/gemini/nano-banana/{project_id}"
    
    headers = {
        "Authorization": token
    }
    
    response = requests.get(url, headers=headers)
    raw_result = response.json()
    logger.info(f"get_ai_task_result response: {raw_result}")
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


def create_kling_image_to_video(
    image_url: str,
    prompt: str,
    mode: str = "std",
    duration: int = 5,
    model_name: str = "kling-v2-5-turbo",
    cfg_scale: float = 0.5,
    negative_prompt: str = ""
):
    """
    Create Kling image to video task
    
    Args:
        image_url: URL of the input image
        prompt: Text prompt for video generation
        mode: Mode - "std" (standard, 5s) or "pro" (professional, >5s)
        duration: Video duration in seconds (5 or 10)
        model_name: Model name (default: "kling-v2-5-turbo")
        cfg_scale: Creativity relevance, 0-1 (default: 0.5)
        negative_prompt: Negative prompt (optional)
    
    Returns:
        Response from the API with task_id
    """
    # 测试模式：返回mock task_id
    if TEST_MODE_ENABLED:
        mock_task_id = _generate_mock_task_id()
        print(f"[TEST MODE] create_kling_image_to_video - Generated mock task_id: {mock_task_id}")
        return {
            "code": 0,
            "message": "success",
            "data": {
                "task_id": mock_task_id
            }
        }
    
    url = "https://duomiapi.com/api/video/kling/v1/videos/image2video"
    
    headers = {
        "Authorization": token,
        "Content-Type": "application/json"
    }
    
    payload = {
        "model_name": model_name,
        "image": image_url,
        "prompt": prompt,
        "mode": mode,
        "duration": duration,
        "cfg_scale": cfg_scale
    }
    
    if negative_prompt:
        payload["negative_prompt"] = negative_prompt
    
    # 记录请求日志
    logger.info(f"[Duomi Kling API] Request URL: {url}")
    logger.info(f"[Duomi Kling API] Request Payload: {json.dumps(payload, ensure_ascii=False, indent=2)}")
    
    try:
        response = requests.post(url, json=payload, headers=headers)
        response.raise_for_status()
        result = response.json()
        
        # 记录响应日志
        logger.info(f"[Duomi Kling API] Response: {json.dumps(result, ensure_ascii=False, indent=2)}")
        
        return result
    except requests.exceptions.RequestException as e:
        logger.error(f"[Duomi Kling API] Error creating Kling video task: {e}")
        if hasattr(e, 'response') and e.response is not None:
            logger.error(f"[Duomi Kling API] Response Status Code: {e.response.status_code}")
            logger.error(f"[Duomi Kling API] Response Body: {e.response.text}")
        return {
            "code": -1,
            "message": str(e),
            "data": {}
        }


def get_kling_task_status(task_id: str):
    """
    Get Kling task status
    
    Args:
        task_id: Task ID to check
    
    Returns:
        Response from the API with task status and result
    """
    # 测试模式：返回mock结果
    if TEST_MODE_ENABLED:
        mock_video_url = MOCK_VIDEOS.get("image_to_video", "http://localhost:5178/upload/test_video.mp4")
        print(f"[TEST MODE] get_kling_task_status - task_id: {task_id}, returning mock video: {mock_video_url}")
        return {
            "code": 0,
            "message": "success",
            "data": {
                "task_id": task_id,
                "task_status": "succeed",
                "task_result": {
                    "videos": [
                        {
                            "id": "mock_video_id",
                            "url": mock_video_url,
                            "duration": "5"
                        }
                    ]
                }
            }
        }
    
    url = f"https://duomiapi.com/api/video/kling/v1/videos/image2video/{task_id}"
    
    headers = {
        "Authorization": token
    }
    
    # 记录请求日志
    logger.info(f"[Duomi Kling API] Status Check URL: {url}")
    logger.info(f"[Duomi Kling API] Task ID: {task_id}")
    
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        result = response.json()
        
        # 记录响应日志
        logger.info(f"[Duomi Kling API] Status Response: {json.dumps(result, ensure_ascii=False, indent=2)}")
        
        return result
    except requests.exceptions.RequestException as e:
        logger.error(f"[Duomi Kling API] Error getting Kling task status: {e}")
        return {
            "code": -1,
            "message": str(e),
            "data": {}
        }
