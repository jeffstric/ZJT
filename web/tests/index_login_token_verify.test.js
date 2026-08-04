import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const root = path.resolve(import.meta.dirname, '../..');
const readSource = (relativePath) => fs.readFileSync(path.join(root, relativePath), 'utf8');

describe('index login=1 主动校验 token（误报不再清登录态）', () => {
    const appSource = readSource('web/js/index_app.js');

    it('login=1 分支不再无条件清除 localStorage', () => {
        // 截取 login=1 处理块（到 redirect_after_login 记录结束）
        const match = appSource.match(/if \(urlParams\.get\('login'\) === '1'\) \{[\s\S]*?\n      \}/);
        expect(match).not.toBeNull();
        expect(match[0]).not.toContain("localStorage.removeItem('auth_token')");
        expect(match[0]).toContain('redirect_after_login');
    });

    it('本地有 token 时触发主动校验', () => {
        expect(appSource).toContain("if (urlParams.get('login') === '1' && this.authToken)");
        expect(appSource).toContain('this.verifyAuthTokenOnLoginEntry()');
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
