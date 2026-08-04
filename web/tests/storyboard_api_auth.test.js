import { describe, it, expect, beforeEach, vi } from 'vitest';
import { handleAuthError } from '../js/storyboard/api.js';

// jsdom 不支持页面跳转，赋值 location.href 只会打印 "Not implemented: navigation"，不会抛错
describe('storyboard handleAuthError 分级处理', () => {
    beforeEach(() => {
        localStorage.clear();
        vi.stubGlobal('alert', vi.fn());
    });

    it('确证失效（TOKEN_EXPIRED）：清 token + alert + 跳转，返回 true', () => {
        localStorage.setItem('auth_token', 't1');
        const handled = handleAuthError(401, { error_code: 'TOKEN_EXPIRED' });
        expect(handled).toBe(true);
        expect(localStorage.getItem('auth_token')).toBeNull();
        expect(alert).toHaveBeenCalled();
    });

    it('确证失效（invalid_auth_token）：清 token，返回 true', () => {
        localStorage.setItem('auth_token', 't1');
        const handled = handleAuthError(401, { error_code: 'invalid_auth_token' });
        expect(handled).toBe(true);
        expect(localStorage.getItem('auth_token')).toBeNull();
    });

    it('确证失效（token_expired 标志位，非 401 状态也生效）', () => {
        localStorage.setItem('auth_token', 't1');
        const handled = handleAuthError(400, { token_expired: true });
        expect(handled).toBe(true);
        expect(localStorage.getItem('auth_token')).toBeNull();
    });

    it('缺 token（missing_auth_token）但本地仍有 token：不清不跳，返回 false', () => {
        localStorage.setItem('auth_token', 'still-valid');
        const handled = handleAuthError(401, { error_code: 'missing_auth_token' });
        expect(handled).toBe(false);
        expect(localStorage.getItem('auth_token')).toBe('still-valid');
        expect(alert).not.toHaveBeenCalled();
    });

    it('无可识别 code 的 401 且本地有 token：不清不跳（误报保护）', () => {
        localStorage.setItem('auth_token', 'still-valid');
        const handled = handleAuthError(401, { message: 'some error' });
        expect(handled).toBe(false);
        expect(localStorage.getItem('auth_token')).toBe('still-valid');
    });

    it('401 且本地无 token：跳转登录，返回 true', () => {
        const handled = handleAuthError(401, { error_code: 'missing_auth_token' });
        expect(handled).toBe(true);
    });

    it('非 401 且无失效标记：不处理，返回 false', () => {
        localStorage.setItem('auth_token', 't1');
        expect(handleAuthError(500, {})).toBe(false);
        expect(handleAuthError(502, { error_code: 'AUTH_SERVICE_UNAVAILABLE' })).toBe(false);
        expect(localStorage.getItem('auth_token')).toBe('t1');
    });
});
