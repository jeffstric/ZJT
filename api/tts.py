"""
火山引擎（豆包语音）TTS 快速合成 + 音色库 API

路由（/api/tts）：
- GET  /voices            音色库列表（附带计价档位，前端本地算预计消耗）
- POST /synthesize        快速合成：计价→预检→预扣→调用火山→落盘→CDN→写 ai_audio
- GET  /preview/{voice_id} 试听固定示例句（免费，按音色落盘缓存）

核心合成链路在 services/volcengine_tts_service.py（与 Agent 工具共用）。
计费：字符档位制预付费，失败自动退款。IndexTTS 克隆链路不受影响。
"""
import asyncio
import logging
import os
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from config.config_util import get_config, get_config_value, get_dynamic_config_value
from config.volcengine_tts_constants import (
    VolcengineTtsConstants,
    normalize_volcengine_tts_speed,
)
from model.voice import PROVIDER_VOLCENGINE, VoiceModel
from perseids_server.utils.permission import require_permission
from utils.volcengine_tts_util import (
    get_volcengine_tts_config,
    resolve_result_dir,
    synthesize_speech,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/tts", tags=["tts"])


class TtsSynthesizeRequest(BaseModel):
    text: str
    voice_id: int
    speed_ratio: Optional[float] = VolcengineTtsConstants.SPEED_DEFAULT


def _normalize_authorization(request: Request) -> str:
    """取标准化的 Authorization 头；开源/无登录态场景返回空串（跳过算力扣减）。"""
    token = request.headers.get('Authorization') or ''
    if token and not token.startswith('Bearer '):
        token = f'Bearer {token}'
    return token


def _resolve_power_tiers():
    """计价档位：动态配置优先（DB → YAML），缺省回退代码默认。"""
    tiers = get_dynamic_config_value("volcengine_tts", "power_tiers")
    if isinstance(tiers, list) and tiers:
        return [(item[0], item[1]) for item in tiers
                if isinstance(item, (list, tuple)) and len(item) == 2]
    return VolcengineTtsConstants.POWER_TIERS


def _build_public_audio_url(filename: str) -> str:
    """本地落盘文件对外 URL：{server_host}/upload/tts/volcengine/{filename}"""
    from services.volcengine_tts_service import build_public_audio_url
    return build_public_audio_url(filename)


@router.get('/voices')
@require_permission("audio:generate")
async def list_voices(
    request: Request,
    gender: Optional[str] = None,
    language: Optional[str] = None,
    keyword: Optional[str] = None,
    page: int = 1,
    page_size: int = 100,
):
    """音色库列表（系统预置 + 当前用户私有），附带计价档位供前端本地算预计消耗。

    返回两类音色（provider 字段区分，前端按场景筛选）：
    - volcengine：火山 TTS 音色（音色库合成模式；受 configured 影响）
    - reference_audio：开源版自带 AI 合成预置音色（克隆参考 / H3 驱动，
      始终可用，不受火山克隆开关管控）
    """
    user_id = getattr(request.state, 'user_id', 0) or 0
    result = await asyncio.to_thread(
        VoiceModel.list_all,
        page=page,
        page_size=max(1, min(page_size, 300)),
        user_id=None,
        provider=PROVIDER_VOLCENGINE,
        gender=gender,
        language=language,
        only_active=True,
        keyword=keyword,
    )
    # 系统预置(user_id=0) 对所有人可见；私有音色仅属主可见
    voices = [v for v in result.get('data', []) if v.get('user_id') == 0 or v.get('user_id') == user_id]
    # 合并 reference_audio 预置音色（开源版自带，不受火山配置/开关管控）
    preset_result = await asyncio.to_thread(
        VoiceModel.list_all,
        page=1,
        page_size=300,
        user_id=None,
        provider='reference_audio',
        gender=gender,
        language=language,
        only_active=True,
        keyword=keyword,
    )
    voices += [v for v in preset_result.get('data', []) if v.get('user_id') == 0 or v.get('user_id') == user_id]
    # 克隆模式「从音色库选择」入口开关：仅从 YAML 配置读取（刻意不走
    # system_config，管理后台不可改），法律风险警示见 config.example.yml。
    allow_clone_from_library = bool(get_config_value(
        "volcengine_tts", "allow_clone_from_voice_library", default=False))
    return JSONResponse({
        'success': True,
        'voices': voices,
        'total': result.get('total', 0),
        'power_tiers': [list(t) for t in _resolve_power_tiers()],
        'max_text_length': VolcengineTtsConstants.MAX_TEXT_LENGTH,
        'speed_min': VolcengineTtsConstants.SPEED_MIN,
        'speed_max': VolcengineTtsConstants.SPEED_MAX,
        'allow_clone_from_voice_library': allow_clone_from_library,
        'configured': bool(get_volcengine_tts_config()['api_key']),
    })


@router.post('/synthesize')
@require_permission("audio:generate")
async def synthesize(request: Request, body: TtsSynthesizeRequest):
    """快速合成：同步秒级返回 audio_url；按字符档位预扣算力，失败原路退款。"""
    from services.volcengine_tts_service import synthesize_speech_for_user

    user_id = getattr(request.state, 'user_id', None)
    result = await synthesize_speech_for_user(
        user_id=user_id,
        text=body.text,
        voice_id=int(body.voice_id),
        speed_ratio=normalize_volcengine_tts_speed(body.speed_ratio),
        auth_header=_normalize_authorization(request),
        message_context="火山TTS语音合成",
    )
    if not result['success']:
        error = result['error'] or ''
        if '音色不存在' in error:
            status = 404
        elif ('不能为空' in error or '过长' in error or '算力' in error):
            status = 400
        else:
            status = 502
        return JSONResponse({'success': False, 'detail': error}, status_code=status)

    return JSONResponse({
        'success': True,
        'audio_id': result['audio_id'],
        'audio_url': result['audio_url'],
        'duration': result['duration'],
        'voice_id': result['voice_id'],
        'voice_type': result['voice_type'],
        'char_count': result['char_count'],
        'computing_power': result['computing_power'],
    })


@router.get('/preview/{voice_id}')
@require_permission("audio:generate")
async def preview_voice(request: Request, voice_id: int):
    """试听：固定示例句合成（免费），按音色落盘缓存，命中缓存不再调火山。"""
    voice = await asyncio.to_thread(VoiceModel.get_by_id, int(voice_id))
    if not voice or not voice.is_active:
        return JSONResponse({'success': False, 'detail': '音色不存在或已下线'}, status_code=404)

    # reference_audio 类预置音色：自带样例音频，直接返回（不走火山合成）
    if voice.provider == 'reference_audio' and voice.audio_url:
        audio_url = voice.audio_url
        if not audio_url.startswith(('http://', 'https://')):
            server_host = (get_config().get("server", {}) or {}).get("host", "")
            audio_url = f"{str(server_host).rstrip('/')}{audio_url}"
        return JSONResponse({'success': True, 'audio_url': audio_url, 'voice_id': voice.id})

    if voice.provider != PROVIDER_VOLCENGINE or not voice.voice_type:
        return JSONResponse({'success': False, 'detail': '音色不存在或已下线'}, status_code=404)

    from utils.volcengine_tts_util import resolve_result_dir, synthesize_speech

    result_dir = await asyncio.to_thread(resolve_result_dir)
    # voice_type 限定为音色库白名单内的火山 ID（迁移种子/运营录入），无路径分隔符风险
    filename = (f"{VolcengineTtsConstants.PREVIEW_FILENAME_PREFIX}{voice.voice_type}.mp3")
    cached_path = os.path.join(result_dir, filename)

    if not await asyncio.to_thread(os.path.isfile, cached_path):
        # 示例句按音色语言选择：外语音色喂中文文本会返回空音频（实测）
        preview_text = VolcengineTtsConstants.PREVIEW_TEXT_BY_LANGUAGE.get(
            voice.language, VolcengineTtsConstants.PREVIEW_TEXT)
        success, audio_bytes, message = await synthesize_speech(
            text=preview_text,
            speaker=voice.voice_type,
            speed_ratio=VolcengineTtsConstants.SPEED_DEFAULT,
            timeout=VolcengineTtsConstants.PREVIEW_TIMEOUT_SECONDS,
        )
        if not success:
            return JSONResponse({'success': False, 'detail': message}, status_code=502)

        def _write_preview():
            tmp_path = cached_path + '.tmp'
            with open(tmp_path, 'wb') as f:
                f.write(audio_bytes)
            os.replace(tmp_path, cached_path)

        try:
            await asyncio.to_thread(_write_preview)
        except Exception as e:  # noqa: BLE001
            logger.error(f"火山TTS试听缓存写入失败: {e}")
            return JSONResponse({'success': False, 'detail': '试听音频保存失败'}, status_code=500)

    return JSONResponse({
        'success': True,
        'audio_url': _build_public_audio_url(filename),
        'voice_id': voice.id,
    })
