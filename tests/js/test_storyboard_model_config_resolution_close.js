const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const root = path.join(__dirname, '../..');
const eventsSource = fs.readFileSync(path.join(root, 'web/js/storyboard/events.js'), 'utf8');
const renderSource = fs.readFileSync(path.join(root, 'web/js/storyboard/render.js'), 'utf8');
const cssSource = fs.readFileSync(path.join(root, 'web/css/storyboard.css'), 'utf8');

const resolutionStart = eventsSource.indexOf("if (action === 'set-video-resolution')");
const resolutionEnd = eventsSource.indexOf("if (action === 'toggle-clip-to-audio')", resolutionStart);
assert.ok(resolutionStart >= 0 && resolutionEnd > resolutionStart, 'resolution action handler should exist');
const resolutionHandler = eventsSource.slice(resolutionStart, resolutionEnd);
assert.match(
  resolutionHandler,
  /rerender\(\[Region\.MODAL, Region\.AGENT_PANEL\]\)/,
  'resolution selection should refresh both modal selected state and agent panel'
);

const modalStart = renderSource.indexOf('function renderModelConfigModal()');
const modalEnd = renderSource.indexOf('function renderDialogueModelConfig()', modalStart);
assert.ok(modalStart >= 0 && modalEnd > modalStart, 'model config modal renderer should exist');
const modalRenderer = renderSource.slice(modalStart, modalEnd);
const closeActions = modalRenderer.match(/data-action="close-model-config"/g) || [];
assert.equal(closeActions.length, 1, 'model config modal should have only one close action');
assert.match(
  modalRenderer,
  /<button type="button" class="model-config-close" data-action="close-model-config" aria-label="关闭模型配置" title="关闭">/,
  'top-right close button should be accessible and use the dedicated style class'
);
assert.doesNotMatch(
  modalRenderer,
  /class="btn-ghost" data-action="close-model-config"/,
  'footer close button should be removed'
);

assert.match(cssSource, /\.model-config-dialog \.model-config-close\s*\{/);
assert.match(cssSource, /\.model-config-dialog \.model-config-close:hover\s*\{/);
assert.match(cssSource, /\.model-config-dialog \.model-config-close:focus-visible\s*\{/);

console.log('storyboard model config resolution and close button test passed');
