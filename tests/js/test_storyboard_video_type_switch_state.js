const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const sourcePath = path.join(__dirname, '../../web/js/storyboard/video_type_switch_state.js');
let source = fs.readFileSync(sourcePath, 'utf8');
source = source
    .replace(/export function /g, 'function ')
    .replace(/export const /g, 'const ');
source += '\nmodule.exports = { canSwitchToDigitalHuman, applyVideoTypeSwitchResult };';

const sandbox = { module: { exports: {} }, exports: {} };
vm.runInNewContext(source, sandbox, { filename: sourcePath });
const { canSwitchToDigitalHuman, applyVideoTypeSwitchResult } = sandbox.module.exports;

const multiSpeakerScene = {
    dialogues: [
        { characterId: 1, text: '甲' },
        { characterId: 2, text: '乙' },
    ],
};
assert.deepEqual(
    JSON.parse(JSON.stringify(canSwitchToDigitalHuman(multiSpeakerScene))),
    { allowed: false, reason: '对口型模式仅支持单个说话角色' }
);

assert.equal(canSwitchToDigitalHuman({
    dialogues: [
        { characterId: 1, text: '第一句' },
        { characterId: 1, text: '第二句' },
        { characterId: null, text: '旁白' },
    ],
}).allowed, true);

const scene = {
    videoType: 'digital_human',
    selectedVideoId: 3,
    videoUrl: '/old.mp4',
    previewAssetType: 'video',
};
applyVideoTypeSwitchResult(scene, {
    video_type: 'video',
    selected_video_id: 9,
    video_url: '/kept.mp4',
});
assert.equal(scene.videoType, 'video');
assert.equal(scene.selectedVideoId, 9);
assert.equal(scene.videoUrl, '/kept.mp4');
assert.equal(scene.previewAssetType, 'video');

applyVideoTypeSwitchResult(scene, {
    video_type: 'digital_human',
    selected_video_id: null,
    video_url: null,
});
assert.equal(scene.selectedVideoId, null);
assert.equal(scene.videoUrl, null);
assert.equal(scene.previewAssetType, 'first_frame');

console.log('storyboard video type switch state tests passed');
