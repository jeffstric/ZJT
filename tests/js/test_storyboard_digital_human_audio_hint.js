const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const root = path.join(__dirname, '../..');
const renderSource = fs.readFileSync(
  path.join(root, 'web/js/storyboard/render.js'),
  'utf8'
);
const pollingSource = fs.readFileSync(
  path.join(root, 'web/js/storyboard/polling.js'),
  'utf8'
);

const helperMatch = renderSource.match(
  /function digitalHumanAudioHint\(scene\) \{[\s\S]*?\n\}/
);
assert.ok(helperMatch, 'render.js should define digitalHumanAudioHint(scene)');

const context = {};
vm.runInNewContext(`${helperMatch[0]}\nresult = digitalHumanAudioHint;`, context);
const hint = context.result;

assert.equal(
  hint({ dialogues: [{ audioUrl: 'https://cdn.example.com/voice.mp3', audioStatus: 2 }] }).label,
  '配音已就绪'
);
assert.equal(
  hint({ dialogues: [{ audioUrl: '', audioStatus: 1 }] }).label,
  '配音生成中'
);
assert.equal(
  hint({ dialogues: [{ audio_url: '', audioStatus: 'pending' }] }).label,
  '配音生成中'
);
assert.equal(
  hint({ dialogues: [{ audioUrl: '', audioStatus: -1 }] }).label,
  '需先配音'
);
assert.equal(hint({ dialogues: [] }).label, '需先配音');

assert.doesNotMatch(
  renderSource,
  />对口型 · LTX2\.3 · 需先配音<\/div>/,
  'AI panel should not render the old hard-coded audio hint'
);
assert.match(
  renderSource,
  /export function updateDigitalHumanAudioHint\(scene\)/,
  'render.js should expose a local DOM updater for polling changes'
);
assert.match(
  pollingSource,
  /updateDigitalHumanAudioHint\(scene\)/,
  'audio polling should refresh the digital-human hint without a full rerender'
);

console.log('storyboard digital-human audio hint test passed');
