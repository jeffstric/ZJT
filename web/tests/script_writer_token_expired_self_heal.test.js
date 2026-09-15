import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const root = path.resolve(import.meta.dirname, '../..');
const readSource = (relativePath) => fs.readFileSync(path.join(root, relativePath), 'utf8');

// 回归背景：script-writer 页面 token 失效时，init 并发的 7+ 个请求各自触发
// handleTokenExpired（裸 alert + 跳转登录页），连环弹窗且反复重设跳转目标，
// 把刚登录成功的用户又拽回登录页；同时 localStorage 残留的失效 Bearer 压住
// 服务端 cookie 翻译（仅 Authorization 为空时翻译），cookie 会话无法自愈。
describe('script_writer token expired self heal', () => {
    const source = readSource('web/js/script_writer.js');
    const handlerStart = source.indexOf('async function handleTokenExpired');
    const handlerBody = source.slice(handlerStart, source.indexOf('function checkTokenExpired'));

    it('handleTokenExpired guards against concurrent 401 re-entry', () => {
        expect(handlerStart).toBeGreaterThan(-1);
        expect(source).toContain('let tokenExpiredHandled = false');
        expect(handlerBody).toContain('if (tokenExpiredHandled)');
        expect(handlerBody).toContain('tokenExpiredHandled = true');
    });

    it('clears stale localStorage token before cookie session probe', () => {
        // 失效 token 以非空 Bearer 发出会绕过 cookie 翻译中间件，必须先清掉
        expect(handlerBody).toContain("localStorage.removeItem('auth_token')");
        expect(handlerBody).toContain("localStorage.removeItem('token')");
        // 探测不带 Authorization 头（浏览器自动带 HttpOnly cookie，由服务端翻译）
        expect(handlerBody).toContain("fetch('/api/user/role'");
        expect(handlerBody).not.toMatch(/fetch\('\/api\/user\/role'[^)]*Authorization/);
    });

    it('reloads to self-heal when cookie session is still valid', () => {
        expect(handlerBody).toContain('window.location.reload()');
        // 60 秒内只自愈一次，避免极端情况下 reload 循环
        expect(handlerBody).toContain('script_writer_cookie_heal_at');
    });

    it('falls back to single alert and login redirect when cookie is dead', () => {
        expect(handlerBody).toContain('alert_login_expired');
        expect(handlerBody).toContain('window.location.href = LOGIN_URL');
        // 登录跳转带回当前页（含 user_id/world_id/workflow_id 参数）
        expect(source).toContain("encodeURIComponent(window.location.pathname + window.location.search)");
    });
});
