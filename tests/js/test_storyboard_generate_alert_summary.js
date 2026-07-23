const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const repoRoot = path.join(__dirname, '../..');
const eventsSource = fs.readFileSync(path.join(repoRoot, 'web/js/storyboard/events.js'), 'utf8');

assert.match(
  eventsSource,
  /function handleAutoDialogueAudioPolling\(response\)[\s\S]*return null;/,
  'auto dialogue audio polling should return a message summary when there is nothing to show'
);

assert.match(
  eventsSource,
  /function handleAutoDialogueAudioPolling\(response\)[\s\S]*return `已提交 \$\{submitted\} 条配音任务，\$\{skipped\} 条跳过`;/,
  'auto dialogue audio polling should return the submitted/skipped summary instead of alerting directly'
);

assert.doesNotMatch(
  eventsSource,
  /function handleAutoDialogueAudioPolling\(response\)[\s\S]*notify\(`已提交/,
  'auto dialogue audio polling should not show its own alert'
);

assert.match(
  eventsSource,
  /const audioMessage = handleAutoDialogueAudioPolling\(response\);[\s\S]*const generatedMessage = `已生成 \$\{response\.generated_count \|\| state\.scenes\.length\} 个分镜`;[\s\S]*notify\(\[generatedMessage, audioMessage\]\.filter\(Boolean\)\.join\('\\n'\)\);/,
  'generate-from-script success should show one combined alert for storyboard and audio summaries'
);

console.log('storyboard generate alert summary tests passed');
