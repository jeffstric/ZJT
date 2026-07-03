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

const functionStart = marketingAgentJs.indexOf('async function submitVerificationAnswer');
assert.notEqual(functionStart, -1, 'submitVerificationAnswer should exist');
const functionEnd = marketingAgentJs.indexOf('function newChat', functionStart);
assert.notEqual(functionEnd, -1, 'submitVerificationAnswer block should be bounded');
const block = marketingAgentJs.slice(functionStart, functionEnd);

[
  'image_urls',
  'video_urls',
  'audio_urls',
  'thumbnail_urls',
].forEach((field) => {
  assert.match(
    block,
    new RegExp(`${field}:`),
    `verification answers should include ${field} in the request body`
  );
  assert.match(
    api,
    new RegExp(`${field}: Optional\\[List\\[str\\]\\] = None`),
    `VerificationSubmitRequest should accept ${field}`
  );
});

assert.match(
  block,
  /buildUserMessageContent\(userInput\)/,
  'verification answer bubble should render uploaded media previews'
);

assert.doesNotMatch(
  api,
  /idempotency_key=f"verification:\{verification_id\}:answer:\{recorder\._content_hash\(\{'text': verify_request\.user_input,[^}]+image_urls/s,
  'verification answer idempotency should not hash raw media fields separately from the final text'
);

assert.match(
  api,
  /persisted_verification_answer = build_agent_user_message_with_media/,
  'verification answer persistence should build one final text used for content and idempotency'
);

console.log('marketing_agent verification media payload tests passed');
