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
import math
import os
import threading
import time
import uuid
from typing import Any, Dict, Optional

import httpx

from config.config_util import get_config
from config.constant import IMAGE_DESCRIBE_PREFERRED_MODEL, IMAGE_DESCRIBE_PREFERRED_VENDOR
from config.constant import (
    DIGITAL_HUMAN_H3_MAX_DURATION_SECONDS,
    DIGITAL_HUMAN_LTX_MAX_DURATION_SECONDS,
    DIGITAL_HUMAN_SPEECH_CHARS_PER_SECOND,
    TaskTypeId,
    TaskTypeRegistry,
)
from model.voice import VoiceModel
from services.volcengine_tts_service import synthesize_speech_for_user
from services.vl_gateway import call_vl, image_url_to_base64, pick_vl_model
from utils.audio_duration_util import probe_audio_duration
from utils.index_tts_util import generate_audio as indextts_generate_audio
from utils.volcengine_tts_util import get_volcengine_tts_config, is_tts_configured

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
    return max(4, min(10, int(math.ceil(seconds))))


def resolve_digital_human_model(est_seconds: float) -> Optional[Dict[str, Any]]:
    """按口播时长路由数字人模型（营销链路，>10s 自动走 LTX2.3）。

    - ≤10s → MiniMax H3（35），时长吸附 4-10 档位；
    - 10-30s → LTX2.3（32），时长=音频时长（向上取整，计费用）；
    - >30s → 返回 None（超出 LTX2.3 建议上限），调用方须拒绝并提示拆分文案。

    返回 dict 含 model_task_type / routing_reason / billable_duration。
    """
    if est_seconds <= DIGITAL_HUMAN_H3_MAX_DURATION_SECONDS:
        return {
            "model_task_type": TaskTypeId.DIGITAL_HUMAN_MINIMAX_H3,
            "routing_reason": "duration_lte_10s_h3",
            "billable_duration": clamp_h3_duration(est_seconds),
        }
    if est_seconds <= DIGITAL_HUMAN_LTX_MAX_DURATION_SECONDS:
        return {
            "model_task_type": TaskTypeId.DIGITAL_HUMAN_LTX2_3_VOICE,
            "routing_reason": "duration_gt_10s_ltx2_3",
            "billable_duration": max(1, int(math.ceil(est_seconds))),
        }
    return None


def _load_voice_candidates(language: str = "zh", provider: str = "volcengine") -> list:
    """加载激活的音色候选（name/gender/style/description 供 VL 挑选）"""
    result = VoiceModel.list_all(
        page=1, page_size=300, user_id=None, provider=provider,
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


def _default_reference_voice_id() -> Optional[int]:
    """默认预置音色（reference_audio 类第一个激活项）"""
    result = VoiceModel.list_all(
        page=1, page_size=1, user_id=None, provider="reference_audio",
        language="zh", only_active=True,
    )
    data = result.get("data") or []
    return data[0]["id"] if data else None


def _resolve_preset_local_path(audio_url: str) -> str:
    """预置音色站内相对路径（/voice_presets/x.mp3）→ 本地绝对路径"""
    from utils.project_path import get_project_root
    rel = audio_url.lstrip("/")
    return os.path.join(get_project_root(), rel.replace("/", os.sep))


async def _synthesize_via_indextts(user_id: int, text: str, ref_voice: Dict[str, Any]) -> Dict[str, Any]:
    """用预置音色（reference_audio）作克隆参考，经自建 IndexTTS 合成驱动音频。

    零火山依赖（TTS 未配置环境的降级路径）。返回与 volcengine 合成同构的 tts dict。
    """
    local_ref = _resolve_preset_local_path(ref_voice["audio_url"])
    if not os.path.isfile(local_ref):
        return {'success': False, 'error': f'预置音色音频缺失: {ref_voice["audio_url"]}',
                'computing_power': 0, 'audio_url': None, 'duration': None,
                'voice_name': ref_voice.get("name"), 'voice_type': None, 'voice_id': ref_voice.get("id")}

    filename = f"audio_{uuid.uuid4().hex[:8]}.wav"
    result_path = f"/home/appuser/comfyui_upload/tts/result_audio/{filename}"

    ok, path_or_err = await indextts_generate_audio(
        text=text,
        spk_audio_path=local_ref,
        result_path=result_path,
        timeout=180,
    )
    if not ok:
        return {'success': False, 'error': f'IndexTTS 克隆合成失败: {path_or_err}',
                'computing_power': 0, 'audio_url': None, 'duration': None,
                'voice_name': ref_voice.get("name"), 'voice_type': None, 'voice_id': ref_voice.get("id")}

    from config.config_util import get_dynamic_config_value
    upload_url = get_dynamic_config_value("tts", "upload_url") or ''
    audio_url = f"{upload_url}{filename}"

    duration = await probe_audio_duration(audio_url)

    return {
        'success': True, 'audio_url': audio_url, 'duration': duration,
        'computing_power': 0,  # IndexTTS 为自建服务，不计字符算力
        'voice_name': ref_voice.get("name"), 'voice_type': ref_voice.get("audio_url"),
        'voice_id': ref_voice.get("id"),
    }


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
            # 内网环境自访问 frp 公网地址不通：改用本地映射直读兜底一次
            from utils.image_upload_utils import try_map_url_to_local_file
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            local_path = try_map_url_to_local_file(image_url, get_config(), project_root)
            if local_path and os.path.isfile(local_path):
                logger.warning("VL 图片远程下载失败（%s），已改用本地映射文件: %s", err, local_path)
                ok, data_url, err = await image_url_to_base64(
                    image_url, compress_timeout=15, allow_remote=False,
                    remote_timeout=None, user_id=user_id, local_path=local_path,
                )
        if not ok or not data_url:
            return _fallback(f"默认音色（角色图读取失败：{err}）")

        import json as _json
        system_prompt = (
            "你是短视频选角导演。根据角色图片完成三件事：\n"
            "1. 判断图片中人物的性别（male=男性 / female=女性 / child=儿童）；\n"
            "2. 只在【与该性别一致的候选音色】中，挑选与人物年龄段、气质、场景感最匹配的一个——"
            "严禁挑选与人物性别不一致的音色（男性人物禁止选女声音色，反之亦然）；\n"
            "3. 为该人物撰写数字人视频的动作提示词：描述人物如何说话（情绪/表情）"
            "与镜头方式（如固定镜头/缓慢推近），参考格式："
            "'角色面向镜头深情的说话，固定镜头。'，30 字以内，不要出现具体台词。\n"
            '只输出 JSON：{"detected_gender": "<male|female|child>", '
            '"voice_id": <候选中的数字>, "reason": "<20字内理由>", '
            '"motion_prompt": "<动作提示词>"}'
        )
        requirement = f"\n用户对声音的额外要求：{voice_requirement}" if voice_requirement else ""
        user_text = (
            f"候选音色列表（JSON，含 gender 字段）：\n{_json.dumps(candidates, ensure_ascii=False)}{requirement}\n"
            "请完成性别判断、音色挑选与动作提示词撰写。"
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
        detected_gender = str(parsed.get("detected_gender", "")).strip().lower()
        valid_ids = {c["voice_id"] for c in candidates}
        if voice_id not in valid_ids:
            return _fallback("默认音色（视觉分析返回了候选之外的音色）")
        picked_voice = next(c for c in candidates if c["voice_id"] == voice_id)
        # 性别一致性硬校验：VL 偶发看错性别时，自动改选同性候选（防串音色）
        if (detected_gender and picked_voice.get("gender")
                and picked_voice["gender"] != detected_gender):
            same_gender = [c for c in candidates if c.get("gender") == detected_gender]
            if same_gender:
                alt = same_gender[0]
                logger.warning(
                    "VL 选音色性别不一致（detected=%s, picked=%s[%s]），自动改选同性候选 %s[%s]",
                    detected_gender, voice_id, picked_voice.get("gender"),
                    alt["voice_id"], alt.get("gender"))
                return {
                    "voice_id": alt["voice_id"],
                    "reason": f"性别校正：{str(parsed.get('reason', ''))[:40]}",
                    "motion_prompt": (str(parsed.get("motion_prompt", "")).strip()[:100]
                                      or default_motion),
                }
        logger.info(
            "VL 选音色：voice_id=%s name=%s gender=%s detected=%s reason=%s",
            voice_id, picked_voice.get("name"), picked_voice.get("gender"),
            detected_gender, str(parsed.get("reason", ""))[:50])
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
        volcengine_configured = is_tts_configured(get_volcengine_tts_config())
        selection_reason = "用户指定音色"
        motion_from_vl = None
        need_voice = not user_audio_url
        need_vl_analysis = (not motion_prompt) and bool(image_url) and (need_voice or not voice_id)
        if need_vl_analysis:
            # 候选按可用性选择：火山已配置→火山音色；未配置→免费预置音色（IndexTTS 克隆）
            candidate_provider = "volcengine" if volcengine_configured else "reference_audio"
            candidates = await asyncio.to_thread(_load_voice_candidates, "zh", candidate_provider)
            picked = await _pick_voice_by_image(image_url, candidates, int(user_id or 0), voice_requirement)
            motion_from_vl = picked.get("motion_prompt")
            if need_voice:
                voice_id = picked["voice_id"]
                selection_reason = f"VL 看图挑选：{picked['reason']}"
                if not voice_id:
                    return {'success': False, 'error': '未能确定音色（音色库为空），请联系管理员'}
        elif need_voice and voice_id:
            voice = VoiceModel.get_by_id(int(voice_id))
            if not voice or not voice.is_active:
                return {'success': False, 'error': f'音色 {voice_id} 不存在或已下线'}
            # 用户指定了火山音色但火山未配置：引导改用预置音色
            if voice.provider == 'volcengine' and not volcengine_configured:
                return {'success': False,
                        'error': '火山语音合成未配置，无法使用该音色。请改用免费预置音色（reference_audio 类）或提供驱动音频'}
        motion_prompt = motion_prompt or motion_from_vl or "角色面向镜头深情的说话，固定镜头。"

        # 3. 合成驱动音频（三个引擎按音色 provider 与配置分派）
        voice_row = VoiceModel.get_by_id(int(voice_id)) if voice_id else None
        if user_audio_url:
            tts = {
                'success': True, 'audio_url': user_audio_url, 'duration': None,
                'computing_power': 0, 'voice_name': '用户提供的驱动音频',
                'voice_type': None, 'voice_id': None,
            }
        elif voice_row and voice_row.provider == 'reference_audio' and voice_row.audio_url:
            # 免费预置音色：经自建 IndexTTS 克隆合成（零火山依赖、零算力）
            tts = await _synthesize_via_indextts(
                int(user_id or 0), script_text,
                {"id": voice_row.id, "name": voice_row.name, "audio_url": voice_row.audio_url})
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

        # 4. 口播时长与模型路由（≤10s 走 H3 档位；10-30s 走 LTX2.3；>30s 拒绝并提示拆分。
        #    见 docs/marketing_agent_digital_human_duration_routing_plan.md）
        est_seconds = float(tts.get('duration') or 0)
        if not est_seconds and user_audio_url:
            # 用户直供驱动音频缺实测时长：补一次探测，路由与计费都依赖它
            est_seconds = float(await probe_audio_duration(user_audio_url) or 0)
            tts['duration'] = est_seconds or None  # 回填实测时长供草案展示
        if not est_seconds:
            est_seconds = len(script_text) / DIGITAL_HUMAN_SPEECH_CHARS_PER_SECOND
        routing = resolve_digital_human_model(est_seconds)
        if routing is None:
            return {
                'success': False,
                'error': (f'口播时长约 {est_seconds:.1f} 秒，超出数字人支持上限 '
                          f'{DIGITAL_HUMAN_LTX_MAX_DURATION_SECONDS} 秒（LTX2.3 数字人）。'
                          f'请把文案拆分成多段后分次生成。'),
            }
        model_task_type = routing["model_task_type"]
        task_config = TaskTypeRegistry.get(model_task_type)
        model_name = task_config.name if task_config else str(model_task_type)
        billable = routing["billable_duration"]
        video_power = task_config.get_computing_power(duration=billable) if task_config else 0
        is_h3 = model_task_type == TaskTypeId.DIGITAL_HUMAN_MINIMAX_H3

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
            "model_task_type": model_task_type,
            "routing_reason": routing["routing_reason"],
            "billable_duration": billable,
            "video_computing_power": video_power,
            # 兼容旧字段：仅 H3 路由时填充，confirm 优先读新字段
            "h3_duration": billable if is_h3 else None,
            "h3_computing_power": video_power if is_h3 else 0,
            "max_edge": max_edge if max_edge in (720, 1280, 1920) else 1280,
            "aspect_ratio": aspect_ratio,
        }
        draft_id = _store_draft(draft)
        draft["draft_id"] = draft_id

        tts_cost_note = (f"已消耗 TTS 算力 {tts.get('computing_power')}；"
                         if not user_audio_url else "驱动音频由用户提供（无 TTS 消耗）；")
        ratio_note = ("；LTX2.3 模式下画幅跟随首帧图" if not is_h3 else "")
        return {
            'success': True,
            'draft': draft,
            'message': (
                f"数字人口播草案已就绪（draft_id: {draft_id}）。"
                f"将使用模型：{model_name}（按口播时长自动路由）；"
                f"音色：{draft['voice_name'] or '用户音频'}（{draft['voice_selection_reason']}）；"
                f"动作提示词：{motion_prompt}；"
                f"音频时长 {draft['audio_duration'] or billable}s；{tts_cost_note}"
                f"确认后生成视频将消耗 {video_power} 算力{ratio_note}。"
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
    """确认数字人口播草案：按草案路由提交 H3 / LTX2.3 生成视频（扣视频时长算力）。

    路由规则见 prepare_digital_human_draft：≤10s → MiniMax H3（/api/digital-human-minimax-h3），
    10-30s → LTX2.3（/api/digital-human-v2）。存量草案缺 model_task_type 时按 H3 处理。
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
        headers = {'Authorization': f'Bearer {auth_token}'} if auth_token else None

        # 下载图与音频为内存文件，multipart 转传 H3 端点。
        # ⚠️ 本服务产出的素材（/upload、/voice_presets、TTS 产物）优先直读本地文件：
        # server.host 可能是 frp 公网映射地址，服务器自身访问不通（实测 000）。
        from utils.image_upload_utils import try_map_url_to_local_file

        async def _fetch_asset_bytes(url: str) -> bytes:
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            local_path = try_map_url_to_local_file(url, get_config(), project_root)
            if local_path and os.path.isfile(local_path):
                with open(local_path, 'rb') as f:
                    return f.read()
            if url.startswith('/'):
                # 站内相对路径：按 web 静态目录与 upload 目录兜底解析
                for base in ('web', 'upload'):
                    cand = os.path.join(project_root, base, url.lstrip('/')) if base == 'web' else os.path.join(project_root, url.lstrip('/'))
                    if os.path.isfile(cand):
                        with open(cand, 'rb') as f:
                            return f.read()
            async with httpx.AsyncClient(timeout=60, verify=False, trust_env=False, follow_redirects=True) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                return resp.content

        try:
            image_bytes = await _fetch_asset_bytes(draft["image_url"])
            audio_bytes = await _fetch_asset_bytes(draft["audio_url"])
        except httpx.HTTPStatusError as e:
            detail = ''
            try:
                detail = e.response.json().get('detail', str(e))
            except Exception:  # noqa: BLE001
                detail = str(e)
            logger.error(f"数字人素材下载失败: {detail}")
            return {'success': False, 'error': f'数字人素材下载失败: {detail}'}
        except Exception as e:  # noqa: BLE001
            logger.error(f"数字人素材获取失败: {e}")
            return {'success': False, 'error': f'数字人素材获取失败: {str(e)}'}

        image_name = "digital_human_image.png"
        audio_name = "digital_human_audio.mp3"
        files = {
            'image': (image_name, image_bytes, 'image/png'),
            'audio': (audio_name, audio_bytes, 'audio/mpeg'),
        }

        # 按草案路由分派端点；存量草案（无 model_task_type）缺省 H3，行为与升级前一致
        model_task_type = draft.get("model_task_type") or TaskTypeId.DIGITAL_HUMAN_MINIMAX_H3
        billable = draft.get("billable_duration") or draft.get("h3_duration") or 10
        video_power = (draft.get("video_computing_power")
                       or draft.get("h3_computing_power") or 0)
        motion_text = (draft.get("motion_prompt")
                       or "角色面向镜头深情的说话，固定镜头。")[:1000]

        if model_task_type == TaskTypeId.DIGITAL_HUMAN_LTX2_3_VOICE:
            # LTX2.3 数字人：音频驱动，时长=音频时长；text 同样是动作提示词；
            # duration 供端点按时长计费（端点缺省时保持旧固定费率行为）
            api_url = f"{base_url.rstrip('/')}/api/digital-human-v2"
            model_used = 'LTX2.3 数字人'
            data = {
                'text': motion_text,
                'duration': str(billable),
                'user_id': str(user_id),
                'auth_token': auth_token or '',
            }
        else:
            api_url = f"{base_url.rstrip('/')}/api/digital-human-minimax-h3"
            model_used = 'MiniMax H3 数字人'
            data = {
                # H3 的 text 是「动作/镜头提示词」（口播内容在 audio 里，勿传口播文案）
                'text': motion_text,
                'duration': str(billable),
                'max_edge': str(draft.get("max_edge") or 1280),
                'start_second': '0',
                'user_id': str(user_id),
                'auth_token': auth_token or '',
            }

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
            'model_used': model_used,
            'model_task_type': model_task_type,
            'computing_power_required': video_power,
            'message': (
                f"数字人视频生成已提交（project_id: {project_id}，模型: {model_used}），"
                f"时长 {billable}s，已消耗视频算力 {video_power}。"
            ),
        }
    except Exception as e:  # noqa: BLE001
        logger.error(f"confirm_digital_human error: {e}", exc_info=True)
        return {'success': False, 'error': f'确认数字人生成异常: {str(e)}'}
