const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const repoRoot = path.join(__dirname, '../..');
const apiJs = fs.readFileSync(path.join(repoRoot, 'web/js/api.js'), 'utf8');
const nodesJs = fs.readFileSync(path.join(repoRoot, 'web/js/nodes.js'), 'utf8');
const imageToVideoNodeJs = fs.readFileSync(path.join(repoRoot, 'web/js/image_to_video_node.js'), 'utf8');
const shotFrameNodeJs = fs.readFileSync(path.join(repoRoot, 'web/js/shot_frame_node.js'), 'utf8');
const shotGroupNodeJs = fs.readFileSync(path.join(repoRoot, 'web/js/shot_group_node.js'), 'utf8');
const workflowNodeJs = `${nodesJs}\n${imageToVideoNodeJs}\n${shotFrameNodeJs}\n${shotGroupNodeJs}`;
const workflowJs = fs.readFileSync(path.join(repoRoot, 'web/js/workflow.js'), 'utf8');
const shotFrameJs = fs.readFileSync(path.join(repoRoot, 'web/js/shot_frame_video_generator.js'), 'utf8');
const digitalHumanJs = fs.readFileSync(path.join(repoRoot, 'web/js/digital_human_node.js'), 'utf8');
const indexHtml = fs.readFileSync(path.join(repoRoot, 'web/index.html'), 'utf8');
const aiVideoGenJs = fs.readFileSync(path.join(repoRoot, 'web/js/pages/ai_video_gen.js'), 'utf8');
const imageToVideoJs = fs.readFileSync(path.join(repoRoot, 'web/js/pages/image_to_video.js'), 'utf8');
const marketingAgentHtml = fs.readFileSync(path.join(repoRoot, 'web/marketing_agent.html'), 'utf8');
const marketingAgentJs = fs.readFileSync(path.join(repoRoot, 'web/js/marketing_agent.js'), 'utf8');

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
  /node\.data\.videoResolution[\s\S]*context\.resolution = node\.data\.videoResolution/,
  'workflow should read image-to-video node video resolution when updating power'
);
assert.match(
  workflowJs,
  /node\.type === 'shot_frame'[\s\S]*node\.data\.videoResolution[\s\S]*context\.resolution = node\.data\.videoResolution[\s\S]*calculateVideoGenerationPower\(videoModel,\s*duration,\s*context\)/,
  'workflow should read shot frame node video resolution when updating power'
);

assert.match(
  imageToVideoNodeJs,
  /videoResolution:\s*opts\?\.data\?\.videoResolution/,
  'image-to-video node should persist videoResolution across reload'
);
assert.match(
  imageToVideoNodeJs,
  /class="[^"]*video-resolution-select/,
  'image-to-video node should render a resolution selector'
);
assert.match(
  imageToVideoNodeJs,
  /resolutionSelect\.addEventListener\('change'/,
  'image-to-video node should react to resolution changes'
);
assert.match(
  imageToVideoNodeJs,
  /generateVideoFromText\(prompt,\s*duration,\s*desiredCount,\s*ratio,\s*videoModel,\s*node\.data\.videoResolution\)/,
  'image-to-video node should submit selected resolution for text-to-video mode'
);
assert.match(
  imageToVideoNodeJs,
  /generateVideoFromImage\([\s\S]*node\.data\.videoResolution\)/,
  'image-to-video node should submit selected resolution for image-to-video modes'
);
assert.match(
  shotFrameJs,
  /appendVideoResolutionToForm\(form,\s*videoModel,\s*node\.data\.videoResolution\)/,
  'shot frame generator should pass videoResolution to generation API'
);
assert.match(
  workflowNodeJs,
  /appendVideoResolutionToForm\(form,\s*videoModel[^,]*,\s*shotGroupNode\.data\.videoResolution\)/,
  'shot group node should submit selected video resolution'
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
  /\/js\/pages\/ai_video_gen\.js/,
  'index should load split text-to-video page component'
);
assert.match(
  indexHtml,
  /\/js\/pages\/image_to_video\.js/,
  'index should load split image-to-video page component'
);
assert.match(
  aiVideoGenJs,
  /videoResolutionOptions/,
  'text-to-video page should expose video resolution options'
);
assert.match(
  aiVideoGenJs,
  /form\.append\('resolution',\s*this\.videoResolution\)/,
  'text-to-video page should submit selected video resolution'
);
assert.match(
  imageToVideoJs,
  /videoResolutionOptions/,
  'image-to-video page should expose video resolution options'
);
assert.match(
  imageToVideoJs,
  /form\.append\('resolution',\s*this\.videoResolution\)/,
  'image-to-video page should submit selected video resolution'
);
assert.match(
  marketingAgentJs,
  /selectedVideoResolution/,
  'marketing agent should keep video resolution separate from image resolution'
);
assert.match(
  marketingAgentHtml,
  /currentVideoResolutionOptions/,
  'marketing agent page should render video resolution options'
);
assert.match(
  marketingAgentJs,
  /form\.append\('resolution',\s*videoResolution\)/,
  'marketing agent should submit selected/default video resolution'
);
assert.match(
  marketingAgentJs,
  /video_preferences:[\s\S]*resolution:/,
  'marketing agent should include video resolution in agent video preferences'
);

console.log('video resolution frontend wiring tests passed');
