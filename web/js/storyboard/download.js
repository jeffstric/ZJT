/**
 * 附件下载工具：走 /api/download 代理，绕过浏览器弹窗拦截器。
 *
 * 为什么不能直接用七牛 CDN URL + a.click()？
 * 1. storyboard 导出返回的 download_url 是七牛私有桶的「已签名 URL」（带 ?e=...&token=...）。
 *    若前端在已签名 URL 上追加 ?attname=xxx，七牛会判定签名不匹配 → 401/400。
 * 2. 若直接 a.href=<已签名URL> 且 a.target='_blank'，浏览器跨域时会忽略 download 属性，
 *    变成「打开新 tab」；而新 tab 会被弹窗拦截器拦掉，用户根本下不到文件。
 *
 * 正确做法：走同源的 /api/download?url=<已签名URL>&filename=<name> 代理。
 *   后端 server.py 的 /api/download 检测到 CDN URL → 调 CDNUtil.get_signed_download_url
 *   （attname 参与新签名）→ 302 重定向到合法的 attachment URL。
 *   浏览器识别 Content-Disposition: attachment 后「原地下载」，不开新 tab、不触发弹窗拦截。
 */
export function downloadAsAttachment(url, filename) {
    if (!url) return;
    const safeName = filename || 'download';
    const apiUrl = `/api/download?url=${encodeURIComponent(url)}&filename=${encodeURIComponent(safeName)}`;
    const a = document.createElement('a');
    a.href = apiUrl;
    a.download = safeName; // 同源兜底（本接口是同源，实际由后端 302 + attachment 头触发下载）
    // 不设 a.target：避免触发新 tab / 弹窗拦截器
    document.body.appendChild(a);
    a.click();
    a.remove();
}
