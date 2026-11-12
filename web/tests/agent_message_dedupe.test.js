const AgentMessageDedupe = require('../js/agent_message_dedupe.js');

const { normalizeContent, hasDisplayedAssistantMessage, isNearDuplicateAssistantMessage, shouldPersistUserMessage, formatAgentUserMessageForDisplay } = AgentMessageDedupe;

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

describe('isNearDuplicateAssistantMessage（LLM 复读总结近似查重，2026-11-12 dev3 实测双份总结）', () => {
  const LONG_SUMMARY = [
    '## 工作总结',
    '- **执行状态**：成功（已提交）',
    '- **project_ids**：[1864]',
    '- **算力消耗**：总计消耗420算力',
    '- **任务说明**：已完成参考视频音轨去除，使用去音轨后的无音频参考视频提交视频克隆任务，前端会自动轮询展示生成进度和最终结果。',
  ].join('\n');

  it('完全相同的内容判重', () => {
    const messages = [{ role: 'ai', content: LONG_SUMMARY }];
    expect(isNearDuplicateAssistantMessage(messages, LONG_SUMMARY)).toBe(true);
  });

  it('LLM 复读版（个别空格/标点差异）判重——全等比对拦不住的场景', () => {
    const messages = [{ role: 'ai', content: LONG_SUMMARY }];
    const paraphrased = LONG_SUMMARY.replace('（已提交）', ' (已提交) ').replace('420算力', '420 算力').replace('\n', '\n\n');
    expect(paraphrased).not.toBe(LONG_SUMMARY);
    expect(isNearDuplicateAssistantMessage(messages, paraphrased)).toBe(true);
  });

  it('短提示不被长总结误杀（长度比例保护）', () => {
    const messages = [{ role: 'ai', content: LONG_SUMMARY }];
    expect(isNearDuplicateAssistantMessage(messages, '视频生成失败，请稍后重试。')).toBe(false);
  });

  it('内容不同的两条正常消息不判重', () => {
    const messages = [{ role: 'ai', content: LONG_SUMMARY }];
    expect(isNearDuplicateAssistantMessage(messages, '## 工作总结\n- **执行状态**：失败（任务未提交）\n- **project_ids**：[]')).toBe(false);
  });

  it('excludeUid 排除自身', () => {
    const messages = [{ _uid: 'u1', role: 'ai', content: LONG_SUMMARY }];
    expect(isNearDuplicateAssistantMessage(messages, LONG_SUMMARY, 'u1')).toBe(false);
  });
});
