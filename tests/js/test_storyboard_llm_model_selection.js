const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const statePath = path.join(__dirname, '../../web/js/storyboard/state.js');
assert.equal(fs.existsSync(statePath), true, 'storyboard state.js should exist');

const source = fs.readFileSync(statePath, 'utf8')
  .replace(/import[\s\S]*?from '\.\/adapters\.js';\s*/, '')
  .replace(/export\s+function\s+/g, 'function ')
  .replace(/export\s+default\s+state;\s*/g, '');

const factory = new Function(
  'assetFromApi',
  'buildStoryboardTitle',
  'sceneFromApi',
  'scenesFromApi',
  'dialogueFromApi',
source + '\nreturn { state, setModels, resolveSelectedLlmModel, resolveSelectedScriptSplitLlmModel, serializeUiConfig, restoreUiConfig };'
);

const helpers = factory(
  item => item,
  storyboard => storyboard.title || '',
  scene => scene,
  scenes => scenes,
  dialogue => dialogue
);

helpers.setModels({
  llm_models: [
    { model: 'qwen/qwen3.5-plus', name: 'Qwen 3.5 Plus', model_id: 42, vendor_id: 7 },
  ],
});

helpers.state.selectedLlmModel = 'qwen/qwen3.5-plus';
const resolvedFromString = helpers.resolveSelectedLlmModel();

assert.equal(resolvedFromString.model, 'qwen/qwen3.5-plus');
assert.equal(resolvedFromString.model_id, 42);
assert.equal(resolvedFromString.vendor_id, 7);
assert.deepEqual(helpers.state.selectedLlmModel, resolvedFromString);

helpers.state.selectedLlmModel = { model: 'qwen/qwen3.5-plus' };
const resolvedFromPartialObject = helpers.resolveSelectedLlmModel();

assert.equal(resolvedFromPartialObject.model_id, 42);
assert.equal(resolvedFromPartialObject.vendor_id, 7);

helpers.setModels({
  llm_models: [
    { model: 'deepseek-v4-flash', name: 'deepseek-v4-flash', model_id: 1007, vendor_id: 9, vendor_name: 'zjt_api' },
    { model: 'deepseek-v4-flash', name: 'deepseek-v4-flash', model_id: 1007, vendor_id: 10, vendor_name: 'deepseek' },
  ],
});

helpers.state.selectedLlmModel = { model: 'deepseek-v4-flash', vendorId: 10 };
const resolvedFromScriptWriterPreference = helpers.resolveSelectedLlmModel();

assert.equal(resolvedFromScriptWriterPreference.model_id, 1007);
assert.equal(resolvedFromScriptWriterPreference.vendor_id, 10);

helpers.state.selectedScriptSplitLlmModel = { model: 'deepseek-v4-flash', vendorId: 10 };
const resolvedScriptSplitModel = helpers.resolveSelectedScriptSplitLlmModel();

assert.equal(resolvedScriptSplitModel.model, 'deepseek-v4-flash');
assert.equal(resolvedScriptSplitModel.model_id, 1007);
assert.equal(resolvedScriptSplitModel.vendor_id, 10);
assert.deepEqual(helpers.state.selectedScriptSplitLlmModel, resolvedScriptSplitModel);

helpers.state.selectedImageTaskId = 26;
helpers.state.selectedVideoTaskId = 12;
const uiConfig = helpers.serializeUiConfig();
assert.equal(uiConfig.selectedImageTaskId, 26);
assert.equal(uiConfig.selectedVideoTaskId, 12);

helpers.state.selectedImageTaskId = null;
helpers.state.selectedVideoTaskId = null;
helpers.restoreUiConfig({ selectedImageTaskId: 17, selectedVideoTaskId: 22, chatMode: 'image' });
assert.equal(helpers.state.selectedImageTaskId, 17);
assert.equal(helpers.state.selectedVideoTaskId, 22);
assert.equal(helpers.state.chatMode, 'dialogue', 'removed image chat mode should restore to dialogue');

console.log('storyboard LLM model selection tests passed');
