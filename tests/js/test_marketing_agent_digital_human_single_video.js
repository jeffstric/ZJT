// 回归测试：营销 Agent 生成数字人后，对话框气泡只应渲染一个视频播放器。
// 根因：pollAgentVideoStatus / pollAgentImageStatus 曾用未过滤的 collectGenerationUrls 把
// 混入的图片(png)项目 URL 也包进 <video>，导致一个气泡出现两个 <video>（其中一个是 png）。
// 修复：改用按媒体类型过滤的辅助函数 collectGenerationUrlsByType / buildGeneratedMediaRowsHtml。
// 2026-09-30：函数已从 marketing_agent.html 迁移到 web/js/marketing_agent.js（AGENTS.md 规则3），
// 本测试同步改为读取 js 文件；buildGeneratedMediaHtml 已重构为 buildGeneratedMediaRowsHtml。

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const js = fs.readFileSync(
  path.join(__dirname, '../../web/js/marketing_agent.js'),
  'utf8'
);

// 1) 从 js 中切出 URL 收集辅助函数块并在沙箱中求值（桩 window.t）。
//    collectGenerationUrls / filterGenerationUrlsByType / collectGenerationUrlsByType
//    互相调用，作为同一块 function 声明一起 eval 即可互相引用。
const blockStart = js.indexOf('function collectGenerationUrls(task)');
const blockEnd = js.indexOf('function collectGenerationRowsByType', blockStart);
assert.notEqual(blockStart, -1, 'collectGenerationUrls helper should exist in marketing_agent.js');
assert.notEqual(blockEnd, -1, 'collectGenerationRowsByType should follow the helpers');
const block = js.slice(blockStart, blockEnd);

const factory = new Function(
  'window',
  block + '\nreturn { collectGenerationUrlsByType, collectGenerationUrls };'
);
const helpers = factory({ t: (key) => key });

// 2) 数字人场景：参考图(png)项目与视频(mp4)项目被一起轮询。
//    video 渲染必须丢弃 png、只保留 mp4。
const mixedTasks = [
  { results: [{ file_url: 'https://cdn.example.com/14482_img.png?token=1' }] },
  { results: [{ file_url: 'https://cdn.example.com/14483_dh.mp4?token=2' }] },
];

const videoUrls = helpers.collectGenerationUrlsByType(mixedTasks, 'video');
assert.deepEqual(
  videoUrls,
  ['https://cdn.example.com/14483_dh.mp4?token=2'],
  'video polling must drop the bundled image (png) url and keep only the mp4'
);

// 3) 对称：image 渲染必须只保留 png、丢弃 mp4（防止 mp4 被渲染成 <img> 裂图）。
const imageUrls = helpers.collectGenerationUrlsByType(mixedTasks, 'image');
assert.deepEqual(
  imageUrls,
  ['https://cdn.example.com/14482_img.png?token=1'],
  'image polling must drop the bundled video (mp4) url and keep only the png'
);

// 4) 无扩展名（签名 CDN 链接）的视频不应被误杀。
const noExtTasks = [{ results: [{ file_url: 'https://cdn.example.com/files/abc-signature' }] }];
assert.deepEqual(
  helpers.collectGenerationUrlsByType(noExtTasks, 'video'),
  ['https://cdn.example.com/files/abc-signature'],
  'unknown-extension (signed cdn) urls must be kept for video rendering'
);

// 5) 渲染函数存在且视频行使用 <video>（文本断言，渲染依赖 Vue 上下文不做整段 eval）。
assert.equal(
  js.includes('function buildGeneratedMediaRowsHtml(type, rows)'),
  true,
  'row-based media renderer should exist'
);
const videoRenderFnStart = js.indexOf('function buildGeneratedMediaRowsHtml(type, rows)');
assert.notEqual(videoRenderFnStart, -1, 'buildGeneratedMediaRowsHtml should exist');
const videoRenderBlock = js.slice(videoRenderFnStart, videoRenderFnStart + 1600);
assert.equal(
  videoRenderBlock.includes('<video'),
  true,
  'video rows should render a <video> player'
);

// 6) 静态回归守卫：两个 Agent 轮询函数必须改用过滤辅助函数，且不得再出现把
//    所有 url 直接 map 成 <video>/<img> 的内联未过滤写法。
const imagePollStart = js.indexOf('function pollAgentImageStatus');
const imagePollEnd = js.indexOf('function handleVideoTaskSubmitted', imagePollStart);
assert.notEqual(imagePollStart, -1, 'pollAgentImageStatus should exist');
assert.notEqual(imagePollEnd, -1, 'handleVideoTaskSubmitted should follow pollAgentImageStatus');
const imagePoll = js.slice(imagePollStart, imagePollEnd);
assert.equal(imagePoll.includes('collectGenerationUrlsByType'), true, 'pollAgentImageStatus must collect urls by type');
assert.equal(imagePoll.includes('buildGeneratedTaskContent'), true, 'pollAgentImageStatus must render via buildGeneratedTaskContent');
assert.equal(imagePoll.includes('imageUrls.map(url'), false, 'pollAgentImageStatus must not inline-map urls to <img>');

const videoPollStart = js.indexOf('function pollAgentVideoStatus');
assert.notEqual(videoPollStart, -1, 'pollAgentVideoStatus should exist');
const videoPollEnd = js.indexOf('function sendVideoRequest', videoPollStart) !== -1
  ? js.indexOf('function sendVideoRequest', videoPollStart)
  : js.indexOf('function handleDirectGeneration', videoPollStart);
assert.notEqual(videoPollEnd, -1, 'a known function should follow pollAgentVideoStatus');
const videoPoll = js.slice(videoPollStart, videoPollEnd);
assert.equal(videoPoll.includes('collectGenerationUrlsByType'), true, 'pollAgentVideoStatus must collect urls by type');
assert.equal(videoPoll.includes('buildGeneratedTaskContent'), true, 'pollAgentVideoStatus must render via buildGeneratedTaskContent');
assert.equal(videoPoll.includes('videoUrls.map(url'), false, 'pollAgentVideoStatus must not inline-map urls to <video>');

console.log('marketing_agent digital-human single-video tests passed');
