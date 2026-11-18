(function(root, factory) {
  if (typeof module === 'object' && module.exports) {
    module.exports = factory();
  } else {
    root.AgentMessageDedupe = factory();
  }
})(typeof self !== 'undefined' ? self : this, function() {
  function normalizeContent(content) {
    return String(content || '').replace(/\r\n/g, '\n').trim();
  }

  function hasDisplayedAssistantMessage(messages, content, excludeUid) {
    const target = normalizeContent(content);
    if (!target) return false;

    return (messages || []).some(function(message) {
      if (!message || (excludeUid && message._uid === excludeUid)) return false;
      if (message.role !== 'ai' && message.role !== 'assistant') return false;
      return normalizeContent(message.content) === target;
    });
  }

  // 去所有空白后的近似重复判定：LLM 复读工作总结时常有个别空格/标点/换行差异
  // （2026-11-12 dev3 实测：同一总结以两条几乎相同的气泡展示），全等比对拦不住。
  // 判据：去空白后短的一方被长的一方完整包含，且短方长度 ≥ 长方 75%。
  // 长度比例条件保护真正的短消息（如"视频生成失败，请稍后重试。"）不被长总结误杀。
  // 全角/半角标点归一表：LLM 复读常伴随标点形态漂移（（↔( 、：↔: 等）
  var PUNCT_NORMALIZE_MAP = {
    '（': '(', '）': ')', '：': ':', '，': ',', '、': ',', '；': ';',
    '！': '!', '?': '?', '？': '?',
    '【': '[', '】': ']', '《': '<', '》': '>'
  };

  function normalizeLoose(content) {
    return String(content || '')
      .replace(/\s+/g, '')
      .replace(/[（）:：,，、；;！?？【】《》]/g, function(ch) {
        return PUNCT_NORMALIZE_MAP[ch] || ch;
      });
  }

  function isNearDuplicateAssistantMessage(messages, content, excludeUid) {
    const target = normalizeLoose(content);
    if (!target) return false;

    return (messages || []).some(function(message) {
      if (!message || (excludeUid && message._uid === excludeUid)) return false;
      if (message.role !== 'ai' && message.role !== 'assistant') return false;
      const existing = normalizeLoose(message.content);
      if (!existing) return false;
      if (existing === target) return true;
      const shorter = existing.length < target.length ? existing : target;
      const longer = existing.length < target.length ? target : existing;
      return longer.indexOf(shorter) !== -1 && shorter.length >= longer.length * 0.75;
    });
  }

  function shouldPersistUserMessage(selectedType) {
    return selectedType !== 'agent';
  }

  // 转义实现统一收敛到 web/js/escape.js（window.escapeHtml）；UMD 在 Node/测试
  // 环境无 window 时降级为等价的本地实现（勿在此新增差异逻辑）
  function escapeHtml(value) {
    if (typeof window !== 'undefined' && typeof window.escapeHtml === 'function') {
      return window.escapeHtml(value);
    }
    return String(value || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function formatAgentUserMessageForDisplay(content) {
    const preferences = [];
    // [输出语言要求] 是多行指令块（API 层由 OUTPUT_LANGUAGE_INSTRUCTION_TEMPLATE 追加），
    // 整块折叠，detail 提取语言名（"输出语言为：X。"）
    let displayContent = normalizeContent(content).replace(
      /\n*\[输出语言要求\]\s*\n([\s\S]*?)(?=\n\n\[|$)/g,
      function(_match, body) {
        const firstLine = (body.split('\n')[0] || '').trim();
        const langMatch = firstLine.match(/输出语言为：(.+?)。/);
        preferences.push({
          label: '输出语言要求',
          detail: langMatch ? langMatch[1] : firstLine
        });
        return '';
      }
    );
    displayContent = displayContent.replace(
      /\n*\[(用户图片偏好|用户视频偏好)]\s*([^\n]*)/g,
      function(_match, label, detail) {
        preferences.push({ label: label, detail: detail });
        return '';
      }
    );

    displayContent = displayContent.replace(/\n{3,}/g, '\n\n').trim();
    if (preferences.length === 0) {
      return displayContent;
    }

    const detailsHtml = preferences.map(function(pref) {
      return '<div class="agent-preference-item"><strong>' +
        escapeHtml(pref.label) +
        '</strong> ' +
        escapeHtml(pref.detail) +
        '</div>';
    }).join('');

    return displayContent +
      '\n\n<details class="agent-preference-details"><summary>查看发送偏好</summary><div class="agent-preference-list">' +
      detailsHtml +
      '</div></details>';
  }

  return {
    hasDisplayedAssistantMessage: hasDisplayedAssistantMessage,
    normalizeContent: normalizeContent,
    shouldPersistUserMessage: shouldPersistUserMessage,
    formatAgentUserMessageForDisplay: formatAgentUserMessageForDisplay
  };
});
