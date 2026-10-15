/**
 * 排队任务取消——前端链路静态断言。
 *
 * 覆盖：api.js 取消函数与终态判定、ai_tool_timeline.js 取消按钮与节点状态、
 * workflow.js 轮询集中同步、i18n 文案、CSS 样式。
 * 互斥语义（取消后绝不调上游）由后端 CAS 保证，前端只验证入口与展示链路完整。
 */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const repoRoot = path.join(__dirname, '../..');
const read = (rel) => fs.readFileSync(path.join(repoRoot, rel), 'utf8');

const timelineJs = read('web/js/ai_tool_timeline.js');
const apiJs = read('web/js/api.js');
const workflowJs = read('web/js/workflow.js');
const css = read('web/css/ai_tool_timeline.css');
const zhCommon = JSON.parse(read('web/i18n/locales/zh-CN/common.json'));
const enCommon = JSON.parse(read('web/i18n/locales/en/common.json'));

// ---- api.js：取消函数走 Authorization 头，token 不进 URL（前端安全红线 X2） ----
assert.match(apiJs, /async function cancelQueuedAiTask/, 'api.js 应定义 cancelQueuedAiTask');
const cancelFn = apiJs.slice(apiJs.indexOf('async function cancelQueuedAiTask'));
assert.match(cancelFn, /\/api\/ai-tool\/\$\{aiToolId\}\/cancel/, '取消接口路径应为 /api/ai-tool/{id}/cancel');
assert.match(cancelFn, /method:\s*'POST'/, '取消请求应为 POST');
assert.doesNotMatch(cancelFn, /auth_token[=:]/, '取消请求不得把 token 拼进 URL/表单');

// ---- api.js：终态判定纳入 CANCELLED；QUEUED 视为未终态 ----
assert.match(apiJs, /anyCancelled = tasks\.some\(t => t\.status === 'CANCELLED'\)/, '应统计 CANCELLED 任务');
assert.match(apiJs, /anyRunning = tasks\.some\(t => t\.status === 'RUNNING' \|\| t\.status === 'QUEUED'\)/, 'QUEUED 应视为未终态');

// ---- ai_tool_timeline.js：取消按钮、节点状态与委托 ----
assert.match(timelineJs, /ai-task-cancel-btn/, '应存在取消按钮类名');
assert.match(timelineJs, /function markNodeCancelled/, '应定义 markNodeCancelled');
assert.match(timelineJs, /function setNodeCancelVisible/, '应定义 setNodeCancelVisible');
assert.match(timelineJs, /function requestNodeCancel/, '应定义 requestNodeCancel');
assert.match(timelineJs, /cancelQueuedAiTask\(/, '取消动作应调用 cancelQueuedAiTask');
assert.match(timelineJs, /closest\('\.ai-task-cancel-btn'\)/, '取消按钮应由全局 click 委托处理');
assert.match(timelineJs, /markNodeCancelled: markNodeCancelled/, 'window.AiToolTimeline 应导出 markNodeCancelled');
assert.match(timelineJs, /setNodeCancelVisible: setNodeCancelVisible/, 'window.AiToolTimeline 应导出 setNodeCancelVisible');
// 重载恢复：markNodeGenerating 后按远端真实状态纠正按钮可见性/终态
assert.match(timelineJs, /syncNodeCancelFromRemote\(node, ids\[0\]\)/, 'markNodeGenerating 应触发远端状态同步（重载恢复）');
assert.match(timelineJs, /task\.status === 'CANCELLED'/, '远端同步应识别 CANCELLED 终态');
assert.match(timelineJs, /task\.status === 'QUEUED'/, '远端同步应仅排队中显示按钮');
// 已取消节点持久化，重载后不重复显示生成态按钮
assert.match(timelineJs, /node\.data\.cancelled = true/, '取消状态应写入 node.data（重载恢复）');

// ---- workflow.js：轮询终态与集中同步 ----
const pollFn = workflowJs.slice(
  workflowJs.indexOf('function pollVideoStatus'),
  workflowJs.indexOf('// 序列化工作流数据')
);
assert.match(pollFn, /result\.status === 'CANCELLED'/, 'pollVideoStatus 终态判断应包含 CANCELLED');
assert.match(pollFn, /setNodeCancelVisible\(node\.id, task\.status === 'QUEUED'\)/, '轮询应按任务状态集中同步取消按钮可见性');
assert.match(pollFn, /markNodeCancelled\(node\.id\)/, '轮询发现 CANCELLED 时应标记节点终态');

// ---- i18n：中英文案齐备 ----
const i18nKeys = [
  'ai_task_cancel_queue',
  'ai_task_cancel_confirm',
  'ai_task_cancel_done',
  'ai_task_cancel_failed',
  'ai_task_cancelled',
  'ai_task_status_queued',
];
for (const key of i18nKeys) {
  assert.ok(zhCommon[key], `zh-CN/common.json 缺少 ${key}`);
  assert.ok(enCommon[key], `en/common.json 缺少 ${key}`);
}

// ---- CSS：取消按钮样式存在 ----
assert.match(css, /\.ai-task-cancel-btn\s*{/, 'CSS 应定义 .ai-task-cancel-btn');

console.log('test_ai_task_cancel_frontend: all assertions passed');
