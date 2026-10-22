# 剧本创作页：图片上传超限的明确报错

## 问题

script_writer 页面上传角色 / 场景 / 道具参考图，图片过大导致上传失败时，界面只显示笼统的「上传失败」，不告诉用户真实原因（如「图片大小不能超过 5MB」）。典型场景：用户传 9.8MB 图片，只看到「图片上传失败」，无法判断是图片过大还是其他故障。

## 根因

1. **i18n 文案吞掉错误详情**：`error_upload_failed` 在 `web/i18n/locales/{zh-CN,en}/index.json` 中是「上传失败」（无 `{error}` 占位符），而 `script_writer.js` 的 8 处调用全部传了 `{error: data.error}` —— 后端返回的具体原因被占位符替换逻辑丢弃。
2. **前端预检写死 10MB，后端限制可动态配置**：后端 `api/script_writer.py` 的 `upload-image` 用 `get_dynamic_config_value('upload', 'max_image_size_mb', default=10)`（数据库优先），管理员把限制调小后，前端仍按 10MB 放行，用户要等整张图传完才收到拒绝。

## 修复（仅前端，后端无需改动）

`web/js/script_writer.js`：

- 新增 `fetchUploadImageLimit()`：页面加载时从 `GET /api/system/server-config` 拉取 `max_image_size_mb` 存入 `uploadImageLimitMb`（拉取失败回退默认 10）。
- 新增 `checkImageFileSize(file)`：统一大小预检，超限时提示「图片大小不能超过{size}MB，当前文件{actual}」，**不发无效请求**。三处上传入口（单图 `uploadImageFile` / 角色多图 / 场景多图）全部改走该预检。
- 新增 `uploadErrorText(rawError)`：统一上传失败文案，透传后端具体原因；后端未返回原因时兜底 i18n `error_unknown`（「未知错误」）。8 处调用点统一替换。

i18n（`zh-CN` / `en` 的 `index.json`）：

- `error_upload_failed`：`上传失败` → `上传失败: {error}` / `Upload failed: {error}`
- `error_image_too_large`：`图片大小不能超过10MB` → `图片大小不能超过{size}MB，当前文件{actual}` / `Image size cannot exceed {size}MB (file: {actual})`

这两个 key 仅被 `script_writer.js` 使用，不影响其他页面。

## 验证（start.bat 本地实测）

| 场景 | 配置 | 文件 | 结果 |
|------|------|------|------|
| A | 10MB | 9.8MB | 上传成功（原行为保持） |
| B | 5MB（数据库动态配置） | 9.8MB | 预检拦截：「图片大小不能超过5MB，当前文件9.8MB」，未发出网络请求 |
| C | 5MB | 9.8MB（绕过预检直传） | 后端拒绝原因完整透传：「上传失败: 图片大小不能超过 5MB」 |
| 回归 | 5MB | 1MB | 上传成功 |

测试后已删除临时插入的 `system_config` 记录，恢复 YAML 默认 10MB。

## 相关

- 动态配置：`upload.max_image_size_mb`（见 `docs/README.md` 配置表），后端缓存 TTL 30 秒，改库后约半分钟生效。
- 后端拒绝逻辑：`api/script_writer.py` `upload_reference_image()`。
