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
  /v-if="isVideoMode && currentVideoResolutionOptions\.length"/,
  'Direct video mode ratio/settings panel should show video resolution options when supported'
);

assert.match(
  ratioPanelMatch[0],
  /v-for="res in currentVideoResolutionOptions"[\s\S]*?selectedVideoResolution\s*=\s*res\.value/,
  'Direct video mode should let users select a supported video resolution'
);

assert.match(
  html,
  /getVideoResolutionOptions\(selectedModelKey\.value\)/,
  'Marketing agent should resolve video resolutions from the selected full model key'
);

console.log('marketing_agent video resolution selector tests passed');
