const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const root = path.join(__dirname, '../..');
const eventsSource = fs.readFileSync(
  path.join(root, 'web/js/storyboard/events.js'),
  'utf8'
);

const toggleViewMatch = eventsSource.match(
  /if \(action === 'toggle-view'\) \{([\s\S]*?)\n    \}/
);

assert.ok(toggleViewMatch, 'toggle-view handler should exist');

assert.match(
  toggleViewMatch[1],
  /const targetSceneId = state\.currentSceneId;[\s\S]*?state\.viewMode === 'timeline'[\s\S]*?requestAnimationFrame\([\s\S]*?scrollTimelineToScene\(targetSceneId\)/,
  'returning from grid to timeline should scroll the selected scene into view after rendering'
);

console.log('storyboard timeline view restore static test passed');
