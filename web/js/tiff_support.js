/**
 * tiff_support.js — TIFF 上传的浏览器端兼容判定（全站公共）。
 *
 * 浏览器 <img> 标签不解码 TIFF（Chrome/Edge/Firefox 均不支持），因此：
 * 1. 本地预览（base64 / objectURL）对 tif 会裂图，须用 isTiffFile 特判
 *    显示占位，不走 FileReader/Image 渲染；
 * 2. 后端（utils/media_upload.convert_tiff_file_to_png）在落盘时会把
 *    tif/tiff 归一化为 PNG，上传成功后拿到的 URL 恒为 png，可直接 <img>。
 *
 * 判定以文件扩展名为准：部分 Windows 环境未注册 image/tiff MIME，
 * file.type 可能为空，不能只依赖 MIME。
 */
(function () {
    'use strict';

    var TIFF_EXTENSIONS = ['.tif', '.tiff'];

    /**
     * 判断文件是否为 TIFF（按扩展名，MIME image/tiff 作为兜底信号）。
     * @param {File|string} file File 对象或文件名
     * @returns {boolean}
     */
    function isTiffFile(file) {
        if (!file) return false;
        var name = typeof file === 'string' ? file : (file.name || '');
        var lower = name.toLowerCase();
        for (var i = 0; i < TIFF_EXTENSIONS.length; i++) {
            if (lower.endsWith(TIFF_EXTENSIONS[i])) return true;
        }
        return typeof file === 'object' && file.type === 'image/tiff';
    }

    /**
     * TIFF 占位块的 HTML（灰底 TIF 徽标，替代 <img> 本地预览）。
     * label 为可选说明文字（文件名/标签），经 escapeHtml 转义后拼接；
     * escape.js 未加载时直接不渲染 label，杜绝未转义路径。
     */
    function tiffPlaceholderHtml(label) {
        var labelHtml = '';
        if (label && window.escapeHtml) {
            labelHtml = '<div style="position:absolute;bottom:22px;left:4px;right:4px;color:#374151;font-size:10px;text-align:center;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">' + window.escapeHtml(label) + '</div>';
        }
        return '<div style="width:100%;height:100%;background:#e5e7eb;display:flex;align-items:center;justify-content:center;overflow:hidden;">' +
            '<span style="background:#4b5563;color:#fff;font-size:10px;font-weight:600;padding:2px 6px;border-radius:4px;">TIF</span>' +
            labelHtml +
            '</div>';
    }

    window.isTiffFile = isTiffFile;
    window.tiffPlaceholderHtml = tiffPlaceholderHtml;
})();
