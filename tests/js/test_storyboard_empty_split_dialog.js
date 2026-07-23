const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const repoRoot = path.join(__dirname, '../..');
const bootstrapSource = fs.readFileSync(path.join(repoRoot, 'web/js/storyboard/bootstrap.js'), 'utf8');
const eventsSource = fs.readFileSync(path.join(repoRoot, 'web/js/storyboard/events.js'), 'utf8');

assert.match(
  bootstrapSource,
  /function maybePromptGenerateFromScript\(\)[\s\S]*state\.scenes\.length > 0[\s\S]*state\.showGenerateFromScriptDialog = true;/,
  'empty storyboard should open the split dialog on initial page load'
);

assert.match(
  eventsSource,
  /if \(action === 'delete-scene'\)[\s\S]*removeSceneFromState\(sceneId\);[\s\S]*if \(state\.scenes\.length === 0\) \{[\s\S]*state\.showGenerateFromScriptDialog = true;[\s\S]*state\.generateFromScriptError = '';[\s\S]*\}[\s\S]*rerender\(\);/,
  'deleting the last storyboard scene should reopen the split dialog'
);

console.log('storyboard empty split dialog tests passed');
