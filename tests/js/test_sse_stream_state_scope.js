const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

// 回归背景（58e459fb，2026-09-11）：
// EventSource 换成 SSEClient.createEventStream 时，把"本轮回复气泡容器"的初始化
// 代码误留在 onMessage 回调体内。SSE 流中 progress/tool_call/heartbeat 等每条事件
// 都会触发回调，导致每次触发都新建一个空白 assistant 气泡（页面上的"小白点"），
// 堆积后把 ask_user 选项卡片顶出可视区，用户无法点击选项。
// 本测试锁定：气泡容器/流式状态必须声明在 SSE 回调之外。

const scriptWriterJs = fs.readFileSync(
  path.join(__dirname, '../../web/js/script_writer.js'),
  'utf8'
);

// 发送路径：气泡容器必须在 createEventStream 之前创建（整次任务仅一次）
const streamCallStart = scriptWriterJs.indexOf(
  'const eventSource = SSEClient.createEventStream(`/api/task/${taskId}/stream`'
);
assert.notEqual(streamCallStart, -1, 'main send path should use SSEClient.createEventStream');

const bubbleCreationStart = scriptWriterJs.indexOf(
  "const messageDiv = addMessage('assistant', '');"
);
assert.notEqual(bubbleCreationStart, -1, 'main send path should create the reply bubble once');
assert.ok(
  bubbleCreationStart < streamCallStart,
  'reply bubble container must be created BEFORE createEventStream; ' +
  'creating it inside onMessage makes every SSE event (progress/tool_call/heartbeat) ' +
  'spawn a blank bubble'
);
assert.ok(
  streamCallStart - bubbleCreationStart < 800,
  'bubble creation should sit right next to the stream call (same function), ' +
  'not in some unrelated earlier scope'
);

// 重连路径：首连未收到任何消息就断线时 contentDiv 为空，必须判空后再复用
assert.match(
  scriptWriterJs,
  /if \(!contentDiv \|\| needsNewMessageDiv\) \{/,
  'reconnectSSE must guard against empty contentDiv (first connection may drop before any message)'
);

// marketing_agent.js 同一提交的孪生回归：流式状态曾被卷进 onMessage 回调，
// 导致 fullContent/msgUid 每条事件被重置、onError 引用不到这些变量（ReferenceError）
const marketingJs = fs.readFileSync(
  path.join(__dirname, '../../web/js/marketing_agent.js'),
  'utf8'
);

const marketingStreamStart = marketingJs.indexOf('SSEClient.createEventStream');
assert.notEqual(marketingStreamStart, -1, 'marketing_agent should use SSEClient.createEventStream');

for (const decl of [
  "let fullContent = '';",
  'let hasReceivedData = false;',
  'let streamSettled = false;',
  'let streamTimeoutId = null;',
  'function settleStream() {',
  'function ensurePlaceholder() {',
]) {
  const pos = marketingJs.indexOf(decl);
  assert.notEqual(pos, -1, `marketing_agent should still declare ${decl}`);
  assert.ok(
    pos < marketingStreamStart,
    `marketing_agent stream state "${decl}" must be declared BEFORE createEventStream; ` +
    'inside onMessage it resets on every SSE event and is invisible to onError/timeout cleanup'
  );
}

console.log('sse stream state scope tests passed');
