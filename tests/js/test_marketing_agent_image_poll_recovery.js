const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const html = fs.readFileSync(
  path.join(__dirname, '../../web/marketing_agent.html'),
  'utf8'
);

assert.equal(
  html.includes('function maybeRecoverImageTaskFromAssistantText'),
  true,
  'marketing agent should recover image polling from assistant text when image_task_submitted SSE is missed'
);

assert.equal(
  html.includes('项目ID'),
  true,
  'project id extraction should support Chinese "项目ID: 744" text'
);

const imageHandlerStart = html.indexOf('function handleImageTaskSubmitted');
assert.notEqual(imageHandlerStart, -1, 'image task submitted handler should exist');
const imageHandler = html.slice(imageHandlerStart, imageHandlerStart + 1200);
assert.equal(
  imageHandler.includes('function handleImageTaskSubmitted(data, explicitSessionId)'),
  true,
  'image task submitted handler should accept an explicit session id from the caller'
);
assert.equal(
  imageHandler.includes('const pollSessionId = explicitSessionId || currentSessionId.value'),
  true,
  'image task submitted handler should prefer the explicit session id and fall back to the current session'
);
assert.equal(
  imageHandler.includes('activeGenerationPollKeys.add(pollKey)'),
  true,
  'image task submitted handler should dedupe active image polling'
);

const imageRecoveryStart = html.indexOf('function maybeRecoverImageTaskFromAssistantText');
const imageRecoveryEnd = html.indexOf('function hasGeneratedImageResult', imageRecoveryStart);
assert.notEqual(imageRecoveryStart, -1, 'image task text recovery function should exist');
assert.notEqual(imageRecoveryEnd, -1, 'image result checker should follow image recovery function');
const imageRecovery = html.slice(imageRecoveryStart, imageRecoveryEnd);
assert.equal(
  imageRecovery.includes('if (isVideoTaskSummaryText(text)) return;'),
  true,
  'image fallback recovery must ignore video summaries that mention image_mode or 图片模式'
);

assert.equal(
  html.includes('function isVideoTaskSummaryText'),
  true,
  'marketing agent should classify video task summaries before image fallback recovery'
);

const proxyImageStart = html.indexOf('function proxyImageUrl');
const proxyImageEnd = html.indexOf('function proxyDownloadUrl', proxyImageStart);
assert.notEqual(proxyImageStart, -1, 'image URL proxy helper should exist');
assert.notEqual(proxyImageEnd, -1, 'download proxy helper should follow image proxy helper');
const proxyImageHelper = html.slice(proxyImageStart, proxyImageEnd);
assert.equal(
  proxyImageHelper.includes('/api/proxy-image?url='),
  true,
  'image proxy helper should route remote images through the signed CDN refresh proxy'
);
assert.equal(
  proxyImageHelper.includes("startsWith('/api/proxy-image')"),
  true,
  'image proxy helper should not wrap already proxied image URLs'
);

const generatedRowsStart = html.indexOf('function buildGeneratedMediaRowsHtml');
const generatedRowsEnd = html.indexOf('function buildGeneratedTaskContent', generatedRowsStart);
assert.notEqual(generatedRowsStart, -1, 'generated media row renderer should exist');
const generatedRows = html.slice(generatedRowsStart, generatedRowsEnd);
assert.equal(
  generatedRows.includes('const displayUrl = proxyImageUrl(url);'),
  true,
  'generated image cards should render through proxyImageUrl so expired CDN signatures refresh automatically'
);
assert.equal(
  generatedRows.includes("document.getElementById('imgModalImg').src='${displayUrl}'"),
  true,
  'generated image modal should open the proxied display URL'
);

const imagePollStart = html.indexOf('function pollAgentImageStatus');
assert.notEqual(imagePollStart, -1, 'image status polling function should exist');
const imagePollEnd = html.indexOf('function handleVideoTaskSubmitted', imagePollStart);
assert.notEqual(imagePollEnd, -1, 'video task handler should follow image polling function');
const imagePoll = html.slice(imagePollStart, imagePollEnd);
assert.equal(
  imagePoll.includes('pollSessionId = currentSessionId.value'),
  true,
  'image status polling function should receive a fallback pollSessionId'
);
assert.equal(
  imagePoll.includes('appendMessageToBackend(') && imagePoll.includes('pollSessionId'),
  true,
  'image status polling should persist final result to the originating session'
);

const videoPollStart = html.indexOf('function pollAgentVideoStatus');
const videoPollEnd = html.indexOf('function sendContinue', videoPollStart);
assert.notEqual(videoPollStart, -1, 'video status polling function should exist');
assert.notEqual(videoPollEnd, -1, 'continue handler should follow video polling function');
const videoPoll = html.slice(videoPollStart, videoPollEnd);
assert.equal(
  videoPoll.includes("appendMessageToBackend('assistant', finalContent, pollSessionId)"),
  true,
  'video status polling fallback should persist final result to the originating session'
);

const pendingRecoveryStart = html.indexOf('async function recoverPendingTasks');
const pendingRecoveryEnd = html.indexOf('// 选择会话', pendingRecoveryStart);
assert.notEqual(pendingRecoveryStart, -1, 'pending task recovery function should exist');
assert.notEqual(pendingRecoveryEnd, -1, 'session selection should follow pending task recovery');
const pendingRecovery = html.slice(pendingRecoveryStart, pendingRecoveryEnd);
assert.equal(
  pendingRecovery.includes('async function recoverPendingTasks(sessionId = currentSessionId.value)'),
  true,
  'pending task recovery should bind backend writes to the session being restored'
);
assert.equal(
  pendingRecovery.includes("appendMessageToBackend('assistant', content, sessionId)"),
  true,
  'pending task recovery fallback should append completed results to the restored session'
);

console.log('marketing agent image poll recovery tests passed');
