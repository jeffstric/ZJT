"""
火山引擎（豆包语音）TTS 快速合成 + 音色库 API

路由（/api/tts）：
- GET  /voices            音色库列表（附带计价档位，前端本地算预计消耗）
- POST /synthesize        快速合成：计价→预检→预扣→调用火山→落盘→CDN→写 ai_audio
- GET  /preview/{voice_id} 试听固定示例句（免费，按音色落盘缓存）

计费：字符档位制预付费（与图像/视频惯例同构），
档位默认值在 config/volcengine_tts_constants.py，可由动态配置
volcengine_tts.power_tiers 热更新。合成失败立即按原流水退款（refund-{txn} 幂等）。
IndexTTS 克隆链路（/api/audio-generate）不受本文件影响，保持免费。
"""
import asyncio
import logging
import os
import uuid
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from config.config_util import get_config, get_dynamic_config_value
from config.constant import AI_AUDIO_STATUS_COMPLETED
from config.media_file_policy import MediaFilePolicy
from config.volcengine_tts_constants import (
    VolcengineTtsConstants,
    calc_volcengine_tts_power,
    normalize_volcengine_tts_speed,
)
from model.ai_audio import AIAudioModel
from model.media_file_mapping import MediaFileEntity
from model.voice import PROVIDER_VOLCENGINE, VoiceModel
from perseids_server.client import async_make_perseids_request
from perseids_server.utils.permission import require_permission
from utils.audio_duration_util import probe_audio_duration
from utils.media_mapping_util import register_uploaded_file_mapping
from utils.volcengine_tts_util import (
    build_audio_filename,
    get_volcengine_tts_config,
    is_tts_configured,
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
    server_host = (get_config().get("server", {}) or {}).get("host", "")
    rel = VolcengineTtsConstants.RESULT_SUBDIR.replace(os.sep, "/")
    return f"{str(server_host).rstrip('/')}/{rel}/{filename}"


async def _deduct_power(auth_header: str, power: int, transaction_id: str):
    """预扣算力；无 Authorization 或 0 算力视为跳过（开源惯例）。返回 (success, message)。"""
    if not auth_header or not power:
        return True, None
    try:
        success, message, _ = await async_make_perseids_request(
            endpoint='user/calculate_computing_power',
            method='POST',
            headers={'Authorization': auth_header},
            data={
                'computing_power': power,
                'behavior': 'deduct',
                'transaction_id': transaction_id,
            },
        )
        return bool(success), message
    except Exception as e:  # noqa: BLE001
        logger.error(f"火山TTS预扣算力失败: {e}")
        return False, str(e)


async def _refund_power(auth_header: str, power: int, transaction_id: str) -> None:
    """按原流水退款（increase + refund-{txn} 幂等）。退款失败只记日志，不影响错误返回。"""
    if not auth_header or not power:
        return
    try:
        success, message, _ = await async_make_perseids_request(
            endpoint='user/calculate_computing_power',
            method='POST',
            headers={'Authorization': auth_header},
            data={
                'computing_power': power,
                'behavior': 'increase',
                'transaction_id': f'refund-{transaction_id}',
            },
        )
        if not success:
            logger.error(f"火山TTS退款失败 txn={transaction_id} power={power}: {message}")
    except Exception as e:  # noqa: BLE001
        logger.error(f"火山TTS退款异常 txn={transaction_id} power={power}: {e}")


async def _check_power_sufficient(auth_header: str, power: int):
    """余额预检；无 Authorization 跳过。返回 (ok, message_or_none)。"""
    if not auth_header or not power:
        return True, None
    try:
        success, message, response_data = await async_make_perseids_request(
            endpoint='user/check_computing_power',
            method='GET',
            headers={'Authorization': auth_header},
        )
        if not success:
            return False, message or '算力查询失败'
        user_power = int(response_data.get('computing_power', 0) or 0)
        if user_power < power:
            return False, f"您的算力不足，需要 {power} 算力，当前仅有 {user_power} 算力"
        return True, None
    except Exception as e:  # noqa: BLE001
        logger.error(f"火山TTS算力预检失败: {e}")
        return False, str(e)


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
    """音色库列表（系统预置 + 当前用户私有），附带计价档位供前端本地算预计消耗。"""
    user_id = getattr(request.state, 'user_id', 0) or 0
    result = await asyncio.to_thread(
        VoiceModel.list_all,
        page=page,
        page_size=max(1, min(page_size, 200)),
        user_id=None,
        provider=PROVIDER_VOLCENGINE,
        gender=gender,
        language=language,
        only_active=True,
        keyword=keyword,
    )
    # 系统预置(user_id=0) 对所有人可见；私有音色仅属主可见
    voices = [v for v in result.get('data', []) if v.get('user_id') == 0 or v.get('user_id') == user_id]
    return JSONResponse({
        'success': True,
        'voices': voices,
        'total': result.get('total', 0),
        'power_tiers': [list(t) for t in _resolve_power_tiers()],
        'max_text_length': VolcengineTtsConstants.MAX_TEXT_LENGTH,
        'speed_min': VolcengineTtsConstants.SPEED_MIN,
        'speed_max': VolcengineTtsConstants.SPEED_MAX,
        'configured': is_tts_configured(get_volcengine_tts_config()),
    })


@router.post('/synthesize')
@require_permission("audio:generate")
async def synthesize(request: Request, body: TtsSynthesizeRequest):
    """快速合成：同步秒级返回 audio_url；按字符档位预扣算力，失败原路退款。"""
    text = (body.text or '').strip()
    if not text:
        return JSONResponse({'success': False, 'detail': '合成文本不能为空'}, status_code=400)
    char_count = len(text)
    if char_count > VolcengineTtsConstants.MAX_TEXT_LENGTH:
        return JSONResponse({
            'success': False,
            'detail': f"文本过长：{char_count} 字符，单次合成上限 {VolcengineTtsConstants.MAX_TEXT_LENGTH} 字符",
        }, status_code=400)

    voice = await asyncio.to_thread(VoiceModel.get_by_id, int(body.voice_id))
    if not voice or not voice.is_active or voice.provider != PROVIDER_VOLCENGINE or not voice.voice_type:
        return JSONResponse({'success': False, 'detail': '音色不存在或已下线，请刷新音色库'}, status_code=404)

    tiers = _resolve_power_tiers()
    power = calc_volcengine_tts_power(char_count, tiers)
    if power <= 0:
        return JSONResponse({
            'success': False,
            'detail': '语音合成计价未配置或文本超出最大档位，请联系管理员',
        }, status_code=400)

    auth_header = _normalize_authorization(request)

    ok, message = await _check_power_sufficient(auth_header, power)
    if not ok:
        return JSONResponse({'success': False, 'detail': message}, status_code=400)

    transaction_id = str(uuid.uuid4())
    ok, message = await _deduct_power(auth_header, power, transaction_id)
    if not ok:
        return JSONResponse({'success': False, 'detail': message or '算力扣除失败'}, status_code=400)

    speed = normalize_volcengine_tts_speed(body.speed_ratio)
    success, audio_bytes, synth_message = await synthesize_speech(
        text=text,
        speaker=voice.voice_type,
        speed_ratio=speed,
        timeout=VolcengineTtsConstants.TIMEOUT_SECONDS,
    )
    if not success:
        await _refund_power(auth_header, power, transaction_id)
        logger.error(f"火山TTS合成失败 voice={voice.voice_type} chars={char_count}: {synth_message}")
        return JSONResponse({'success': False, 'detail': synth_message}, status_code=502)

    # 落盘（同步文件写放线程池，避免阻塞事件循环）
    result_dir = await asyncio.to_thread(resolve_result_dir)
    filename = build_audio_filename("tts")
    file_path = os.path.join(result_dir, filename)

    def _write_file():
        tmp_path = file_path + '.tmp'
        with open(tmp_path, 'wb') as f:
            f.write(audio_bytes)
        os.replace(tmp_path, file_path)  # 原子替换，避免半文件被 CDN/播放读到

    try:
        await asyncio.to_thread(_write_file)
    except Exception as e:  # noqa: BLE001
        await _refund_power(auth_header, power, transaction_id)
        logger.error(f"火山TTS音频落盘失败: {e}")
        return JSONResponse({'success': False, 'detail': '音频保存失败，已退还算力'}, status_code=500)

    audio_url = _build_public_audio_url(filename)

    # CDN mapping 注册（失败不影响主流程，本地直出兜底）
    rel_path = f"{VolcengineTtsConstants.RESULT_SUBDIR.replace(os.sep, '/')}/{filename}"
    try:
        await asyncio.to_thread(
            register_uploaded_file_mapping,
            None,
            rel_path,
            MediaFileEntity.TTS,
            MediaFilePolicy.NEVER_EXPIRE,
            None,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning(f"火山TTS CDN 注册失败（不影响返回，本地直出兜底）: {e}")

    duration = await probe_audio_duration(file_path)

    user_id = getattr(request.state, 'user_id', None)
    try:
        audio_id = await asyncio.to_thread(
            AIAudioModel.create,
            text=text,
            user_id=user_id,
            transaction_id=transaction_id,
            result_url=audio_url,
            status=AI_AUDIO_STATUS_COMPLETED,
            message='火山TTS快速合成成功',
            speed=speed,
            engine=PROVIDER_VOLCENGINE,
            voice_id=voice.id,
        )
    except Exception as e:  # noqa: BLE001
        logger.error(f"火山TTS写入 ai_audio 历史失败（不影响返回）: {e}")
        audio_id = None

    return JSONResponse({
        'success': True,
        'audio_id': audio_id,
        'audio_url': audio_url,
        'duration': duration,
        'voice_id': voice.id,
        'voice_type': voice.voice_type,
        'char_count': char_count,
        'computing_power': power,
    })


@router.get('/preview/{voice_id}')
@require_permission("audio:generate")
async def preview_voice(request: Request, voice_id: int):
    """试听：固定示例句合成（免费），按音色落盘缓存，命中缓存不再调火山。"""
    voice = await asyncio.to_thread(VoiceModel.get_by_id, int(voice_id))
    if not voice or not voice.is_active or voice.provider != PROVIDER_VOLCENGINE or not voice.voice_type:
        return JSONResponse({'success': False, 'detail': '音色不存在或已下线'}, status_code=404)

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
