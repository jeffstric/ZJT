# 七牛下载链接协议跟随 HTTPS 配置修复

## 问题现象

剧本创作页（`/script-writer`）「暂存文件管理 → 导出世界数据」点击后：

1. 前端 `exportWorld()`（`web/js/script_writer.js`）请求 `/api/export-world`；
2. 后端打包上传七牛后返回 `download_url`；
3. 前端创建 `<a download target="_blank">` 触发下载。

站点从 HTTP 切换到 HTTPS 后，用户点击导出表现为「跳转/新开一个链接，但看不到文件」。

## 根因

`utils/file_storage/qiniu_storage.py` 的 `get_public_url()` **硬编码 `http://`**：

```python
return f"http://{domain}/{key}"
```

站点切 HTTPS 后产生两层浏览器安全拦截：

- **混合内容下载（mixed content download）**：HTTPS 页面发起的 `http://` 下载，
  Chrome/Edge 等现代浏览器默认阻止——文件保存不下来；
- **`<a download>` 跨域失效**：`download` 属性仅对同源 URL 生效，浏览器退化为
  普通导航（`target="_blank"` → 新开标签页）——即用户看到的「跳转」。

链接本身（CDN 侧）HTTP/HTTPS 均 200 可访问，问题完全出在下发协议上。

## 修复

`get_public_url()` 协议改为跟随 `server.https.enabled` 配置（`config_prod.yml`）：

```python
scheme = "https" if get_config_value("server", "https", "enabled", default=False) else "http"
return f"{scheme}://{domain}/{key}"
```

- 与 `script_writer_core/mcp_tool.py` 既有 `server.https.enabled` 读取方式一致；
- `get_download_url()`（私有签名链接）复用 `get_public_url()`，一处修改全部生效；
- 运行时读取（`get_config()` 带内存缓存，无磁盘 IO），配置修改后新生成链接即时生效。

## 影响面（同一修复覆盖的所有 http:// 链接出口）

| 调用点 | 场景 |
|--------|------|
| `api/script_writer.py` | 剧本文件下载、世界导出（本次 BUG）、世界导入下载 |
| `services/storyboard_export_service.py` | 故事板导出 zip 下载 |
| `utils/cdn_util.py` | CDN 链接生成 / 签名 URL 刷新 |
| `utils/image_upload_utils.py` | 图片上传后 CDN URL |

## 运维注意

生产环境启用 HTTPS 后，`config_prod.yml` 必须置位：

```yaml
server:
  https:
    enabled: true
```

否则下载链接仍为 `http://`，继续被浏览器拦截。

## 测试

`tests/utils/test_qiniu_storage.py::TestGetPublicUrlScheme`：

- `enabled=true` → `https://`；`false` / 缺失 → 保持 `http://`；
- `get_download_url`（含 attname 编码）跟随协议。
