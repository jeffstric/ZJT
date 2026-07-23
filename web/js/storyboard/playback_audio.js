/** 时间轴单镜音轨来源。任一时刻只允许一个主音源。 */
export const SCENE_AUDIO_MODE = Object.freeze({
    VIDEO: 'video',
    TTS: 'tts',
    SILENCE: 'silence',
});

/**
 * 分镜是否已有可播放的对话配音（与预览/导出 has_tts 口径一致）。
 * @param {Array<{ audioUrl?: string, audio_url?: string }>|null|undefined} dialogues
 */
export function sceneHasDialogueAudio(dialogues) {
    if (!Array.isArray(dialogues)) return false;
    return dialogues.some((d) => {
        const url = d?.audioUrl ?? d?.audio_url ?? '';
        return Boolean(String(url).trim());
    });
}

/**
 * 与完整视频导出的音轨选择保持一致：
 * - 用户显式「视频原声」(audioEmbedded) 且有视频：播视频音轨、跳过 TTS；
 * - 否则有 TTS：播 TTS、视频静音；
 * - 无 TTS 但有视频：默认视频原声（自动兜底；TTS 生成后自动回到 TTS）；
 * - 其余：静音；
 * - videoHasAudio=false 时不走视频音轨，可降级 TTS。
 */
export function resolveSceneAudioMode({
    visualType,
    audioEmbedded,
    audios = [],
    videoHasAudio,
} = {}) {
    const hasVideo = visualType === 'video';
    const hasTts = Array.isArray(audios) && audios.length > 0;
    const videoAudioOk = hasVideo && videoHasAudio !== false;

    // 用户/数字人显式视频原声
    if (videoAudioOk && Boolean(audioEmbedded)) {
        return SCENE_AUDIO_MODE.VIDEO;
    }
    // 有可播放配音 → TTS（audioEmbedded=false 时；为 true 已在上面返回 VIDEO）
    if (hasTts) {
        return SCENE_AUDIO_MODE.TTS;
    }
    // 无配音时默认视频原声，避免「有成片音轨却整段静音」
    if (videoAudioOk) {
        return SCENE_AUDIO_MODE.VIDEO;
    }
    return SCENE_AUDIO_MODE.SILENCE;
}
