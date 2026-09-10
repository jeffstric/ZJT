"""分镜成片音色替换入队（同步，API 用 asyncio.to_thread）。"""
from __future__ import annotations

from typing import Any, Dict, Optional

from config.constant import VoiceReplaceConstants as C, VoiceReplaceJobStatus
from config.unified_config import SceneVideoType
from model.storyboard_scene import StoryboardSceneModel
from model.video_voice_replace import VideoVoiceReplaceJob, VideoVoiceReplaceJobModel
from services.voice_replace.worker import (
    load_dialogues,
    resolve_character_voice,
    resolve_scene_video_url,
)

SKIP_MESSAGES = {
    C.SKIP_DIGITAL_HUMAN: "对口型分镜不需要替换音色",
    C.SKIP_NO_VIDEO: "请先生成或选中分镜视频",
    C.SKIP_NO_DIALOGUE: "当前分镜没有对白",
    C.SKIP_MISSING_REFERENCE_AUDIO: "对白角色还没有参考音色",
    C.SKIP_ALREADY_COMPLETED: "该成片已经替换过音色",
}


def _job_payload(job: Optional[VideoVoiceReplaceJob]) -> Optional[Dict[str, Any]]:
    return job.to_dict() if job else None


def _result(
    *,
    queued: bool,
    skipped: bool,
    skip_reason: Optional[str] = None,
    job: Optional[VideoVoiceReplaceJob] = None,
    reused: bool = False,
) -> Dict[str, Any]:
    message = SKIP_MESSAGES.get(skip_reason or "", "")
    return {
        "queued": queued,
        "skipped": skipped,
        "skip_reason": skip_reason,
        "message": message,
        "reused": reused,
        "job": _job_payload(job),
    }


def enqueue_scene_job(
    user_id: int,
    scene_id: int,
    force: bool = False,
) -> Dict[str, Any]:
    scene = StoryboardSceneModel.get_by_id(int(scene_id))
    if not scene:
        return _result(queued=False, skipped=True, skip_reason=C.SKIP_NO_VIDEO)

    if (scene.video_type or SceneVideoType.VIDEO) == SceneVideoType.DIGITAL_HUMAN:
        return _result(queued=False, skipped=True, skip_reason=C.SKIP_DIGITAL_HUMAN)

    video_url = resolve_scene_video_url(int(scene_id))
    if not video_url:
        return _result(queued=False, skipped=True, skip_reason=C.SKIP_NO_VIDEO)

    dialogues = load_dialogues(int(scene_id))
    spoken = [d for d in dialogues if (d.text or "").strip()]
    if not spoken:
        return _result(queued=False, skipped=True, skip_reason=C.SKIP_NO_DIALOGUE)

    has_voice = False
    for line in spoken:
        if line.character_id and resolve_character_voice(line.character_id):
            has_voice = True
            break
    if not has_voice:
        return _result(
            queued=False,
            skipped=True,
            skip_reason=C.SKIP_MISSING_REFERENCE_AUDIO,
        )

    inflight = VideoVoiceReplaceJobModel.find_in_flight(int(scene_id), video_url)
    if inflight:
        return _result(queued=False, skipped=False, job=inflight, reused=True)

    if not force:
        latest = VideoVoiceReplaceJobModel.get_latest_by_scene(int(scene_id))
        if (
            latest
            and latest.source_video_url == video_url
            and latest.status == VoiceReplaceJobStatus.COMPLETED
        ):
            return _result(
                queued=False,
                skipped=True,
                skip_reason=C.SKIP_ALREADY_COMPLETED,
                job=latest,
                reused=True,
            )

    job_id = VideoVoiceReplaceJobModel.create(
        user_id=int(user_id),
        source_type=C.SOURCE_STORYBOARD_SCENE,
        source_video_url=video_url,
        scene_id=int(scene_id),
        status=VoiceReplaceJobStatus.QUEUED,
    )
    job = VideoVoiceReplaceJobModel.get_by_id(int(job_id))
    return _result(queued=True, skipped=False, job=job)
