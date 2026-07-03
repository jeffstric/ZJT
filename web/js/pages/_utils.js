  function buildDownloadUrl(url, filename) {
    if (url && url.startsWith('http')) {
      const separator = url.includes('?') ? '&' : '?';
      return `${url}${separator}attname=${encodeURIComponent(filename)}`;
    }
    return `/api/download?url=${encodeURIComponent(url)}&filename=${encodeURIComponent(filename)}`;
  }

// 挂载到全局供 HTML onclick 使用
if (typeof window !== "undefined") window.buildDownloadUrl = buildDownloadUrl;
if (typeof module !== "undefined") module.exports = { buildDownloadUrl };
  // 全局工具函数：获取生成模式标签
  function getGenerationModeLabel(item) {
    try {
      const extraConfig = item.extra_config ? (typeof item.extra_config === 'string' ? JSON.parse(item.extra_config) : item.extra_config) : null;
      const imageMode = extraConfig?.image_mode;
      
      const modeMap = {
        'first_last_frame': '首尾帧模式',
        'first_last_with_tail': '首尾帧模式',
        'multi_reference': '多参考图模式',
        'first_last_with_ref': '首尾帧+参考图模式'
      };
      
      return (imageMode && modeMap[imageMode]) ? modeMap[imageMode] : '-';
    } catch (e) {
      console.error('解析 extra_config 失败:', e);
      return '-';
    }
  }

if (typeof window !== "undefined") window.getGenerationModeLabel = getGenerationModeLabel;
