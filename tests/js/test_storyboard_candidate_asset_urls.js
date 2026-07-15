const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const eventsPath = path.join(__dirname, '../../web/js/storyboard/events.js');
const source = fs.readFileSync(eventsPath, 'utf8');
const pollingPath = path.join(__dirname, '../../web/js/storyboard/polling.js');
const pollingSource = fs.readFileSync(pollingPath, 'utf8');
const cssPath = path.join(__dirname, '../../web/css/storyboard.css');
const cssSource = fs.readFileSync(cssPath, 'utf8');
const renderPath = path.join(__dirname, '../../web/js/storyboard/render.js');
const renderSource = fs.readFileSync(renderPath, 'utf8');

assert.match(source, /function getSceneAssetCandidateUrl\(asset\)/);
assert.match(source, /asset\.result_url/);
assert.match(source, /asset\.url/);
assert.match(source, /asset\.image_url/);
assert.match(source, /asset\.video_url/);
assert.match(source, /asset\.ai_tool\?\.result_url/);
assert.match(source, /url: getSceneAssetCandidateUrl\(asset\)/);
assert.match(source, /function mapSceneAssetCandidates\(response,\s*assetType\)/);
assert.match(source, /response\?\.selected\?\.\[assetType\]/);
assert.match(
  source,
  /async function selectSceneCandidate\(target,\s*\{\s*autoplay\s*=\s*false\s*\}\s*=\s*\{\}\)/
);
assert.match(source, /api\.selectSceneAsset\(current\.id,\s*assetType,\s*assetId\)/);
assert.match(source, /scene\.previewAssetType = 'first_frame'/);
assert.match(source, /scene\.previewAssetType = 'video'/);
assert.match(source, /data-candidate-id/);
assert.match(
  renderSource,
  /<button[^>]*class="candidate-video-badge"[^>]*data-candidate-play/,
  'video candidate center control should be a semantic play button'
);
assert.match(
  source,
  /event\.target\.closest\('\[data-candidate-play\]'\)/,
  'candidate click routing should detect the center play button'
);
assert.match(
  source,
  /selectSceneCandidate\(candidateTarget,\s*\{\s*autoplay:/,
  'candidate selection should receive the autoplay intent'
);
assert.match(
  source,
  /previewVideo\?\.play\(\)/,
  'center play button should start the main preview video'
);
assert.doesNotMatch(
  source,
  /playPromise\.catch\(\(\) => notify/,
  'autoplay rejection handling must not block the UI with window.alert'
);
assert.match(
  source,
  /restoreVideoCandidateSelection/,
  'failed optimistic selection should restore the previous video candidate'
);

assert.match(pollingSource, /function upsertSceneCandidateFromTask\(sceneId,\s*assetType,\s*taskInfo\)/);
assert.match(pollingSource, /scene\.selectedFirstFrameId = data\.first_frame\.asset_id/);
assert.match(pollingSource, /upsertSceneCandidateFromTask\(scene\.id,\s*'first_frame',\s*data\.first_frame\)/);
assert.match(pollingSource, /captureAssetSelection\(sceneAtRequest\)/);
assert.match(pollingSource, /isPollAssetSelectionCurrent\(scene,\s*'first_frame',\s*requestSelection\)/);

assert.match(
  cssSource,
  /\.candidate-grid\s*\{[\s\S]*grid-template-columns:\s*1fr;/,
  'storyboard image candidates should render one item per row'
);

assert.match(renderSource, /candidate-placeholder/);
assert.match(renderSource, /choosePreviewMedia\(scene\)/);

console.log('storyboard candidate asset url tests passed');
