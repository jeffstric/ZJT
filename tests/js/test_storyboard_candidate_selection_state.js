const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const modulePath = path.join(__dirname, '../../web/js/storyboard/candidate_selection_state.js');
assert.equal(fs.existsSync(modulePath), true, 'candidate selection state module should exist');

const source = fs.readFileSync(modulePath, 'utf8')
  .replace(/export\s+function\s+/g, 'function ');
const factory = new Function(
  source + '\nreturn { choosePreviewMedia, captureAssetSelection, isPollAssetSelectionCurrent, captureVideoCandidateSelection, applyVideoCandidateSelection, restoreVideoCandidateSelection };'
);
const selectionState = factory();

const sceneWithVideo = {
  firstFrameUrl: '/frames/old.png',
  videoUrl: '/videos/scene.mp4',
  previewAssetType: 'first_frame',
};
assert.deepEqual(
  selectionState.choosePreviewMedia(sceneWithVideo),
  { kind: 'image', url: '/frames/old.png' },
  'clicking an image candidate should preview the first frame even when the scene has a video'
);

assert.deepEqual(
  selectionState.choosePreviewMedia({ ...sceneWithVideo, previewAssetType: 'video' }),
  { kind: 'video', url: '/videos/scene.mp4' },
  'clicking a video candidate should preview the selected video'
);

const beforeRequest = selectionState.captureAssetSelection({
  selectedFirstFrameId: 11,
  selectedVideoId: 21,
});
assert.equal(
  selectionState.isPollAssetSelectionCurrent(
    { selectedFirstFrameId: 12, selectedVideoId: 21 },
    'first_frame',
    beforeRequest
  ),
  false,
  'a poll started before the user selected another first frame must be treated as stale'
);
assert.equal(
  selectionState.isPollAssetSelectionCurrent(
    { selectedFirstFrameId: 12, selectedVideoId: 21 },
    'video',
    beforeRequest
  ),
  true,
  'changing the first frame must not invalidate the video portion of the same poll response'
);

const videoCandidates = [
  { id: 31, url: '/videos/31.mp4', selected: true },
  { id: 32, url: '/videos/32.mp4', selected: false },
];
const sceneWithCandidateSelection = {
  selectedVideoId: 31,
  videoUrl: '/videos/31.mp4',
  previewAssetType: 'first_frame',
};
const selectionSnapshot = selectionState.captureVideoCandidateSelection(
  sceneWithCandidateSelection,
  videoCandidates
);

selectionState.applyVideoCandidateSelection(
  sceneWithCandidateSelection,
  videoCandidates,
  32,
  '/videos/32.mp4'
);
assert.equal(sceneWithCandidateSelection.selectedVideoId, 32);
assert.equal(sceneWithCandidateSelection.videoUrl, '/videos/32.mp4');
assert.equal(sceneWithCandidateSelection.previewAssetType, 'video');
assert.deepEqual(videoCandidates.map(item => item.selected), [false, true]);

selectionState.restoreVideoCandidateSelection(
  sceneWithCandidateSelection,
  videoCandidates,
  selectionSnapshot
);
assert.equal(sceneWithCandidateSelection.selectedVideoId, 31);
assert.equal(sceneWithCandidateSelection.videoUrl, '/videos/31.mp4');
assert.equal(sceneWithCandidateSelection.previewAssetType, 'first_frame');
assert.deepEqual(videoCandidates.map(item => item.selected), [true, false]);

console.log('storyboard candidate selection state tests passed');
