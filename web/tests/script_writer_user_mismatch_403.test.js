import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it, vi } from 'vitest';

const root = path.resolve(import.meta.dirname, '../..');
const readSource = (relativePath) => fs.readFileSync(path.join(root, relativePath), 'utf8');

// 回归背景（2026-11-14）：分享链接带他人 user_id 打开 script-writer 时，
// 后端 query 参数身份校验（check_claimed_user_id）返回 403 + error_code=user_mismatch，
// 而前端 checkTokenExpired 只在 response.status === 401 分支里判 user_mismatch，
// 403 响应被完全忽略——页面停在无权状态，不跳转不自愈。
// 修复：user_mismatch 判断提前为独立分支，401/403 一律走 handleUserMismatch。
describe('script_writer user_mismatch 403 self heal', () => {
    const source = readSource('web/js/script_writer.js');

    const fnStart = source.indexOf('function handleUserMismatch');
    const checkStart = source.indexOf('function checkTokenExpired');
    const checkEnd = source.indexOf('const carouselState');

    it('源码包含身份错误处理三件套', () => {
        expect(fnStart).toBeGreaterThan(-1);
        expect(checkStart).toBeGreaterThan(fnStart);
        expect(checkEnd).toBeGreaterThan(checkStart);
    });

    it('user_mismatch 判断独立于 401 分支（403 也触发）', () => {
        const checkBody = source.slice(checkStart, checkEnd);
        // user_mismatch 判断必须在 401 判断之前，且不再嵌在 401 分支内部
        const mismatchIdx = checkBody.indexOf("data.error_code === 'user_mismatch'");
        const status401Idx = checkBody.indexOf('response.status === 401');
        expect(mismatchIdx).toBeGreaterThan(-1);
        expect(status401Idx).toBeGreaterThan(-1);
        expect(mismatchIdx).toBeLessThan(status401Idx);
        expect(checkBody).toContain('handleUserMismatch()');
    });

    it('403 user_mismatch 走 handleUserMismatch 跳首页（行为级验证）', () => {
        const alertSpy = vi.fn();
        vi.stubGlobal('alert', alertSpy);
        const hrefSetter = vi.fn();
        // jsdom 下 location.href 赋值受保护，用 defineProperty 拦截
        Object.defineProperty(window, 'location', {
            value: {
                href: '',
                origin: 'http://127.0.0.1:13008',
                pathname: '/script-writer',
                search: '?user_id=2',
                set href(v) { hrefSetter(v); },
                get href() { return ''; },
            },
            writable: true,
        });

        // 提取闭包内三个函数（连同防重入标志）做行为验证；
        // LOGIN_URL 是同闭包外层常量，测试内补桩
        const snippet = `
            const LOGIN_URL = 'http://127.0.0.1:13008/?login=1';
            let tokenExpiredHandled = false;
            let userMismatchHandled = false;
            ${source.slice(source.indexOf('function handleUserMismatch'), checkEnd)}
            return { checkTokenExpired };
        `;
        const factory = new Function('window', snippet);
        const { checkTokenExpired } = factory(window);

        // 403 + user_mismatch（query 参数身份不一致的实际响应）
        const handled403 = checkTokenExpired(
            { success: false, error_code: 'user_mismatch', error: 'user_id 与当前登录用户不一致' },
            { status: 403 },
        );
        expect(handled403).toBe(true);
        expect(alertSpy).toHaveBeenCalledTimes(1);
        expect(hrefSetter).toHaveBeenCalledWith('http://127.0.0.1:13008/');

        // 401 + user_mismatch（X-User-Id 头不一致）仍走同一处理，且防重入
        const handled401 = checkTokenExpired(
            { success: false, error_code: 'user_mismatch' },
            { status: 401 },
        );
        expect(handled401).toBe(true);
        expect(alertSpy).toHaveBeenCalledTimes(1);

        // 401 无 error_code → token 过期语义（不清 userMismatch 分支的账）
        expect(checkTokenExpired(null, { status: 401 })).toBe(true);

        vi.unstubAllGlobals();
    });

    it('初始化链路的身份请求接入 checkTokenExpired', () => {
        // loadUserWorlds：X-User-Id 头不一致 → 401/403，此前只显示「加载失败」
        const worldsStart = source.indexOf('async function loadUserWorlds');
        const worldsBody = source.slice(worldsStart, source.indexOf('async function toggleDeletedWorldsView'));
        expect(worldsBody).toContain('checkTokenExpired');

        // loadWorldDefaultModels：user_id query 不一致 → 403，此前静默失败
        const defaultsStart = source.indexOf('async function loadWorldDefaultModels');
        const defaultsBody = source.slice(defaultsStart, source.indexOf('async function setWorldDefaultLlmFromSelector'));
        expect(defaultsBody).toContain('checkTokenExpired');

        // 会话复用（initOrReuseSession）：/api/sessions?user_id= 是 403 user_mismatch 的直接来源
        const initStart = source.indexOf('async function initOrReuseSession');
        const initBody = source.slice(initStart, initStart + 900);
        expect(initBody).toContain('checkTokenExpired');
    });
});
