// 重新编辑必须切到图片/视频模式，并把 2K/3K/9:16/Seedream 等参数映射回输入栏选项。
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const js = fs.readFileSync(
  path.join(__dirname, '../../web/js/marketing_agent.js'),
  'utf8'
);

const start = js.indexOf('function imageSizeToUiResolution(');
const end = js.indexOf('function resolveTaskFromMeta(', start);
assert.notEqual(start, -1, 'imageSizeToUiResolution should exist');
assert.notEqual(end, -1, 'resolveTaskFromMeta should follow the pure helpers');

const helpers = new Function(
  js.slice(start, end) + '\nreturn { imageSizeToUiResolution, uiResolutionToImageSize, findModelOptionForGeneration, normalizeRestoredVideoImageMode };'
)();

const labels = { resolution_2k: '高清 2K', resolution_4k: '超清 4K' };

assert.equal(helpers.imageSizeToUiResolution('2K', labels), '高清 2K');
assert.equal(helpers.imageSizeToUiResolution('2k', labels), '高清 2K');
assert.equal(helpers.imageSizeToUiResolution('3K', labels), '3K');
assert.equal(helpers.imageSizeToUiResolution('3k', labels), '3K');
assert.equal(helpers.imageSizeToUiResolution('4K', labels), '超清 4K');
assert.equal(helpers.imageSizeToUiResolution('1K', labels), '1K');
assert.equal(helpers.imageSizeToUiResolution('auto', labels), 'auto');

assert.equal(helpers.uiResolutionToImageSize('高清 2K', labels), '2K');
assert.equal(helpers.uiResolutionToImageSize('3K', labels), '3K');
assert.equal(helpers.uiResolutionToImageSize('超清 4K', labels), '4K');
assert.equal(helpers.uiResolutionToImageSize('auto', labels), '');

const seedream = { key: 'seedream-5.0', name: 'Seedream 5.0（性价比，6算力）', value: 'seedream-5.0' };
const seedreamPro = { key: 'seedream-5.0-pro', name: 'Seedream 5.0 Pro（效果，20算力）', value: 'seedream-5.0-pro' };
const pools = [[seedreamPro, seedream]];

assert.equal(
  helpers.findModelOptionForGeneration(pools, { key: 'seedream-5.0', short_key: 'seedream-5.0' }, 'Seedream 5.0').key,
  'seedream-5.0'
);
assert.equal(
  helpers.findModelOptionForGeneration(pools, { key: 'seedream-5.0-pro' }, '').key,
  'seedream-5.0-pro'
);
assert.equal(
  helpers.findModelOptionForGeneration(pools, null, 'Seedream 5.0').key,
  'seedream-5.0'
);

assert.equal(helpers.normalizeRestoredVideoImageMode('multi_reference'), 'multi_reference');
assert.equal(helpers.normalizeRestoredVideoImageMode('first_last_with_ref'), 'multi_reference');
assert.equal(helpers.normalizeRestoredVideoImageMode('first_last_frame'), 'first_last_frame');

const restoreStart = js.indexOf('async function restoreGenerationParamsToEditor(');
const restoreEnd = js.indexOf('async function handleGeneratedResultEdit(', restoreStart);
assert.notEqual(restoreStart, -1);
const restoreBody = js.slice(restoreStart, restoreEnd);
assert.equal(restoreBody.includes('selectType(typeObj)'), true, 're-edit must switch image/video mode');
assert.equal(restoreBody.includes('restoringGenerationParams = true'), true);
assert.equal(restoreBody.includes('applyRestoredGenerationScalars'), true);

assert.equal(js.includes('if (restoringGenerationParams) return;'), true, 'model/media watchers must ignore restore');
assert.equal(js.includes("form.append('ref_image_urls', urlOnlyImages.join(','))"), true);
assert.equal(js.includes("form.append('image_urls', urlOnlyImages.join(','))"), true);
assert.equal(js.includes('const regenImageSize = uiResolutionToImageSize(meta.image_size, imageResolutionLabels());'), true);

console.log('marketing agent re-edit param tests passed');
