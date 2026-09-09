"""成片音色替换单任务编排：抽音 → UVR → ASR → 对齐 → VC(人声) → 混回环境声 → mux。"""
from __future__ import annotations

from dataclasses import asdict
import logging
import os
from typing import List, Optional
from urllib.parse import urlparse

import httpx

from config.constant import VoiceReplaceConstants as C, VoiceReplaceJobStatus
from config.unified_config import SceneVideoType
from model.character import CharacterModel
from model.storyboard_dialogue import StoryboardDialogueModel
from model.storyboard_scene import StoryboardSceneModel
from model.storyboard_scene_asset import StoryboardSceneAssetModel
from model.ai_tools import AIToolsModel
from model.video_voice_replace import (
    VideoVoiceReplaceJob,
    VideoVoiceReplaceJobModel,
    VideoVoiceReplaceSegmentModel,
)
from services.voice_replace.aligner import (
    AlignedSegment,
    AlignmentResult,
    AsrSegment,
    DialogueLine,
    align_dialogues,
)
from services.voice_replace.asr_driver import SenseVoiceAsrDriver, SenseVoiceAsrError
from services.voice_replace.ffmpeg_util import (
    FfmpegError,
    concat_wavs,
    extract_audio,
    mix_wavs,
    mux_video_audio,
    probe_duration,
    slice_audio,
    stretch_to_duration,
)
from services.voice_replace.vevo2_driver import Vevo2Driver, Vevo2Error
from services.voice_replace.uvr_driver import UvrDriver, UvrError
from utils.project_path import (
    build_upload_url,
    get_upload_subdir,
    resolve_upload_url_to_local_path,
)

logger = logging.getLogger(__name__)


class VoiceReplaceWorkerError(Exception):
    pass


def _job_work_dir(job_id: int) -> str:
    return get_upload_subdir(C.WORK_SUBDIR, str(job_id))


def _result_url(job_id: int) -> str:
    return build_upload_url(C.WORK_SUBDIR, str(job_id), C.RESULT_FILENAME)


async def _download_file(url: str, dest: str) -> str:
    timeout = httpx.Timeout(float(C.DOWNLOAD_TIMEOUT), connect=float(C.HTTP_CONNECT_TIMEOUT))
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
        with open(dest, "wb") as fh:
            fh.write(resp.content)
    return dest


async def _resolve_media(url_or_path: str, dest: str) -> str:
    if not url_or_path:
        raise VoiceReplaceWorkerError("missing media path")
    parsed = urlparse(url_or_path)
    if parsed.scheme in ("http", "https"):
        try:
            local = resolve_upload_url_to_local_path(url_or_path)
            if os.path.isfile(local):
                return local
        except ValueError:
            pass
        return await _download_file(url_or_path, dest)
    if os.path.isfile(url_or_path):
        return url_or_path
    try:
        local = resolve_upload_url_to_local_path(url_or_path)
    except ValueError as exc:
        raise VoiceReplaceWorkerError(f"cannot resolve media: {url_or_path}") from exc
    if os.path.isfile(local):
        return local
    raise VoiceReplaceWorkerError(f"media not found: {url_or_path}")


def resolve_scene_video_url(scene_id: int) -> Optional[str]:
    scene = StoryboardSceneModel.get_by_id(scene_id)
    if not scene or not scene.selected_video_id:
        return None
    asset = StoryboardSceneAssetModel.get_by_id(scene.selected_video_id)
    if not asset:
        return None
    if asset.result_url:
        return asset.result_url
    if asset.ai_tool_id:
        tool = AIToolsModel.get_by_id(asset.ai_tool_id)
        if tool and getattr(tool, "result_url", None):
            return tool.result_url
    return None


def load_dialogues(scene_id: int) -> List[DialogueLine]:
    rows = StoryboardDialogueModel.list_by_scene(scene_id)
    out: List[DialogueLine] = []
    for row in rows:
        cid = row.get("character_id")
        name = ""
        if cid:
            ch = CharacterModel.get_by_id(int(cid))
            if ch:
                name = ch.name or ""
        out.append(
            DialogueLine(
                text=row.get("text") or "",
                character_id=cid,
                character_name=name,
                id=row.get("id"),
                sort_order=float(row.get("sort_order") or 0),
            )
        )
    return out


def resolve_character_voice(character_id: Optional[int]) -> Optional[str]:
    if not character_id:
        return None
    ch = CharacterModel.get_by_id(int(character_id))
    if not ch:
        return None
    return ch.default_voice or None


def _alignment_to_json(result: AlignmentResult) -> dict:
    return {
        "status": result.status,
        "mean_score": result.mean_score,
        "unmatched_asr_ratio": result.unmatched_asr_ratio,
        "skip_reason": result.skip_reason,
        "segments": [asdict(s) for s in result.segments],
        "leftover_asr": [asdict(s) for s in result.leftover_asr],
    }


def _persist_segments(job_id: int, segments: List[AlignedSegment]) -> None:
    for seg in segments:
        VideoVoiceReplaceSegmentModel.create(
            job_id=job_id,
            start_ms=int(round(seg.start * 1000)),
            end_ms=int(round(seg.end * 1000)),
            asr_text=seg.asr_text,
            dialogue_id=seg.dialogue_id,
            character_id=seg.character_id,
            match_method=seg.method,
            match_confidence=seg.score,
        )


class VoiceReplaceWorker:
    def __init__(
        self,
        asr: Optional[SenseVoiceAsrDriver] = None,
        vc: Optional[Vevo2Driver] = None,
        uvr: Optional[UvrDriver] = None,
    ):
        self.asr = asr or SenseVoiceAsrDriver()
        self.vc = vc or Vevo2Driver()
        self.uvr = uvr or UvrDriver()

    async def process_job(self, job: VideoVoiceReplaceJob, force: bool = False) -> str:
        job_id = int(job.id)
        work_dir = _job_work_dir(job_id)
        os.makedirs(work_dir, exist_ok=True)
        logger.info("[voice-replace] job=%s start source=%s", job_id, job.source_type)
        try:
            status = await self._run(job, work_dir, force=force)
            logger.info("[voice-replace] job=%s done status=%s", job_id, status)
            return status
        except Exception as exc:
            logger.exception("[voice-replace] job=%s failed", job_id)
            VideoVoiceReplaceJobModel.update_status(
                job_id,
                VoiceReplaceJobStatus.FAILED,
                error_message=str(exc)[:500],
            )
            raise

    async def _run(self, job: VideoVoiceReplaceJob, work_dir: str, force: bool) -> str:
        job_id = int(job.id)
        if job.source_type == C.SOURCE_WORKFLOW_NODE:
            VideoVoiceReplaceJobModel.update_status(
                job_id,
                VoiceReplaceJobStatus.SKIPPED,
                skip_reason="workflow_not_supported",
            )
            return VoiceReplaceJobStatus.SKIPPED

        scene = None
        if job.scene_id:
            scene = StoryboardSceneModel.get_by_id(int(job.scene_id))
            if scene and scene.video_type == SceneVideoType.DIGITAL_HUMAN:
                VideoVoiceReplaceJobModel.update_status(
                    job_id,
                    VoiceReplaceJobStatus.SKIPPED,
                    skip_reason=C.SKIP_DIGITAL_HUMAN,
                )
                return VoiceReplaceJobStatus.SKIPPED

        video_url = job.source_video_url
        if not video_url and job.scene_id:
            video_url = resolve_scene_video_url(int(job.scene_id))
        if not video_url:
            raise VoiceReplaceWorkerError("no source video")

        VideoVoiceReplaceJobModel.update_status(
            job_id, VoiceReplaceJobStatus.ASR, source_video_url=video_url
        )
        video_path = await _resolve_media(video_url, os.path.join(work_dir, "source.mp4"))
        wav_path = os.path.join(work_dir, C.EXTRACTED_WAV)
        try:
            await extract_audio(video_path, wav_path)
        except FfmpegError as exc:
            logger.info("[voice-replace] job=%s no audio: %s", job_id, exc)
            VideoVoiceReplaceJobModel.update_status(
                job_id, VoiceReplaceJobStatus.SKIPPED, skip_reason=C.SKIP_NO_SPEECH
            )
            return VoiceReplaceJobStatus.SKIPPED

        vocals_path, instrumental_path = await self._split_vocals(work_dir, wav_path)
        dialogues = load_dialogues(int(job.scene_id)) if job.scene_id else []
        try:
            asr_segments, vocals_path, instrumental_path = await self._pick_speech_stem(
                vocals_path, instrumental_path
            )
        except SenseVoiceAsrError as exc:
            raise VoiceReplaceWorkerError(f"asr failed: {exc}") from exc

        VideoVoiceReplaceJobModel.update_status(job_id, VoiceReplaceJobStatus.MATCHING)
        alignment = align_dialogues(dialogues, asr_segments)
        match_json = _alignment_to_json(alignment)
        _persist_segments(job_id, alignment.segments)

        if alignment.status == C.STATUS_SKIP:
            VideoVoiceReplaceJobModel.update_status(
                job_id,
                VoiceReplaceJobStatus.SKIPPED,
                match_json=match_json,
                skip_reason=alignment.skip_reason or C.SKIP_NO_SPEECH,
            )
            return VoiceReplaceJobStatus.SKIPPED

        if alignment.status in (C.STATUS_WAIT_CONFIRM, C.STATUS_NEEDS_LLM) and not force:
            VideoVoiceReplaceJobModel.update_status(
                job_id,
                VoiceReplaceJobStatus.WAIT_CONFIRM,
                match_json=match_json,
            )
            return VoiceReplaceJobStatus.WAIT_CONFIRM

        VideoVoiceReplaceJobModel.update_status(
            job_id, VoiceReplaceJobStatus.CONVERTING, match_json=match_json
        )
        converted_vocals = await self._convert_and_mix(
            work_dir, vocals_path, alignment.segments
        )
        mixed = converted_vocals
        if instrumental_path:
            mixed = os.path.join(work_dir, "mixed.wav")
            await mix_wavs(converted_vocals, instrumental_path, mixed)
        dest = os.path.join(work_dir, C.RESULT_FILENAME)
        VideoVoiceReplaceJobModel.update_status(job_id, VoiceReplaceJobStatus.MUXING)
        await mux_video_audio(video_path, mixed, dest)
        result_url = _result_url(job_id)
        VideoVoiceReplaceJobModel.update_status(
            job_id,
            VoiceReplaceJobStatus.COMPLETED,
            result_video_url=result_url,
            match_json=match_json,
        )
        if job.scene_id:
            self._attach_scene_result(int(job.scene_id), result_url)
        return VoiceReplaceJobStatus.COMPLETED

    async def _convert_and_mix(
        self,
        work_dir: str,
        source_wav: str,
        segments: List[AlignedSegment],
    ) -> str:
        duration = await probe_duration(source_wav)
        pieces: List[str] = []
        cursor = 0.0
        usable = [
            s for s in segments
            if s.method != C.METHOD_SKIPPED and s.end > s.start
        ]
        usable.sort(key=lambda s: s.start)
        pad = float(C.VC_CONTEXT_PAD_SECONDS)
        for i, seg in enumerate(usable):
            if seg.start > cursor + 0.02:
                gap = os.path.join(work_dir, f"gap_{i}.wav")
                await slice_audio(source_wav, gap, cursor, seg.start)
                pieces.append(gap)
            voice = resolve_character_voice(seg.character_id)
            if not voice:
                logger.info(
                    "[voice-replace] missing voice character_id=%s keep original",
                    seg.character_id,
                )
                clip = os.path.join(work_dir, f"src_{i}.wav")
                await slice_audio(source_wav, clip, seg.start, seg.end)
                pieces.append(clip)
                cursor = seg.end
                continue
            ctx_start = max(0.0, seg.start - pad)
            ctx_end = min(duration, seg.end + pad)
            ctx_clip = os.path.join(work_dir, f"ctx_{i}.wav")
            await slice_audio(source_wav, ctx_clip, ctx_start, ctx_end)
            ref_local = await _resolve_media(voice, os.path.join(work_dir, f"ref_{i}.wav"))
            ctx_conv = os.path.join(work_dir, f"vc_{i}_ctx.wav")
            try:
                await self.vc.convert(ctx_clip, ref_local, ctx_conv)
                offset = seg.start - ctx_start
                cropped = os.path.join(work_dir, f"vc_{i}.wav")
                await slice_audio(ctx_conv, cropped, offset, offset + (seg.end - seg.start))
                stretched = os.path.join(work_dir, f"vc_{i}_fit.wav")
                await stretch_to_duration(cropped, stretched, seg.end - seg.start)
                pieces.append(stretched)
            except Vevo2Error as exc:
                logger.warning("[voice-replace] vc failed seg=%s: %s keep original", i, exc)
                clip = os.path.join(work_dir, f"src_{i}.wav")
                await slice_audio(source_wav, clip, seg.start, seg.end)
                pieces.append(clip)
            cursor = seg.end
        if cursor < duration - 0.02:
            tail = os.path.join(work_dir, "tail.wav")
            await slice_audio(source_wav, tail, cursor, duration)
            pieces.append(tail)
        if not pieces:
            return source_wav
        mixed = os.path.join(work_dir, "converted_vocals.wav")
        await concat_wavs(pieces, mixed)
        return mixed

    async def _split_vocals(self, work_dir: str, wav_path: str) -> tuple:
        vocals_path = os.path.join(work_dir, C.UVR_VOCALS_FILENAME)
        instrumental_path = os.path.join(work_dir, C.UVR_INSTRUMENTAL_FILENAME)
        try:
            vocals, instrumental = await self.uvr.separate(
                wav_path, vocals_path, instrumental_path
            )
            return vocals, instrumental
        except UvrError as exc:
            logger.warning("[voice-replace] uvr failed, keep mixed audio: %s", exc)
            return wav_path, None

    async def _pick_speech_stem(
        self,
        vocals_path: str,
        instrumental_path: Optional[str],
    ):
        """Kim_Vocal_2 等 karaoke 模型有时把对白分到 Instrumental。用 ASR 选有字的那条当人声。"""
        vocal_segs = await self.asr.transcribe_segments(vocals_path, language="auto")
        if not instrumental_path:
            return vocal_segs, vocals_path, instrumental_path
        inst_segs = await self.asr.transcribe_segments(instrumental_path, language="auto")
        vocal_chars = _asr_char_count(vocal_segs)
        inst_chars = _asr_char_count(inst_segs)
        if inst_chars > vocal_chars:
            logger.info(
                "[voice-replace] UVR stems swapped: speech is on instrumental (%s chars vs vocals %s)",
                inst_chars,
                vocal_chars,
            )
            return inst_segs, instrumental_path, vocals_path
        return vocal_segs, vocals_path, instrumental_path

    @staticmethod
    def _attach_scene_result(scene_id: int, result_url: str) -> None:
        try:
            asset_id = StoryboardSceneAssetModel.create(
                scene_id=scene_id,
                asset_type="video",
                result_url=result_url,
            )
            StoryboardSceneAssetModel.set_selected(scene_id, "video", asset_id)
            StoryboardSceneModel.update(scene_id, audio_embedded=1)
        except Exception:
            logger.exception("[voice-replace] attach scene result failed scene=%s", scene_id)


def _asr_char_count(segments: List[AsrSegment]) -> int:
    return sum(len((s.text or "").strip()) for s in segments)
