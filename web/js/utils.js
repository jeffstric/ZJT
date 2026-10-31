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
 * 生视频参考资产收集用：只从生视频提示词提取【【角色名】】。
 * 图片提示词的角色属于画面构成（分镜图可以画多个角色），不等于本镜
 * 生视频要带的角色——ai_tools 13137 事故：视频提示词只点名王福成，
 * 李成建因图片提示词被带成图3+音频2，优化提示词凭空多出一个角色并
 * 上传了他的音色。
 * @param {Object} node
 * @returns {string[]}
 */
function videoShotCharacterNames(node) {
  if (!node || !node.data) return [];
  const videoPrompt = node.data.videoPromptText || node.data.videoPrompt || '';
  return extractMarkedCharacterNames(videoPrompt);
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

// 浏览器环境：挂载到 window。
// escapeHtml 的浏览器端权威实现由 web/js/escape.js 提供（本文件仅保留本地定义
// 供 Node/Vitest 导出使用）；escape.js 未引入时保留兜底挂载，避免调用点报 undefined。
if (typeof window !== 'undefined') {
  if (typeof window.escapeHtml !== 'function') {
    window.escapeHtml = escapeHtml;
  }
  window.IMAGE_SOURCE_NODE_TYPES = IMAGE_SOURCE_NODE_TYPES;
  window.getNodeImageUrl = getNodeImageUrl;
  window.isImageSourceNodeType = isImageSourceNodeType;
    window.extractMarkedCharacterNames = extractMarkedCharacterNames;
    window.mergeShotCharacterNames = mergeShotCharacterNames;
    window.videoShotCharacterNames = videoShotCharacterNames;
  window.truncateRefCollection = truncateRefCollection;
  window.compressImageFile = compressImageFile;
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
    videoShotCharacterNames,
    truncateRefCollection,
    compressImageFile
  };
}

/**
 * mime 对应的文件扩展名
 */
function extForImageMime(mime) {
  if (mime === 'image/png') return '.png';
  if (mime === 'image/webp') return '.webp';
  return '.jpg';
}

/**
 * 用压缩后的 blob 重建 File，保留原文件名主干、按输出格式替换扩展名
 */
function fileFromImageBlob(blob, mime, originalName) {
  const base = String(originalName || 'image').replace(/\.[^.]+$/, '');
  const name = base + extForImageMime(mime);
  try {
    return new File([blob], name, { type: mime });
  } catch (e) {
    // 旧浏览器兜底
    blob.name = name;
    return blob;
  }
}

/**
 * 将超过大小上限的图片在前端压缩后再上传（仅 video_workflow 页面使用）。
 *
 * 策略：优先保持原格式缩放重编码（png/webp，保留透明通道），不达标再依次尝试
 * webp 0.9 → jpeg 0.9/0.75/0.6（白底填充）；仍未达标则把边长减半再跑一轮。
 * 全程返回最优结果（可能仍略超上限，由服务端兜底校验）。
 *
 * 以下情况原样返回 file，由调用方按超限处理：
 * - 未超上限 / 非 image/* / GIF（canvas 压缩会丢动画帧）/ 解码失败
 *
 * @param {File|Blob} file 待上传图片
 * @param {number} maxBytes 大小上限（字节）
 * @returns {Promise<File|Blob>} 原文件或压缩后的新 File
 */
async function compressImageFile(file, maxBytes) {
  if (!file || !maxBytes || file.size <= maxBytes) return file;
  const type = (file.type || '').toLowerCase();
  if (!type || type.indexOf('image/') !== 0 || type === 'image/gif') return file;

  const objectUrl = URL.createObjectURL(file);
  let img;
  try {
    img = await new Promise((resolve, reject) => {
      const el = new Image();
      el.onload = function () { resolve(el); };
      el.onerror = function () { reject(new Error('image decode failed')); };
      el.src = objectUrl;
    });
  } catch (e) {
    URL.revokeObjectURL(objectUrl);
    return file;
  }

  try {
    const w0 = img.naturalWidth || img.width;
    const h0 = img.naturalHeight || img.height;
    if (!w0 || !h0) return file;

    const MAX_DIM = 4096;
    let scale = Math.min(1, MAX_DIM / Math.max(w0, h0));
    let best = null; // { blob, mime }

    // 最多两轮：第二轮把边长减半（全页缩略图可接受）
    for (let round = 0; round < 2; round++) {
      const w = Math.max(1, Math.round(w0 * scale));
      const h = Math.max(1, Math.round(h0 * scale));
      const canvas = document.createElement('canvas');
      canvas.width = w;
      canvas.height = h;
      const ctx = canvas.getContext('2d');

      const candidates = [];
      // 同格式优先（png/webp 保留透明；png 无质量参数，仅靠缩放）
      if (type === 'image/png' || type === 'image/webp') {
        candidates.push({ mime: type, quality: type === 'image/webp' ? 0.9 : undefined });
      }
      candidates.push({ mime: 'image/webp', quality: 0.9 });
      candidates.push({ mime: 'image/jpeg', quality: 0.9 });
      candidates.push({ mime: 'image/jpeg', quality: 0.75 });
      candidates.push({ mime: 'image/jpeg', quality: 0.6 });

      for (let i = 0; i < candidates.length; i++) {
        const cand = candidates[i];
        if (cand.mime === 'image/jpeg') {
          ctx.fillStyle = '#fff';
          ctx.fillRect(0, 0, w, h);
        } else {
          ctx.clearRect(0, 0, w, h);
        }
        ctx.drawImage(img, 0, 0, w, h);
        const blob = await new Promise((resolve) => canvas.toBlob(resolve, cand.mime, cand.quality));
        if (!blob || blob.size === 0) continue;
        if (!best || blob.size < best.blob.size) best = { blob: blob, mime: cand.mime };
        if (blob.size <= maxBytes) {
          return fileFromImageBlob(blob, cand.mime, file.name);
        }
      }
      scale /= 2;
    }

    // 两轮后仍未达标：返回最优结果，交由服务端校验兜底
    if (best) return fileFromImageBlob(best.blob, best.mime, file.name);
    return file;
  } finally {
    URL.revokeObjectURL(objectUrl);
  }
}
