const assert = require('assert');
const ModelCatalog = require('../../web/js/model_catalog.js');

assert.strictEqual(ModelCatalog.inferTrack('llm.script_split', 'deepseek-v4-flash'), 'value');
assert.strictEqual(ModelCatalog.inferTrack('llm.script_split', 'deepseek-v4-pro'), 'quality');
assert.strictEqual(ModelCatalog.inferTrack('llm.marketing', 'doubao-seed-2-0-lite'), 'value');
assert.strictEqual(ModelCatalog.inferTrack('llm.marketing', 'doubao-seed-2-0-pro'), 'quality');
assert.strictEqual(ModelCatalog.inferTrack('image.text_to_image', 'gpt-image-2'), 'value');
assert.strictEqual(ModelCatalog.FALLBACK_CATALOG['image.text_to_image'].quality, 'gpt-image-2');
assert.strictEqual(ModelCatalog.FALLBACK_CATALOG['image.image_edit'].value, 'gpt-image-2');
assert.strictEqual(ModelCatalog.FALLBACK_CATALOG['image.image_edit'].quality, 'gpt-image-2');
assert.strictEqual(ModelCatalog.inferTrack('video.image_to_video', 'minimax_h3'), 'value');
assert.strictEqual(ModelCatalog.inferTrack('video.image_to_video', 'seedance_2_0'), 'quality');
assert.strictEqual(ModelCatalog.FALLBACK_CATALOG['video.text_to_video'].value, 'minimax_h3');
assert.strictEqual(ModelCatalog.FALLBACK_CATALOG['video.text_to_video'].quality, 'seedance_2_0');
assert.strictEqual(ModelCatalog.FALLBACK_CATALOG['video.reference_to_video'].value, 'minimax_h3_r2v');
assert.strictEqual(ModelCatalog.FALLBACK_CATALOG['video.reference_to_video'].quality, 'seedance_2_0');
assert.strictEqual(ModelCatalog.inferTrack('video.reference_to_video', 'minimax_h3_r2v'), 'value');
assert.strictEqual(ModelCatalog.inferTrack('video.reference_to_video', 'seedance_2_0'), 'quality');
assert.strictEqual(ModelCatalog.sceneForVideoImageMode('multi_reference'), 'video.reference_to_video');
assert.strictEqual(ModelCatalog.sceneForVideoImageMode('first_last_frame'), 'video.image_to_video');
assert.strictEqual(
  ModelCatalog.findTaskByTrack(
    [{ key: 'minimax_h3_reference_to_video', value: 'minimax_h3_r2v', name: 'MiniMax H3 参考生视频' }],
    'video.reference_to_video',
    null,
    'value',
  ).value,
  'minimax_h3_r2v',
);
assert.strictEqual(ModelCatalog.inferTrack('image.script_writer', 'gpt-image-2'), 'value');
assert.strictEqual(ModelCatalog.inferTrack('image.script_writer', 'seedream-5.0-pro'), 'quality');

const collapsed = ModelCatalog.collapseLlmModels([
  { name: 'deepseek-v4-flash', vendor_name: 'zjt_api', vendor_id: 2, model_id: 10 },
  { name: 'deepseek-v4-flash', vendor_name: 'deepseek', vendor_id: 1, model_id: 10 },
  { name: 'deepseek-v4-pro', vendor_name: 'deepseek', vendor_id: 1, model_id: 11 },
], 'llm.chat', null);
assert.strictEqual(collapsed.length, 2);
const flash = collapsed.find((i) => i.canonical === 'deepseek-v4-flash');
assert.strictEqual(flash.defaultRoute.vendor_name, 'deepseek');

console.log('test_model_catalog.js ok');
