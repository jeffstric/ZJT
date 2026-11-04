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
assert.match(apiJs, /anyRunning = tasks\.some\(t => t\.status === 'RUNNING' \|\| t\.status === 'QUEUED' \|\| t\.status === 'CANCELLING'\)/, 'QUEUED 与 CANCELLING 应视为未终态');

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

// ---- 重载恢复死代码修复（2026-10-23 浏览器实测发现）----
// 修复①：快照已持久化取消态的节点，markNodeGenerating 必须直接渲染「✗ 已取消」
// 终态，而非无条件写「生成中...」（否则刷新后已取消节点卡生成中）。
const genFn = timelineJs.slice(
  timelineJs.indexOf('function markNodeGenerating'),
  timelineJs.indexOf('/** 在容器内创建（幂等）')
);
assert.ok(genFn.length > 100, 'markNodeGenerating 源码段截取失败');
assert.match(genFn, /node\.data\.cancelled/, 'markNodeGenerating 应识别快照持久化的取消终态');
assert.match(genFn, /ai_task_cancelled/, 'markNodeGenerating 应渲染已取消终态文案');
// 修复②：远端纠正 CANCELLED 时必须用完整 markNodeCancelled（写终态文案），
// 仅 persistOnly 只藏按钮不写文案，节点仍卡「生成中」。
const syncFn = timelineJs.slice(
  timelineJs.indexOf('function syncNodeCancelFromRemote'),
  timelineJs.indexOf('/** 设置节点「取消排队」按钮可见性')
);
assert.ok(syncFn.length > 100, 'syncNodeCancelFromRemote 源码段截取失败');
assert.doesNotMatch(syncFn, /markNodeCancelled\(node\.id, true\)/, '远端纠正不得用 persistOnly（不写终态文案）');
assert.match(syncFn, /markNodeCancelled\(node\.id\)/, '远端纠正 CANCELLED 应完整标记节点终态');

// ---- workflow.js：轮询终态与集中同步 ----
const pollFn = workflowJs.slice(
  workflowJs.indexOf('function pollVideoStatus'),
  workflowJs.indexOf('// 序列化工作流数据')
);
assert.match(pollFn, /result\.status === 'CANCELLED'/, 'pollVideoStatus 终态判断应包含 CANCELLED');
assert.match(pollFn, /setNodeCancelVisible\(node\.id, task\.status === 'QUEUED'\)/, '轮询应按任务状态集中同步取消按钮可见性');
assert.match(pollFn, /markNodeCancelled\(node\.id\)/, '轮询发现 CANCELLED 时应标记节点终态');
// 修复③：轮询集中同步的过滤集合必须包含 CANCELLED——此前只收 RUNNING/QUEUED，
// CANCELLED 节点在 runningIds 检查处提前 return，markNodeCancelled 分支不可达。
assert.match(
  pollFn,
  /t\.status === 'RUNNING' \|\| t\.status === 'QUEUED' \|\| t\.status === 'CANCELLED'/,
  '轮询同步过滤集合必须包含 CANCELLED（否则终态标记为死代码）'
);

// ---- i18n：中英文案齐备 ----
const i18nKeys = [
  'ai_task_cancel_queue',
  'ai_task_cancel_confirm',
  'ai_task_cancel_done',
  'ai_task_cancel_pending',
  'ai_task_cancel_failed',
  'ai_task_cancelled',
  'ai_task_cancelling',
  'ai_task_status_queued',
];
for (const key of i18nKeys) {
  assert.ok(zhCommon[key], `zh-CN/common.json 缺少 ${key}`);
  assert.ok(enCommon[key], `en/common.json 缺少 ${key}`);
}

// ---- CSS：取消按钮样式存在 ----
assert.match(css, /\.ai-task-cancel-btn\s*{/, 'CSS 应定义 .ai-task-cancel-btn');

// ---- storyboard：图片/视频候选生成占位均可取消，且不复用画布按钮类名 ----
const sbApi = read('web/js/storyboard/api.js');
const sbRender = read('web/js/storyboard/render.js');
const sbEvents = read('web/js/storyboard/events.js');
const sbPolling = read('web/js/storyboard/polling.js');
const sbCss = read('web/css/storyboard.css');
const zhStoryboard = JSON.parse(read('web/i18n/locales/zh-CN/storyboard.json'));
const enStoryboard = JSON.parse(read('web/i18n/locales/en/storyboard.json'));

const sbCancelStart = sbApi.indexOf('export async function cancelAiToolTask');
const sbCancelNext = sbApi.indexOf('export async function', sbCancelStart + 1);
const sbCancelFn = sbApi.slice(sbCancelStart, sbCancelNext > sbCancelStart ? sbCancelNext : undefined);
assert.ok(sbCancelFn.length > 80, 'storyboard/api.js 应定义 cancelAiToolTask');
assert.match(sbCancelFn, /\/api\/ai-tool\/\$\{id\}\/cancel/, '故事板取消应走 /api/ai-tool/{id}/cancel');
assert.match(sbCancelFn, /method:\s*'POST'/, '故事板取消请求应为 POST');
assert.match(sbCancelFn, /authHeaders\(false\)/, '故事板取消应走 Authorization 头');
assert.doesNotMatch(sbCancelFn, /auth_token[=:]/, '故事板取消不得把 token 拼进 URL');
assert.doesNotMatch(sbCancelFn, /request\(/, '故事板取消不能走 /api/storyboard 前缀的 request()');

assert.match(sbRender, /class="candidate-task-cancel/, '生成占位应渲染 candidate-task-cancel');
assert.match(sbRender, /data-action="cancel-scene-task"/, '取消按钮动作应为 cancel-scene-task');
assert.doesNotMatch(sbRender, /ai-task-cancel-btn/, '故事板不得复用 ai-task-cancel-btn（捕获监听会吞点击）');
assert.match(sbRender, /kind !== 'video' && kind !== 'image'/, '取消按钮要同时覆盖视频与图片候选');
assert.match(sbRender, /status_task_cancelled/, '取消成功后占位应显示已取消');
assert.match(sbRender, /candidateSidebarSig/, '候选区签名应包含取消状态，否则按钮不刷新');
// 签名必须包含首帧任务状态：图片候选取消/取消中不触发重绘按钮就不会出现
const sbSig = sbRender.slice(sbRender.indexOf('function candidateSidebarSig'), sbRender.indexOf('export function patchCandidates'));
assert.match(sbSig, /first_frame/, '候选区签名应包含首帧任务状态与任务 ID');

const sbClick = sbEvents.slice(
  sbEvents.indexOf('data-action="delete-scene-candidate"'),
  sbEvents.indexOf("event.target.closest('[data-route]')"),
);
assert.match(sbClick, /cancel-scene-task/, '取消点击必须在候选选中之前处理');
assert.match(sbEvents, /function handleCancelSceneTask/, '应定义 handleCancelSceneTask');
assert.match(sbEvents, /function markSceneTaskCancelled/, '应定义 markSceneTaskCancelled');
assert.match(sbEvents, /\['videos', 'images'\]\.forEach/, '本地取消标记要同时处理视频与图片候选');
assert.match(sbEvents, /cancelAiToolTask\(/, '点击应调用 cancelAiToolTask');
assert.match(sbEvents, /result\.status === 'CANCELLING'/, '预处理在途应进入取消中');

assert.match(sbPolling, /function applySceneTaskCancelGuard/, '轮询应挡住过期响应把已取消卡片写回生成中');
assert.match(sbPolling, /phase === 'cancelled'\) return -2/, '已取消标记在没有结果 URL 时保持 -2');
assert.match(sbPolling, /frameStatus = applySceneTaskCancelGuard/, '首帧任务状态也要过取消标记防护');
assert.match(sbPolling, /\['videos', 'images'\]\.forEach/, '收尾兜底要同时纠正视频与图片候选');
assert.doesNotMatch(sbPolling, /applyVideoCancelGuard/, '旧的 video 专用防护函数名应已移除');

assert.match(sbCss, /\.candidate-task-cancel\s*{/, 'CSS 应定义 .candidate-task-cancel');
assert.match(sbCss, /pointer-events:\s*auto/, '取消按钮必须能穿透 is-loading 的 pointer-events:none');
assert.match(sbCss, /\.candidate-video-grid \.candidate-thumb\.is-loading\s*{[^}]*min-height:\s*86px/s, '生成中的视频卡要加高，避免裁掉取消按钮');

for (const key of ['status_task_cancelled', 'status_task_cancelling', 'btn_cancel']) {
  assert.ok(zhStoryboard[key], `zh-CN/storyboard.json 缺少 ${key}`);
  assert.ok(enStoryboard[key], `en/storyboard.json 缺少 ${key}`);
}

console.log('test_ai_task_cancel_frontend: all assertions passed');
