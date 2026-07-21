const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const sourcePath = path.join(__dirname, '../../web/js/storyboard/playback_audio.js');
let source = fs.readFileSync(sourcePath, 'utf8');
source = source
    .replace(/export function /g, 'function ')
    .replace(/export const /g, 'const ');
source += '\nmodule.exports = { SCENE_AUDIO_MODE, resolveSceneAudioMode };';

const sandbox = { module: { exports: {} }, exports: {}, Object, Array, Boolean };
vm.runInNewContext(source, sandbox, { filename: sourcePath });
const { SCENE_AUDIO_MODE, resolveSceneAudioMode } = sandbox.module.exports;

assert.equal(resolveSceneAudioMode({
    visualType: 'video',
    audioEmbedded: true,
    audios: [{ url: '/tts.mp3' }],
}), SCENE_AUDIO_MODE.VIDEO, '视频原声应优先于 TTS，避免双音轨');

assert.equal(resolveSceneAudioMode({
    visualType: 'video',
    audioEmbedded: false,
    audios: [{ url: '/tts.mp3' }],
}), SCENE_AUDIO_MODE.TTS, '关闭视频原声后应使用 TTS');

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
}), SCENE_AUDIO_MODE.SILENCE, '无可用音源时应静音');

console.log('storyboard playback audio tests passed');
