# 上传媒体文件安全校验（防存储型 XSS / 资源滥用）

## 背景

安全审计 P0：`/api/video-workflow/upload` 曾只校验 Content-Type 前缀
（客户端可任意伪造），且落盘文件保留用户扩展名、无大小上限。
攻击者上传改名为 `.png` 的 `poc.html`（Content-Type 填 `image/png`）即可
落盘 `upload/workflow/<uid>/xxx.html`，经 StaticFiles 以 `text/html` 同域返回，
形成存储型 XSS；GB 级上传还会打满内存/磁盘并触发七牛 CDN 成本滥用。

同型风险端点（`/api/image-to-video/upload-media`、`_save_uploaded_image`
服务的生成类接口）已一并收口。

2026-10 二轮审计（BUG-R2-S2-A5-H1，CVSS 9.3）：characters/locations/props
参考图 12 处落盘点（含 `POST /api/{characters,locations}/{id}/reference-images`
及 create/update 主图与多图字段）当时仅做大小校验、扩展名完全由客户端控制，
`.html/.svg` 落盘后经同一 StaticFiles 挂载以 `text/html` 同域返回，构成
匿名存储型 XSS。已通过在 `_validate_image_size`（12 处落盘点的唯一校验
入口）统一追加 `resolve_media_extension` 白名单 + `check_media_magic`
魔数校验收口（server.py），tif/tiff 放行后仍走原有落盘后 PNG 归一化。

## 防线（纵深）

| 层级 | 位置 | 说明 |
| --- | --- | --- |
| token 校验 | `server.py` upload 端点 | `Authorization` 必须是有效 token 且归属与 `X-User-Id` 一致（uid 头可伪造，落盘目录按 uid 隔离且文件永久保留） |
| Content-Type 初筛 | `server.py` upload 端点 | 仅作快速拒绝（image/\|video/\|audio/ 前缀），不作为可信依据 |
| 扩展名白名单 | `utils/media_upload.py` `resolve_media_extension()` | 白名单见 `config/constant.py` `MediaUploadSafetyConstants`；`.html/.htm/.svg/.xhtml/.xml/.js/.mjs/.css` 显式拒绝并返回针对性提示 |
| 魔数校验 | `utils/media_upload.py` `save_upload_chunked()` / `check_media_magic()` | 按扩展名校验文件头前 32 字节（PNG/JPEG/RIFF 容器/ftyp/EBML/ID3/TIFF 双字节序 `II*\x00`/`MM\x00*` 等），伪造扩展名的 HTML 一律拒绝；`check_media_magic` 供已持有文件内容的调用方（`_validate_image_size`）复用 |
| TIFF 归一化 | `utils/media_upload.py` `convert_tiff_file_to_png()` | tif/tiff 落盘后立即转 PNG 并删除原文件（见下节），`/upload/` 目录不得残留 `.tif` |
| JFIF 归一化 | `utils/media_upload.py` `normalize_jfif_file_to_jpg()` | `.jfif` 内容即标准 JPEG（同 `FF D8 FF` 魔数），落盘后无损重命名为 `.jpg` 并删除原文件（见下节），`/upload/` 目录不得残留 `.jfif` |
| 大小上限 | 同上 | 分块（1MB）读取累计字节数，超限立即中断并清理半成品：图片 10MB（tif/tiff/jfif 同档）、视频 200MB、音频 50MB |
| nosniff 兜底 | `server.py` `cdn_redirect_middleware` | `/upload/` 静态响应统一带 `X-Content-Type-Options: nosniff`，禁止浏览器 MIME 嗅探（nginx 侧可再叠加同款头） |

## TIFF 归一化（tif/tiff 仅作为上传入口格式）

浏览器 `<img>` 标签不解码 TIFF（Chrome/Edge/Firefox 均不支持），且 CDN
重定向扩展名表（`server.py` `_MEDIA_EXTENSIONS`）与 `/api/proxy-image`
的 MIME 映射均不含 tif。因此 tif/tiff 只允许作为上传入口格式：

- **后端**：`save_upload_chunked` 白名单放行 + TIFF 魔数校验后，
  `convert_tiff_file_to_png()`（纯同步，经 `asyncio.to_thread` 调用）
  用 PIL 转为 PNG、删除原 tif。多帧 TIFF 取第一帧；CMYK/16bit 降为
  8bit RGB/RGBA；解码失败（损坏/超 PIL 像素安全上限）时原文件与半成品
  一并清理并抛 `UploadValidationError`（端点映射 400）。
- **对外 URL 恒为 `.png` 后缀**，预览、CDN、proxy、RunningHub/ComfyUI
  链路零适配。转码产物体积不设上限（10MB 限制约束的是上传原文件，
  无损 TIFF 转 PNG 后可能变大）。
- **前端**：`web/js/tiff_support.js` 提供 `isTiffFile(file)` 与
  `tiffPlaceholderHtml(label)`；本地 base64/objectURL 预览对 tif 会裂图，
  各上传入口须特判显示占位（video_workflow 画风图/多服装/多角度缩略、
  画布图片/图生视频首尾帧/数字人节点、index 系 ai_script_gen 配图等）。
  画布拖放（`web/js/canvas_drop.js`）白名单含 tif/tiff，按扩展名放行；
  超限 TIFF 不走 `compressImageFile`（浏览器 Image 解不出），按体积拒绝。
- 接入点：`_save_uploaded_image` / `_save_user_asset` /
  `/api/image-to-video/upload-media`（A 类，经 media_upload）与
  characters/locations/props 参考图 12 处落盘点（C 类：统一经
  `server.py` `_validate_image_size` 做白名单 + 魔数校验，写盘后追加
  TIFF 转码），常量见
  `MediaUploadSafetyConstants.TIFF_EXTS / TIFF_CONVERT_TARGET_EXT`。

## JFIF 归一化（.jfif 仅作为上传入口格式）

`.jfif` 是 JPEG 文件交换格式（JFIF）的扩展名，内容与 `.jpg` 完全相同
（魔数同为 `FF D8 FF`），浏览器 `<img>` 可正常解码。归一化的动机是
部分 CDN/proxy 的 MIME 表与第三方 API 不认 jfif 扩展名。与 TIFF 同策略：

- **后端**：白名单放行 + JPEG 魔数校验后，`normalize_jfif_file_to_jpg()`
  （纯同步，经 `asyncio.to_thread` 调用）做**无损重命名** `.jfif → .jpg`
  （不转码，避免重编码画质损失）。重命名失败时清理原文件并抛
  `UploadValidationError`（端点映射 400）。
- **统一入口**：各落盘点一律调用 `normalize_uploaded_image_file()`——
  内部按扩展名分派 TIFF→PNG 转码、JFIF→JPG 重命名、其余原样返回；
  直传（预签名/客户端直传）路径对 jfif 与 TIFF 同样拒绝，引导走服务器
  上传归一化。
- **老接口**：`api/script_writer.py` 参考图上传 / `upload-agent-image`、
  `api/storyboard.py` 分镜资产上传在保存前直接把 `.jfif` 扩展名归一为
  `.jpg`（内容即 JPEG，无需后处理）。
- **前端**：marketing_agent（2 处 accept + 4 处 `ALLOWED_IMAGE_EXTENSIONS*`）、
  storyboard（`events.js` `validateCandidateUploadFile` + `render.js`
  candidate accept）、涂鸦编辑器（`image_doodle_editor.js` `UPLOAD_ACCEPT`）
  白名单均含 `.jfif`；video_workflow 的 accept 为 `image/*` 天然覆盖。
  常量见 `MediaUploadSafetyConstants.JFIF_EXTS / JFIF_CONVERT_TARGET_EXT`。

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

## 路径拼接与读取型端点（issue 2835/2869，2026-11-10 修复）

上游安全分支（`security_2826_2851_merge`）曾定位过两处问题但未合入，
2026-11-10 在 develop 上重新修复：

- **Agent 上传接口 session_id 目录穿越**（`api/script_writer.py`
  `/api/upload-agent-{image,video,audio}`）：`session_id` 表单字段直接
  `os.path.join` 拼存储目录，`../../evil`（Windows 带盘符值更直接落绝对
  路径）可穿越出 `upload/` 树任意建目录写文件。修复：`_validate_session_id`
  仅接受标准 UUID（会话创建即 `str(uuid.uuid4())`），非法 400 不落盘。
- **`/api/thumbnail` 匿名读取**（`server.py`）：按 `url` 参数解析 `/upload/`
  下任意素材回缩略图，未鉴权时构成对素材的匿名读取面。修复：套
  `@require_permission("file:thumbnail")`（登录即可）；浏览器 `<img>` 场景
  由 `auth_cookie_translation_middleware` 自动携带凭据，前端无需在 URL
  拼 token（符合"凭据不进 URL"红线）。

## 测试

`tests/utils/test_media_upload.py`：覆盖白名单/黑名单/双扩展名、伪造魔数
（`poc.png` 实为 HTML）、超限清理半成品、多块完整写入，以及 TIFF 双字节序
魔数、伪造 tif 拒绝、RGB/CMYK/多帧 tif 转 PNG、损坏 tif 转码失败清理、
jfif 魔数、伪造 jfif 拒绝、jfif→jpg 无损重命名与统一入口分派 no-op、
`check_media_magic` 复用函数，以及 `_validate_image_size` 收口点（AST
守卫，防白名单/魔数校验被重构移除）等共 83 例。

## 运维建议

- nginx 对 `/upload/` 叠加 `X-Content-Type-Options: nosniff`（应用层已带，双保险）。
- 新增允许的媒体格式时，同步更新 `MediaUploadSafetyConstants` 白名单与
  `utils/media_upload.py` 的 `_MAGIC_CHECKS` 魔数表（两者键需保持一致），
  并补充测试用例；若浏览器/CDN 不能直接解码该格式，参照 TIFF/JFIF 在
  `normalize_uploaded_image_file()` 追加落盘归一化。
