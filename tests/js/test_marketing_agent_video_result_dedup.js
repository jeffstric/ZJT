// 回归测试：生成结果去重必须兼容「代理 URL 编码 + CDN 一次性签名」形态。
// 事故（会话 66875523-3737-4d10-8db1-115127d8b0d2，project 12549）：
// 结果卡片里的视频 src 是 /api/download?url=<encodeURIComponent(带签名CDN URL)>，
// 而 contentHasGeneratedTaskId 只按原文 `/12549_` 匹配（编码后为 `%2F12549_`），
// URL 精确匹配又因每次轮询签名不同必然失败 → 每次刷新页面都判定"尚无结果"，
// 重启轮询后重复追加"视频已生成"消息（同视频重复展示 4 次）。

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const js = fs.readFileSync(
  path.join(__dirname, '../../web/js/marketing_agent.js'),
  'utf8'
);

// —— 提取工具函数块（stripUrlSignature / contentIncludesMediaUrl / normalizeMediaUrlKey）——
const utilStart = js.indexOf('function stripUrlSignature(url)');
const utilEnd = js.indexOf('function isImageResultUrl', utilStart);
assert.notEqual(utilStart, -1, 'stripUrlSignature helper should exist');
assert.notEqual(utilEnd, -1, 'URL helpers should precede isImageResultUrl');
const utilBlock = js.slice(utilStart, utilEnd);

// —— 提取去重判定块（contentHasGeneratedTaskId / hasGeneratedImageResult / hasGeneratedVideoResult）——
const dedupeStart = js.indexOf('function contentHasGeneratedTaskId(content, id)');
const dedupeEnd = js.indexOf('function recoverVideoTasksFromAssistantMessages', dedupeStart);
assert.notEqual(dedupeStart, -1, 'contentHasGeneratedTaskId should exist');
assert.notEqual(dedupeEnd, -1, 'recoverVideoTasksFromAssistantMessages should follow dedupe helpers');
const dedupeBlock = js.slice(dedupeStart, dedupeEnd);

// —— 提取历史加载去重块（normalizeLoadedMessages）——
const normalizeStart = js.indexOf('function normalizeLoadedMessages(messageList)');
const normalizeEnd = js.indexOf("const selectedDuration = ref('auto')", normalizeStart);
assert.notEqual(normalizeStart, -1, 'normalizeLoadedMessages should exist');
assert.notEqual(normalizeEnd, -1, 'normalizeLoadedMessages block end marker should exist');
const normalizeBlock = js.slice(normalizeStart, normalizeEnd);

const dedupeFactory = new Function(
  'messages',
  utilBlock + '\n' + dedupeBlock + '\nreturn { contentHasGeneratedTaskId, contentIncludesMediaUrl, hasGeneratedImageResult, hasGeneratedVideoResult };'
);
const normalizeFactory = new Function(
  utilBlock + '\n' + normalizeBlock + '\nreturn { normalizeLoadedMessages };'
);

// 事故会话真实消息内容（chat_messages id=23447 的 JSON text 字段原文，
// 视频文件 12549_20260930100212_4fcc9930.mp4，签名为写入时刻的 e=1790834787）
const INCIDENT_VIDEO_CONTENT =
  '视频已生成：\n\n' +
  '<div class="generated-result-card"><video src="/api/download?url=https%3A%2F%2Fcdntest.perseids.cn%2Fupload%2Fcache%2F2026-09-30%2F12549_20260930100212_4fcc9930.mp4%3Fe%3D1790834787%26token%3DIAM-Pt2PpF216ir_ecWxGTwMOOHiI_TJONvyCG7ROvZS%3AIhZHa8_ZwOplVSRKTX5gbv38WvQ%3D" controls style="max-width:100%;max-height:400px;border-radius:8px;margin:8px 0;"></video>' +
  '<div class="generated-result-actions"><button class="publish-result-btn" data-publish-tool-id="12549" data-publish-title="">发布</button></div></div>';

// 后续轮询 get-status 返回的同一文件（签名必然不同）
const FRESH_SIGNED_URL =
  'https://cdntest.perseids.cn/upload/cache/2026-09-30/12549_20260930100212_4fcc9930.mp4?e=1790834830&token=IAM-Pt2PpF216ir_ecWxGTwMOOHiI_TJONvyCG7ROvZS%3AJxs2njxL-tc_U89Ir-KJByga6B0%3D';

const OTHER_FILE_URL =
  'https://cdntest.perseids.cn/upload/cache/2026-09-30/12550_20260930101500_abcdef01.mp4?e=1790834830&token=IAM-x';

const helpers = dedupeFactory({ value: [] });
const { normalizeLoadedMessages } = normalizeFactory();

// 1) 事故场景：contentHasGeneratedTaskId 必须命中当前卡片 HTML 形态
assert.equal(
  helpers.contentHasGeneratedTaskId(INCIDENT_VIDEO_CONTENT, '12549'),
  true,
  'must match data-publish-tool-id / %2F12549_ in proxied result card (incident 66875523)'
);
assert.equal(
  helpers.contentHasGeneratedTaskId(INCIDENT_VIDEO_CONTENT, '1254'),
  false,
  'must not prefix-collide: 1254 must not match 12549'
);
assert.equal(
  helpers.contentHasGeneratedTaskId(INCIDENT_VIDEO_CONTENT, '12550'),
  false,
  'must not match unrelated project id'
);
// 旧版卡片内联 onclick 形态仍需兼容
assert.equal(
  helpers.contentHasGeneratedTaskId("<img src='x' onclick=\"setModalImageInfo('123', 't')\">", '123'),
  true,
  'legacy setModalImageInfo pattern must keep matching'
);
assert.equal(
  helpers.contentHasGeneratedTaskId('前置/123_2026 文件名片段', '123'),
  true,
  'raw /<pid>_ filename fragment must keep matching'
);

// 2) URL 匹配：去签名 + 编码形态，跨轮询签名变化必须仍判定为同一资源
assert.equal(
  helpers.contentIncludesMediaUrl(INCIDENT_VIDEO_CONTENT, FRESH_SIGNED_URL),
  true,
  'fresh signed URL must match content holding the old signed (encoded) URL of the same file'
);
assert.equal(
  helpers.contentIncludesMediaUrl('看这个 https://cdn.perseids.cn/a/b/12549_x.mp4 已生成', 'https://cdn.perseids.cn/a/b/12549_x.mp4?e=2&token=T'),
  true,
  'raw URL in content must match fresh signed URL of same file (signature stripped)'
);
assert.equal(
  helpers.contentIncludesMediaUrl(INCIDENT_VIDEO_CONTENT, OTHER_FILE_URL),
  false,
  'different file must not match'
);

// 3) hasGeneratedVideoResult：事故恢复路径（仅 project_ids）与轮询完成路径（带新签名 URL）
const messagesWithResult = { value: [{ _uid: 'u1', role: 'ai', content: INCIDENT_VIDEO_CONTENT }] };
const videoHelpers = dedupeFactory(messagesWithResult);
assert.equal(
  videoHelpers.hasGeneratedVideoResult(['12549']),
  true,
  'recovery path: existing video card must be detected by project id (was the incident bug)'
);
assert.equal(
  videoHelpers.hasGeneratedVideoResult(['12549'], [FRESH_SIGNED_URL]),
  true,
  'poll path: existing video card must be detected via fresh signed URL + id fallback'
);
assert.equal(
  videoHelpers.hasGeneratedVideoResult(['99999'], [OTHER_FILE_URL]),
  false,
  'absent project/url must not be reported as generated'
);
assert.equal(
  videoHelpers.hasGeneratedVideoResult(['12549'], []),
  true,
  'empty urls must fall back to id check'
);
const userMessageOnly = { value: [{ role: 'user', content: INCIDENT_VIDEO_CONTENT }] };
assert.equal(
  dedupeFactory(userMessageOnly).hasGeneratedVideoResult(['12549']),
  false,
  'user messages must not count as generated results'
);

// 4) hasGeneratedImageResult：图片卡片（data-tool-id + generated-image-wrapper）同规则
const IMAGE_CARD_CONTENT =
  '图片已生成：\n\n' +
  '<div class="generated-image-wrapper generated-result-card" data-modal-src="/api/proxy-image?url=https%3A%2F%2Fcdn.perseids.cn%2Fa%2F777_img.png" data-tool-id="777" data-tool-title="">' +
  '<img src="/api/proxy-image?url=https%3A%2F%2Fcdn.perseids.cn%2Fa%2F777_img.png" class="generated-image" alt="结果">' +
  '<div class="generated-result-actions"><button class="publish-result-btn" data-publish-tool-id="777" data-publish-title="">发布</button></div></div>';
const imageHelpers = dedupeFactory({ value: [{ role: 'ai', content: IMAGE_CARD_CONTENT }] });
assert.equal(imageHelpers.hasGeneratedImageResult(['777']), true, 'image card must be detected by data-tool-id');
assert.equal(
  imageHelpers.hasGeneratedImageResult(['777'], ['https://cdn.perseids.cn/a/777_img.png?e=9&token=T']),
  true,
  'image card must be detected via fresh signed URL'
);
assert.equal(imageHelpers.hasGeneratedImageResult(['778']), false, 'other project id must not match image card');

// 5) normalizeLoadedMessages：同一视频多次追加（签名各异）只保留一条
const duplicateHistory = [
  { role: 'ai', content: '视频已生成：\n\n<div class="generated-result-card"><video src="/api/download?url=https%3A%2F%2Fcdn.perseids.cn%2Fv%2F12549_a.mp4%3Fe%3D1%26token%3DT1" controls></video></div>', timestamp: '2026-09-30T10:02:19Z' },
  { role: 'ai', content: '视频已生成：\n\n<div class="generated-result-card"><video src="/api/download?url=https%3A%2F%2Fcdn.perseids.cn%2Fv%2F12549_a.mp4%3Fe%3D2%26token%3DT2" controls></video></div>', timestamp: '2026-09-30T10:06:27Z' },
  { role: 'ai', content: '视频已生成：\n\n<div class="generated-result-card"><video src="/api/download?url=https%3A%2F%2Fcdn.perseids.cn%2Fv%2F12549_a.mp4%3Fe%3D3%26token%3DT3" controls></video></div>', timestamp: '2026-09-30T10:07:10Z' }
];
const deduped = normalizeLoadedMessages(duplicateHistory);
assert.equal(deduped.length, 1, 'same video appended with different signatures must collapse to one message');
assert.equal(deduped[0].content.includes('e%3D1'), true, 'the earliest copy is kept');

const distinctHistory = [
  { role: 'ai', content: '<video src="/api/download?url=https%3A%2F%2Fcdn.perseids.cn%2Fv%2F12549_a.mp4%3Fe%3D1%26token%3DT1" controls></video>', timestamp: 't1' },
  { role: 'ai', content: '<video src="/api/download?url=https%3A%2F%2Fcdn.perseids.cn%2Fv%2F12550_b.mp4%3Fe%3D2%26token%3DT2" controls></video>', timestamp: 't2' }
];
assert.equal(
  normalizeLoadedMessages(distinctHistory).length,
  2,
  'different videos must both be kept'
);

// 6) 前端 replacePendingTask 必须识别后端 duplicate 响应，跳过追加
assert.equal(
  js.includes('data.replaced > 0 || data.duplicate === true'),
  true,
  'replacePendingTask must treat backend duplicate=true as handled (skip append)'
);

console.log('test_marketing_agent_video_result_dedup: all assertions passed');
