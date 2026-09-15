# 上传媒体文件安全校验（防存储型 XSS / 资源滥用）

## 背景

安全审计 P0：`/api/video-workflow/upload` 曾只校验 Content-Type 前缀
（客户端可任意伪造），且落盘文件保留用户扩展名、无大小上限。
攻击者上传改名为 `.png` 的 `poc.html`（Content-Type 填 `image/png`）即可
落盘 `upload/workflow/<uid>/xxx.html`，经 StaticFiles 以 `text/html` 同域返回，
形成存储型 XSS；GB 级上传还会打满内存/磁盘并触发七牛 CDN 成本滥用。

同型风险端点（`/api/image-to-video/upload-media`、`_save_uploaded_image`
服务的生成类接口）已一并收口。

## 防线（纵深）

| 层级 | 位置 | 说明 |
| --- | --- | --- |
| token 校验 | `server.py` upload 端点 | `Authorization` 必须是有效 token 且归属与 `X-User-Id` 一致（uid 头可伪造，落盘目录按 uid 隔离且文件永久保留） |
| Content-Type 初筛 | `server.py` upload 端点 | 仅作快速拒绝（image/\|video/\|audio/ 前缀），不作为可信依据 |
| 扩展名白名单 | `utils/media_upload.py` `resolve_media_extension()` | 白名单见 `config/constant.py` `MediaUploadSafetyConstants`；`.html/.htm/.svg/.xhtml/.xml/.js/.mjs/.css` 显式拒绝并返回针对性提示 |
| 魔数校验 | `utils/media_upload.py` `save_upload_chunked()` | 按扩展名校验文件头前 32 字节（PNG/JPEG/RIFF 容器/ftyp/EBML/ID3 等），伪造扩展名的 HTML 一律拒绝 |
| 大小上限 | 同上 | 分块（1MB）读取累计字节数，超限立即中断并清理半成品：图片 10MB、视频 200MB、音频 50MB |
| nosniff 兜底 | `server.py` `cdn_redirect_middleware` | `/upload/` 静态响应统一带 `X-Content-Type-Options: nosniff`，禁止浏览器 MIME 嗅探（nginx 侧可再叠加同款头） |

## 接入方式

新端点接收用户上传媒体文件时，不要手写 `file.read()` + 落盘，统一走：

```python
from utils.media_upload import (
    UploadValidationError, resolve_media_extension, save_upload_chunked,
)

ext = resolve_media_extension(upload_file.filename)   # 白名单
info = generate_upload_filename(prefix, ext)
file_path = os.path.join(asset_dir, info.filename)
save_upload_chunked(upload_file, file_path, ext)      # 魔数 + 分块限流
# 在 asyncio 端点中用 await asyncio.to_thread(...) 包裹同步保存
```

`UploadValidationError` 是 `ValueError` 子类，端点层 `except` 后映射
HTTP 400，message 可直接透出给用户。

## 测试

`tests/utils/test_media_upload.py`：覆盖白名单/黑名单/双扩展名、伪造魔数
（`poc.png` 实为 HTML）、超限清理半成品、多块完整写入等 46 例。

## 运维建议

- nginx 对 `/upload/` 叠加 `X-Content-Type-Options: nosniff`（应用层已带，双保险）。
- 新增允许的媒体格式时，同步更新 `MediaUploadSafetyConstants` 白名单与
  `utils/media_upload.py` 的 `_MAGIC_CHECKS` 魔数表（两者键需保持一致），
  并补充测试用例。
