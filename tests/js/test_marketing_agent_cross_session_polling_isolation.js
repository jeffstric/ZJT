const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const html = fs.readFileSync(
  path.join(__dirname, '../../web/js/marketing_agent.js'),
  'utf8'
);

// 缺陷1：checkDirectGenerationStatus（视频/图片「直接发起模式」轮询）在 await 之后必须再次校验会话，
// 防止任务进行中切换对话后，旧轮询回调把「视频生成失败 / 图片生成失败」写进当前（已切换的）对话。
const directPollStart = html.indexOf('async function checkDirectGenerationStatus');
assert.notEqual(directPollStart, -1, 'direct generation status checker should exist');
const directPollEnd = html.indexOf('async function checkImageStatus', directPollStart);
assert.notEqual(directPollEnd, -1, 'image status checker should follow direct generation checker');
const directPoll = html.slice(directPollStart, directPollEnd);
const directGuardCount = (directPoll.match(/currentSessionId\.value !== task\.sessionId/g) || []).length;
assert.ok(
  directGuardCount >= 2,
  `direct generation polling must re-check the session after the await (expected >=2 guards, got ${directGuardCount})`
);

// 缺陷2：handleStream 的 SSE onmessage 必须按发起会话 streamSessionId 守卫，
// 丢弃切换对话后仍在事件队列里排队的残留事件（message / task_submitted / verification 等）。
assert.equal(
  html.includes('const streamSessionId = currentSessionId.value'),
  true,
  'handleStream should capture the originating session id when the stream starts'
);
const streamGuardIdx = html.indexOf('if (currentSessionId.value !== streamSessionId)');
assert.notEqual(streamGuardIdx, -1, 'handleStream onmessage should drop events whose session no longer matches');
assert.ok(
  html.slice(streamGuardIdx, streamGuardIdx + 200).includes('eventSource.close()'),
  'the stream session guard should close the stale event source'
);

// 缺陷3：两个任务 handler 接受显式 session 入参，
// 避免 SSE 延迟事件被处理时取到错误的「当前对话」。
assert.equal(
  html.includes('function handleImageTaskSubmitted(data, explicitSessionId)'),
  true,
  'image task submitted handler should accept an explicit session id from the caller'
);
assert.equal(
  html.includes('function handleVideoTaskSubmitted(data, explicitSessionId)'),
  true,
  'video task submitted handler should accept an explicit session id from the caller'
);
const explicitFallbackCount = (html.match(/explicitSessionId \|\| currentSessionId\.value/g) || []).length;
assert.ok(
  explicitFallbackCount >= 2,
  `both task handlers should prefer the explicit session id and fall back to the current session (expected >=2, got ${explicitFallbackCount})`
);

// handleStream 派发任务时传入 streamSessionId，确保轮询与后端写入归属发起会话。
assert.equal(
  html.includes('handleImageTaskSubmitted(data, streamSessionId)'),
  true,
  'handleStream should bind image task polling to the stream session'
);
assert.equal(
  html.includes('handleVideoTaskSubmitted(data, streamSessionId)'),
  true,
  'handleStream should bind video task polling to the stream session'
);

// 回归保护：从历史 / 文本恢复任务的路径仍以「当前对话」为默认，不传显式 session（行为不变）。
assert.equal(
  html.includes('handleVideoTaskSubmitted({'),
  true,
  'assistant text recovery should keep using the current session when restoring polling'
);
assert.equal(
  html.includes('handleImageTaskSubmitted({'),
  true,
  'assistant text recovery should keep using the current session when restoring polling'
);

console.log('marketing_agent cross-session polling isolation tests passed');
