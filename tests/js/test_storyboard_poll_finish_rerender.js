// 分镜轮询收尾回归：占位卡能展示 URL、DOWNLOADING(6) 口径一致、停轮询收尾必须重绘。
// 背景：视频已生成成功但页面停在「生成中」——轮询收尾只刷数据不重绘，占位卡永驻。
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const pollingPath = path.join(__dirname, '../../web/js/storyboard/polling.js');
const pollingSource = fs.readFileSync(pollingPath, 'utf8');
const renderPath = path.join(__dirname, '../../web/js/storyboard/render.js');
const renderSource = fs.readFileSync(renderPath, 'utf8');

// 1. 占位卡：生成中行带可播 URL 时立即填入，不允许只改 status 丢掉 result_url
assert.match(
  pollingSource,
  /isRenderableCandidateUrl\(genInfo\.result_url\)/,
  'upsertGeneratingCandidate should read genInfo.result_url'
);
assert.match(
  pollingSource,
  /candidate\.url = String\(genInfo\.result_url\)\.trim\(\)/,
  'generating candidate url should be filled from genInfo.result_url'
);

// 2. hasRunning：选中资产与 generating 同一套非终态口径，至少包含 6（DOWNLOADING）
assert.match(
  pollingSource,
  /vals\.some\(v => v === 0 \|\| v === 1 \|\| v === 6\)/,
  'hasRunning should keep polling while selected asset is DOWNLOADING(6)'
);

// 3. 停轮询收尾：await 刷新候选后必须回写选中 URL 并重绘，禁止 fire-and-forget
assert.match(
  pollingSource,
  /await loadSceneCandidates\(sceneId\);[\s\S]*?applySceneUpdate\(scene, \[\]\)/,
  'poll finish should await loadSceneCandidates and applySceneUpdate'
);
assert.match(
  pollingSource,
  /scene\.videoUrl = preferSceneMediaUrl\(scene\.videoUrl, selVideo\.url\)/,
  'poll finish should write selected video url back to scene.videoUrl'
);
assert.match(
  pollingSource,
  /scene\.firstFrameUrl = preferSceneMediaUrl\(scene\.firstFrameUrl, selImage\.url\)/,
  'poll finish should write selected first frame url back to scene.firstFrameUrl'
);
assert.doesNotMatch(
  pollingSource,
  /loadSceneCandidates\(sceneId\)\.catch\(\(\) => \{\}\)/,
  'poll finish must not be fire-and-forget (no re-render otherwise)'
);
// 收尾整段自捕获：外层 catch 会把收尾异常当轮询错误退避，复活已停止的轮询
assert.match(
  pollingSource,
  /delete pollHadActivity\[sceneId\];\s*\n\s*try \{\s*\n\s*await loadSceneCandidates/,
  'poll finish block must be wrapped in its own try/catch after clearing pollHadActivity'
);

// 4. render.js：isCandidateTaskRunning 与轮询口径一致，认 6 / 'downloading'
assert.match(
  renderSource,
  /status === 0 \|\| status === 1 \|\| status === 6/,
  'isCandidateTaskRunning should treat DOWNLOADING(6) as running'
);
assert.match(
  renderSource,
  /status === 'downloading'/,
  "isCandidateTaskRunning should accept 'downloading' string status"
);

console.log('storyboard poll finish rerender tests passed');
