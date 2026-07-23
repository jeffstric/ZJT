const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const repoRoot = path.join(__dirname, '../..');
const htmlSource = fs.readFileSync(path.join(repoRoot, 'web/script_writer.html'), 'utf8');
const cssSource = fs.readFileSync(path.join(repoRoot, 'web/css/script_writer.css'), 'utf8');
const jsSource = fs.readFileSync(path.join(repoRoot, 'web/js/script_writer.js'), 'utf8');
const zhIndex = JSON.parse(fs.readFileSync(path.join(repoRoot, 'web/i18n/locales/zh-CN/index.json'), 'utf8'));
const enIndex = JSON.parse(fs.readFileSync(path.join(repoRoot, 'web/i18n/locales/en/index.json'), 'utf8'));

assert.match(
  cssSource,
  /@media\s*\(max-width:\s*1400px\)[\s\S]*\.file-sidebar\s*\{[\s\S]*position:\s*fixed[\s\S]*transform:\s*translateX\(100%\)/,
  'script writer should collapse the staging sidebar into a drawer at medium widths'
);

assert.match(
  cssSource,
  /\.top-header\s*\{[\s\S]*max-width:\s*100vw[\s\S]*overflow-x:\s*hidden/,
  'top header should not overflow the viewport'
);

assert.match(
  cssSource,
  /\.header-left\s*,\s*\.header-right\s*\{[\s\S]*min-width:\s*0/,
  'header columns should be allowed to shrink'
);

assert.match(
  cssSource,
  /@media\s*\(max-width:\s*1400px\)[\s\S]*\.top-header\s*\{[\s\S]*flex-wrap:\s*nowrap[\s\S]*overflow-y:\s*visible/,
  'top header should keep left and right regions on the same row while allowing inner controls to wrap'
);

assert.match(
  cssSource,
  /@media\s*\(max-width:\s*1400px\)[\s\S]*\.header-right\s*\{[\s\S]*justify-content:\s*flex-start[\s\S]*flex-wrap:\s*wrap/,
  'header controls should wrap from the left edge of the available right-side area'
);

assert.match(
  cssSource,
  /@media\s*\(max-width:\s*1400px\)[\s\S]*\.model-selector-card\s*\{[\s\S]*flex-wrap:\s*wrap/,
  'model selector card should wrap its internal controls when crowded'
);

assert.match(
  cssSource,
  /@media\s*\(max-width:\s*1400px\)[\s\S]*\.feedback-fab-container\s*\{[\s\S]*display:\s*none/,
  'feedback floating button should disappear on narrow screens'
);

assert.match(
  cssSource,
  /@media\s*\(max-width:\s*1024px\)[\s\S]*\.step-nav\s*\{[\s\S]*display:\s*none/,
  'left floating step-nav should hide on narrow screens to avoid covering chat/input'
);

assert.match(
  cssSource,
  /\.chat-area\s*\{[\s\S]*min-width:\s*0[\s\S]*overflow-x:\s*hidden/,
  'chat area must not expand past viewport when history has wide content'
);

assert.match(
  cssSource,
  /\.input-container\s*\{[\s\S]*position:\s*relative/,
  'input container should be positioning context for the send button'
);

assert.match(
  cssSource,
  /\.send-btn\s*\{[\s\S]*position:\s*absolute[\s\S]*right:\s*8px/,
  'send button should stay inside the input box at all widths'
);

assert.match(
  cssSource,
  /\.send-btn\s*\{[\s\S]*top:\s*50%[\s\S]*transform:\s*translateY\(-50%\)/,
  'send button should be vertically centered in single-line input'
);

assert.match(
  cssSource,
  /\.input-container\.is-expanded\s+\.send-btn\s*\{[\s\S]*bottom:\s*8px/,
  'send button should stick to bottom-right when input is multi-line expanded'
);

assert.match(
  cssSource,
  /\.input-section\s*\{[\s\S]*safe-area-inset-bottom/,
  'input section should respect bottom safe-area on notched phones'
);

assert.match(
  jsSource,
  /function\s+syncSendBtnLayout\s*\(/,
  'syncSendBtnLayout should exist to toggle is-expanded on the input container'
);

assert.match(
  jsSource,
  /function\s+restoreInputControlsAfterHistory\([\s\S]*syncSendBtnLayout/,
  'history restore should re-sync send button layout after messages render'
);

assert.match(
  jsSource,
  /function\s+restoreInputControlsAfterHistory\([\s\S]*loadAndDisplayHistory|function\s+loadAndDisplayHistory[\s\S]*restoreInputControlsAfterHistory/,
  'history load should restore input controls after rendering messages'
);

assert.match(
  cssSource,
  /@media\s*\(max-width:\s*1400px\)[\s\S]*\.file-sidebar-toggle-btn\s*\{[\s\S]*right:\s*28px[\s\S]*bottom:\s*156px/,
  'staging sidebar floating button should keep distance from the send button'
);

assert.match(
  htmlSource,
  /class="model-settings-toggle-btn"[\s\S]*onclick="toggleModelSettingsPanel\(\)"/,
  'header should provide a compact model settings button'
);

assert.match(
  htmlSource,
  /class="model-settings-overlay"[\s\S]*onclick="closeModelSettingsPanel\(\)"/,
  'compact model settings panel should have a dismiss overlay'
);

assert.match(
  cssSource,
  /\.model-settings-toggle-btn\s*\{[\s\S]*display:\s*none/,
  'compact model settings button should be hidden by default'
);

assert.match(
  cssSource,
  /@media\s*\(max-width:\s*900px\)[\s\S]*\.model-settings-toggle-btn\s*\{[\s\S]*display:\s*flex/,
  'compact model settings button should appear below 900px'
);

assert.match(
  cssSource,
  /@media\s*\(max-width:\s*900px\)[\s\S]*\.model-selector-card\s*\{[\s\S]*display:\s*none/,
  'model selector card should collapse below 900px'
);

assert.match(
  cssSource,
  /@media\s*\(max-width:\s*900px\)[\s\S]*\.model-selector-card\.compact-open\s*\{[\s\S]*position:\s*fixed[\s\S]*display:\s*flex/,
  'collapsed model selector should reopen as a fixed panel'
);

assert.match(
  jsSource,
  /function\s+toggleModelSettingsPanel\(\)[\s\S]*compact-open/,
  'script writer should toggle the compact model settings panel'
);

assert.match(
  jsSource,
  /function\s+closeModelSettingsPanel\(\)[\s\S]*compact-open/,
  'script writer should close the compact model settings panel'
);

for (const key of [
  'intervention_level',
  'select_intervention_level',
  'intervention_balanced',
  'intervention_concise',
  'intervention_detailed',
  'staging_files',
  'model_settings',
]) {
  assert.ok(zhIndex[key], `zh-CN index locale should define ${key}`);
  assert.ok(enIndex[key], `en index locale should define ${key}`);
}

assert.match(
  jsSource,
  /const\s+INTERVENTION_LEVEL_I18N_KEYS\s*=\s*\{[\s\S]*balanced:\s*'intervention_balanced'[\s\S]*concise:\s*'intervention_concise'[\s\S]*detailed:\s*'intervention_detailed'/,
  'intervention selector display should map values to i18n keys'
);

assert.match(
  jsSource,
  /display\.textContent\s*=\s*window\.t\s*\?\s*window\.t\(translationKey\)\s*:\s*\(fallbackLabels/,
  'intervention selector display should use window.t instead of raw option text'
);

assert.match(
  jsSource,
  /ZJTi18n\.on\('locale-changed'[\s\S]*updateInterventionLevelDisplay\(\)/,
  'language changes should refresh the custom intervention display text'
);

assert.match(
  cssSource,
  /\.model-select-display\s*\{[\s\S]*pointer-events:\s*auto[\s\S]*cursor:\s*pointer/,
  'model selector display should capture clicks instead of opening the native select menu'
);

assert.match(
  cssSource,
  /\.custom-model-select-menu\s*\{[\s\S]*position:\s*fixed[\s\S]*z-index:\s*1600/,
  'custom model select menu should render as a fixed overlay'
);

assert.match(
  jsSource,
  /function\s+openCustomModelSelectMenu\([\s\S]*getBoundingClientRect\(\)[\s\S]*style\.top\s*=\s*`\$\{rect\.bottom \+ 6\}px`/,
  'custom model select menu should be positioned below the control'
);

assert.match(
  jsSource,
  /selector\.dispatchEvent\(new Event\('change',\s*\{\s*bubbles:\s*true\s*\}\)\)/,
  'custom model select choices should dispatch native change events'
);

console.log('script writer responsive i18n tests passed');
