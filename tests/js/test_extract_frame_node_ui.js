// 提取帧节点 UI 源码断言：帧类型选项 / 时间轴 / 关键帧网格 / 重载恢复 / i18n key
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const jsPath = path.join(__dirname, '../../web/js/extract_frame_node.js');
const nodeJs = fs.readFileSync(jsPath, 'utf8');

// 帧类型下拉：四种选项且均可翻译
assert.match(
  nodeJs,
  /option value="first"[^>]*data-i18n="frame_first"/,
  'first frame option should be translatable'
);
assert.match(
  nodeJs,
  /option value="last"[^>]*data-i18n="frame_last"/,
  'last frame option should be translatable'
);
assert.match(
  nodeJs,
  /option value="custom"[^>]*data-i18n="frame_custom"/,
  'custom time option should be translatable'
);
assert.match(
  nodeJs,
  /option value="keyframes"[^>]*data-i18n="frame_keyframes"/,
  'keyframes option should be translatable'
);

// 时间轴选帧：滑杆 + 时间显示 + time_sec 提交
assert.match(nodeJs, /class="time-slider"/, 'time slider input should exist');
assert.match(nodeJs, /time-current[\s\S]*time-total/, 'time display (current/total) should exist');
assert.match(nodeJs, /formData\.append\('time_sec'/, 'custom mode should submit time_sec');
assert.match(
  nodeJs,
  /addEventListener\('loadedmetadata'[\s\S]*timeSlider\.max = String\(dur\)/,
  'slider max should be set from video duration on loadedmetadata'
);
assert.match(
  nodeJs,
  /loadedmetadata'[\s\S]*node\.data\.timeSec[\s\S]*thumbVideo\.currentTime = t/,
  'saved timeSec should be restored on loadedmetadata (workflow reload)'
);
assert.match(
  nodeJs,
  /function applyFrameTypeUi\(\)[\s\S]*var showPicker = isCustom \|\| isKeyframes[\s\S]*syncSliderToData\(\)/,
  'switching mode should resync slider to the saved time of that mode (mode-switch restore path)'
);

// 关键帧：候选网格渲染 + 选中 + 使用按钮 + 不直接建节点
assert.match(nodeJs, /function renderKeyframeGrid\(/, 'keyframe grid renderer should exist');
assert.match(nodeJs, /classList\.add\('selected'\)/, 'keyframe cell selection should exist');
assert.match(nodeJs, /class="gen-btn use-keyframe-btn"/, 'use-selected-frame button should exist');
// use-keyframe-btn 同为 .gen-btn 且 DOM 靠前，提取按钮必须按容器限定查询（防按钮绑定错位回归）
assert.match(
  nodeJs,
  /var extractBtn = el\.querySelector\('\.extract-actions-field \.gen-btn'\)/,
  'extract button should be scoped to .extract-actions-field (use-keyframe-btn is also .gen-btn)'
);
assert.match(
  nodeJs,
  /frameType === 'keyframes'[\s\S]*showKeyframeGrid\(frames\)/,
  'keyframes response should render candidate grid instead of creating image node directly'
);

// 重载恢复：候选帧与选中态在 createWithData 回调中重建
assert.match(
  nodeJs,
  /createNodeWithDataFactory[\s\S]*candidateFrames[\s\S]*renderKeyframeGrid\(/,
  'candidate grid should be restored on workflow reload'
);
assert.match(
  nodeJs,
  /selectedFrameTime !== null && node\.data\.selectedFrameTime !== undefined && useBtn/,
  'selected frame restore should re-show use button'
);

// 持久化字段齐全
for (const field of ['timeSec: null', 'keyframeStartSec: 0', 'candidateFrames: null', 'selectedFrameTime: null']) {
  assert.ok(nodeJs.includes(field), `defaultData should declare ${field}`);
}

// 关键帧翻页：提交 start_time + 响应推进起点 + 空批次提示
assert.match(nodeJs, /formData\.append\('start_time'/, 'keyframes mode should submit start_time');
assert.match(
  nodeJs,
  /result\.data\.last_time_sec[\s\S]*node\.data\.keyframeStartSec = result\.data\.last_time_sec[\s\S]*syncSliderToData\(\)/,
  'successful keyframe batch should advance start time to last frame and resync slider'
);
assert.match(
  nodeJs,
  /function activeTimeField\(\)[\s\S]*frameType === 'custom' \? 'timeSec' : 'keyframeStartSec'/,
  'time slider should read/write the active mode field (timeSec vs keyframeStartSec)'
);
assert.match(
  nodeJs,
  /var showPicker = isCustom \|\| isKeyframes/,
  'time picker should be visible in both custom and keyframes modes'
);
assert.match(nodeJs, /extract_frame_start_label/, 'keyframes mode should relabel the slider to start time');

// 命名后缀与实际输出格式一致（jpg），custom 带时间戳
assert.ok(!nodeJs.includes("'.png'") && !/frameTypeName \+ '\.png'/.test(nodeJs), 'frame naming should not use .png (output is jpg)');
assert.match(nodeJs, /toFixed\(2\) \+ 's' \+ ext/, 'custom frame name should embed timecode');

// i18n 资源：新 key 在 zh-CN / en 均存在
for (const loc of ['zh-CN', 'en']) {
  const i18nPath = path.join(__dirname, `../../web/i18n/locales/${loc}/video_workflow.json`);
  const i18n = JSON.parse(fs.readFileSync(i18nPath, 'utf8'));
  for (const key of ['frame_custom', 'frame_keyframes', 'extract_frame_time_label',
    'extract_frame_keyframe_grid_label', 'extract_frame_use_selected',
    'extract_frame_time_required', 'extract_frame_no_keyframes']) {
    assert.ok(i18n[key], `i18n ${loc} should define ${key}`);
  }
}

console.log('test_extract_frame_node_ui.js: all assertions passed');
