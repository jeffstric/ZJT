const AgentMessageDedupe = require('../js/agent_message_dedupe.js');

const { normalizeContent, hasDisplayedAssistantMessage, shouldPersistUserMessage, formatAgentUserMessageForDisplay } = AgentMessageDedupe;

// ── normalizeContent ──
describe('normalizeContent', () => {
  test('null/undefined 返回空字符串', () => {
    expect(normalizeContent(null)).toBe('');
    expect(normalizeContent(undefined)).toBe('');
  });

  test('去除首尾空白', () => {
    expect(normalizeContent('  hello  ')).toBe('hello');
  });

  test('\\r\\n 转换为 \\n', () => {
    expect(normalizeContent('line1\r\nline2')).toBe('line1\nline2');
  });

  test('纯空白返回空字符串', () => {
    expect(normalizeContent('   ')).toBe('');
  });

  test('正常文本原样返回', () => {
    expect(normalizeContent('hello world')).toBe('hello world');
  });
});

// ── hasDisplayedAssistantMessage ──
describe('hasDisplayedAssistantMessage', () => {
  test('空消息列表返回 false', () => {
    expect(hasDisplayedAssistantMessage([], 'hello')).toBe(false);
  });

  test('null 消息列表返回 false', () => {
    expect(hasDisplayedAssistantMessage(null, 'hello')).toBe(false);
  });

  test('空内容返回 false', () => {
    expect(hasDisplayedAssistantMessage([{ role: 'ai', content: 'hi' }], '')).toBe(false);
  });

  test('匹配到 assistant 消息返回 true', () => {
    const messages = [
      { role: 'user', content: 'hello' },
      { role: 'assistant', content: 'hi there' }
    ];
    expect(hasDisplayedAssistantMessage(messages, 'hi there')).toBe(true);
  });

  test('匹配到 ai 角色消息返回 true', () => {
    const messages = [{ role: 'ai', content: 'response' }];
    expect(hasDisplayedAssistantMessage(messages, 'response')).toBe(true);
  });

  test('不匹配 user 消息', () => {
    const messages = [{ role: 'user', content: 'hello' }];
    expect(hasDisplayedAssistantMessage(messages, 'hello')).toBe(false);
  });

  test('excludeUid 排除指定消息', () => {
    const messages = [
      { role: 'assistant', content: 'hi', _uid: 'msg1' },
      { role: 'assistant', content: 'hi', _uid: 'msg2' }
    ];
    expect(hasDisplayedAssistantMessage(messages, 'hi', 'msg1')).toBe(true);
    expect(hasDisplayedAssistantMessage(messages, 'hi', 'msg2')).toBe(true);
    expect(hasDisplayedAssistantMessage(messages, 'hi', 'msg3')).toBe(true);
  });

  test('所有消息都被 excludeUid 排除时返回 false', () => {
    const messages = [
      { role: 'assistant', content: 'hi', _uid: 'msg1' }
    ];
    expect(hasDisplayedAssistantMessage(messages, 'hi', 'msg1')).toBe(false);
  });

  test('内容规范化后比较（忽略空白差异）', () => {
    const messages = [{ role: 'ai', content: '  hello  ' }];
    expect(hasDisplayedAssistantMessage(messages, 'hello')).toBe(true);
  });
});

// ── shouldPersistUserMessage ──
describe('shouldPersistUserMessage', () => {
  test('agent 类型返回 false', () => {
    expect(shouldPersistUserMessage('agent')).toBe(false);
  });

  test('image 类型返回 true', () => {
    expect(shouldPersistUserMessage('image')).toBe(true);
  });

  test('video 类型返回 true', () => {
    expect(shouldPersistUserMessage('video')).toBe(true);
  });

  test('空字符串返回 true', () => {
    expect(shouldPersistUserMessage('')).toBe(true);
  });
});

// ── formatAgentUserMessageForDisplay ──
describe('formatAgentUserMessageForDisplay', () => {
  test('纯文本直接返回', () => {
    expect(formatAgentUserMessageForDisplay('hello world')).toBe('hello world');
  });

  test('提取图片偏好并生成 details HTML', () => {
    const result = formatAgentUserMessageForDisplay('some text\n[用户图片偏好] 偏好A');
    expect(result).toContain('some text');
    expect(result).toContain('<details');
    expect(result).toContain('用户图片偏好');
    expect(result).toContain('偏好A');
  });

  test('提取视频偏好', () => {
    const result = formatAgentUserMessageForDisplay('text\n[用户视频偏好] 偏好B');
    expect(result).toContain('用户视频偏好');
    expect(result).toContain('偏好B');
  });

  test('多个偏好都提取', () => {
    const result = formatAgentUserMessageForDisplay('text\n[用户图片偏好] A\n[用户视频偏好] B');
    expect(result).toContain('用户图片偏好');
    expect(result).toContain('用户视频偏好');
  });

  test('无偏好时只返回清理后内容', () => {
    const result = formatAgentUserMessageForDisplay('  hello  ');
    expect(result).toBe('hello');
    expect(result).not.toContain('<details');
  });

  test('多余空行被压缩', () => {
    const result = formatAgentUserMessageForDisplay('a\n\n\n\nb');
    expect(result).toBe('a\n\nb');
  });
});
