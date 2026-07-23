const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const root = path.join(__dirname, '../..');
const renderSource = fs.readFileSync(path.join(root, 'web/js/storyboard/render.js'), 'utf8');
const eventsSource = fs.readFileSync(path.join(root, 'web/js/storyboard/events.js'), 'utf8');
const serverPy = fs.readFileSync(path.join(root, 'server.py'), 'utf8');

assert.match(
  renderSource,
  /<div class="header-logo" data-route="storyboard-list">智<\/div>/,
  'storyboard editor header logo should route to storyboard list'
);

assert.match(
  eventsSource,
  /if\s*\(\s*route\s*===\s*['"]storyboard-list['"]\s*\)\s*{\s*window\.location\.href\s*=\s*['"]\/storyboard-list['"];\s*return;\s*}/s,
  'storyboard-list route should navigate to /storyboard-list'
);

assert.match(serverPy, /@app\.get\("\/storyboard-list"\)/);

console.log('storyboard editor navigation static tests passed');
