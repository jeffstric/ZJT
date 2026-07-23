// 故事板剧本分段拆分 - 前端源码静态回归测试（Node 原生 assert，手动运行）。
// 覆盖测试方案 §3.2：验证拆分相关 UI 标记、轮询函数、API 封装、CSS 规则存在，
// 防止重构时静默丢失关键接入点。
//
// 运行：node tests/js/test_storyboard_script_split_static.js
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const repoRoot = path.join(__dirname, '../..');
const readSrc = (rel) => fs.readFileSync(path.join(repoRoot, rel), 'utf8');

const eventsSrc = readSrc('web/js/storyboard/events.js');
const pollingSrc = readSrc('web/js/storyboard/polling.js');
const apiSrc = readSrc('web/js/storyboard/api.js');
const renderSrc = readSrc('web/js/storyboard/render.js');
const stateSrc = readSrc('web/js/storyboard/state.js');
const bootstrapSrc = readSrc('web/js/storyboard/bootstrap.js');
const cssSrc = readSrc('web/css/storyboard.css');

// 1. 拆分相关 data-action 分发存在
assert.match(eventsSrc, /generate-from-script-confirm/, 'events.js 应分发 generate-from-script-confirm');
assert.match(eventsSrc, /generate-from-script-cancel/, 'events.js 应分发 generate-from-script-cancel');
assert.match(eventsSrc, /toggle-enable-script-split-qc/, 'events.js 应分发 toggle-enable-script-split-qc');
assert.match(eventsSrc, /close-generate-progress/, 'events.js 应分发 close-generate-progress');
assert.match(eventsSrc, /retry-generate-progress/, 'events.js 应分发 retry-generate-progress');

// 2. 拆分参数开关
assert.match(eventsSrc, /toggle-force-medium-shot/, 'events.js 应有 toggle-force-medium-shot');
assert.match(eventsSrc, /toggle-no-bg-music/, 'events.js 应有 toggle-no-bg-music');
assert.match(eventsSrc, /toggle-split-multi-dialogue/, 'events.js 应有 toggle-split-multi-dialogue');

// 3. 拆分语言与小屏固定操作栏
assert.match(renderSrc, /data-config-select="scriptDialogueLanguage"/, '应渲染对话语言选项');
assert.match(renderSrc, /data-config-select="scriptPromptLanguage"/, '应渲染提示词语言选项');
assert.match(renderSrc, /data-script-language-custom="dialogue"/, '对话语言应支持自定义输入');
assert.match(renderSrc, /data-script-language-custom="prompt"/, '提示词语言应支持自定义输入');
assert.match(eventsSrc, /dialogue_language: state\.scriptDialogueLanguage/, '拆分请求应透传对话语言');
assert.match(eventsSrc, /prompt_language: state\.scriptPromptLanguage/, '拆分请求应透传提示词语言');
assert.match(stateSrc, /scriptDialogueLanguage: state\.scriptDialogueLanguage/, '对话语言应持久化到 config_json');
assert.match(stateSrc, /scriptPromptLanguage: state\.scriptPromptLanguage/, '提示词语言应持久化到 config_json');
assert.match(cssSrc, /\.generate-from-script-dialog\s*\{[^}]*display:\s*flex;[^}]*overflow:\s*hidden;/s, '拆分弹窗应由内部区域滚动');
assert.match(cssSrc, /\.generate-from-script-dialog \.gfs-body\s*\{[^}]*overflow-y:\s*auto;/s, '拆分设置区应可滚动');
assert.match(cssSrc, /\.generate-from-script-dialog \.dialog-footer\s*\{[^}]*flex:\s*0 0 auto;/s, '底部操作栏应固定可见');
assert.match(cssSrc, /\.generate-from-script-dialog \.config-select-wrapper select\s*\{[^}]*width:\s*100%;[^}]*max-width:\s*none;/s, '拆分弹窗选择框应铺满栏位');

// 4. 轮询基础设施
assert.match(pollingSrc, /export function pollScriptSplitTask/, 'polling.js 应导出 pollScriptSplitTask');
assert.match(pollingSrc, /export function stopScriptSplitTaskPolling/, 'polling.js 应导出 stopScriptSplitTaskPolling');
assert.match(pollingSrc, /SPLIT_TERMINAL_STATUSES/, 'polling.js 应定义 SPLIT_TERMINAL_STATUSES');
assert.match(pollingSrc, /SPLIT_INTERACTIVE_STATUSES/, 'polling.js 应定义 SPLIT_INTERACTIVE_STATUSES（paused/waiting_auth）');

// 5. API 封装（拆分任务接口）
assert.match(apiSrc, /export async function getScriptSplitTaskStatus/, 'api.js 应封装 getScriptSplitTaskStatus');
assert.match(apiSrc, /export async function getScriptSplitTaskResult/, 'api.js 应封装 getScriptSplitTaskResult');
assert.match(apiSrc, /export async function getActiveScriptSplitTask/, 'api.js 应封装 getActiveScriptSplitTask（刷新恢复）');
assert.match(apiSrc, /export async function resumeScriptSplitTask/, 'api.js 应封装 resumeScriptSplitTask');
assert.match(apiSrc, /export async function cancelScriptSplitTask/, 'api.js 应封装 cancelScriptSplitTask');

// 6. 进度弹框 ARIA 无障碍标记
assert.match(renderSrc, /role="progressbar"/, 'render.js 进度条应有 role="progressbar"');
assert.match(renderSrc, /aria-valuenow="\$\{progressPercent\}"/, 'render.js 进度条应有 aria-valuenow');
assert.match(renderSrc, /generate-progress-percent/, 'render.js 应有 generate-progress-percent 类');
assert.match(renderSrc, /generate-progress-message/, 'render.js 应有 generate-progress-message 类');

// 7. bootstrap 刷新恢复活跃任务
assert.match(bootstrapSrc, /getActiveScriptSplitTask|active-task/, 'bootstrap.js 应在加载时查询活跃拆分任务以恢复');

// 8. 进度弹框 CSS 规则
assert.match(cssSrc, /\.generate-progress-track/, 'storyboard.css 应有 .generate-progress-track 规则');
assert.match(cssSrc, /\.generate-progress-fill/, 'storyboard.css 应有 .generate-progress-fill 规则');

// 9. 视频工作流拆分任务节点客户端存在
const nodeClientPath = path.join(repoRoot, 'web/js/script_split_task.js');
assert.ok(fs.existsSync(nodeClientPath), 'web/js/script_split_task.js（视频工作流拆分节点客户端）应存在');

console.log('storyboard script split static tests passed');
