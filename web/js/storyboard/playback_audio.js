/** 时间轴单镜音轨来源。任一时刻只允许一个主音源。 */
export const SCENE_AUDIO_MODE = Object.freeze({
    VIDEO: 'video',
    TTS: 'tts',
    SILENCE: 'silence',
});

/**
 * 与完整视频导出的音轨选择保持一致：
 * - 有视频且选择视频原声：播放视频音轨、跳过 TTS；
 * - 其余情况：有 TTS 则播放 TTS，否则静音；
 * - videoHasAudio=false 为后续素材音轨探测预留，届时可自动降级 TTS。
 */
export function resolveSceneAudioMode({
    visualType,
    audioEmbedded,
    audios = [],
    videoHasAudio,
} = {}) {
    const hasVideo = visualType === 'video';
    const hasTts = Array.isArray(audios) && audios.length > 0;

    if (hasVideo && Boolean(audioEmbedded) && videoHasAudio !== false) {
        return SCENE_AUDIO_MODE.VIDEO;
    }
    if (hasTts) return SCENE_AUDIO_MODE.TTS;
    return SCENE_AUDIO_MODE.SILENCE;
}
