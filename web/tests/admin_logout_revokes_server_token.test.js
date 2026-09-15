import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const root = path.resolve(import.meta.dirname, '../..');
const readSource = (relativePath) => fs.readFileSync(path.join(root, relativePath), 'utf8');

// 回归背景：admin 页"退出"曾只清 localStorage，不调 /api/auth/logout，
// 导致服务端 token 未吊销（登出后原 token 仍可调用接口）且 HttpOnly cookie 残留。
describe('admin logout revokes server token', () => {
    it('admin logout calls /api/auth/logout before clearing local state', () => {
        const source = readSource('web/js/admin.js');
        const logoutBody = source.slice(source.indexOf('async logout()'), source.indexOf('async logout()') + 1600);
        expect(logoutBody).toContain('/api/auth/logout');
        // 显式带 Authorization（与 admin.js 其余调用一致），cookie 会话由服务端翻译兜底
        expect(logoutBody).toContain('Authorization');
        // 本地清理保留：auth_token / logged_in 相关键的旧 key 也要清
        expect(logoutBody).toContain("localStorage.removeItem('auth_token')");
        expect(logoutBody).toContain("localStorage.removeItem('admin_mode')");
        expect(logoutBody).toContain("window.location.href = '/'");
    });

    it('backend logout deletes token row and clears auth cookie', () => {
        const authService = readSource('perseids_server/services/auth_service.py');
        expect(authService).toMatch(/def logout\(token[\s\S]*?UserTokensModel\.delete_by_token\(token\)/);
        const server = readSource('server.py');
        expect(server).toContain('delete_cookie(key=AUTH_COOKIE_NAME');
    });
});
