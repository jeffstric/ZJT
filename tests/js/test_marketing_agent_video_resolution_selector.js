const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const html = fs.readFileSync(
  path.join(__dirname, '../../web/marketing_agent.html'),
  'utf8'
);

const ratioPanelMatch = html.match(
  /<div v-if="showRatioPanel"[\s\S]*?<\/div>\s*<\/div>\s*<\/template>/
);
assert.ok(ratioPanelMatch, 'Marketing agent should render the non-Agent ratio/settings panel');

assert.match(
  ratioPanelMatch[0],
  /v-else-if="currentVideoResolutionOptions\.length"/,
  'Direct video mode ratio/settings panel should show video resolution options when supported'
);

assert.match(
  ratioPanelMatch[0],
  /v-for="res in currentVideoResolutionOptions"[\s\S]*?selectedVideoResolution\s*=\s*res\.value/,
  'Direct video mode should let users select a supported video resolution'
);

assert.match(
  fs.readFileSync(path.join(__dirname, '../../web/js/marketing_agent.js'), 'utf8'),
  /getVideoResolutionOptions\(modelValue\)/,
  'Marketing agent should resolve video resolutions from the selected video model value'
);

console.log('marketing_agent video resolution selector tests passed');
