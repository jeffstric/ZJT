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
    
token = config["ai_tools"]["token"]


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
    url = "https://zcbservice.aizfw.cn/kyyApi/apiAiProject/createSora2"
    
    payload = {
        "prompt": prompt,
        "ratio": ratio,
        "imgUrl": img_url,
        "duration": duration
    }
    
    headers = {
        "Content-Type": "application/json",
        "token": token
    }
    
    response = requests.post(url, json=payload, headers=headers)
    return response.json()


def get_ai_task_result(project_id):
    """
    Query AI task generation result
    
    Args:
        project_id: Project ID (string)
    
    Returns:
        Response from the API
    """
    url = "https://zcbservice.aizfw.cn/kyyApi/apiAiProject/getAiTaskResult"
    
    params = {
        "projectId": project_id
    }
    
    headers = {
        "token": token
    }
    
    response = requests.get(url, params=params, headers=headers)
    return response.json()


def create_ai_image(prompt, ratio="9:16", img_url=None):
    """
    Generate AI image using NanoBanana API
    
    Args:
        prompt: Text prompt for image generation
        ratio: Image aspect ratio (default: "9:16")
        img_url: Optional image URL
    
    Returns:
        Response from the API
    """
    url = "https://zcbservice.aizfw.cn/kyyApi/apiAiProject/createNanoBanana"
    
    payload = {
        "prompt": prompt,
        "ratio": ratio,
        "imgUrl": img_url
    }
    
    headers = {
        "Content-Type": "application/json",
        "token": token
    }
    
    response = requests.post(url, json=payload, headers=headers)
    return response.json()