/**
 * qr_code.js — 支付二维码生成唯一权威实现（全站公共）。
 *
 * 背景：此前各支付入口直接把微信 code_url 拼给第三方公共服务
 * api.qrserver.com 渲染二维码图片；该服务托管在海外且无 SLA，
 * 部分用户网络无法访问导致二维码裂图、无法付款（线上事故）。
 * 现统一改为浏览器本地生成（依赖 /js/vendor/qrcode-generator.js，
 * Kazuhiko Arase, MIT），不再依赖任何外部网络请求；
 * 仅在本地生成异常（如库未加载）时降级回第三方服务，保证可用性。
 *
 * 注意：新增支付二维码入口一律调用 window.buildPaymentQrUrl，
 * 禁止再直接引用 api.qrserver.com（web/tests/payment_qrcode_local.test.js 会拦截）。
 */
(function () {
    'use strict';

    var FALLBACK_BASE = 'https://api.qrserver.com/v1/create-qr-code/';

    /**
     * 生成微信支付二维码图片地址。
     * @param {string} text 微信支付 code_url（weixin://wxpay/bizpayurl?...）
     * @param {number} [size=280] 目标边长（像素）
     * @returns {string} 本地生成的 data:image/gif URL；本地生成失败时降级为第三方服务 URL
     */
    function buildPaymentQrUrl(text, size) {
        var target = Number(size) > 0 ? Math.floor(Number(size)) : 280;
        var value = String(text == null ? '' : text);
        try {
            if (typeof qrcode !== 'function') {
                throw new Error('qrcode-generator not loaded');
            }
            var qr = qrcode(0, 'M');
            qr.addData(value);
            qr.make();
            // 静区（quiet zone）4 模块，扫码枪/手机识别需要
            var cells = qr.getModuleCount() + 8;
            var cellSize = Math.max(2, Math.floor(target / cells));
            return qr.createDataURL(cellSize, 4);
        } catch (err) {
            console.warn('[qr_code] 本地二维码生成失败，降级为第三方服务:', err);
            return FALLBACK_BASE + '?size=' + target + 'x' + target + '&data=' + encodeURIComponent(value);
        }
    }

    window.buildPaymentQrUrl = buildPaymentQrUrl;
})();
