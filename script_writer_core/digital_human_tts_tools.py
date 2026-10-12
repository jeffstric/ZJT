"""
营销数字人口播工具：TTS 选音色 + 音频合成 + MiniMax H3 数字人提交

两段式（确认制）：
- prepare_digital_human_draft：确定音色（VL 看图/指定/默认）→ 火山 TTS 合成
  驱动音频（扣 TTS 字符算力）→ 产出草案（draft_id），不提交视频
- confirm_digital_human：draft_id → 提交 MiniMax H3（扣视频时长算力）

草案存内存（TTL 30 分钟），会话内确认后即消费；服务重启失效可重新准备。
SOP 场景判定规则见 agents/skills/marketing-pm/sops/sop-digital-human.md。
"""
import asyncio
import json
import threading
import time
import uuid
from typing import Any, Dict, Optional

import httpx

from config.config_util import get_config
from config.constant import IMAGE_DESCRIBE_PREFERRED_MODEL, IMAGE_DESCRIBE_PREFERRED_VENDOR
from config.constant import TaskTypeId, TaskTypeRegistry
from model.voice import VoiceModel
from services.volcengine_tts_service import synthesize_speech_for_user
from services.vl_gateway import call_vl, image_url_to_base64, pick_vl_model

logger_name = "digital_human_tts_tools"

import logging

logger = logging.getLogger(logger_name)

# H3 视频时长档位（秒）与默认音色
H3_ALLOWED_DURATIONS = tuple(range(4, 11))
DEFAULT_VOICE_TYPE = "zh_female_vv_uranus_bigtts"  # Vivi 2.0

# 草案内存存储：{draft_id: {"draft": {...}, "expires_at": ts}}
_DRAFT_STORE: Dict[str, Dict[str, Any]] = {}
_DRAFT_LOCK = threading.Lock()
_DRAFT_TTL_SECONDS = 30 * 60
_DRAFT_MAX = 200


def _store_draft(draft: Dict[str, Any]) -> str:
    draft_id = f"dh-{uuid.uuid4().hex[:12]}"
    now = time.time()
    with _DRAFT_LOCK:
        # 清理过期
        expired = [k for k, v in _DRAFT_STORE.items() if v["expires_at"] < now]
        for k in expired:
            _DRAFT_STORE.pop(k, None)
        # 超上限时淘汰最旧
        if len(_DRAFT_STORE) >= _DRAFT_MAX:
            oldest = sorted(_DRAFT_STORE.items(), key=lambda kv: kv[1]["expires_at"])[0][0]
            _DRAFT_STORE.pop(oldest, None)
        _DRAFT_STORE[draft_id] = {"draft": draft, "expires_at": now + _DRAFT_TTL_SECONDS}
    return draft_id


def get_draft(draft_id: str) -> Optional[Dict[str, Any]]:
    with _DRAFT_LOCK:
        entry = _DRAFT_STORE.get(draft_id)
        if not entry or entry["expires_at"] < time.time():
            return None
        return dict(entry["draft"])


def consume_draft(draft_id: str) -> Optional[Dict[str, Any]]:
    """取出并移除草案（确认后一次性消费，防止重复提交）"""
    with _DRAFT_LOCK:
        entry = _DRAFT_STORE.pop(draft_id, None)
        if not entry or entry["expires_at"] < time.time():
            return None
        return dict(entry["draft"])


def clamp_h3_duration(seconds: float) -> int:
    """TTS 时长吸附到 H3 档位 4–10 秒（向上取整）"""
    if seconds <= 0:
        return 4
    import math
    return max(4, min(10, int(math.ceil(seconds))))


def _load_voice_candidates(language: str = "zh") -> list:
    """加载激活的火山中文音色候选（name/gender/style/description 供 VL 挑选）"""
    result = VoiceModel.list_all(
        page=1, page_size=300, user_id=None, provider="volcengine",
        language=language, only_active=True,
    )
    return [
        {
            "voice_id": v["id"],
            "name": v.get("name"),
            "gender": v.get("gender"),
            "style": v.get("style"),
            "description": (v.get("description") or "")[:60],
        }
        for v in (result.get("data") or [])
    ]


def _default_voice_id() -> Optional[int]:
    voice = VoiceModel.get_by_voice_type(DEFAULT_VOICE_TYPE)
    return voice.id if voice and voice.is_active else None


async def _pick_voice_by_image(
    image_url: str,
    candidates: list,
    user_id: Optional[int],
    voice_requirement: str = "",
) -> Dict[str, Any]:
    """VL 看角色图：挑选匹配音色 + 生成 H3 动作提示词。失败降级默认。

    返回 {"voice_id", "reason", "motion_prompt"}。
    """
    default_motion = "角色面向镜头深情的说话，固定镜头。"

    def _fallback(reason: str) -> Dict[str, Any]:
        # 惰性查库：仅在真正需要降级时才取默认音色
        return {"voice_id": _default_voice_id(), "reason": reason,
                "motion_prompt": default_motion}

    if not candidates:
        return _fallback("默认音色（候选为空）")
    try:
        picked = await pick_vl_model(IMAGE_DESCRIBE_PREFERRED_VENDOR, IMAGE_DESCRIBE_PREFERRED_MODEL)
        if not picked:
            return _fallback("默认音色（无可用视觉模型）")
        ok, data_url, err = await image_url_to_base64(
            image_url, compress_timeout=15, allow_remote=True,
            remote_timeout=30, user_id=user_id,
        )
        if not ok or not data_url:
            return _fallback(f"默认音色（角色图读取失败：{err}）")

        import json as _json
        system_prompt = (
            "你是短视频选角导演。根据角色图片完成两件事：\n"
            "1. 从候选音色列表中挑选与人物（性别/年龄段/气质）最匹配的一个；\n"
            "2. 为该人物撰写数字人视频的动作提示词：描述人物如何说话（情绪/表情）"
            "与镜头方式（如固定镜头/缓慢推近），参考格式："
            "'角色面向镜头深情的说话，固定镜头。'，30 字以内，不要出现具体台词。\n"
            '只输出 JSON：{"voice_id": <候选中的数字>, "reason": "<20字内理由>", '
            '"motion_prompt": "<动作提示词>"}'
        )
        requirement = f"\n用户对声音的额外要求：{voice_requirement}" if voice_requirement else ""
        user_text = (
            f"候选音色列表（JSON）：\n{_json.dumps(candidates, ensure_ascii=False)}{requirement}\n"
            "请完成音色挑选与动作提示词撰写。"
        )
        v_ok, content, v_err = await call_vl(
            system_prompt, user_text, data_url,
            model=picked.get("name"),
            vendor_id=picked.get("vendor_id"),
            model_id=picked.get("id"),
            llm_timeout=60,
            temperature=0.2,
            max_tokens=300,
        )
        if not v_ok or not content:
            return _fallback(f"默认音色（视觉分析失败：{v_err}）")

        # 解析 JSON（容忍 ```json 包裹）
        text = content.strip()
        if text.startswith("```"):
            text = text.strip("`").lstrip("json").strip()
        start, end = text.find("{"), text.rfind("}") + 1
        if start < 0 or end <= start:
            return _fallback("默认音色（视觉分析输出无法解析）")
        parsed = _json.loads(text[start:end])
        voice_id = int(parsed.get("voice_id", 0))
        valid_ids = {c["voice_id"] for c in candidates}
        if voice_id not in valid_ids:
            return _fallback("默认音色（视觉分析返回了候选之外的音色）")
        return {
            "voice_id": voice_id,
            "reason": str(parsed.get("reason", ""))[:60],
            "motion_prompt": (str(parsed.get("motion_prompt", "")).strip()[:100]
                              or default_motion),
        }
    except Exception as e:  # noqa: BLE001
        logger.warning(f"VL 选音色失败，降级默认音色: {e}")
        return _fallback("默认音色（视觉分析异常）")


async def prepare_digital_human_draft(
    user_id: str,
    world_id: str,
    auth_token: str,
    image_url: str,
    script_text: str,
    audio_url: str = None,
    voice_id: int = None,
    voice_requirement: str = "",
    motion_prompt: str = "",
    max_edge: int = 1280,
    aspect_ratio: str = "9:16",
) -> Dict[str, Any]:
    """准备数字人口播草案：确定音色 → TTS 合成驱动音频 → 产出草案（不提交视频）。

    用户提供驱动音频（audio_url，想让人物说这段音频）时跳过 TTS 与音色选择，
    直接以该音频出草案（不消耗 TTS 算力）。

    音色确定优先级（无 audio_url 时）：voice_id 显式指定 > VL 看角色图挑选 > 默认音色。
    动作提示词（H3 的 text 参数，描述说话情绪与镜头方式，不是口播内容）
    确定优先级：motion_prompt 显式指定 > VL 看角色图生成 > 默认
    （"角色面向镜头深情的说话，固定镜头。"）。
    script_text 必须是最终口播文案；用户未提供文案时请先生成文案再调用本工具。

    Args:
        image_url: 角色图片 URL（必填，须来自对话中用户上传或已生成的真实图片）
        script_text: 口播文案（必填，即数字人要说的内容，≤2000 字）
        audio_url: 用户提供的驱动音频 URL（可选；提供时跳过 TTS）
        voice_id: 音色库音色 ID（可选；给定则跳过 VL 挑选）
        voice_requirement: 对声音的要求描述（可选，如"成熟男性、纪录片感"）
        motion_prompt: 动作提示词（可选；如"角色面向镜头深情的说话，固定镜头。"）
        max_edge: 视频最长边 720/1280/1920（默认 1280）
        aspect_ratio: 视频比例（默认 9:16），仅透传给确认信息

    Returns:
        dict: success=True 时含 draft_id 与草案明细（文案/图/音色/试听URL/时长/两段算力）
    """
    try:
        if not image_url or not isinstance(image_url, str):
            return {'success': False, 'error': '角色图片 URL 不能为空'}
        if not script_text or not isinstance(script_text, str) or not script_text.strip():
            return {'success': False, 'error': '口播文案不能为空。请先生成或确认口播文案，再调用本工具'}
        script_text = script_text.strip()
        if len(script_text) > 2000:
            return {'success': False, 'error': '口播文案不能超过 2000 字'}
        motion_prompt = (motion_prompt or '').strip()[:200] or None

        # 1. 用户提供驱动音频：跳过音色选择与 TTS
        user_audio_url = (audio_url or '').strip() or None

        # 2. 确定音色与动作提示词（有用户音频时音色不需要，但动作提示词仍看图生成）
        selection_reason = "用户指定音色"
        motion_from_vl = None
        need_voice = not user_audio_url
        need_vl_analysis = (not motion_prompt) and bool(image_url) and (need_voice or not voice_id)
        if need_vl_analysis:
            candidates = await asyncio.to_thread(_load_voice_candidates, "zh")
            picked = await _pick_voice_by_image(image_url, candidates, int(user_id or 0), voice_requirement)
            motion_from_vl = picked.get("motion_prompt")
            if need_voice:
                voice_id = picked["voice_id"]
                selection_reason = f"VL 看图挑选：{picked['reason']}"
                if not voice_id:
                    return {'success': False, 'error': '未能确定音色（音色库为空），请联系管理员'}
        elif need_voice and voice_id:
            voice = VoiceModel.get_by_id(int(voice_id))
            if not voice or not voice.is_active or voice.provider != 'volcengine':
                return {'success': False, 'error': f'音色 {voice_id} 不存在或已下线'}
        motion_prompt = motion_prompt or motion_from_vl or "角色面向镜头深情的说话，固定镜头。"

        # 3. TTS 合成驱动音频（用户提供 audio_url 时跳过；扣字符算力；失败自动退款）
        if user_audio_url:
            tts = {
                'success': True, 'audio_url': user_audio_url, 'duration': None,
                'computing_power': 0, 'voice_name': '用户提供的驱动音频',
                'voice_type': None, 'voice_id': None,
            }
        else:
            tts = await synthesize_speech_for_user(
                user_id=int(user_id or 0),
                text=script_text,
                voice_id=int(voice_id),
                auth_header=f"Bearer {auth_token}" if auth_token else "",
                message_context="营销数字人口播",
            )
            if not tts.get('success'):
                return {'success': False, 'error': f"驱动音频合成失败：{tts.get('error')}"}

        # 4. 时长与 H3 算力预估（用户音频缺时长时按文案长度粗估：约 4 字/秒，clamp 4-10）
        est_seconds = float(tts.get('duration') or 0)
        if not est_seconds:
            est_seconds = max(4.0, min(10.0, len(script_text) / 4.0))
        duration = clamp_h3_duration(est_seconds)
        task_config = TaskTypeRegistry.get(TaskTypeId.DIGITAL_HUMAN_MINIMAX_H3)
        h3_power = task_config.get_computing_power(duration=duration) if task_config else 0

        draft = {
            "draft_id": None,  # store 后回填
            "script_text": script_text,
            "image_url": image_url,
            "voice_id": int(voice_id) if voice_id else None,
            "voice_name": tts.get('voice_name'),
            "voice_type": tts.get('voice_type'),
            "voice_selection_reason": selection_reason if not user_audio_url else "用户提供的驱动音频",
            "motion_prompt": motion_prompt,
            "audio_url": tts.get('audio_url'),
            "audio_duration": tts.get('duration'),
            "tts_computing_power": tts.get('computing_power'),
            "h3_duration": duration,
            "h3_computing_power": h3_power,
            "max_edge": max_edge if max_edge in (720, 1280, 1920) else 1280,
            "aspect_ratio": aspect_ratio,
        }
        draft_id = _store_draft(draft)
        draft["draft_id"] = draft_id

        tts_cost_note = (f"已消耗 TTS 算力 {tts.get('computing_power')}；"
                         if not user_audio_url else "驱动音频由用户提供（无 TTS 消耗）；")
        return {
            'success': True,
            'draft': draft,
            'message': (
                f"数字人口播草案已就绪（draft_id: {draft_id}）。"
                f"音色：{draft['voice_name'] or '用户音频'}（{draft['voice_selection_reason']}）；"
                f"动作提示词：{motion_prompt}；"
                f"音频时长 {draft['audio_duration'] or duration}s；{tts_cost_note}"
                f"确认后生成视频将消耗 {h3_power} 算力。"
                f"请向用户展示草案（文案/音色/试听链接 {draft['audio_url']}）并等待用户确认，"
                f"用户确认后调用 confirm_digital_human 提交生成。"
            ),
        }
    except Exception as e:  # noqa: BLE001
        logger.error(f"prepare_digital_human_draft error: {e}", exc_info=True)
        return {'success': False, 'error': f'准备数字人草案异常: {str(e)}'}


async def confirm_digital_human(
    user_id: str,
    world_id: str,
    auth_token: str,
    draft_id: str,
) -> Dict[str, Any]:
    """确认数字人口播草案：提交 MiniMax H3 生成视频（扣视频时长算力）。

    仅在用户明确确认后调用。草案一次性消费，重复调用返回失败。

    Args:
        draft_id: prepare_digital_human_draft 返回的草案 ID

    Returns:
        dict: success=True 时含 project_ids 与视频任务信息
    """
    try:
        draft = consume_draft(str(draft_id))
        if not draft:
            return {'success': False, 'error': '草案不存在、已提交或已过期（30分钟有效）。请重新调用 prepare_digital_human_draft 准备'}

        server_config = get_config().get("server", {})
        base_url = server_config.get("comfyui_base_url_inner") or server_config.get("host", "")
        if not base_url:
            return {'success': False, 'error': '配置文件中未找到服务器地址'}

        # 下载图与音频为内存文件，multipart 转传 H3 端点
        headers = {'Authorization': f'Bearer {auth_token}'} if auth_token else None
        try:
            async with httpx.AsyncClient(timeout=60, verify=False, trust_env=False) as client:
                img_resp = await client.get(draft["image_url"])
                img_resp.raise_for_status()
                image_bytes = img_resp.content
                audio_resp = await client.get(draft["audio_url"])
                audio_resp.raise_for_status()
                audio_bytes = audio_resp.content
        except httpx.HTTPStatusError as e:
            detail = ''
            try:
                detail = e.response.json().get('detail', str(e))
            except Exception:  # noqa: BLE001
                detail = str(e)
            logger.error(f"数字人素材下载失败: {detail}")
            return {'success': False, 'error': f'数字人素材下载失败: {detail}'}

        image_name = "digital_human_image.png"
        audio_name = "digital_human_audio.mp3"
        files = {
            'image': (image_name, image_bytes, 'image/png'),
            'audio': (audio_name, audio_bytes, 'audio/mpeg'),
        }
        data = {
            # H3 的 text 是「动作/镜头提示词」（口播内容在 audio 里，勿传口播文案）
            'text': (draft.get("motion_prompt") or "角色面向镜头深情的说话，固定镜头。")[:1000],
            'duration': str(draft["h3_duration"]),
            'max_edge': str(draft["max_edge"]),
            'start_second': '0',
            'user_id': str(user_id),
            'auth_token': auth_token or '',
        }
        api_url = f"{base_url.rstrip('/')}/api/digital-human-minimax-h3"
        try:
            resp = await asyncio.to_thread(
                httpx.post, api_url, data=data, files=files,
                headers=headers, timeout=120, verify=False, trust_env=False,
            )
            resp.raise_for_status()
            result_data = resp.json()
        except httpx.HTTPStatusError as e:
            try:
                detail = e.response.json().get('detail', str(e))
            except Exception:  # noqa: BLE001
                detail = str(e)
            logger.error(f"数字人 H3 API 错误: {detail}")
            return {'success': False, 'error': f'数字人生成请求失败: {detail}'}

        if not result_data.get('success'):
            return {'success': False, 'error': result_data.get('error', '数字人生成请求失败')}

        project_id = result_data.get('project_id')
        if not project_id:
            return {'success': False, 'error': '数字人生成请求成功但未返回 project_id'}

        return {
            'success': True,
            'project_ids': [str(project_id)],
            'status': 'submitted',
            'model_used': 'MiniMax H3 数字人',
            'computing_power_required': draft["h3_computing_power"],
            'message': (
                f"数字人视频生成已提交（project_id: {project_id}），"
                f"时长 {draft['h3_duration']}s，已消耗视频算力 {draft['h3_computing_power']}。"
            ),
        }
    except Exception as e:  # noqa: BLE001
        logger.error(f"confirm_digital_human error: {e}", exc_info=True)
        return {'success': False, 'error': f'确认数字人生成异常: {str(e)}'}
