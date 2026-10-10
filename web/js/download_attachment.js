/**
 * 附件下载：用 Authorization 头请求 /api/download?format=json，再跳到 CDN 签名地址。
 * <a> / window.open 带不上自定义头，只能靠 HttpOnly cookie；cookie 与 localStorage
 * token 脱节时下载会 401。播放用的 <video>/<audio> src 仍走原来的 302 代理，不经过这里。
 * 登录 token 不放进 URL。
 */
(function (root) {
    function pageOrigin() {
        if (root.location && root.location.origin) return root.location.origin;
        return 'http://localhost';
    }

    function readToken() {
        try {
            if (root.localStorage) return root.localStorage.getItem('auth_token') || '';
        } catch (e) { /* ignore */ }
        return '';
    }

    function authHeaders() {
        const token = readToken();
        if (!token) return {};
        return {
            Authorization: token.indexOf('Bearer ') === 0 ? token : 'Bearer ' + token,
        };
    }

    function unwrapMediaUrl(url) {
        const raw = String(url || '').trim();
        if (!raw) return '';
        if (raw.indexOf('data:') === 0 || raw.indexOf('blob:') === 0) return raw;
        try {
            const parsed = new URL(raw, pageOrigin());
            if (parsed.pathname === '/api/download' || parsed.pathname === '/api/proxy-image') {
                const inner = parsed.searchParams.get('url');
                if (inner) return inner;
            }
            if (parsed.origin === pageOrigin()) {
                return parsed.pathname + parsed.search + parsed.hash;
            }
            return parsed.href;
        } catch (e) {
            return raw;
        }
    }

    function clickAttachment(href, filename) {
        const doc = root.document;
        if (!doc || !doc.body) return;
        const a = doc.createElement('a');
        a.href = href;
        if (filename) a.download = filename;
        a.style.display = 'none';
        doc.body.appendChild(a);
        a.click();
        if (a.remove) a.remove();
        else if (a.parentNode) a.parentNode.removeChild(a);
    }

    function loginRedirect() {
        if (typeof root.redirectToLogin === 'function') {
            root.redirectToLogin();
            return;
        }
        const loc = root.location;
        if (!loc) return;
        const target = (loc.pathname || '') + (loc.search || '');
        loc.href = '/?login=1&redirect_url=' + encodeURIComponent(target);
    }

    async function downloadWithAuth(url, filename, options) {
        const opts = options || {};
        const safeName = filename || 'download';
        const target = unwrapMediaUrl(url);
        if (!target) return;

        if (target.indexOf('data:') === 0 || target.indexOf('blob:') === 0) {
            clickAttachment(target, safeName);
            return;
        }
        if (target.charAt(0) === '/' && target.indexOf('/api/') !== 0) {
            clickAttachment(target, safeName);
            return;
        }

        const apiUrl = '/api/download?url=' + encodeURIComponent(target)
            + '&filename=' + encodeURIComponent(safeName)
            + '&format=json';
        const resp = await fetch(apiUrl, { headers: authHeaders() });
        const contentType = (resp.headers && resp.headers.get('content-type')) || '';
        if (contentType.indexOf('application/json') !== -1 || !resp.ok) {
            const data = await resp.json().catch(function () { return {}; });
            if (resp.status === 401) {
                if (typeof opts.onUnauthorized === 'function') opts.onUnauthorized();
                else loginRedirect();
                const error = new Error(data.error || '登录已过期');
                error.status = 401;
                error.code = data.error_code || '';
                throw error;
            }
            if (!resp.ok || data.success === false) {
                const error = new Error(data.error || data.message || ('下载失败 HTTP ' + resp.status));
                error.status = resp.status;
                throw error;
            }
            if (!data.redirect_url) {
                throw new Error('下载地址为空');
            }
            if (root.location && typeof root.location.assign === 'function') {
                root.location.assign(data.redirect_url);
            }
            return;
        }

        const blob = await resp.blob();
        const blobUrl = URL.createObjectURL(blob);
        clickAttachment(blobUrl, safeName);
        setTimeout(function () { URL.revokeObjectURL(blobUrl); }, 1000);
    }

    const api = { downloadWithAuth: downloadWithAuth, unwrapMediaUrl: unwrapMediaUrl };
    if (typeof module !== 'undefined' && module.exports) module.exports = api;
    root.downloadWithAuth = downloadWithAuth;
    root.unwrapMediaUrl = unwrapMediaUrl;
})(typeof window !== 'undefined' ? window : globalThis);
