import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const root = path.resolve(import.meta.dirname, '../..');
const readSource = (relativePath) => fs.readFileSync(path.join(root, relativePath), 'utf8');

describe('index login=1 主动校验 token（误报不再清登录态）', () => {
    const appSource = readSource('web/js/index_app.js');

    it('login=1 且有 token 时走主动校验，不在 mounted 无条件清 localStorage', () => {
        expect(appSource).toContain("if (urlParams.get('login') === '1' && this.authToken)");
        expect(appSource).toContain('this.verifyAuthTokenOnLoginEntry()');
        const mountedMatch = appSource.match(/if \(urlParams\.get\('login'\) === '1' && this\.authToken\) \{[\s\S]*?\n      \}/);
        expect(mountedMatch).not.toBeNull();
        expect(mountedMatch[0]).not.toContain("localStorage.removeItem('auth_token')");
    });

    it('兼容期登录双写同一 token 到 localStorage', () => {
        expect(appSource).toContain('persistBrowserAuth');
        const persistMatch = appSource.match(/persistBrowserAuth\(data\) \{[\s\S]*?\n      \}/);
        expect(persistMatch).not.toBeNull();
        expect(persistMatch[0]).toContain("localStorage.setItem('auth_token', token)");
        expect(appSource).toContain('this.persistBrowserAuth(response.data.data)');
    });

    it('cookie 有效但无 localStorage token 时强制重新登录', () => {
        const probeMatch = appSource.match(/async probeCookieSession\(onInvalid = null\) \{[\s\S]*?\n      \}/);
        expect(probeMatch).not.toBeNull();
        expect(probeMatch[0]).toContain('auth_compat_relogin');
        expect(probeMatch[0]).toContain("localStorage.removeItem('logged_in')");
        expect(probeMatch[0]).not.toContain("localStorage.setItem('logged_in', '1')");
    });

    it('主动校验只在确证失效（401 + error_code）时清理', () => {
        expect(appSource).toContain("code === 'invalid_auth_token' || code === 'TOKEN_EXPIRED'");
        // 校验请求只带 Authorization，请求头中不发送 X-User-Id（避免服务端本地兜底掩盖 401）
        const fnMatch = appSource.match(/async verifyAuthTokenOnLoginEntry\(\) \{[\s\S]*?\n      \}/);
        expect(fnMatch).not.toBeNull();
        expect(fnMatch[0]).not.toContain("'X-User-Id'");
        expect(fnMatch[0]).toContain('this.clearLocalAuthInfo()');
    });
});
