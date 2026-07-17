const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

// 逻辑已拆到独立 JS；勿再从 script_writer.html 内联脚本断言
const js = fs.readFileSync(
  path.join(__dirname, '../../web/js/script_writer.js'),
  'utf8'
);

const mainDisconnectHandlerStart = js.indexOf('status_connection_lost');
assert.notEqual(mainDisconnectHandlerStart, -1, 'main SSE status-check failure branch should exist');
const mainDisconnectHandler = js.slice(
  Math.max(0, mainDisconnectHandlerStart - 500),
  mainDisconnectHandlerStart + 800
);
assert.equal(
  mainDisconnectHandler.includes('resetProcessingState()'),
  true,
  'main SSE status-check failure must reset the sending button and processing state'
);
assert.equal(
  mainDisconnectHandler.includes('hideTypingIndicator()'),
  true,
  'main SSE status-check failure must hide the typing indicator'
);

const reconnectFailureStart = js.indexOf('status_reconnect_final');
assert.notEqual(reconnectFailureStart, -1, 'reconnect status-check failure branch should exist');
const reconnectFailureHandler = js.slice(
  Math.max(0, reconnectFailureStart - 500),
  reconnectFailureStart + 800
);
assert.equal(
  reconnectFailureHandler.includes('resetProcessingState()'),
  true,
  'reconnect status-check failure must reset the sending button and processing state'
);
assert.equal(
  reconnectFailureHandler.includes('showError('),
  true,
  'reconnect status-check failure should surface an actionable error'
);

// ask_user 出现后必须恢复发送按钮，避免长期 disabled+sending 看起来像“消失”
const handleHumanVerificationStart = js.indexOf('function handleHumanVerification');
assert.notEqual(handleHumanVerificationStart, -1, 'handleHumanVerification should exist');
const handleHumanVerificationBody = js.slice(
  handleHumanVerificationStart,
  handleHumanVerificationStart + 3500
);
assert.match(
  handleHumanVerificationBody,
  /sendBtn\.disabled\s*=\s*false/,
  'handleHumanVerification must re-enable the send button when ask_user is shown'
);
assert.match(
  handleHumanVerificationBody,
  /sendBtn\.classList\.remove\(['"]sending['"]\)/,
  'handleHumanVerification must clear the sending class when ask_user is shown'
);

// verification_timeout 后必须允许用户重新发送
const timeoutOccurrences = [];
let searchFrom = 0;
while (true) {
  const idx = js.indexOf("data.type === 'verification_timeout'", searchFrom);
  if (idx === -1) break;
  timeoutOccurrences.push(idx);
  searchFrom = idx + 1;
}
assert.ok(
  timeoutOccurrences.length >= 2,
  'verification_timeout should be handled in main SSE and reconnect SSE paths'
);
for (const idx of timeoutOccurrences) {
  const snippet = js.slice(idx, idx + 1400);
  assert.match(
    snippet,
    /isProcessing\s*=\s*false/,
    'verification_timeout must clear isProcessing so the user can resend'
  );
  assert.match(
    snippet,
    /sendBtn\.disabled\s*=\s*false/,
    'verification_timeout must re-enable the send button'
  );
}

console.log('script_writer SSE disconnect state tests passed');
