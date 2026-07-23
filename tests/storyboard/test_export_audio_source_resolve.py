"""导出音轨 keep_video_audio 与前端 resolveSceneAudioMode 对齐。"""

from services.storyboard_export_service import resolve_scene_keep_video_audio


def test_explicit_video_audio_keeps_track_even_with_tts():
    assert resolve_scene_keep_video_audio(
        audio_embedded=True,
        has_tts=True,
        visual_type="video",
        video_has_audio=True,
    ) is True


def test_tts_mode_with_dialogue_audio_mutes_video():
    assert resolve_scene_keep_video_audio(
        audio_embedded=False,
        has_tts=True,
        visual_type="video",
        video_has_audio=True,
    ) is False


def test_no_tts_defaults_to_video_original_audio():
    assert resolve_scene_keep_video_audio(
        audio_embedded=False,
        has_tts=False,
        visual_type="video",
        video_has_audio=True,
    ) is True


def test_no_video_audio_stream_does_not_keep():
    assert resolve_scene_keep_video_audio(
        audio_embedded=True,
        has_tts=False,
        visual_type="video",
        video_has_audio=False,
    ) is False


def test_non_video_visual_never_keeps():
    assert resolve_scene_keep_video_audio(
        audio_embedded=True,
        has_tts=False,
        visual_type="image",
        video_has_audio=True,
    ) is False
