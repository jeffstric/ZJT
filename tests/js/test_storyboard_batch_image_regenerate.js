const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const repoRoot = path.join(__dirname, '../..');
const read = (relativePath) => fs.readFileSync(path.join(repoRoot, relativePath), 'utf8');

const operationsSource = read('web/js/storyboard/batch_operations.js');
const autoImagesSource = read('web/js/storyboard/auto_missing_images.js');
const imageStateSource = read('web/js/storyboard/auto_missing_images_state.js');
const eventsSource = read('web/js/storyboard/events.js');
const renderSource = read('web/js/storyboard/render.js');

assert.match(
  operationsSource,
  /batchGenerateFirstFrames[\s\S]*existingPolicy:\s*'regenerate'/,
  'selected-scene image generation should explicitly request regeneration'
);
assert.match(
  autoImagesSource,
  /existing_policy:\s*existingPolicy/,
  'the frontend request should pass existing_policy to the storyboard API'
);
assert.match(
  imageStateSource,
  /regenerate_pending[\s\S]*regenerating[\s\S]*regenerate_failed/,
  'regeneration should expose pending, running, and failed display states while retaining the old image'
);
assert.match(
  imageStateSource,
  /String\(curSel\)\s*===\s*String\(item\.baseAssetId\)/,
  'a regenerated result should only replace the original selection when the user has not switched candidates'
);
assert.match(
  eventsSource,
  /原图片会保留，生成成功后自动选中新图/,
  'the confirmation should explain candidate preservation and selection behavior'
);
assert.match(
  renderSource,
  /existingImageCount[\s\S]*重新生成[\s\S]*已有图片会保留为候选/,
  'the batch toolbar should identify regeneration and explain that existing images are retained'
);

const testState = {
  scenes: [{
    id: 11,
    selectedFirstFrameId: 101,
    firstFrameUrl: '/frames/original.png',
    taskStatus: {},
  }],
};
const executableStateSource = imageStateSource
  .replace("import state from './state.js';", 'const state = globalThis.__storyboardBatchTestState;')
  .replace(/export\s+(?=(const|function)\s)/g, '');
globalThis.__storyboardBatchTestState = testState;
const imageState = new Function(
  `${executableStateSource}\nreturn { applyImageBatchStatus, getFirstFrameDisplayStatus };`
)();

imageState.applyImageBatchStatus({
  batch_id: 77,
  status: 'running',
  existing_policy: 'regenerate',
  items: [{
    scene_id: 11,
    status: 'pending',
    plan_status: 'regenerate_pending',
    existing_policy: 'regenerate',
    base_asset_id: 101,
  }],
});
assert.equal(imageState.getFirstFrameDisplayStatus(testState.scenes[0]), 'regenerate_pending');
assert.equal(testState.scenes[0].firstFrameUrl, '/frames/original.png');
assert.equal(testState.scenes[0].selectedFirstFrameId, 101);

imageState.applyImageBatchStatus({
  batch_id: 77,
  status: 'running',
  existing_policy: 'regenerate',
  items: [{
    scene_id: 11,
    status: 'running',
    plan_status: 'regenerate_pending',
    existing_policy: 'regenerate',
    base_asset_id: 101,
    asset_id: 102,
  }],
});
assert.equal(imageState.getFirstFrameDisplayStatus(testState.scenes[0]), 'regenerating');
assert.equal(testState.scenes[0].firstFrameUrl, '/frames/original.png');
assert.equal(testState.scenes[0].selectedFirstFrameId, 101);

imageState.applyImageBatchStatus({
  batch_id: 77,
  status: 'completed',
  existing_policy: 'regenerate',
  items: [{
    scene_id: 11,
    status: 'completed',
    plan_status: 'regenerate_pending',
    existing_policy: 'regenerate',
    base_asset_id: 101,
    asset_id: 102,
    result_url: '/frames/regenerated.png',
  }],
});
assert.equal(testState.scenes[0].firstFrameUrl, '/frames/regenerated.png');
assert.equal(testState.scenes[0].selectedFirstFrameId, 102);

testState.scenes[0].selectedFirstFrameId = 103;
testState.scenes[0].firstFrameUrl = '/frames/manually-selected.png';
imageState.applyImageBatchStatus({
  batch_id: 78,
  status: 'completed',
  existing_policy: 'regenerate',
  items: [{
    scene_id: 11,
    status: 'completed',
    plan_status: 'regenerate_pending',
    existing_policy: 'regenerate',
    base_asset_id: 101,
    asset_id: 104,
    result_url: '/frames/late-result.png',
  }],
});
assert.equal(testState.scenes[0].firstFrameUrl, '/frames/manually-selected.png');
assert.equal(testState.scenes[0].selectedFirstFrameId, 103);
delete globalThis.__storyboardBatchTestState;

console.log('storyboard batch image regenerate tests passed');
