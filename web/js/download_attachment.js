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

    function absoluteUrl(url) {
        try {
            return new URL(url, pageOrigin()).href;
        } catch (e) {
            return url;
        }
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

    const IMAGE_EXT_RE = /\.(png|jpe?g|gif|webp|bmp|tiff?)$/i;

    /**
     * 下载文件名保证带图片扩展名。name 本身已带扩展名时原样返回；
     * 否则从 URL 路径段提取扩展名（忽略查询串与锚点），仍取不到时用
     * fallbackExt 兜底。背景：图片节点生成结果名（"生成结果1"）无后缀，
     * CDN attname 原样透传会下载出无扩展名的文件。
     */
    function ensureDownloadExtension(name, url, fallbackExt) {
        const base = String(name || '').trim();
        if (base && IMAGE_EXT_RE.test(base)) return base;
        const pathPart = String(url || '').split('#')[0].split('?')[0];
        const m = IMAGE_EXT_RE.exec(pathPart);
        const ext = m ? m[1].toLowerCase() : (fallbackExt || 'png');
        return (base || 'image') + '.' + ext;
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
        // /upload/ 媒体不能 <a download> 直下：cdn_redirect_middleware 会把它
        // 302 到跨域 CDN，download 属性跨域重定向后失效，浏览器直接导航展示
        // （图片节点上传图点下载变成打开标签页即此因）。改走 /api/download
        // 重签名通道，由后端签出带 attname 的 CDN 地址强制附件下载。
        // 其中 /upload/cache/ 保持相对路径（后端本地文件分支按前缀识别，
        // FileResponse 自带 attachment 头，省一次代理）；其余 /upload/ 传绝对
        // URL，后端才能改写为 CDN 域名重签名。
        if (target.charAt(0) === '/' && target.indexOf('/api/') !== 0
                && target.indexOf('/upload/') !== 0) {
            clickAttachment(target, safeName);
            return;
        }

        // /upload/cache/ 保持相对路径：后端本地文件分支按该前缀识别并直接
        // FileResponse 返回（自带 attachment 头）；其余 /upload/ 必须绝对
        // URL，后端才能改写为 CDN 域名重签名。
        const apiTarget = (target.charAt(0) === '/'
            && target.indexOf('/upload/cache/') !== 0) ? absoluteUrl(target) : target;
        const apiUrl = '/api/download?url=' + encodeURIComponent(apiTarget)
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

    const api = {
        downloadWithAuth: downloadWithAuth,
        unwrapMediaUrl: unwrapMediaUrl,
        ensureDownloadExtension: ensureDownloadExtension,
    };
    if (typeof module !== 'undefined' && module.exports) module.exports = api;
    root.downloadWithAuth = downloadWithAuth;
    root.unwrapMediaUrl = unwrapMediaUrl;
    root.ensureDownloadExtension = ensureDownloadExtension;
})(typeof window !== 'undefined' ? window : globalThis);
