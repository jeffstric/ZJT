/**
 * 附件下载：先带 Authorization 头向 /api/download?format=json 取重签名地址，
 * 再跳到 CDN。不能用 <a href> 打开 /api/download——那种跳转带不上自定义请求头，
 * 只能靠 HttpOnly cookie。cookie 与 localStorage.auth_token 脱节（例如管理端
 * 切换用户只改了 localStorage）时，cookie 里的旧 token 会让下载 401，
 * 而页面其余接口仍用 localStorage 的有效 token 返回 200。
 *
 * CDN 签名 URL 自带存储签名，不把登录 auth_token 放进任何 URL。
 * 不把文件读进 JS，大文件由浏览器按 Content-Disposition: attachment 流式下载。
 */
import { authHeaders, handleAuthError } from './api.js';

export async function downloadAsAttachment(url, filename) {
    if (!url) return;
    const safeName = filename || 'download';
    const apiUrl = `/api/download?url=${encodeURIComponent(url)}&filename=${encodeURIComponent(safeName)}&format=json`;
    const resp = await fetch(apiUrl, { headers: authHeaders(false) });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok || data.success === false) {
        handleAuthError(resp.status, data);
        const error = new Error(data.error || data.message || `下载失败 HTTP ${resp.status}`);
        error.status = resp.status;
        error.code = data.error_code || '';
        throw error;
    }
    if (!data.redirect_url) {
        throw new Error('下载地址为空');
    }
    window.location.assign(data.redirect_url);
}
