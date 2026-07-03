const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const marketingAgentJs = fs.readFileSync(
  path.join(__dirname, '../../web/js/marketing_agent.js'),
  'utf8'
);
const api = fs.readFileSync(
  path.join(__dirname, '../../api/script_writer.py'),
  'utf8'
);

assert.match(
  marketingAgentJs,
  /function buildAgentVideoPreferences\(validImageUrls\)/,
  'Agent send should have a helper that builds video preferences independently of the visible media panel'
);

assert.match(
  marketingAgentJs,
  /video_preferences:\s*isAgentMode\s*\?\s*buildAgentVideoPreferences\(validImageUrls\)\s*:\s*undefined/,
  'Agent task payload should include video_preferences for all Agent messages, not only Agent video panel messages'
);

assert.doesNotMatch(
  marketingAgentJs,
  /video_preferences:\s*\(isAgentMode\s*&&\s*mediaType\.value\s*===\s*'video'\)/,
  'Agent video preferences must not be gated by mediaType === video'
);

assert.match(
  marketingAgentJs,
  /validImageUrls\.length\s*>\s*0\s*\?\s*'image_to_video'\s*:\s*'text_to_video'/,
  'Agent video preferences should choose image_to_video only when the current message has real image URLs'
);

assert.match(
  marketingAgentJs,
  /marketing_selected_i2v_model/,
  'Agent video preferences should be able to restore the saved image-to-video model'
);

assert.match(
  marketingAgentJs,
  /marketing_selected_t2v_model/,
  'Agent video preferences should be able to restore the saved text-to-video model'
);

assert.match(
  marketingAgentJs,
  /buildAgentVideoPreferences[\s\S]{0,2000}?resolution:\s*selectedVideoResolution\.value\s*\|\|\s*undefined/,
  'Agent video preferences should include resolution from selectedVideoResolution'
);

assert.match(
  api,
  /effective_video_preferences\s*=\s*task_request\.video_preferences\s*or\s*get_video_preferences\(user_id,\s*world_id\)/,
  'Backend should fall back to stored video preferences when older clients omit video_preferences'
);

console.log('marketing_agent Agent video preference payload tests passed');
