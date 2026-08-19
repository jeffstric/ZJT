const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const html = fs.readFileSync(
  path.join(__dirname, '../../web/marketing_agent.html'),
  'utf8'
);
const js = fs.readFileSync(
  path.join(__dirname, '../../web/js/marketing_agent.js'),
  'utf8'
);

assert.equal(
  html.includes('v-if="!msg._isPendingTask && msg.role !== \'system\'"'),
  true,
  'chat template must hide internal pending_task / system recovery rows'
);

assert.equal(
  js.includes('function unwrapHistoryText'),
  true,
  'history parser should unwrap {text: ...} JSON before detecting pending markers'
);

const parseStart = js.indexOf('function parseHistoryMessage');
assert.notEqual(parseStart, -1, 'parseHistoryMessage should exist');
const parseFn = js.slice(parseStart, parseStart + 2200);
assert.equal(
  parseFn.includes("h.message_type === 'pending_task'"),
  true,
  'pending_task message_type should be treated as an internal recovery marker even if content wrapping differs'
);
assert.equal(
  parseFn.includes('_isPendingTask: true'),
  true,
  'recognized pending markers must stay marked so the template can hide them'
);

const selectStart = js.indexOf('async function selectSession');
const selectFn = js.slice(selectStart, js.indexOf('// 加载本地历史', selectStart));
const pendingIdx = selectFn.indexOf('await recoverPendingTasks(sessionId)');
const fallbackIdx = selectFn.indexOf('recoverVideoTasksFromAssistantMessages()');
assert.ok(pendingIdx !== -1 && fallbackIdx !== -1, 'session restore should recover pending tasks and text fallbacks');
assert.ok(
  pendingIdx < fallbackIdx,
  'pending-task recovery must run before assistant-text fallback so the hidden marker is consumed first'
);

console.log('marketing agent pending task visibility tests passed');
