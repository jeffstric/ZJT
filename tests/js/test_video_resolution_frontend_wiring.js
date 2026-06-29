const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const repoRoot = path.join(__dirname, '../..');
const apiJs = fs.readFileSync(path.join(repoRoot, 'web/js/api.js'), 'utf8');
const nodesJs = fs.readFileSync(path.join(repoRoot, 'web/js/nodes.js'), 'utf8');
const workflowJs = fs.readFileSync(path.join(repoRoot, 'web/js/workflow.js'), 'utf8');
const shotFrameJs = fs.readFileSync(path.join(repoRoot, 'web/js/shot_frame_video_generator.js'), 'utf8');
const digitalHumanJs = fs.readFileSync(path.join(repoRoot, 'web/js/digital_human_node.js'), 'utf8');
const indexHtml = fs.readFileSync(path.join(repoRoot, 'web/index.html'), 'utf8');
const marketingAgentHtml = fs.readFileSync(path.join(repoRoot, 'web/marketing_agent.html'), 'utf8');

assert.match(
  apiJs,
  /generateVideoFromImage\([^)]*resolution/,
  'generateVideoFromImage should accept resolution'
);
assert.match(
  apiJs,
  /generateVideoFromText\([^)]*resolution/,
  'generateVideoFromText should accept resolution'
);
assert.match(
  apiJs,
  /form\.append\('resolution',\s*resolvedResolution\)/,
  'api.js helper should append resolved resolution'
);
assert.match(
  apiJs,
  /appendVideoResolutionToForm\(form,\s*videoModel/,
  'api.js generation functions should call resolution helper'
);

assert.match(
  workflowJs,
  /function calculateVideoGenerationPower\(videoModel,\s*duration,\s*context\s*=\s*\{\}\)/,
  'workflow calculateVideoGenerationPower should accept context'
);
assert.match(
  workflowJs,
  /videoResolution|video_resolution/,
  'workflow should read node video resolution when updating power'
);

assert.match(
  nodesJs,
  /videoResolution:\s*opts\?\.data\?\.videoResolution/,
  'image-to-video node should persist videoResolution across reload'
);
assert.match(
  nodesJs,
  /class="[^"]*video-resolution-select/,
  'image-to-video node should render a resolution selector'
);
assert.match(
  nodesJs,
  /resolutionSelect\.addEventListener\('change'/,
  'image-to-video node should react to resolution changes'
);
assert.match(
  nodesJs,
  /generateVideoFrom(?:Image|Text)\([^;]*node\.data\.videoResolution/s,
  'image-to-video node should pass videoResolution to generation API'
);

assert.match(
  shotFrameJs,
  /appendVideoResolutionToForm/,
  'shot frame generator should append video resolution through helper'
);
assert.match(
  digitalHumanJs,
  /appendVideoResolutionToForm/,
  'digital human node should append video resolution through helper'
);

assert.match(
  indexHtml,
  /videoResolutionOptions/,
  'index video panels should expose video resolution options'
);
assert.match(
  indexHtml,
  /form\.append\('resolution',\s*this\.videoResolution\)/,
  'index video panels should submit selected video resolution'
);
assert.match(
  marketingAgentHtml,
  /selectedVideoResolution/,
  'marketing agent should keep video resolution separate from image resolution'
);
assert.match(
  marketingAgentHtml,
  /form\.append\('resolution',\s*videoResolution\)/,
  'marketing agent should submit selected/default video resolution'
);

console.log('video resolution frontend wiring tests passed');
