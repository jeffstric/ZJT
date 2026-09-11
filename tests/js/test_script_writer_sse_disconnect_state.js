const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

// 逻辑已拆到独立 JS；勿再从 script_writer.html 内联脚本断言
const js = fs.readFileSync(
  path.join(__dirname, '../../web/js/script_writer.js'),
  'utf8'
);

assert.equal(
  /\bfunction\s+escapeHtml\s*\(/.test(js),
  false,
  'script_writer.js must not declare function escapeHtml (it overwrites window.escapeHtml and recurses)'
);
assert.match(
  js,
  /const escapeHtml = function/,
  'script_writer.js must wrap window.escapeHtml with a const alias'
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
const restoreSendButtonIdleStart = js.indexOf('function restoreSendButtonIdle');
assert.notEqual(restoreSendButtonIdleStart, -1, 'restoreSendButtonIdle should exist');
const restoreSendButtonIdleBody = js.slice(
  restoreSendButtonIdleStart,
  restoreSendButtonIdleStart + 400
);
assert.match(
  restoreSendButtonIdleBody,
  /sendBtn\.disabled\s*=\s*false/,
  'restoreSendButtonIdle must re-enable the send button'
);
assert.match(
  restoreSendButtonIdleBody,
  /sendBtn\.classList\.remove\(['"]sending['"]\)/,
  'restoreSendButtonIdle must clear the sending class'
);

const handleHumanVerificationStart = js.indexOf('function handleHumanVerification');
assert.notEqual(handleHumanVerificationStart, -1, 'handleHumanVerification should exist');
const handleHumanVerificationBody = js.slice(
  handleHumanVerificationStart,
  handleHumanVerificationStart + 4500
);
assert.match(
  handleHumanVerificationBody,
  /restoreSendButtonIdle\s*\(/,
  'handleHumanVerification must idle the send button when ask_user is shown'
);
assert.match(
  handleHumanVerificationBody,
  /data-verification-id/,
  'handleHumanVerification must stamp data-verification-id on the question card'
);
assert.match(
  handleHumanVerificationBody,
  /isVerificationCardActive/,
  'option clicks must ignore expired / non-pending verification cards'
);

const expireVerificationUIStart = js.indexOf('function expireVerificationUI');
assert.notEqual(expireVerificationUIStart, -1, 'expireVerificationUI should exist');
const expireVerificationUIBody = js.slice(
  expireVerificationUIStart,
  expireVerificationUIStart + 1200
);
assert.match(
  expireVerificationUIBody,
  /is-expired/,
  'expireVerificationUI must mark the question card as expired'
);
assert.match(
  expireVerificationUIBody,
  /btn\.disabled\s*=\s*true/,
  'expireVerificationUI must disable option buttons'
);

const handleVerificationTimeoutStart = js.indexOf('function handleVerificationTimeout');
assert.notEqual(handleVerificationTimeoutStart, -1, 'handleVerificationTimeout should exist');
const handleVerificationTimeoutBody = js.slice(
  handleVerificationTimeoutStart,
  handleVerificationTimeoutStart + 1200
);
assert.match(
  handleVerificationTimeoutBody,
  /expireVerificationUI\s*\(/,
  'verification_timeout must grey out the question card'
);
assert.match(
  handleVerificationTimeoutBody,
  /isProcessing\s*=\s*false/,
  'verification_timeout must clear isProcessing so the user can resend'
);
assert.match(
  handleVerificationTimeoutBody,
  /restoreSendButtonIdle\s*\(/,
  'verification_timeout must stop the send-button spinner'
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
  const snippet = js.slice(idx, idx + 400);
  assert.match(
    snippet,
    /handleVerificationTimeout\s*\(/,
    'verification_timeout SSE branches must call handleVerificationTimeout'
  );
}

console.log('script_writer SSE disconnect state tests passed');
