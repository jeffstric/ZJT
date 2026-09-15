/**
 * security.js — 不可信内容（LLM 输出/用户输入/历史消息）渲染为 HTML 的唯一净化入口。
 *
 * 背景：存储型 XSS 链修复（docs/security/xss_stored_chain_fix_plan.md）。
 * 铁律：
 *   1. 任何 marked.parse 的结果在进入 innerHTML/v-html 之前必须经过
 *      window.secureSanitize；
 *   2. 净化使用 DOMPurify 显式白名单，事件属性（on*）、javascript:/data: URI、
 *      script/iframe/base 等危险标签一律不进白名单；
 *   3. 禁止再新写正则版 sanitizeHtml（黑名单正则永远存在新绕过）。
 *
 * 依赖加载顺序：marked.min.js → purify.min.js → escape.js → 本文件。
 */
(function () {
    'use strict';

    var ALLOWED_TAGS = [
        // markdown 基础
        'p', 'br', 'hr', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'blockquote', 'pre', 'code',
        'ul', 'ol', 'li', 'del', 'em', 'strong', 'b', 'i', 's', 'sup', 'sub',
        'table', 'thead', 'tbody', 'tr', 'th', 'td',
        'a', 'img', 'span', 'div', 'input',
        // 营销 agent 会把裸媒体 URL 转成媒体标签
        'video', 'audio', 'source'
    ];

    var ALLOWED_ATTR = [
        'href', 'src', 'alt', 'title', 'class', 'id', 'target', 'rel',
        'style', 'controls', 'preload', 'type', 'disabled', 'checked',
        // 事件委托改造后承载点击行为的 data 属性（见 migrateLegacyOnclick / 调用方）
        'data-full-src', 'data-modal-src', 'data-tool-id', 'data-tool-title',
        'data-publish-tool-id', 'data-publish-title'
    ];

    // 与 DOMPurify 默认一致的 URI 白名单（http/https/mailto/tel/blob + 相对地址），
    // 显式写出以防默认清单变化；javascript:/vbscript: 一律拒绝。
    // data: URI 由下方 hook 单独收紧（仅放行 data:image/*）。
    var ALLOWED_URI_REGEXP = /^(?:(?:(?:f|ht)tps?|mailto|tel|callto|sms|cid|xmpp|blob):|[^a-z]|[a-z+.\-]+(?:[^a-z+.\-:]|$))/i;

    if (typeof window.DOMPurify === 'undefined') {
        // DOMPurify 未加载时拒绝一切富文本渲染：调用方会走 escapeHtml 降级。
        // 不做静默放行——宁可丢样式，不可放 XSS。
        console.error('[security] DOMPurify 未加载，secureSanitize 将拒绝渲染富文本');
    } else {
        // 收紧 data: URI：DOMPurify 对 img/audio/video 等标签的 data: src 有内部放行
        // 通道（不受 ALLOWED_URI_REGEXP 约束），data:text/html 会被保留。此处仅放行
        // data:image/*（script_writer 存在 base64 图片场景），其余 data:* 一律剥除。
        window.DOMPurify.addHook('uponSanitizeAttribute', function (node, data) {
            if ((data.attrName === 'src' || data.attrName === 'href' || data.attrName === 'xlink:href')
                && /^data:/i.test(data.attrValue)
                && !/^data:image\//i.test(data.attrValue)) {
                data.keepAttr = false;
            }
        });
    }

    /**
     * 净化已解析的 HTML。DOMPurify 不可用时返回空串（调用方需自行降级为纯文本）。
     * 注意：不配置 KEEP_CONTENT:false——jsdom 下它会误删文本节点，且 script/iframe
     * 等标签的内容清除已由 DOMPurify 默认 FORBID_CONTENTS 覆盖，无安全收益。
     */
    window.secureSanitize = function (html) {
        if (typeof window.DOMPurify === 'undefined') return '';
        return window.DOMPurify.sanitize(String(html == null ? '' : html), {
            ALLOWED_TAGS: ALLOWED_TAGS,
            ALLOWED_ATTR: ALLOWED_ATTR,
            ALLOWED_URI_REGEXP: ALLOWED_URI_REGEXP
        });
    };

    /**
     * markdown → 净化 HTML 的唯一入口。
     * 不可用（缺 marked/DOMPurify）时降级为纯文本转义。
     */
    window.secureRenderMarkdown = function (text) {
        var raw = String(text == null ? '' : text);
        if (typeof marked === 'undefined' || typeof window.DOMPurify === 'undefined') {
            return window.escapeHtml ? window.escapeHtml(raw) : raw;
        }
        var html;
        try {
            html = marked.parse(raw);
        } catch (e) {
            return window.escapeHtml ? window.escapeHtml(raw) : raw;
        }
        return window.secureSanitize(html);
    };

    /**
     * 历史存量消息迁移：commit 0bf53fe 之前「生成结果以已渲染 HTML 入库」，其中
     * 点击放大/发布按钮以内联 onclick 实现。净化会剥掉全部 on* 属性，若不迁移，
     * 旧消息的点击放大与发布按钮将失效。本函数在净化【前】调用，把已知的旧
     * onclick 模式（均为 marketing_agent.js 历史版本生成，模式固定）改写为
     * data-* 属性；无法识别的 onclick 直接删除，交由 secureSanitize 兜底。
     *
     * @param {string} html marked.parse 之后的原始 HTML
     * @returns {string} 已迁移的 HTML（仍需 secureSanitize）
     */
    window.migrateLegacyOnclick = function (html) {
        var str = String(html == null ? '' : html);
        if (str.indexOf('onclick=') === -1) return str;

        // 解码 escapeHtmlAttr 产生的实体/转义（旧 onclick 属性值内的呈现形式）
        function unescapeAttrValue(v) {
            return String(v)
                .replace(/&quot;/g, '"')
                .replace(/&#39;/g, "'")
                .replace(/&lt;/g, '<')
                .replace(/&gt;/g, '>')
                .replace(/&amp;/g, '&');
        }

        return str.replace(/\sonclick=(?:"([^"]*)"|'([^']*)')/gi, function (match, dq, sq) {
            var body = unescapeAttrValue(dq !== undefined ? dq : sq);
            var m;

            // 模式A：<img ...> 点击放大（resetModalImageInfo 结尾）
            m = body.match(/^document\.getElementById\('imgModal'\)\.style\.display='flex';document\.getElementById\('imgModalImg'\)\.src='([^']*)';window\.resetModalImageInfo && window\.resetModalImageInfo\(\)$/);
            if (m) {
                return ' data-full-src="' + window.escapeHtml(unescapeAttrValue(m[1])) + '"';
            }

            // 模式B：generated-image-wrapper 点击放大 + 发布信息
            m = body.match(/^document\.getElementById\('imgModal'\)\.style\.display='flex';document\.getElementById\('imgModalImg'\)\.src='([^']*)';window\.setModalImageInfo && window\.setModalImageInfo\('([^']*)',\s*'((?:[^'\\]|\\.)*)'\)$/);
            if (m) {
                return ' data-modal-src="' + window.escapeHtml(unescapeAttrValue(m[1])) + '"'
                    + ' data-tool-id="' + window.escapeHtml(unescapeAttrValue(m[2])) + '"'
                    + ' data-tool-title="' + window.escapeHtml(unescapeAttrValue(m[3].replace(/\\(['\\])/g, '$1'))) + '"';
            }

            // 模式C：发布按钮
            m = body.match(/^event\.stopPropagation\(\); window\.publishGeneratedResult && window\.publishGeneratedResult\(("(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*'),\s*'((?:[^'\\]|\\.)*)'\)$/);
            if (m) {
                var toolId = m[1];
                try { toolId = JSON.parse(m[1]); } catch (e) { /* 保持原值 */ }
                if (typeof toolId !== 'string') toolId = String(toolId == null ? '' : toolId);
                var title = m[2].replace(/\\(['\\])/g, '$1');
                return ' data-publish-tool-id="' + window.escapeHtml(toolId) + '"'
                    + ' data-publish-title="' + window.escapeHtml(unescapeAttrValue(title)) + '"';
            }

            return ''; // 未知模式：删除 onclick，secureSanitize 会再兜底
        });
    };
})();
