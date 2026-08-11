"""
Storyboard digital-human (lip-sync) generation — MiniMax H3 单模型。

分镜对口型统一提交 MiniMax H3（task_type=35）：
图片=选中首帧，音频=成片 TTS，提示词=动作描述，
时长 clamp 到 4–10 秒，最长边由分辨率偏好映射。

所有入口（直接 API / Agent / CLI / 批量补全）必须先调用
``orchestrate_digital_human_generation`` 生成统一计划，再扣费、再提交。

异步契约：本模块是同步领域服务；处于事件循环中的调用方必须用
``asyncio.to_thread(orchestrate_digital_human_generation, ...)`` 包装完整的
「解析、探测、准备、提交」链路，不得只包装数据库查询。
"""
from __future__ import annotations

import json
import logging
import math
import os
import subprocess
import urllib.request
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from config.config_util import get_config_value, resolve_bin_path
from config.constant import (
    AI_TOOL_STATUS_PENDING,
    TASK_STATUS_QUEUED,
    TASK_TYPE_GENERATE_VIDEO,
    StoryboardDigitalHumanConstants as _DHC,
    StoryboardDigitalHumanConstants,
    StoryboardTimeouts,
)
from config.unified_config import SceneVideoType, TaskTypeId, UnifiedConfigRegistry
from model.ai_tools import AIToolsModel
from model.storyboard import (
    StoryboardDialogueModel,
    StoryboardModel,
    StoryboardSceneAssetModel,
    StoryboardSceneModel,
)
from model.tasks import TasksModel
from services.storyboard_scene_type import count_speaking_characters

logger = logging.getLogger(__name__)


class StoryboardDigitalHumanError(Exception):
    """Expected validation error when submitting digital-human video."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 400,
        payload: Optional[dict] = None,
    ):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.payload = payload or {}

    def to_dict(self) -> dict:
        body = {
            "success": False,
            "error": self.message,
            "error_code": self.code,
            "reason": self.code,
        }
        if self.payload:
            body.update(self.payload)
        return body


# --------------------------------------------------------------------------- #
# 数据结构
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class DigitalHumanGenerationPlan:
    """不可变的数字人生成计划。所有入口先生成计划，再扣费、再建单。"""

    model: str  # 'minimax_h3'
    task_type: int  # TaskTypeId.DIGITAL_HUMAN_MINIMAX_H3 = 35
    speaker_character_id: int
    speech_text: str  # 按对白顺序拼接的完整讲话内容（元数据）
    speech_duration: Optional[float]  # TTS 总时长；无法识别时为 None
    first_frame_path: str  # 当前分镜已选中的首帧图
    ratio: str  # 工作流比例，仅元数据（MiniMax 无 aspect 节点）
    billable_duration: float  # clamp 后的 4–10，用于计费与驱动 duration
    prompt: str  # 动作描述提示词
    audio_input: str  # 最终传给驱动的说话音频
    audio_input_role: str  # 恒为 speech_audio
    routing_reason: str  # 可观测原因（现为 minimax_h3_only）
    resolution: str = _DHC.DEFAULT_RESOLUTION  # 480P/720P/1080P
    max_edge: int = _DHC.DEFAULT_MAX_EDGE  # 720/1280/1920
    start_second: int = _DHC.DEFAULT_START_SECOND
    duration_clamp_reason: str = "none"  # none | floor_to_4 | ceil_to_10


@dataclass(frozen=True)
class TtsSegment:
    """一段已选中的 TTS 音频元数据（纯读取，不做 IO）。"""

    dialogue_id: int
    audio_url: str
    duration: Optional[float]  # 已知时长（秒）；未知为 None


# --------------------------------------------------------------------------- #
# 小工具
# --------------------------------------------------------------------------- #
def _get_field(obj: Any, key: str, default=None):
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _round_ms(seconds: Optional[float]) -> Optional[float]:
    """按毫秒精度规整，避免浮点误差导致阈值边界（1.000s）误分配。"""
    if seconds is None:
        return None
    try:
        return round(float(seconds), 3)
    except (TypeError, ValueError):
        return None


def list_scene_dialogues(scene_id: int) -> List[dict]:
    return StoryboardDialogueModel.list_by_scene(int(scene_id)) or []


def _get_ffmpeg_path() -> str:
    """从主配置文件读取 ffmpeg 路径。"""
    ffmpeg = get_config_value("bin", "ffmpeg", default="ffmpeg")
    return resolve_bin_path(ffmpeg, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# --------------------------------------------------------------------------- #
# 流水线 step 1：解析对白与说话角色
# --------------------------------------------------------------------------- #
def resolve_digital_human_dialogues(
    scene_id: int,
    *,
    character_id: Optional[int] = None,
) -> Tuple[int, List[dict]]:
    """
    校验单说话角色，按 ``sort_order, id`` 顺序返回该角色的全部有效对白。

    Returns:
        (speaker_character_id, ordered_dialogues)

    Raises:
        StoryboardDigitalHumanError: 无对白 / 多说话角色 / 无已完成音频。
    """
    dialogues = list_scene_dialogues(scene_id)
    non_empty = [d for d in dialogues if str(d.get("text") or "").strip()]
    if not non_empty:
        raise StoryboardDigitalHumanError(
            _DHC.ERROR_NO_DIALOGUE,
            "无对白，无法生成对口型视频",
        )

    speaker_count, sole = count_speaking_characters(non_empty)
    if speaker_count != 1:
        raise StoryboardDigitalHumanError(
            _DHC.ERROR_MULTI_SPEAKER,
            "多人对话分镜不支持对口型，请使用图生视频或拆成单人分镜",
            payload={"speaker_count": speaker_count},
        )

    effective_character_id = character_id if character_id is not None else sole
    if effective_character_id is None:
        raise StoryboardDigitalHumanError(
            _DHC.ERROR_NO_DIALOGUE,
            "对白缺少说话角色，无法生成对口型视频",
        )

    # 仅取该说话角色的对白（旁白 character_id 为 None 已被 count_speaking_characters 忽略）
    speaker_dialogues = [
        d for d in non_empty
        if d.get("character_id") is not None
        and int(d.get("character_id")) == int(effective_character_id)
    ]
    if not speaker_dialogues:
        raise StoryboardDigitalHumanError(
            _DHC.ERROR_NO_DIALOGUE,
            "无对白，无法生成对口型视频",
        )

    # 校验：至少有一条已完成且已选中的 TTS
    has_completed = any(
        str(d.get("audio_url") or "").strip() and d.get("selected_audio_id")
        for d in speaker_dialogues
    )
    if not has_completed:
        # 区分 pending vs missing
        pending_like = [
            d for d in speaker_dialogues
            if d.get("selected_audio_id") and not str(d.get("audio_url") or "").strip()
        ]
        if pending_like:
            raise StoryboardDigitalHumanError(
                _DHC.ERROR_AUDIO_PENDING,
                "配音生成中，请完成后再生成对口型视频",
            )
        raise StoryboardDigitalHumanError(
            _DHC.ERROR_AUDIO_REQUIRED,
            "请先生成配音后再生成对口型视频",
        )

    return int(effective_character_id), speaker_dialogues


# --------------------------------------------------------------------------- #
# 流水线 step 2：加载 TTS 元数据（纯 DB，无 IO）
# --------------------------------------------------------------------------- #
def load_digital_human_tts_metadata(dialogues: List[dict]) -> List[TtsSegment]:
    """
    只读取数据库中的 TTS URL、选中指针和已保存时长。
    不下载文件、不运行 ffprobe、不合并音频。
    """
    segments: List[TtsSegment] = []
    for d in dialogues:
        audio_url = str(d.get("audio_url") or "").strip()
        if not audio_url or not d.get("selected_audio_id"):
            continue
        raw_dur = d.get("audio_duration")
        if raw_dur is None:
            raw_dur = d.get("duration")
        try:
            duration = float(raw_dur) if raw_dur is not None else None
        except (TypeError, ValueError):
            duration = None
        segments.append(
            TtsSegment(
                dialogue_id=int(d.get("id") or 0),
                audio_url=audio_url,
                duration=_round_ms(duration),
            )
        )
    return segments


# --------------------------------------------------------------------------- #
# 流水线 step 3：探测缺失时长（仅 ffprobe，不下载/合并）
# --------------------------------------------------------------------------- #
def probe_missing_digital_human_tts_durations(
    segments: List[TtsSegment],
) -> List[TtsSegment]:
    """
    仅对数据库时长缺失的 TTS 执行 ffprobe，返回补全后的时长元数据。
    不下载或合并音频。ffprobe 复用 utils.audio_duration_util 的同步实现。
    """
    if not segments:
        return segments
    from utils.audio_duration_util import get_audio_duration_seconds

    probed: List[TtsSegment] = []
    for seg in segments:
        if seg.duration is not None and seg.duration > 0:
            probed.append(seg)
            continue
        duration = get_audio_duration_seconds(seg.audio_url)
        probed.append(
            TtsSegment(
                dialogue_id=seg.dialogue_id,
                audio_url=seg.audio_url,
                duration=_round_ms(duration) if (duration is not None and duration > 0) else None,
            )
        )
    return probed


# --------------------------------------------------------------------------- #
# 流水线 step 4：生成计划（路由决策）
# --------------------------------------------------------------------------- #
def _sum_tts_duration(segments: List[TtsSegment]) -> Tuple[Optional[float], bool]:
    """累计全部 TTS 时长。返回 (total, any_unknown)。"""
    total = 0.0
    any_unknown = False
    for seg in segments:
        if seg.duration is None or seg.duration <= 0:
            any_unknown = True
            continue
        total += float(seg.duration)
    if any_unknown:
        return None, True
    return _round_ms(total), False


def _resolve_first_frame_path(scene) -> str:
    """只使用当前分镜已选中且已生成完成的首帧图。"""
    first_frame_id = _get_field(scene, "selected_first_frame_id")
    if first_frame_id:
        asset = StoryboardSceneAssetModel.get_by_id(int(first_frame_id))
        url = _get_field(asset, "result_url") if asset else None
        # asset.result_url 是冗余字段，智能体/宫格生成的首帧常不回填（恒为 NULL）；
        # 与 assets 接口、generate-video 路由一致，用 ai_tool.result_url 兜底。
        if (not url or not str(url).strip()) and _get_field(asset, "ai_tool_id"):
            tool = AIToolsModel.get_by_id(int(_get_field(asset, "ai_tool_id")))
            url = _get_field(tool, "result_url") if tool else None
        if url and str(url).strip():
            return str(url).strip()
    raise StoryboardDigitalHumanError(
        _DHC.ERROR_MISSING_IMAGE,
        "对口型需要已生成完成的选中首帧图片",
    )


def resolve_max_edge_from_resolution(resolution: Optional[str]) -> Tuple[str, int]:
    """分辨率偏好 → (规范化 resolution 标签, max_edge)。"""
    raw = (str(resolution).strip() if resolution is not None else "") or _DHC.DEFAULT_RESOLUTION
    key = raw.upper().replace(" ", "")
    # 480p / 720P / 1080P
    if key.endswith("P") and key[:-1].isdigit():
        pass
    elif key.endswith("P"):
        pass
    edge = _DHC.RESOLUTION_TO_MAX_EDGE.get(raw)
    if edge is None:
        edge = _DHC.RESOLUTION_TO_MAX_EDGE.get(key)
    if edge is None:
        return _DHC.DEFAULT_RESOLUTION, int(_DHC.DEFAULT_MAX_EDGE)
    normalized = key if key in ("480P", "720P", "1080P") else (
        _DHC.DEFAULT_RESOLUTION if key not in _DHC.RESOLUTION_TO_MAX_EDGE else key
    )
    if key in ("480P", "720P", "1080P"):
        normalized = key
    elif raw in ("480P", "720P", "1080P"):
        normalized = raw
    else:
        # 从 edge 反推标准标签
        reverse = {720: "480P", 1280: "720P", 1920: "1080P"}
        normalized = reverse.get(int(edge), _DHC.DEFAULT_RESOLUTION)
    return normalized, int(edge)


def clamp_minimax_video_duration(raw_seconds: Optional[float]) -> Tuple[int, str]:
    """
    MiniMax 时长硬限制 4–10 秒。
    返回 (duration, clamp_reason)，reason: none | floor_to_4 | ceil_to_10。
    """
    try:
        value = float(raw_seconds) if raw_seconds is not None else float(_DHC.DEFAULT_VIDEO_DURATION)
    except (TypeError, ValueError):
        value = float(_DHC.DEFAULT_VIDEO_DURATION)
    if value <= 0:
        value = float(_DHC.DEFAULT_VIDEO_DURATION)
    ceiled = int(math.ceil(value))
    if ceiled < int(_DHC.MIN_VIDEO_DURATION):
        return int(_DHC.MIN_VIDEO_DURATION), "floor_to_4"
    if ceiled > int(_DHC.MAX_VIDEO_DURATION):
        return int(_DHC.MAX_VIDEO_DURATION), "ceil_to_10"
    return ceiled, "none"


def build_digital_human_generation_plan(
    scene,
    storyboard,
    speaker_id: int,
    dialogues: List[dict],
    segments: List[TtsSegment],
    *,
    resolution: Optional[str] = None,
) -> DigitalHumanGenerationPlan:
    """
    固定 MiniMax H3 计划：动作 prompt + 成片说话音频 + 时长 clamp + 分辨率→max_edge。

    注意：此函数不做音频下载/合并 IO；多段合并由 prepare 阶段回填。
    """
    config = UnifiedConfigRegistry.get_by_id(TaskTypeId.DIGITAL_HUMAN_MINIMAX_H3)
    if not config:
        raise StoryboardDigitalHumanError(
            _DHC.ERROR_MODEL_UNAVAILABLE,
            "数字人模型（MiniMax H3）未配置",
        )

    total_duration, any_unknown = _sum_tts_duration(segments)
    speech_text = "".join(
        str(d.get("text") or "").strip() for d in dialogues
    ).strip()
    first_frame_path = _resolve_first_frame_path(scene)

    # 提示词：优先分镜 video_prompt，否则默认动作句（台词已在音频里）
    video_prompt = str(_get_field(scene, "video_prompt") or "").strip()
    prompt = video_prompt or _DHC.DEFAULT_PROMPT

    ratio = (_get_field(storyboard, "workflow_ratio") or "").strip() or "9:16"
    audio_input = segments[0].audio_url if segments else ""

    # 原始时长：TTS 总时长 → scene.duration → 默认
    if total_duration is not None and not any_unknown:
        raw_duration = total_duration
        speech_duration_meta = total_duration
    else:
        scene_dur = None
        try:
            scene_dur = float(_get_field(scene, "duration") or 0) or None
        except (TypeError, ValueError):
            scene_dur = None
        raw_duration = scene_dur
        speech_duration_meta = total_duration if not any_unknown else None

    video_duration, clamp_reason = clamp_minimax_video_duration(raw_duration)
    resolved_resolution, max_edge = resolve_max_edge_from_resolution(resolution)

    return DigitalHumanGenerationPlan(
        model=_DHC.MODEL_MINIMAX_H3,
        task_type=TaskTypeId.DIGITAL_HUMAN_MINIMAX_H3,
        speaker_character_id=int(speaker_id),
        speech_text=speech_text,
        speech_duration=speech_duration_meta,
        first_frame_path=first_frame_path,
        ratio=ratio,
        billable_duration=float(video_duration),
        prompt=prompt,
        audio_input=audio_input,
        audio_input_role=_DHC.AUDIO_ROLE_SPEECH_AUDIO,
        routing_reason=_DHC.ROUTING_REASON_MINIMAX,
        resolution=resolved_resolution,
        max_edge=int(max_edge),
        start_second=int(_DHC.DEFAULT_START_SECOND),
        duration_clamp_reason=clamp_reason,
    )


# --------------------------------------------------------------------------- #
# 流水线 step 5：准备音频输入（下载 / 合并 IO 只在此处发生）
# --------------------------------------------------------------------------- #
def _download_audio(url: str, dest_dir: str, *, timeout: int = 60) -> Optional[str]:
    """同步下载音频到本地文件。失败返回 None。"""
    try:
        os.makedirs(dest_dir, exist_ok=True)
        suffix = ".wav"
        parsed_ext = os.path.splitext(url.split("?")[0])[1]
        if parsed_ext:
            suffix = parsed_ext
        dest_path = os.path.join(dest_dir, f"{uuid.uuid4().hex}{suffix}")
        req = urllib.request.Request(url, headers={"User-Agent": "storyboard-digital-human/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp, open(dest_path, "wb") as f:
            import shutil
            shutil.copyfileobj(resp, f)
        if os.path.isfile(dest_path) and os.path.getsize(dest_path) > 0:
            return dest_path
        return None
    except Exception as e:
        logger.warning("数字人音频下载失败 %s: %s", url, e)
        return None


def _merge_audio_files(
    local_paths: List[str],
    dest_path: str,
) -> bool:
    """
    用 ffmpeg 合并多段音频为单个 WAV（统一采样率/声道/PCM）。
    成功返回 True。超时由 DIGITAL_HUMAN_AUDIO_MERGE_TIMEOUT_SECONDS 控制。
    """
    if not local_paths:
        return False
    if len(local_paths) == 1:
        # 单段无需合并，但仍转码为统一 WAV 以保证格式一致
        pass

    os.makedirs(os.path.dirname(dest_path) or ".", exist_ok=True)
    # 用 concat demuxer 合并
    list_path = dest_path + ".list.txt"
    try:
        with open(list_path, "w", encoding="utf-8") as f:
            for p in local_paths:
                # concat demuxer 要求绝对路径并对特殊字符转义
                safe = p.replace("'", r"\'")
                f.write(f"file '{safe}'\n")

        cmd = [
            _get_ffmpeg_path(), "-y",
            "-f", "concat", "-safe", "0",
            "-i", list_path,
            "-ar", "44100", "-ac", "1", "-acodec", "pcm_s16le",
            dest_path,
        ]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=StoryboardTimeouts.DIGITAL_HUMAN_AUDIO_MERGE_TIMEOUT_SECONDS,
        )
        if result.returncode != 0:
            logger.warning(
                "ffmpeg 合并音频失败 returncode=%s stderr=%s",
                result.returncode,
                (result.stderr or "").strip()[:500],
            )
            return False
        return os.path.isfile(dest_path) and os.path.getsize(dest_path) > 0
    except subprocess.TimeoutExpired:
        logger.warning(
            "ffmpeg 合并音频超时(%ss)",
            StoryboardTimeouts.DIGITAL_HUMAN_AUDIO_MERGE_TIMEOUT_SECONDS,
        )
        return False
    except Exception as e:
        logger.warning("ffmpeg 合并音频异常: %s", e)
        return False
    finally:
        try:
            if os.path.isfile(list_path):
                os.remove(list_path)
        except OSError:
            pass


def _task_assets_dir(scene_id: int, ai_tool_id_hint: Optional[int] = None) -> str:
    """数字人任务的持久化资产目录。"""
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    upload_dir = os.path.join(project_root, "upload", "storyboard_digital_human", str(int(scene_id)))
    os.makedirs(upload_dir, exist_ok=True)
    return upload_dir


def _plan_with_audio(plan: DigitalHumanGenerationPlan, audio_input: str) -> DigitalHumanGenerationPlan:
    """复制 plan 并替换 audio_input（frozen dataclass）。"""
    return DigitalHumanGenerationPlan(
        model=plan.model,
        task_type=plan.task_type,
        speaker_character_id=plan.speaker_character_id,
        speech_text=plan.speech_text,
        speech_duration=plan.speech_duration,
        first_frame_path=plan.first_frame_path,
        ratio=plan.ratio,
        billable_duration=plan.billable_duration,
        prompt=plan.prompt,
        audio_input=audio_input,
        audio_input_role=plan.audio_input_role,
        routing_reason=plan.routing_reason,
        resolution=plan.resolution,
        max_edge=plan.max_edge,
        start_second=plan.start_second,
        duration_clamp_reason=plan.duration_clamp_reason,
    )


def prepare_digital_human_audio_input(
    plan: DigitalHumanGenerationPlan,
    segments: List[TtsSegment],
    *,
    scene_id: int,
) -> DigitalHumanGenerationPlan:
    """
    MiniMax H3 使用成片说话音频：单段直接用原始 URL；多段下载并合并为本地 WAV。
    所有下载和 ffmpeg IO 只发生在该阶段。合并失败时抛错（不得扣费）。
    """
    if plan.audio_input_role != _DHC.AUDIO_ROLE_SPEECH_AUDIO:
        return plan

    if len(segments) <= 1:
        return plan

    assets_dir = _task_assets_dir(scene_id)
    local_paths: List[str] = []
    try:
        for seg in segments:
            local = _download_audio(seg.audio_url, assets_dir)
            if not local:
                raise StoryboardDigitalHumanError(
                    _DHC.ERROR_AUDIO_MERGE_FAILED,
                    "多段 TTS 音频下载失败，无法合并",
                )
            local_paths.append(local)

        merged_path = os.path.join(assets_dir, f"{uuid.uuid4().hex}.wav")
        if not _merge_audio_files(local_paths, merged_path):
            raise StoryboardDigitalHumanError(
                _DHC.ERROR_AUDIO_MERGE_FAILED,
                "多段 TTS 音频合并失败，无法生成对口型视频",
            )
        return _plan_with_audio(plan, merged_path)
    except StoryboardDigitalHumanError:
        raise
    except Exception as e:
        raise StoryboardDigitalHumanError(
            _DHC.ERROR_AUDIO_MERGE_FAILED,
            f"多段 TTS 音频处理失败: {e}",
        )


# --------------------------------------------------------------------------- #
# 流水线 step 6：提交计划（建 ai_tools / Task / Asset）
# --------------------------------------------------------------------------- #
def submit_digital_human_plan(
    plan: DigitalHumanGenerationPlan,
    *,
    scene_id: int,
    user_id: int,
    transaction_id: str,
    computing_power: Optional[float] = None,
    clip_to_audio_duration: bool = True,
    resolution: Optional[str] = None,
) -> Dict[str, Any]:
    """
    使用已经确定的计划创建 ``ai_tools``、异步 Task 和 ``StoryboardSceneAsset(video)``，
    并维护当前选中视频。
    """
    config = UnifiedConfigRegistry.get_by_id(plan.task_type)
    if not config:
        raise StoryboardDigitalHumanError(
            _DHC.ERROR_MODEL_UNAVAILABLE,
            f"数字人模型（task_type={plan.task_type}）未配置",
        )

    # MiniMax：说话音频写入 audio_path；分辨率映射为 max_edge 写入 extra_config
    effective_resolution = resolution or plan.resolution
    if resolution:
        resolved_res, resolved_edge = resolve_max_edge_from_resolution(resolution)
    else:
        resolved_res, resolved_edge = plan.resolution, plan.max_edge

    extra_payload = {
        "video_type": SceneVideoType.DIGITAL_HUMAN,
        "source": _DHC.SOURCE,
        "clip_to_audio_duration": bool(clip_to_audio_duration),
        "speaker_character_id": int(plan.speaker_character_id),
        "digital_human_model": plan.model,
        "speech_duration": plan.speech_duration,
        "video_duration": int(plan.billable_duration),
        "duration_clamp_reason": plan.duration_clamp_reason,
        "routing_reason": plan.routing_reason,
        "audio_input_role": plan.audio_input_role,
        "ratio": plan.ratio,
        "resolution": resolved_res,
        "max_edge": int(resolved_edge),
        "start_second": int(plan.start_second),
    }

    ai_tool_id = AIToolsModel.create(
        prompt=plan.prompt,
        user_id=int(user_id),
        type=plan.task_type,
        image_path=plan.first_frame_path,
        message=None,
        audio_path=plan.audio_input,
        duration=int(plan.billable_duration),
        ratio=plan.ratio,
        transaction_id=transaction_id,
        status=AI_TOOL_STATUS_PENDING,
        extra_config=json.dumps(extra_payload, ensure_ascii=False),
    )
    TasksModel.create(
        task_type=TASK_TYPE_GENERATE_VIDEO,
        task_id=ai_tool_id,
        status=TASK_STATUS_QUEUED,
    )
    asset_id = StoryboardSceneAssetModel.create(
        scene_id=int(scene_id),
        asset_type="video",
        ai_tool_id=ai_tool_id,
    )
    StoryboardSceneAssetModel.set_selected(int(scene_id), "video", asset_id)
    StoryboardSceneModel.update(int(scene_id), last_modified_user_id=int(user_id))

    return {
        "success": True,
        "ai_tool_id": ai_tool_id,
        "asset_id": asset_id,
        "video_type": SceneVideoType.DIGITAL_HUMAN,
        "task_type": plan.task_type,
        "model_used": "MiniMax H3",
        "speech_duration": plan.speech_duration,
        "video_duration": int(plan.billable_duration),
        "duration_clamp_reason": plan.duration_clamp_reason,
        "resolution": resolved_res,
        "max_edge": int(resolved_edge),
        "routing_reason": plan.routing_reason,
        "audio_input_role": plan.audio_input_role,
        "computing_power": computing_power,
        "status": "submitted",
        "image_path": plan.first_frame_path,
        "speaker_character_id": int(plan.speaker_character_id),
        "transaction_id": transaction_id,
    }


# --------------------------------------------------------------------------- #
# 统一编排入口（规划 → 准备 → 计费时长）
# --------------------------------------------------------------------------- #
def orchestrate_digital_human_generation(
    scene_id: int,
    *,
    character_id: Optional[int] = None,
    prepare_audio: bool = True,
    resolution: Optional[str] = None,
) -> Tuple[DigitalHumanGenerationPlan, List[TtsSegment], Any, Any]:
    """
    执行「解析对白 → 加载 TTS 元数据 → 探测缺失时长 → 生成计划 → 准备音频输入」
    完整同步链路。返回 ``(plan, segments, scene, storyboard)``。

    扣费与建单由调用方拿到 plan 后执行（不同入口的扣费方式不同：
    API 用 Authorization header、Agent/CLI 用 auth_token 同步扣）。

    Args:
        prepare_audio: True 时执行 prepare_digital_human_audio_input（多段合并）。
            批量就绪判断(plan_digital_human_ready)传 False 只做规划。
        resolution: 视频分辨率偏好（480P/720P/1080P），映射为 max_edge。
    """
    scene = StoryboardSceneModel.get_by_id(int(scene_id))
    if not scene:
        raise StoryboardDigitalHumanError("not_found", "分镜不存在", status_code=404)

    video_type = _get_field(scene, "video_type") or SceneVideoType.VIDEO
    if str(video_type) != SceneVideoType.DIGITAL_HUMAN:
        raise StoryboardDigitalHumanError(
            "invalid_video_type",
            f"分镜类型不是对口型（当前: {video_type}）",
        )

    speaker_id, dialogues = resolve_digital_human_dialogues(
        int(scene_id), character_id=character_id
    )
    segments = load_digital_human_tts_metadata(dialogues)
    if not segments:
        raise StoryboardDigitalHumanError(
            _DHC.ERROR_AUDIO_REQUIRED,
            "请先生成配音后再生成对口型视频",
        )
    segments = probe_missing_digital_human_tts_durations(segments)

    storyboard = StoryboardModel.get_by_id(int(_get_field(scene, "storyboard_id")))
    plan = build_digital_human_generation_plan(
        scene, storyboard, speaker_id, dialogues, segments, resolution=resolution
    )
    if prepare_audio:
        plan = prepare_digital_human_audio_input(plan, segments, scene_id=int(scene_id))
    return plan, segments, scene, storyboard


# --------------------------------------------------------------------------- #
# 计费辅助
# --------------------------------------------------------------------------- #
def compute_digital_human_power(plan: DigitalHumanGenerationPlan) -> float:
    """按 MiniMax H3 配置与 clamp 后时长计算算力。返回 0 表示无需扣费。"""
    config = UnifiedConfigRegistry.get_by_id(plan.task_type)
    if not config:
        return 0.0
    try:
        duration = int(plan.billable_duration) if plan.billable_duration else None
        return float(config.get_computing_power(duration=duration) or 0)
    except Exception:
        return 0.0


def deduct_computing_power_sync(
    auth_token: str,
    computing_power: float,
    transaction_id: str,
) -> Tuple[bool, str]:
    """
    同步扣费（Agent / CLI 入口用）。无 auth_token 或算力为 0 视为跳过（返回成功）。
    返回 (success, message)。
    """
    if not auth_token or not computing_power:
        return True, ""
    try:
        from perseids_server.client import make_perseids_request

        token = auth_token if auth_token.startswith("Bearer ") else f"Bearer {auth_token}"
        ok, message, _ = make_perseids_request(
            endpoint="user/calculate_computing_power",
            data={
                "computing_power": computing_power,
                "behavior": "deduct",
                "transaction_id": transaction_id,
            },
            method="POST",
            headers={"Authorization": token},
        )
        return bool(ok), message or ""
    except Exception as e:
        logger.error("数字人同步扣费失败: %s", e)
        return False, str(e)


# --------------------------------------------------------------------------- #
# 批量就绪判断（语义随 resolve_digital_human_image_path 收紧）
# --------------------------------------------------------------------------- #
def plan_digital_human_ready(scene_id: int) -> Tuple[str, str]:
    """
    For batch planning: return (plan_status, skip_reason).

    plan_status: 'ready' | 'missing_audio' | 'audio_pending' | 'missing_image' | 'invalid'

    就绪判定委托给 orchestrate_digital_human_generation（prepare_audio=False），
    图片校验语义随 _resolve_first_frame_path 收紧：仅靠角色参考图而无选中首帧
    的分镜会被标记为 missing_image 跳过。
    """
    try:
        scene = StoryboardSceneModel.get_by_id(int(scene_id))
        if not scene:
            return "invalid", "not_found"
        orchestrate_digital_human_generation(int(scene_id), prepare_audio=False)
        return "ready", ""
    except StoryboardDigitalHumanError as exc:
        if exc.code == _DHC.ERROR_AUDIO_PENDING:
            return "audio_pending", _DHC.SKIP_REASON_AUDIO_PENDING
        if exc.code == _DHC.ERROR_AUDIO_REQUIRED:
            return "missing_audio", _DHC.SKIP_REASON_MISSING_AUDIO
        if exc.code == _DHC.ERROR_MISSING_IMAGE:
            return "missing_image", _DHC.SKIP_REASON_MISSING_IMAGE
        return "invalid", exc.code


# --------------------------------------------------------------------------- #
# 向后兼容：旧入口仍可调用的提交函数（内部走新流水线）
# --------------------------------------------------------------------------- #
def submit_storyboard_digital_human_video(
    scene_id: int,
    user_id: int,
    *,
    prompt: Optional[str] = None,
    character_id: Optional[int] = None,
    ratio: Optional[str] = None,
    duration: Optional[float] = None,
    clip_to_audio_duration: bool = True,
    resolution: Optional[str] = None,
    transaction_id: Optional[str] = None,
    computing_power: Optional[float] = None,
) -> Dict[str, Any]:
    """
    [已废弃·保留兼容] 旧的直接提交入口。

    新代码应使用 orchestrate_digital_human_generation + submit_digital_human_plan。
    本函数忽略调用方传入的 prompt / duration / ratio（以服务端规划为准），
    内部走统一流水线。扣费仍由调用方先完成（通过 transaction_id 传入）。
    """
    plan, _segments, _scene, _sb = orchestrate_digital_human_generation(
        int(scene_id),
        character_id=character_id,
        prepare_audio=True,
        resolution=resolution,
    )
    tx_id = transaction_id or str(uuid.uuid4())
    return submit_digital_human_plan(
        plan,
        scene_id=int(scene_id),
        user_id=int(user_id),
        transaction_id=tx_id,
        computing_power=computing_power,
        clip_to_audio_duration=clip_to_audio_duration,
        resolution=resolution,
    )


# --------------------------------------------------------------------------- #
# 旧函数保留（resolve_digital_human_image_path / speaker_audio / ensure_* ）
# 供尚未迁移的调用方使用；语义已更新。
# --------------------------------------------------------------------------- #
def resolve_digital_human_image_path(
    scene,
    character_id: Optional[int],
) -> str:
    """
    [已更新] 只使用当前分镜已选中且已生成完成的首帧图。
    不再读取 character.reference_image，也不回退任何参考图。
    ``character_id`` 参数保留只为签名兼容，内部不使用。
    """
    return _resolve_first_frame_path(scene)
