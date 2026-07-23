// 回归测试：营销 Agent 生成数字人后，对话框气泡只应渲染一个视频播放器。
// 根因：pollAgentVideoStatus / pollAgentImageStatus 曾用未过滤的 collectGenerationUrls 把
// 混入的图片(png)项目 URL 也包进 <video>，导致一个气泡出现两个 <video>（其中一个是 png）。
// 修复：改用按媒体类型过滤的辅助函数 collectGenerationUrlsByType / buildGeneratedMediaHtml。

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const html = fs.readFileSync(
  path.join(__dirname, '../../web/marketing_agent.html'),
  'utf8'
);

// 1) 从 HTML 中切出纯辅助函数块并在沙箱中求值（桩 window.t）。
//    这些函数互相调用，作为同一块 function 声明一起 eval 即可互相引用。
const blockStart = html.indexOf('function collectGenerationUrls(task)');
// 注意：persistDirectGenerationResult 声明为 async function，必须按 'async function' 切，
// 否则切片尾部会残留 'async ' 关键字导致 eval 报 'async is not defined'。
const blockEnd = html.indexOf('async function persistDirectGenerationResult', blockStart);
assert.notEqual(blockStart, -1, 'collectGenerationUrls helper should exist');
assert.notEqual(blockEnd, -1, 'persistDirectGenerationResult should follow the helpers');
const block = html.slice(blockStart, blockEnd);

const factory = new Function(
  'window',
  block + '\nreturn { collectGenerationUrlsByType, buildGeneratedMediaHtml, collectGenerationUrls };'
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

const videoHtml = helpers.buildGeneratedMediaHtml('video', videoUrls);
assert.equal(
  (videoHtml.match(/<video/g) || []).length,
  1,
  'exactly one <video> player should be rendered for a digital human result'
);
assert.equal(videoHtml.includes('.png'), false, 'rendered video bubble must not contain a png url');
// 行为保持：单视频产出的 HTML 与原先内联写法逐字节一致。
assert.equal(
  videoHtml,
  '<video src="https://cdn.example.com/14483_dh.mp4?token=2" controls style="max-width:100%;max-height:400px;border-radius:8px;margin:8px 0;"></video>',
  'single-video html must be byte-identical to the previous inline rendering'
);

// 3) 对称：image 渲染必须只保留 png、丢弃 mp4（防止 mp4 被渲染成 <img> 裂图）。
const imageUrls = helpers.collectGenerationUrlsByType(mixedTasks, 'image');
assert.deepEqual(
  imageUrls,
  ['https://cdn.example.com/14482_img.png?token=1'],
  'image polling must drop the bundled video (mp4) url and keep only the png'
);
const imageHtml = helpers.buildGeneratedMediaHtml('image', imageUrls);
assert.equal((imageHtml.match(/<img/g) || []).length, 1, 'exactly one <img> for image result');
assert.equal(imageHtml.includes('.mp4'), false, 'rendered image bubble must not contain an mp4 url');

// 4) 无扩展名（签名 CDN 链接）的视频不应被误杀。
const noExtTasks = [{ results: [{ file_url: 'https://cdn.example.com/files/abc-signature' }] }];
assert.deepEqual(
  helpers.collectGenerationUrlsByType(noExtTasks, 'video'),
  ['https://cdn.example.com/files/abc-signature'],
  'unknown-extension (signed cdn) urls must be kept for video rendering'
);

// 5) 静态回归守卫：两个 Agent 轮询函数必须改用过滤辅助函数，且不得再出现把
//    所有 url 直接 map 成 <video>/<img> 的内联未过滤写法。
const imagePollStart = html.indexOf('function pollAgentImageStatus');
const imagePollEnd = html.indexOf('function handleVideoTaskSubmitted', imagePollStart);
const imagePoll = html.slice(imagePollStart, imagePollEnd);
assert.equal(imagePoll.includes('collectGenerationUrlsByType'), true, 'pollAgentImageStatus must collect urls by type');
assert.equal(imagePoll.includes('buildGeneratedMediaHtml'), true, 'pollAgentImageStatus must render via buildGeneratedMediaHtml');
assert.equal(imagePoll.includes('imageUrls.map(url'), false, 'pollAgentImageStatus must not inline-map urls to <img>');

const videoPollStart = html.indexOf('function pollAgentVideoStatus');
const videoPollEnd = html.indexOf('function sendVideoRequest', videoPollStart);
const videoPoll = html.slice(videoPollStart, videoPollEnd);
assert.equal(videoPoll.includes('collectGenerationUrlsByType'), true, 'pollAgentVideoStatus must collect urls by type');
assert.equal(videoPoll.includes('buildGeneratedMediaHtml'), true, 'pollAgentVideoStatus must render via buildGeneratedMediaHtml');
assert.equal(videoPoll.includes('videoUrls.map(url'), false, 'pollAgentVideoStatus must not inline-map urls to <video>');

// 6) buildResultContent 的不可达旧实现（死代码）应已清理。
const buildResultStart = html.indexOf('function buildResultContent');
const buildResultEnd = html.indexOf('function recoverPendingTasks', buildResultStart);
const buildResult = html.slice(buildResultStart, buildResultEnd);
assert.equal(buildResult.includes('const urls = []'), false, 'buildResultContent dead code should be removed');

console.log('marketing_agent digital-human single-video tests passed');
