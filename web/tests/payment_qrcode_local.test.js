/**
 * 支付二维码本地生成（替换 api.qrserver.com 第三方依赖）。
 *
 * 背景：原先 8 处支付入口直接把微信 code_url 拼给海外公共服务
 * api.qrserver.com 渲染二维码，部分用户网络无法访问导致裂图、无法付款。
 * 现统一走 window.buildPaymentQrUrl（web/js/qr_code.js）浏览器本地生成。
 *
 * 契约：
 * - 正常路径：返回 data:image/gif 本地 URL，不含 qrserver
 * - 降级路径：qrcode-generator 未加载等异常时，回退 qrserver URL 保证可用
 * - 所有支付入口禁止直接引用 api.qrserver.com（本文件静态断言拦截）
 * - 使用方页面必须先于使用脚本引入 /js/vendor/qrcode-generator.js 与 /js/qr_code.js
 */
import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const root = path.resolve(import.meta.dirname, '../..');
const vendorSource = fs.readFileSync(path.join(root, 'web/js/vendor/qrcode-generator.js'), 'utf8');
const wrapperSource = fs.readFileSync(path.join(root, 'web/js/qr_code.js'), 'utf8');

// 在隔离沙箱中加载 vendor 库 + 封装（与浏览器经典脚本等价：顶层 var qrcode 暴露给后续代码）
function loadBuildPaymentQrUrl({ withVendor = true } = {}) {
    const sandbox = { window: {}, console, encodeURIComponent };
    const src = (withVendor ? vendorSource + '\n' : '') + wrapperSource;
    const factory = new Function('window', 'console', 'encodeURIComponent', src);
    factory(sandbox.window, console, encodeURIComponent);
    return sandbox.window.buildPaymentQrUrl;
}

const SAMPLE_CODE_URL = 'weixin://wxpay/bizpayurl?pr=5QQN8rWkMN3hpLod';

describe('buildPaymentQrUrl 本地生成', () => {
    it('返回本地 data URL，不再请求 qrserver', () => {
        const build = loadBuildPaymentQrUrl();
        const url = build(SAMPLE_CODE_URL, 280);
        expect(url.startsWith('data:image/gif;base64,')).toBe(true);
        expect(url).not.toContain('qrserver');
    });

    it('默认尺寸 280，显式尺寸生效且输出随尺寸缩放', () => {
        const build = loadBuildPaymentQrUrl();
        const def = build(SAMPLE_CODE_URL);
        const big = build(SAMPLE_CODE_URL, 560);
        expect(def.startsWith('data:image/gif;base64,')).toBe(true);
        expect(big.length).toBeGreaterThan(def.length);
    });

    it('中文等 UTF-8 内容也能生成', () => {
        const build = loadBuildPaymentQrUrl();
        expect(build('测试中文内容', 200).startsWith('data:image/gif;base64,')).toBe(true);
    });

    it('库未加载时降级为 qrserver URL，不抛异常', () => {
        const build = loadBuildPaymentQrUrl({ withVendor: false });
        const url = build(SAMPLE_CODE_URL, 280);
        expect(url).toContain('https://api.qrserver.com/v1/create-qr-code/?size=280x280&data=');
        expect(url).toContain(encodeURIComponent(SAMPLE_CODE_URL));
    });
});

describe('支付入口不再直接引用 api.qrserver.com', () => {
    const callSites = [
        'web/js/index_app.js',
        'web/js/recharge_center.js',
        'web/js/marketing_agent.js',
        'web/js/script_writer.js',
        'web/js/storyboard/events.js',
        'web/video_workflow.html',
    ];

    it.each(callSites)('%s 不直接引用 qrserver', (rel) => {
        const src = fs.readFileSync(path.join(root, rel), 'utf8');
        expect(src).not.toContain('api.qrserver.com');
    });

    it('qrserver 仅存于 qr_code.js 的降级分支', () => {
        const expectNoQrserver = ['web/js/index_app.js', 'web/js/recharge_center.js'];
        for (const rel of expectNoQrserver) {
            expect(fs.readFileSync(path.join(root, rel), 'utf8')).not.toContain('qrserver');
        }
        const wrapper = fs.readFileSync(path.join(root, 'web/js/qr_code.js'), 'utf8');
        expect(wrapper).toContain('api.qrserver.com');
        expect(wrapper).toContain('window.buildPaymentQrUrl');
    });

    const pages = [
        'web/index.html',
        'web/marketing_agent.html',
        'web/script_writer.html',
        'web/storyboard.html',
        'web/video_workflow.html',
    ];

    it.each(pages)('%s 先引入 qrcode-generator.js 与 qr_code.js，再引入使用方脚本', (rel) => {
        const html = fs.readFileSync(path.join(root, rel), 'utf8');
        const vendorIdx = html.indexOf('/js/vendor/qrcode-generator.js');
        const wrapperIdx = html.indexOf('/js/qr_code.js');
        expect(vendorIdx).toBeGreaterThan(-1);
        expect(wrapperIdx).toBeGreaterThan(vendorIdx);
        // 使用方脚本必须在 qr_code.js 之后加载
        for (const user of ['/js/index_app.js', '/js/recharge_center.js']) {
            const userIdx = html.indexOf(user);
            if (userIdx > -1) expect(userIdx).toBeGreaterThan(wrapperIdx);
        }
    });
});
