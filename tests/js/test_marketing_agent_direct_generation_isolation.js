const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const html = fs.readFileSync(
  path.join(__dirname, '../../web/marketing_agent.html'),
  'utf8'
);

assert.equal(
  html.includes('const directGenerationTasks = new Map()'),
  true,
  'direct image/video generation should track every submitted task independently'
);

assert.equal(
  html.includes('function createDirectGenerationTask'),
  true,
  'direct generation should create a task instance bound to type, project_ids, session and message uid'
);

const imagePollStart = html.indexOf('async function checkImageStatus');
const imagePollEnd = html.indexOf('function startImageStatusCheck', imagePollStart);
assert.notEqual(imagePollStart, -1, 'direct image status checker should exist');
assert.notEqual(imagePollEnd, -1, 'direct image status starter should follow checker');
const imagePoll = html.slice(imagePollStart, imagePollEnd);
assert.equal(
  imagePoll.includes('task.projectIds'),
  true,
  'direct image polling must use the task instance project_ids instead of the global imageProjectIds ref'
);

const videoPollStart = html.indexOf('async function checkVideoStatus');
const videoPollEnd = html.indexOf('function startVideoStatusCheck', videoPollStart);
assert.notEqual(videoPollStart, -1, 'direct video status checker should exist');
assert.notEqual(videoPollEnd, -1, 'direct video status starter should follow checker');
const videoPoll = html.slice(videoPollStart, videoPollEnd);
assert.equal(
  videoPoll.includes('task.projectIds'),
  true,
  'direct video polling must use the task instance project_ids instead of the global videoProjectIds ref'
);

assert.equal(
  html.includes("replacePendingTask(task.sessionId, 'image_task_submitted', task.projectIds, finalContent)"),
  true,
  'direct image completion should replace the matching pending history row by project_ids'
);

assert.equal(
  html.includes("replacePendingTask(task.sessionId, 'video_task_submitted', task.projectIds, finalContent)"),
  true,
  'direct video completion should replace the matching pending history row by project_ids'
);

assert.equal(
  html.includes("buildGeneratedMediaRowsHtml('image'") || html.includes("buildGeneratedMediaHtml('image'"),
  true,
  'image results should be rendered through media-type aware HTML builder'
);

assert.equal(
  html.includes("buildGeneratedMediaRowsHtml('video'") || html.includes("buildGeneratedMediaHtml('video'"),
  true,
  'video results should be rendered through media-type aware HTML builder'
);

console.log('marketing_agent direct generation isolation tests passed');
