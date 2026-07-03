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
assert.match(source, /async function selectSceneCandidate\(target\)/);
assert.match(source, /api\.selectSceneAsset\(current\.id,\s*assetType,\s*assetId\)/);
assert.match(source, /data-candidate-id/);

assert.match(pollingSource, /function upsertSceneCandidateFromTask\(sceneId,\s*assetType,\s*taskInfo\)/);
assert.match(pollingSource, /scene\.selectedFirstFrameId = data\.first_frame\.asset_id/);
assert.match(pollingSource, /upsertSceneCandidateFromTask\(scene\.id,\s*'first_frame',\s*data\.first_frame\)/);

assert.match(
  cssSource,
  /\.candidate-grid\s*\{[\s\S]*grid-template-columns:\s*1fr;/,
  'storyboard image candidates should render one item per row'
);

assert.match(renderSource, /candidate-placeholder/);
assert.match(renderSource, /img\.url\s*\?/);

console.log('storyboard candidate asset url tests passed');
