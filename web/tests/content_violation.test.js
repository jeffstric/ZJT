// web/js/content_violation.js 测试
// 特征清单来自 /nas/tmp/api_request_log/ 2026-08-01 ~ 2026-08-30 真实失败样本；
// 与后端 utils/content_moderation_error.py（方案 A 规则映射）同源对齐。

const cv = require('../js/content_violation.js');

function clearOverlays() {
  document.querySelectorAll('.cv-overlay').forEach(el => el.parentNode && el.parentNode.removeChild(el));
}

beforeEach(() => {
  cv._resetForTest();
  clearOverlays();
});

afterEach(() => {
  clearOverlays();
});

describe('isViolation', () => {
  // 真实日志中出现的违规特征（2026-08 样本）
  const POSITIVE = [
    // Grok 渠道（占样本 95%+）
    'Content security audit did not pass | 内容安全审查未通过',
    '内容安全审查未通过',
    // Gemini duomi
    '任务执行失败: gemini blocked: finish_reason:STOP (candidate stopped before producing an image)',
    '任务执行失败: sensitive_words_detected',
    '任务执行失败: The provided prompt is considered unsafe and it cannot be used to generate content.',
    '任务执行失败: The generated images appear to be unsafe.',
    // GPT Image
    'Your request was rejected by the safety system. (request id: 20260810123456abcdef)',
    'moderation_blocked',
    'invalid_prompt: the prompt contains prohibited material',
    // Gemini 网关
    'Gemini image generation blocked [IMAGE_OTHER]: Image generation was stopped, often related to copyright or trademark concerns',
    'Gemini image generation blocked [IMAGE_SAFETY]: the request may contain sensitive content',
    'Gemini image generation blocked [PROHIBITED_CONTENT]',
    'The generated images appear to be unsafe. Try modifying the prompts or the seeds.',
    // 火山 Seedream / Seedance
    'InputImageSensitiveContentDetected.PrivacyInformation: The input image may contain real person.',
    'InputVideoSensitiveContentDetected: the input video may contain sensitive information',
    'OutputVideoSensitiveContentDetected: the output video contains sensitive content',
    'OutputAudioSensitiveContentDetected.PolicyViolation: copyright policy violation',
    // 后端友好文案（方案 A 归一后的 reason）
    '内容审核未通过：提示词包含敏感/违禁内容，请修改提示词后重试',
    '内容审核未通过（版权/商标）：提示词或参考内容可能涉及受保护形象/标识，请修改后重试',
  ];

  test.each(POSITIVE.map(t => [t]))('识别违规文案: %s', text => {
    expect(cv.isViolation(text)).toBe(true);
  });

  // 非违规错误：繁忙/限额/基础设施类失败不得误报
  const NEGATIVE = [
    'AI服务繁忙，请稍后重试',
    '抱歉，系统繁忙，请稍后重试',
    '抱歉，任务处理遇到了一点小问题',
    '图片大小超过 10MB',
    'Image exceeds limit (12345678 > 10485760)',
    'Total reference images and elements cannot exceed 4, got 5.',
    '模型 grok-video-channel 并发上限(10)已达，请等待其他任务完成后重试',
    '无可用渠道',
    'APIKEY_TASK_NOT_FOUND',
    '图片下载HTTP错误 404',
    'The model load is too high, please try again later',
    '未知原因,可能是当前官方算力问题',
    '任务超时，请稍后重试',
    null,
    '',
  ];

  test.each(NEGATIVE.map(t => [t]))('不误报: %j', text => {
    expect(cv.isViolation(text)).toBe(false);
  });

  test('提示词正文中的 "blocked" 等词不误报', () => {
    expect(cv.isViolation('a road blocked by fallen debris in the snow')).toBe(false);
    expect(cv.isViolation('审核员在路口拦截车辆')).toBe(false);
  });
});

describe('describe', () => {
  test('非违规返回 null', () => {
    expect(cv.describe('AI服务繁忙，请稍后重试')).toBe(null);
    expect(cv.describe('')).toBe(null);
    expect(cv.describe(null)).toBe(null);
  });

  test('后端友好文案不二次包裹', () => {
    const msg = '内容审核未通过：参考图片包含敏感内容，请更换参考图后重试';
    expect(cv.describe(msg)).toBe(msg);
  });

  test('Grok 渠道 → 通用文案', () => {
    expect(cv.describe('Content security audit did not pass | 内容安全审查未通过')).toBe(
      '内容审核未通过：请求被安全系统拦截，请检查提示词和参考图后重试'
    );
  });

  test('版权/商标 → 版权文案', () => {
    expect(cv.describe(
      'Gemini image generation blocked [IMAGE_OTHER]: Image generation was stopped, often related to copyright or trademark concerns'
    )).toBe('内容审核未通过（版权/商标）：提示词或参考内容可能涉及受保护形象/标识，请修改后重试');
  });

  test('IMAGE_SAFETY → 生成结果文案 + 安全策略标签', () => {
    expect(cv.describe('Gemini image generation blocked [IMAGE_SAFETY]: the request may contain sensitive content')).toBe(
      '内容审核未通过（安全策略）：生成结果可能包含敏感内容，请调整提示词或参考图后重试'
    );
  });

  test('火山 Output 敏感 → 生成结果文案', () => {
    expect(cv.describe('OutputVideoSensitiveContentDetected: the output video contains sensitive content')).toBe(
      '内容审核未通过：生成结果可能包含敏感内容，请调整提示词或参考图后重试'
    );
  });

  test('火山 Input 隐私 → 参考图文案', () => {
    expect(cv.describe('InputImageSensitiveContentDetected.PrivacyInformation: The input image may contain real person.')).toBe(
      '内容审核未通过：参考图片包含敏感内容，请更换参考图后重试'
    );
  });

  test('sensitive_words_detected → 提示词文案', () => {
    expect(cv.describe('任务执行失败: sensitive_words_detected')).toBe(
      '内容审核未通过：提示词包含敏感/违禁内容，请修改提示词后重试'
    );
  });

  test('generated images appear unsafe → 生成结果文案', () => {
    expect(cv.describe('The generated images appear to be unsafe. Try modifying the prompts or the seeds.')).toBe(
      '内容审核未通过：生成结果可能包含敏感内容，请调整提示词或参考图后重试'
    );
  });

  test('prompt considered unsafe → 提示词文案', () => {
    expect(cv.describe('The provided prompt is considered unsafe and it cannot be used to generate content.')).toBe(
      '内容审核未通过：提示词包含敏感/违禁内容，请修改提示词后重试'
    );
  });

  test('gemini blocked (candidate stopped) → 提示词文案', () => {
    expect(cv.describe('任务执行失败: gemini blocked: finish_reason:STOP (candidate stopped before producing an image)')).toBe(
      '内容审核未通过：提示词包含敏感/违禁内容，请修改提示词后重试'
    );
  });

  test('safety_violations 标签映射为中文', () => {
    expect(cv.describe('Your request was rejected by the safety system. (safety_violations=[sexual, violence])')).toBe(
      '内容审核未通过（色情、暴力）：请求被安全系统拦截，请检查提示词和参考图后重试'
    );
  });
});

describe('notify', () => {
  test('非违规不弹框', () => {
    const notified = cv.notify('wf:1', 'AI服务繁忙，请稍后重试');
    expect(notified).toBe(false);
    expect(document.querySelectorAll('.cv-overlay').length).toBe(0);
  });

  test('违规弹出提醒弹框，正文为友好文案', () => {
    const notified = cv.notify('wf:1', 'Content security audit did not pass | 内容安全审查未通过');
    expect(notified).toBe(true);
    const overlay = document.querySelector('.cv-overlay');
    expect(overlay).not.toBeNull();
    expect(overlay.querySelector('.cv-title').textContent).toContain('内容违规提醒');
    expect(overlay.querySelector('.cv-body').textContent).toBe(
      '内容审核未通过：请求被安全系统拦截，请检查提示词和参考图后重试'
    );
    expect(overlay.querySelector('details').textContent).toContain('Content security audit did not pass');
  });

  test('「我知道了」按钮可关闭弹框', () => {
    cv.notify('wf:1', '内容审核未通过：提示词包含敏感/违禁内容，请修改提示词后重试');
    const btn = document.querySelector('.cv-overlay .cv-btn');
    btn.click();
    expect(document.querySelectorAll('.cv-overlay').length).toBe(0);
  });

  test('点击遮罩可关闭弹框', () => {
    cv.notify('wf:1', '内容审核未通过：提示词包含敏感/违禁内容，请修改提示词后重试');
    const overlay = document.querySelector('.cv-overlay');
    overlay.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    expect(document.querySelectorAll('.cv-overlay').length).toBe(0);
  });

  test('同 key 冷却窗口内不重复弹', () => {
    expect(cv.notify('wf:1', '内容审核未通过：提示词包含敏感/违禁内容，请修改提示词后重试')).toBe(true);
    clearOverlays();
    // 全局冷却未到期 + 同 key 冷却未到期
    expect(cv.notify('wf:1', '内容审核未通过：提示词包含敏感/违禁内容，请修改提示词后重试')).toBe(false);
    expect(document.querySelectorAll('.cv-overlay').length).toBe(0);
  });

  test('不同 key 但全局冷却内不连环弹', () => {
    expect(cv.notify('wf:1', '内容审核未通过：提示词包含敏感/违禁内容，请修改提示词后重试')).toBe(true);
    clearOverlays();
    expect(cv.notify('wf:2', 'Content security audit did not pass')).toBe(false);
    expect(document.querySelectorAll('.cv-overlay').length).toBe(0);
  });

  test('重置去重状态后同 key 可再次提醒', () => {
    expect(cv.notify('wf:1', '内容审核未通过：提示词包含敏感/违禁内容，请修改提示词后重试')).toBe(true);
    clearOverlays();
    cv._resetForTest();
    expect(cv.notify('wf:1', '内容审核未通过：提示词包含敏感/违禁内容，请修改提示词后重试')).toBe(true);
    clearOverlays();
  });

  test('onNotified 回调收到友好文案与原文', () => {
    const calls = [];
    cv.notify('wf:9', '内容安全审查未通过', {
      onNotified: (friendly, raw) => calls.push([friendly, raw]),
    });
    expect(calls.length).toBe(1);
    expect(calls[0][0]).toContain('内容审核未通过');
    expect(calls[0][1]).toBe('内容安全审查未通过');
  });

  test('自定义 title 生效', () => {
    cv.notify('wf:9', '内容安全审查未通过', { title: '生成内容违规' });
    expect(document.querySelector('.cv-overlay .cv-title').textContent).toContain('生成内容违规');
  });
});
