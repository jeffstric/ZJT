const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const repoRoot = path.join(__dirname, '../..');
const renderSource = fs.readFileSync(path.join(repoRoot, 'web/js/storyboard/render.js'), 'utf8');
const eventsSource = fs.readFileSync(path.join(repoRoot, 'web/js/storyboard/events.js'), 'utf8');
const playbackSource = fs.readFileSync(path.join(repoRoot, 'web/js/storyboard/playback.js'), 'utf8');

assert.doesNotMatch(
    renderSource,
    /声音同出|toggle-audio-embedded/,
    '旧的“声音同出”复选框不应继续显示'
);

assert.match(
    renderSource,
    /function renderDialoguePanel\(scene\)[\s\S]*renderDialogueAudioSource\(scene\)/,
    '音频来源选择应位于对话页签'
);

assert.match(renderSource, /data-audio-source="tts"[\s\S]*对话配音（TTS）/);
assert.match(renderSource, /data-audio-source="video"/);
assert.match(renderSource, /resolveSceneAudioMode/);
assert.match(renderSource, /autoVideoFallback/);
assert.match(renderSource, /dialogue-audio-source-auto-badge/);
assert.match(renderSource, /已自动使用视频原声/);
assert.match(eventsSource, /action === 'set-scene-audio-source'/);
assert.match(eventsSource, /audio_embedded:\s*scene\.audioEmbedded \? 1 : 0/);

assert.match(
    playbackSource,
    /video\.muted = plan\.audioMode !== SCENE_AUDIO_MODE\.VIDEO/,
    '时间轴视频应按音频来源决定是否静音'
);
assert.match(
    playbackSource,
    /plan\.audioMode === SCENE_AUDIO_MODE\.TTS[\s\S]*runAudioQueue/,
    '只有对话配音模式才应启动 TTS 队列'
);

console.log('storyboard audio source UI tests passed');
