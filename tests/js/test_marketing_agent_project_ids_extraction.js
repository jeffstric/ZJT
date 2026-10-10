// 回归测试：extractProjectIdsFromText 必须兼容数字人专家总结的
// "project_ids：12548"（复数键 + 中文冒号 + 裸值）写法。
// 事故（会话 5847bc38）：数字人总结用该格式，兜底恢复提取不到 project_ids，
// 视频轮询未恢复；同时 isVideoTaskSummaryText 必须把含"视频"的数字人总结
// 判定为视频摘要，阻止图片兜底误启动图片轮询。

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const js = fs.readFileSync(
  path.join(__dirname, '../../web/js/marketing_agent.js'),
  'utf8'
);

const blockStart = js.indexOf('function extractProjectIdsFromText(text)');
const blockEnd = js.indexOf('function maybeRecoverImageTaskFromAssistantText', blockStart);
assert.notEqual(blockStart, -1, 'extractProjectIdsFromText should exist');
assert.notEqual(blockEnd, -1, 'maybeRecoverImageTaskFromAssistantText should follow extraction');
const block = js.slice(blockStart, blockEnd);

const factory = new Function(block + '\nreturn { extractProjectIdsFromText, isVideoTaskSummaryText };');
const helpers = factory();

// 1) 事故场景：数字人专家总结的 "project_ids：12548"（复数 + 中文冒号）
assert.deepEqual(
  helpers.extractProjectIdsFromText('- project_ids：12548\n- 使用模型：MiniMax H3 数字人'),
  ['12548'],
  'plural project_ids with Chinese colon must be extracted (digital-human summary)'
);

// 2) 既有格式回归
assert.deepEqual(
  helpers.extractProjectIdsFromText('project_id: 266'),
  ['266'],
  'singular project_id with ascii colon must keep working'
);
assert.deepEqual(
  helpers.extractProjectIdsFromText('**项目ID**: 266'),
  ['266'],
  'Chinese 项目ID with markdown bold must keep working'
);
assert.deepEqual(
  helpers.extractProjectIdsFromText('project_ids: [123, 456]'),
  ['123', '456'],
  'array form must keep working and take precedence'
);

// 3) 数字人总结是视频摘要：图片兜底必须跳过（防误启图片轮询）
assert.equal(
  helpers.isVideoTaskSummaryText('## 工作总结\n- project_ids：12548\n- 视频比例：9:16\n数字人视频生成'),
  true,
  'digital-human summary mentioning 视频 must be treated as a video summary'
);

console.log('test_marketing_agent_project_ids_extraction: all assertions passed');
