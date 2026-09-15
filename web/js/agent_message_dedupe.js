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
    let displayContent = normalizeContent(content).replace(
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
