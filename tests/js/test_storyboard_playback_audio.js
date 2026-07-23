const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const sourcePath = path.join(__dirname, '../../web/js/storyboard/playback_audio.js');
let source = fs.readFileSync(sourcePath, 'utf8');
source = source
    .replace(/export function /g, 'function ')
    .replace(/export const /g, 'const ');
source += '\nmodule.exports = { SCENE_AUDIO_MODE, resolveSceneAudioMode, sceneHasDialogueAudio };';

const sandbox = { module: { exports: {} }, exports: {}, Object, Array, Boolean, String };
vm.runInNewContext(source, sandbox, { filename: sourcePath });
const {
    SCENE_AUDIO_MODE,
    resolveSceneAudioMode,
    sceneHasDialogueAudio,
} = sandbox.module.exports;

assert.equal(resolveSceneAudioMode({
    visualType: 'video',
    audioEmbedded: true,
    audios: [{ url: '/tts.mp3' }],
}), SCENE_AUDIO_MODE.VIDEO, '显式视频原声应优先于 TTS，避免双音轨');

assert.equal(resolveSceneAudioMode({
    visualType: 'video',
    audioEmbedded: false,
    audios: [{ url: '/tts.mp3' }],
}), SCENE_AUDIO_MODE.TTS, '关闭视频原声且有 TTS 时应使用 TTS');

assert.equal(resolveSceneAudioMode({
    visualType: 'image',
    audioEmbedded: true,
    audios: [{ url: '/tts.mp3' }],
}), SCENE_AUDIO_MODE.TTS, '没有视频时应降级使用 TTS');

assert.equal(resolveSceneAudioMode({
    visualType: 'video',
    audioEmbedded: true,
    videoHasAudio: false,
    audios: [{ url: '/tts.mp3' }],
}), SCENE_AUDIO_MODE.TTS, '确认视频无音轨时应降级使用 TTS');

assert.equal(resolveSceneAudioMode({
    visualType: 'video',
    audioEmbedded: false,
    audios: [],
}), SCENE_AUDIO_MODE.VIDEO, '无对话配音时应默认视频原声，而非静音');

assert.equal(resolveSceneAudioMode({
    visualType: 'video',
    audioEmbedded: false,
    videoHasAudio: false,
    audios: [],
}), SCENE_AUDIO_MODE.SILENCE, '无配音且确认视频无音轨时应静音');

assert.equal(resolveSceneAudioMode({
    visualType: 'image',
    audioEmbedded: false,
    audios: [],
}), SCENE_AUDIO_MODE.SILENCE, '无视频无配音时应静音');

assert.equal(sceneHasDialogueAudio([
    { audioUrl: '' },
    { audio_url: '  ' },
]), false, '空配音 URL 不算有对话音频');

assert.equal(sceneHasDialogueAudio([
    { audioUrl: '' },
    { audioUrl: '/a.wav' },
]), true, '任一非空 audioUrl 即视为有对话音频');

console.log('storyboard playback audio tests passed');
