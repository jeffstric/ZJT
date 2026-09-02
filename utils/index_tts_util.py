"""
Index TTS Utility - Functions for interacting with TTS API
"""
import logging
import httpx
import traceback
import os
from typing import Optional, List
import yaml
from config.config_util import get_config_path
from utils.project_path import resolve_upload_url_to_local_path

logger = logging.getLogger(__name__)

def get_tts_api_url() -> str:
    """
    从配置文件获取 TTS API URL
    Returns:
        str: TTS API URL
    """
    try:
        config_file = get_config_path()
        with open(config_file, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
        return config.get("tts", {}).get("api_url", "http://47.98.190.124")
    except Exception as e:
        logger.warning(f"Failed to read TTS API URL from config: {e}, using default")
        return "http://47.98.190.124"

async def generate_audio(
    text: str,
    spk_audio_path: str,
    emo_control_method: int = 0,
    emo_ref_path: Optional[str] = None,
    emo_weight: float = 1.0,
    emo_vec: Optional[List[float]] = None,
    emo_text: Optional[str] = None,
    result_path: str = "",
    max_text_tokens_per_sentence: int = 120,
    timeout: int = 300
) -> tuple[bool, str]:
    """
    Generate audio using TTS API
    
    Args:
        text: Text to convert to speech
        spk_audio_path: Path or URL to speaker reference audio
        emo_control_method: Emotion control method (0-3)
            0: Same as voice reference audio
            1: Use emotion reference audio
            2: Use emotion vector control
            3: Use emotion description text control
        emo_ref_path: Path to emotion reference audio (optional)
        emo_weight: Emotion weight (0.0-1.0, default: 1.0)
        emo_vec: Emotion vector control (list of 8 floats, default: [0]*8)
        emo_text: Emotion description text (optional)
        result_path: Absolute path where the generated audio should be saved
        max_text_tokens_per_sentence: Maximum text tokens per sentence (default: 120)
        timeout: Request timeout in seconds (default: 300)
    
    Returns:
        tuple: (success: bool, audio_path_or_error: str)
            - success: True if generation succeeded, False otherwise
            - audio_path_or_error: Audio file path on success, error message on failure
    """
    try:
        # Get TTS API URL from config
        tts_api_url = get_tts_api_url()
        
        # Step 1: Upload reference audio to TTS server if it's a local file path
        # ref_path 在数据库中可能存为 /upload/...、upload/... 或完整 URL（含 host），
        # 直接 os.path.isfile() 会对带前导斜杠的路径在文件系统根解析而误判为 False，
        # 导致跳过上传、把不可达的路径透传给远程 TTS。这里先归一化为本地绝对路径再判断。
        uploaded_spk_audio_path = spk_audio_path
        local_spk_path = None
        if spk_audio_path:
            try:
                local_spk_path = resolve_upload_url_to_local_path(spk_audio_path)
            except ValueError:
                # 非法/绝对路径等解析失败时走下方 isfile 兜底（原逻辑中兜底不可达）
                local_spk_path = None
            if not (local_spk_path and os.path.isfile(local_spk_path)):
                if os.path.isfile(spk_audio_path):
                    local_spk_path = spk_audio_path
                else:
                    local_spk_path = None
        if local_spk_path and os.path.isfile(local_spk_path):
            logger.info(f"Uploading reference audio to TTS server: {local_spk_path}")
            upload_url = f"{tts_api_url}/upload_reference"
            
            async with httpx.AsyncClient() as client:
                with open(local_spk_path, 'rb') as audio_file:
                    files = {'file': (os.path.basename(local_spk_path), audio_file, 'audio/wav')}
                    upload_response = await client.post(
                        upload_url,
                        files=files,
                        timeout=60
                    )
                
                if upload_response.status_code == 200:
                    upload_data = upload_response.json()
                    if upload_data.get("status") == "ok":
                        uploaded_spk_audio_path = upload_data.get("file_path")
                        logger.info(f"Reference audio uploaded successfully: {uploaded_spk_audio_path}")
                    else:
                        error_msg = "Failed to upload reference audio: non-ok status"
                        logger.error(error_msg)
                        return False, error_msg
                else:
                    error_msg = f"Failed to upload reference audio: HTTP {upload_response.status_code}"
                    logger.error(error_msg)
                    return False, error_msg
        
        # Step 2: Upload emotion reference audio if provided and is a local file
        uploaded_emo_ref_path = emo_ref_path
        local_emo_path = None
        if emo_ref_path:
            try:
                local_emo_path = resolve_upload_url_to_local_path(emo_ref_path)
            except ValueError:
                local_emo_path = None
            if not (local_emo_path and os.path.isfile(local_emo_path)):
                if os.path.isfile(emo_ref_path):
                    local_emo_path = emo_ref_path
                else:
                    local_emo_path = None
        if local_emo_path and os.path.isfile(local_emo_path):
            logger.info(f"Uploading emotion reference audio to TTS server: {local_emo_path}")
            upload_url = f"{tts_api_url}/upload_reference"
            
            async with httpx.AsyncClient() as client:
                with open(local_emo_path, 'rb') as audio_file:
                    files = {'file': (os.path.basename(local_emo_path), audio_file, 'audio/wav')}
                    upload_response = await client.post(
                        upload_url,
                        files=files,
                        timeout=60
                    )
                
                if upload_response.status_code == 200:
                    upload_data = upload_response.json()
                    if upload_data.get("status") == "ok":
                        uploaded_emo_ref_path = upload_data.get("file_path")
                        logger.info(f"Emotion reference audio uploaded successfully: {uploaded_emo_ref_path}")
                    else:
                        error_msg = "Failed to upload emotion reference audio: non-ok status"
                        logger.error(error_msg)
                        return False, error_msg
                else:
                    error_msg = f"Failed to upload emotion reference audio: HTTP {upload_response.status_code}"
                    logger.error(error_msg)
                    return False, error_msg
        
        # Step 3: Prepare request data with uploaded paths
        if emo_vec is None:
            emo_vec = [0] * 8
        
        data = {
            "text": text,
            "spk_audio_path": uploaded_spk_audio_path,
            "emo_control_method": emo_control_method,
            "emo_ref_path": uploaded_emo_ref_path,
            "emo_weight": emo_weight,
            "emo_vec": emo_vec,
            "emo_text": emo_text,
            "result_path": result_path,
            "max_text_tokens_per_sentence": max_text_tokens_per_sentence
        }
        
        # Step 4: Make POST request to TTS API
        url = f"{tts_api_url}/tts_url"
        logger.info(f"Calling TTS API: {url}")
        logger.debug(f"Request data: {data}")
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                json=data,
                timeout=timeout
            )
        
        # Check response status
        if response.status_code == 200:
            # Success - parse JSON response to get audio path
            try:
                response_data = response.json()
                if response_data.get("status") == "ok":
                    audio_path = response_data.get("path", "")
                    logger.info(f"Successfully generated audio, path: {audio_path}")
                    return True, audio_path
                else:
                    error_msg = "TTS API returned non-ok status"
                    logger.error(error_msg)
                    return False, error_msg
            except Exception as e:
                error_msg = f"Failed to parse TTS API response: {str(e)}"
                logger.error(error_msg)
                return False, error_msg
        else:
            # Error response
            try:
                error_data = response.json()
                error_msg = error_data.get("error", "Unknown error")
            except:
                error_msg = response.text or f"HTTP {response.status_code}"
            
            logger.error(f"TTS API error: {error_msg}")
            return False, error_msg
    
    except httpx.TimeoutException:
        error_msg = f"TTS API request timeout after {timeout} seconds"
        logger.error(error_msg)
        return False, error_msg
    
    except httpx.ConnectError:
        error_msg = f"Failed to connect to TTS API at {tts_api_url}"
        logger.error(error_msg)
        return False, error_msg
    
    except Exception as e:
        error_msg = f"TTS API request failed: {str(e)}"
        logger.error(error_msg)
        logger.error(traceback.format_exc())
        return False, error_msg


def validate_emotion_vector(emo_vec: List[float]) -> tuple[bool, str]:
    """
    Validate emotion vector
    
    Args:
        emo_vec: Emotion vector (list of floats)
    
    Returns:
        tuple: (is_valid: bool, error_message: str)
    """
    if not isinstance(emo_vec, list):
        return False, "Emotion vector must be a list"
    
    if len(emo_vec) != 8:
        return False, "Emotion vector must have exactly 8 elements"
    
    vec_sum = sum(emo_vec)
    if vec_sum > 1.5:
        return False, "情感向量之和不能超过1.5，请调整后重试。"
    
    return True, ""
