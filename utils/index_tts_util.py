"""
Index TTS Utility - Functions for interacting with TTS API
"""
import logging
import httpx
import traceback
from typing import Optional, List

logger = logging.getLogger(__name__)

# TTS API configuration - should be set via environment or config
TTS_API_URL = "http://192.168.10.243:6007"  # Default, should be configured

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
        # Prepare request data
        if emo_vec is None:
            emo_vec = [0] * 8
        
        data = {
            "text": text,
            "spk_audio_path": spk_audio_path,
            "emo_control_method": emo_control_method,
            "emo_ref_path": emo_ref_path,
            "emo_weight": emo_weight,
            "emo_vec": emo_vec,
            "emo_text": emo_text,
            "result_path": result_path,
            "max_text_tokens_per_sentence": max_text_tokens_per_sentence
        }
        
        # Make POST request to TTS API
        url = f"{TTS_API_URL}/tts_url"
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
        error_msg = f"Failed to connect to TTS API at {TTS_API_URL}"
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
