"""
火山引擎 TTS 合成服务（供 HTTP 接口与 Agent 工具共用）

从 api/tts.py 抽取的核心链路：校验 → 音色校验 → 计价 → 预检 → 预扣 →
调火山 2.0 → 落盘 → CDN → 写 ai_audio 历史。失败自动退款。
"""
import asyncio
import logging
import os
import uuid
from typing import Optional

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


def resolve_power_tiers():
    """计价档位：动态配置优先（DB → YAML），缺省回退代码默认。"""
    tiers = get_dynamic_config_value("volcengine_tts", "power_tiers")
    if isinstance(tiers, list) and tiers:
        return [(item[0], item[1]) for item in tiers
                if isinstance(item, (list, tuple)) and len(item) == 2]
    return VolcengineTtsConstants.POWER_TIERS


def build_public_audio_url(filename: str) -> str:
    """本地落盘文件对外 URL：{server_host}/upload/tts/volcengine/{filename}"""
    server_host = (get_config().get("server", {}) or {}).get("host", "")
    rel = VolcengineTtsConstants.RESULT_SUBDIR.replace(os.sep, "/")
    return f"{str(server_host).rstrip('/')}/{rel}/{filename}"


def normalize_authorization(auth_header: Optional[str]) -> str:
    """取标准化的 Bearer 头；空/无登录态返回空串（跳过算力扣减，开源惯例）。"""
    token = auth_header or ''
    if token and not token.startswith('Bearer '):
        token = f'Bearer {token}'
    return token


async def check_power_sufficient(auth_header: str, power: int):
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
        logger.error(f"算力预检失败: {e}")
        return False, str(e)


async def deduct_power(auth_header: str, power: int, transaction_id: str, message: Optional[str] = None):
    """预扣算力；无 Authorization 或 0 算力视为跳过（开源惯例）。返回 (success, message)。"""
    if not auth_header or not power:
        return True, None
    try:
        success, msg, _ = await async_make_perseids_request(
            endpoint='user/calculate_computing_power',
            method='POST',
            headers={'Authorization': auth_header},
            data={
                'computing_power': power,
                'behavior': 'deduct',
                'transaction_id': transaction_id,
                'message': message or '火山TTS语音合成',
            },
        )
        return bool(success), msg
    except Exception as e:  # noqa: BLE001
        logger.error(f"预扣算力失败: {e}")
        return False, str(e)


async def refund_power(auth_header: str, power: int, transaction_id: str, message: Optional[str] = None) -> None:
    """按原流水退款（increase + refund-{txn} 幂等）。失败只记日志。"""
    if not auth_header or not power:
        return
    try:
        success, msg, _ = await async_make_perseids_request(
            endpoint='user/calculate_computing_power',
            method='POST',
            headers={'Authorization': auth_header},
            data={
                'computing_power': power,
                'behavior': 'increase',
                'transaction_id': f'refund-{transaction_id}',
                'message': message or '火山TTS合成失败退款',
            },
        )
        if not success:
            logger.error(f"退款失败 txn={transaction_id} power={power}: {msg}")
    except Exception as e:  # noqa: BLE001
        logger.error(f"退款异常 txn={transaction_id} power={power}: {e}")


async def synthesize_speech_for_user(
    user_id: Optional[int],
    text: str,
    voice_id: int,
    speed_ratio: float = VolcengineTtsConstants.SPEED_DEFAULT,
    auth_header: str = "",
    message_context: str = "语音合成",
) -> dict:
    """TTS 快速合成完整链路（供 HTTP 接口与 Agent 工具共用）。

    Args:
        user_id: 用户 ID（写 ai_audio 历史）
        text: 合成文本
        voice_id: 音色库音色 ID（provider=volcengine）
        speed_ratio: 语速
        auth_header: 标准化 Bearer 头（空串 = 跳过算力扣减）
        message_context: 算力流水描述前缀（如"营销数字人口播"）

    Returns:
        dict: {success, audio_url, duration, audio_id, computing_power,
               voice_id, voice_name, voice_type, char_count, error}
    """
    result = {
        'success': False, 'audio_url': None, 'duration': None, 'audio_id': None,
        'computing_power': 0, 'voice_id': voice_id, 'voice_name': None,
        'voice_type': None, 'char_count': 0, 'error': None,
    }

    text = (text or '').strip()
    result['char_count'] = len(text)
    if not text:
        result['error'] = '合成文本不能为空'
        return result
    if len(text) > VolcengineTtsConstants.MAX_TEXT_LENGTH:
        result['error'] = f"文本过长：{len(text)} 字符，单次合成上限 {VolcengineTtsConstants.MAX_TEXT_LENGTH} 字符"
        return result

    voice = await asyncio.to_thread(VoiceModel.get_by_id, int(voice_id))
    if not voice or not voice.is_active or voice.provider != PROVIDER_VOLCENGINE or not voice.voice_type:
        result['error'] = '音色不存在或已下线，请刷新音色库'
        return result
    result['voice_name'] = voice.name
    result['voice_type'] = voice.voice_type

    if not is_tts_configured(get_volcengine_tts_config()):
        result['error'] = '火山语音合成未配置，请联系管理员填写 volcengine_tts.api_key'
        return result

    power = calc_volcengine_tts_power(len(text), resolve_power_tiers())
    if power <= 0:
        result['error'] = '语音合成计价未配置或文本超出最大档位，请联系管理员'
        return result
    result['computing_power'] = power

    auth_header = normalize_authorization(auth_header)

    ok, message = await check_power_sufficient(auth_header, power)
    if not ok:
        result['error'] = message
        return result

    transaction_id = str(uuid.uuid4())
    ok, message = await deduct_power(
        auth_header, power, transaction_id,
        message=f"{message_context}：{voice.name}（{len(text)}字）")
    if not ok:
        result['error'] = message or '算力扣除失败'
        return result

    speed = normalize_volcengine_tts_speed(speed_ratio)
    success, audio_bytes, synth_message = await synthesize_speech(
        text=text,
        speaker=voice.voice_type,
        speed_ratio=speed,
        timeout=VolcengineTtsConstants.TIMEOUT_SECONDS,
    )
    if not success:
        await refund_power(
            auth_header, power, transaction_id,
            message=f"{message_context}失败退款：{voice.name}（{len(text)}字）")
        logger.error(f"TTS合成失败 voice={voice.voice_type} chars={len(text)}: {synth_message}")
        result['error'] = synth_message
        return result

    result_dir = await asyncio.to_thread(resolve_result_dir)
    filename = build_audio_filename("tts")
    file_path = os.path.join(result_dir, filename)

    def _write_file():
        tmp_path = file_path + '.tmp'
        with open(tmp_path, 'wb') as f:
            f.write(audio_bytes)
        os.replace(tmp_path, file_path)

    try:
        await asyncio.to_thread(_write_file)
    except Exception as e:  # noqa: BLE001
        await refund_power(
            auth_header, power, transaction_id,
            message=f"{message_context}保存失败退款：{voice.name}（{len(text)}字）")
        logger.error(f"TTS音频落盘失败: {e}")
        result['error'] = '音频保存失败，已退还算力'
        return result

    audio_url = build_public_audio_url(filename)
    rel_path = f"{VolcengineTtsConstants.RESULT_SUBDIR.replace(os.sep, '/')}/{filename}"
    try:
        await asyncio.to_thread(
            register_uploaded_file_mapping,
            None, rel_path, MediaFileEntity.TTS, MediaFilePolicy.NEVER_EXPIRE, None,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning(f"TTS CDN 注册失败（本地直出兜底）: {e}")

    duration = await probe_audio_duration(file_path)

    try:
        audio_id = await asyncio.to_thread(
            AIAudioModel.create,
            text=text,
            user_id=user_id,
            transaction_id=transaction_id,
            result_url=audio_url,
            status=AI_AUDIO_STATUS_COMPLETED,
            message=f'{message_context}成功',
            speed=speed,
            engine=PROVIDER_VOLCENGINE,
            voice_id=voice.id,
        )
    except Exception as e:  # noqa: BLE001
        logger.error(f"TTS写入 ai_audio 历史失败（不影响返回）: {e}")
        audio_id = None

    result.update({
        'success': True,
        'audio_url': audio_url,
        'duration': duration,
        'audio_id': audio_id,
        'voice_id': voice.id,
    })
    return result
