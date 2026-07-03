/**
 * 统一工具函数
 *
 * 本文件集中管理跨页面复用的工具函数，消除各文件中的重复定义。
 * 函数挂载到 window 对象，确保浏览器全局可用；同时通过 module.exports
 * 导出，供 Vitest 测试使用。
 *
 * 已统一的函数：
 *   - escapeHtml: 原 nodes.js:2479 / dialogue_group_node.js:8 / agent_message_dedupe.js:27
 *                  选择 nodes.js 版本（显式 null/undefined 检查，&#39; 实体）
 */

/**
 * 转义 HTML 特殊字符，防止 XSS 注入
 *
 * @param {*} value - 任意类型输入，null/undefined 返回空字符串
 * @returns {string} 转义后的安全字符串
 *
 * 注意：
 * - 使用 &#39; 而非 &#039; 作为单引号实体（与 HTML5 规范一致）
 * - 对数值 0 等 falsy 但合法的值不会错误返回空字符串
 *   （修复了 agent_message_dedupe.js 中 `value || ''` 丢失 0 的 bug）
 */
function escapeHtml(value) {
  if (value === null || value === undefined) return '';
  return String(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

// 浏览器环境：挂载到 window
if (typeof window !== 'undefined') {
  window.escapeHtml = escapeHtml;
}

// Node.js 环境（Vitest）：导出供测试使用
if (typeof module !== 'undefined') {
  module.exports = { escapeHtml };
}
