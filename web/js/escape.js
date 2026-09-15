/**
 * escape.js — HTML 转义函数唯一权威实现（全站公共）。
 *
 * 背景：代码库曾散落 13+ 份互不一致的 escapeHtml 副本（部分漏转单引号，
 * 在属性上下文可被逃逸，见 docs/security/xss_stored_chain_fix_plan.md）。
 * 现已收敛到本文件；新增转义需求一律修改这里，禁止再拷贝副本
 * （CI scripts/lint_frontend_xss.py 会拦截新增定义）。
 *
 * 注意：marketing_agent.js 中的 escapeHtmlAttr 是「JS 字符串字面量」转义器
 * （额外转义反斜杠/换行，用于往内联事件里嵌值），语义不同，勿与之混淆。
 */
(function () {
    'use strict';

    var ESCAPE_MAP = {
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#39;'
    };

    /**
     * HTML 文本转义：用于元素文本内容与双引号属性值。
     * 五个 HTML 敏感字符全部转义，单引号一并处理，属性上下文安全。
     */
    function escapeHtml(value) {
        if (value === null || value === undefined) return '';
        return String(value).replace(/[&<>"']/g, function (m) {
            return ESCAPE_MAP[m];
        });
    }

    /** escapeHtml 的别名，语义等价；保留独立名字以便调用点自解释。 */
    function escapeHtmlAttr(value) {
        return escapeHtml(value);
    }

    window.escapeHtml = escapeHtml;
    window.escapeHtmlAttr = escapeHtmlAttr;
})();
