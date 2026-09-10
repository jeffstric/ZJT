"""成片对白音色替换：对齐引擎与后续 ASR/VC driver。"""
from .aligner import (
    AlignedSegment,
    AlignmentResult,
    AsrSegment,
    DialogueLine,
    align_dialogues,
    normalize_text,
    score_pair,
)
from .asr_driver import (
    AsrDriver,
    SenseVoiceAsrDriver,
    SenseVoiceAsrError,
    get_asr_base_url,
    get_asr_driver,
    parse_asr_segments_payload,
)
from .seedvc_driver import SeedVcDriver, SeedVcError, get_seedvc_base_url
from .uvr_driver import UvrDriver, UvrError, get_uvr_base_url, get_uvr_driver
from .enqueue import enqueue_scene_job

__all__ = [
    "AlignedSegment",
    "AlignmentResult",
    "AsrDriver",
    "AsrSegment",
    "DialogueLine",
    "SeedVcDriver",
    "SeedVcError",
    "SenseVoiceAsrDriver",
    "SenseVoiceAsrError",
    "UvrDriver",
    "UvrError",
    "enqueue_scene_job",
    "align_dialogues",
    "get_seedvc_base_url",
    "get_asr_base_url",
    "get_asr_driver",
    "get_uvr_base_url",
    "get_uvr_driver",
    "normalize_text",
    "parse_asr_segments_payload",
    "score_pair",
]
