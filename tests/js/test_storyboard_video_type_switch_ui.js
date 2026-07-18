const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const read = relative => fs.readFileSync(path.join(__dirname, '../..', relative), 'utf8');
const stateSource = read('web/js/storyboard/state.js');
const apiSource = read('web/js/storyboard/api.js');
const renderSource = read('web/js/storyboard/render.js');
const eventsSource = read('web/js/storyboard/events.js');
const cssSource = read('web/css/storyboard.css');

assert.match(stateSource, /videoTypeSwitch:\s*\{[\s\S]*saving:\s*false/);
assert.match(apiSource, /export async function switchSceneVideoType/);
assert.match(apiSource, /expected_video_type/);

assert.match(renderSource, /data-action="request-video-type-switch"/);
assert.match(renderSource, /data-action="confirm-video-type-switch"/);
assert.match(renderSource, /data-action="cancel-video-type-switch"/);
assert.match(renderSource, /对口型模式仅支持单个说话角色/);

assert.match(eventsSource, /action === 'request-video-type-switch'/);
assert.match(eventsSource, /action === 'confirm-video-type-switch'/);
assert.match(eventsSource, /if \(state\.videoTypeSwitch\.saving\) return/);
assert.match(eventsSource, /await loadSceneCandidates\(current\.id\)/);
assert.match(eventsSource, /applyVideoTypeSwitchResult\(current, response\)/);
assert.match(eventsSource, /Region\.CANDIDATES/);
assert.match(eventsSource, /Region\.GRID/);

assert.match(cssSource, /\.scene-video-type-switch/);
assert.match(cssSource, /\.video-type-switch-option\.active/);

console.log('storyboard video type switch ui tests passed');
