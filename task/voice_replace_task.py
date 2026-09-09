"""音色替换 scheduler 消费者：拾取 queued 任务并跑 worker。"""
from __future__ import annotations

import logging

from config.constant import VoiceReplaceConstants as C, VoiceReplaceJobStatus
from model.video_voice_replace import VideoVoiceReplaceJobModel
from services.voice_replace.worker import VoiceReplaceWorker

logger = logging.getLogger(__name__)


async def process_voice_replace_jobs() -> None:
    jobs = VideoVoiceReplaceJobModel.list_queued(C.JOB_BATCH_LIMIT)
    if not jobs:
        return
    worker = VoiceReplaceWorker()
    for job in jobs:
        claimed = VideoVoiceReplaceJobModel.claim(
            int(job.id),
            VoiceReplaceJobStatus.QUEUED,
            VoiceReplaceJobStatus.ASR,
        )
        if not claimed:
            continue
        job.status = VoiceReplaceJobStatus.ASR
        try:
            await worker.process_job(job)
        except Exception:
            logger.exception("[voice-replace] scheduler job=%s crashed", job.id)
