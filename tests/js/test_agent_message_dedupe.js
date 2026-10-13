const assert = require('node:assert/strict');
const dedupe = require('../../web/js/agent_message_dedupe.js');

const existingMessages = [
  { role: 'user', content: '请分析图片' },
  { role: 'ai', content: '### 图片内容识别\r\n这是一张清新治愈风格的人像摄影作品' },
];

assert.equal(
  dedupe.hasDisplayedAssistantMessage(
    existingMessages,
    '### 图片内容识别\n这是一张清新治愈风格的人像摄影作品'
  ),
  true,
  '应识别历史中已经展示过的 assistant 内容'
);

assert.equal(
  dedupe.hasDisplayedAssistantMessage(existingMessages, '新的回复内容'),
  false,
  '不同内容不应被判定为重复'
);

assert.equal(
  dedupe.hasDisplayedAssistantMessage(
    [{ _uid: 'stream-1', role: 'ai', content: 'streaming' }],
    'streaming',
    'stream-1'
  ),
  false,
  '当前流式占位消息不应把自己判定为重复'
);

assert.equal(
  dedupe.shouldPersistUserMessage('agent'),
  false,
  'agent user messages should be persisted by backend enriched history'
);

assert.equal(
  dedupe.shouldPersistUserMessage('image'),
  true,
  'non-agent user messages should keep frontend persistence'
);

const enhancedUserContent = [
  '[图片1]（URL: http://localhost:9003/upload/marketing/pic/a/test.png）',
  '',
  '这个什么图片？',
  '',
  '[用户图片偏好] 图片比例: 9:16, 生图模型: Seedance 2.0 Fast',
  '',
  '[用户视频偏好] 视频比例: 9:16, 视频时长: 5秒, 图片模式: first_last_frame'
].join('\n');

const displayContent = dedupe.formatAgentUserMessageForDisplay(enhancedUserContent);
assert.equal(
  displayContent.includes('[用户图片偏好]'),
  false,
  'image preference marker should be hidden from main bubble'
);
assert.equal(
  displayContent.includes('[用户视频偏好]'),
  false,
  'video preference marker should be hidden from main bubble'
);
assert.equal(
  displayContent.includes('<details class="agent-preference-details">'),
  true,
  'preference details should be collapsed'
);
assert.equal(
  displayContent.includes('这个什么图片？'),
  true,
  'original user question should remain visible'
);
assert.equal(
  displayContent.includes('图片比例: 9:16'),
  true,
  'collapsed details should keep preference values'
);

// [输出语言要求] 多行指令块也应整块折叠，details 中提取语言名
const outputLanguageBlock = [
  '',
  '[输出语言要求]',
  '用户指定本次生成素材的输出语言为：English。请遵守：',
  '1. 生成的图片/视频素材中呈现给观众的所有文字（海报文案、店招、字幕、包装、招牌等）必须使用English',
  '2. 视频口播旁白、数字人播报文案必须使用English',
  '6. PM 委托专家智能体时，必须在 task_description 中明确传达本输出语言要求'
].join('\n');
const langDisplay = dedupe.formatAgentUserMessageForDisplay(
  '帮我做一张海报' + outputLanguageBlock
);
assert.equal(
  langDisplay.includes('[输出语言要求]'),
  false,
  'output language marker should be hidden from main bubble'
);
assert.equal(
  langDisplay.includes('必须使用English'),
  false,
  'output language instruction body should be fully folded'
);
assert.equal(
  langDisplay.includes('<strong>输出语言要求</strong> English</div>'),
  true,
  'collapsed details should extract the language name'
);
assert.equal(
  langDisplay.includes('帮我做一张海报'),
  true,
  'original user question should remain visible'
);

console.log('agent_message_dedupe tests passed');
