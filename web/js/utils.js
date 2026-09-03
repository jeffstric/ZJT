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

/** 可作为图片源连接到生视频/图片参考口的节点类型 */
var IMAGE_SOURCE_NODE_TYPES = ['image', 'character', 'location', 'props'];

/**
 * 读取节点对外提供的图片 URL。
 * 图片节点用 data.url；角色/场景/道具用 data.reference_image。
 * @param {Object|null} node
 * @returns {string}
 */
function getNodeImageUrl(node) {
  if (!node || !node.data) return '';
  if (node.type === 'image') return node.data.url || node.data.preview || '';
  if (node.type === 'character' || node.type === 'location' || node.type === 'props') {
    return node.data.reference_image || '';
  }
  return node.data.url || node.data.preview || node.data.reference_image || '';
}

function isImageSourceNodeType(type) {
  return IMAGE_SOURCE_NODE_TYPES.indexOf(type) !== -1;
}

/**
 * 从提示词中提取 【【角色名】】，按出现顺序去重。
 * @param {string} prompt
 * @returns {string[]}
 */
function extractMarkedCharacterNames(prompt) {
  if (!prompt) return [];
  const pattern = /【【([^】]+)】】/g;
  const names = [];
  let match;
  while ((match = pattern.exec(String(prompt))) !== null) {
    const name = match[1].trim();
    if (name && names.indexOf(name) === -1) names.push(name);
  }
  return names;
}

/**
 * 合并分镜节点图片提示词与生视频提示词中的角色名。
 * 图片提示词中先出现的角色在前，视频提示词多出的角色追加在后。
 * @param {Object} node
 * @returns {string[]}
 */
function mergeShotCharacterNames(node) {
  if (!node || !node.data) return [];
  const names = extractMarkedCharacterNames(node.data.imagePrompt || '');
  const videoPrompt = node.data.videoPromptText || node.data.videoPrompt || '';
  extractMarkedCharacterNames(videoPrompt).forEach(function(name) {
    if (names.indexOf(name) === -1) names.push(name);
  });
  return names;
}

/**
 * 按 max 同步裁切参考图 URL 与「图N是xxx」后缀，避免提示词编号超过实际张数。
 * @param {string[]} urls
 * @param {string[]} suffix
 * @param {number} maxCount
 */
function truncateRefCollection(urls, suffix, maxCount) {
  const max = Number(maxCount);
  if (!max || !urls || urls.length <= max) return;
  urls.length = max;
  if (Array.isArray(suffix) && suffix.length > max) suffix.length = max;
}

// 浏览器环境：挂载到 window
if (typeof window !== 'undefined') {
  window.escapeHtml = escapeHtml;
  window.IMAGE_SOURCE_NODE_TYPES = IMAGE_SOURCE_NODE_TYPES;
  window.getNodeImageUrl = getNodeImageUrl;
  window.isImageSourceNodeType = isImageSourceNodeType;
  window.extractMarkedCharacterNames = extractMarkedCharacterNames;
  window.mergeShotCharacterNames = mergeShotCharacterNames;
  window.truncateRefCollection = truncateRefCollection;
}

// Node.js 环境（Vitest）：导出供测试使用
if (typeof module !== 'undefined') {
  module.exports = {
    escapeHtml,
    IMAGE_SOURCE_NODE_TYPES,
    getNodeImageUrl,
    isImageSourceNodeType,
    extractMarkedCharacterNames,
    mergeShotCharacterNames,
    truncateRefCollection
  };
}
