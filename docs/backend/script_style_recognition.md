# 剧本创作页 · 上传图片识别画风并写入 world.json

> 入口：`web/script_writer.html` 暂存区「世界」tab 列表**底部**的「🎨 画风识别」区块。
> 用途：拖入/上传一张参考图 → 调用支持视觉（`supports_vl=1`）且**已配置密钥**的模型识别画风 →
> 用户在确认弹窗中确认/编辑 → 写入 `world.json` 的 `visual_style` / `composition_preference`，
> 并在 `world.json` 内追加一条 `style_history` 记录。

## 一、涉及文件

| 层 | 文件 | 说明 |
|----|------|------|
| 后端常量 | `config/constant.py` | `IMAGE_STYLE_COMPRESS_TIMEOUT`、`IMAGE_STYLE_LLM_TIMEOUT`、`IMAGE_STYLE_PREFERRED_VENDOR`、`IMAGE_STYLE_PREFERRED_MODEL` |
| 后端接口 | `api/script_writer.py` | 新增 `/api/style-models`、`/api/recognize-style`、`/api/world-style`；扩展 `upload_reference_image` 支持 `item_type=4` |
| 前端页面 | `web/script_writer.html` | 暂存区底部「画风识别」拖放区 + 确认弹窗 |
| 前端样式 | `web/css/script_writer.css` | `.style-recognize-section` / `.style-drop-zone` 等样式 |
| 前端逻辑 | `web/js/script_writer.js` | `initStyleDropZone` / `loadStyleModels` / `recognizeStyle` / `applyRecognizedStyle` 等 |
| i18n | `web/i18n/locales/{zh-CN,en}/index.json` | `style_recognize_*` / `style_confirm_*` 文案 |

## 二、接口

### 1. 获取可用 vl 模型 — `GET /api/style-models`

- 权限：`world:view_files`
- 返回：
  ```json
  {
    "success": true,
    "models": [
      {
        "model_id": 9,
        "vendor_id": 4,
        "name": "doubao-seed-2-0-lite",
        "vendor_name": "volcengine",
        "recommended": true,
        "input_token_threshold": 32
      }
    ],
    "llm_timeout": 120,
    "preferred_vendor": "volcengine",
    "preferred_model": "doubao-seed-2-0-lite"
  }
  ```
- **筛选规则**（与上方 LLM 模型选择器同源）：复用 `llm_client_factory.get_available_models()`，它已：
  1. 通过 `is_vendor_configured()` 过滤掉**未填密钥的 vendor**；
  2. 仅返回 `enabled=true` 且 `supports_tools=true` 的模型。
  本接口再按 `supports_vl == True` 过滤。
- **排序与默认推荐**：
  1. `volcengine` + `doubao-seed-2-0-lite` 置顶并标记 `recommended=true`；
  2. 其余 `volcengine` 视觉模型；
  3. 其他已配置密钥供应商的视觉模型。
  前端按 vendor 分组（optgroup + 图标），默认选中推荐项。

### 2. 上传画风参考图 — 复用 `POST /api/upload-image`

- `item_type=4` → 落盘到 `<app_dir>/upload/style/pic/<16位uuid>.<ext>`。
- 静态服务由 `/upload` 挂载提供，返回形如 `http://host/upload/style/pic/xxx.png` 的 url。

### 3. 识别画风 — `POST /api/recognize-style`

- 权限：`world:view_files`
- 请求体：
  ```json
  {
    "user_id": "1", "world_id": "1", "auth_token": "xxx",
    "image_url": "http://host/upload/style/pic/xxx.png",
    "model": "doubao-seed-2-0-pro",
    "model_id": 12, "vendor_id": 3
  }
  ```
- 流程（全异步、非阻塞，遵守 AGENTS.md 超时红线）：
  1. 解析 `image_url` → 本地 `upload/style/pic/<file>`，做目录穿越校验（必须落在 `upload_root` 下）。
  2. `compress_local_image_to_base64(path, 2.0, 2_073_600)` 压缩为 base64 data URL（同步 CPU 操作，
     用 `asyncio.wait_for(asyncio.to_thread(...), IMAGE_STYLE_COMPRESS_TIMEOUT)` 包装）。
  3. 构造多模态消息（OpenAI 兼容格式）调用 LLM：
     - `call_api` 为同步方法，统一用 `asyncio.wait_for(asyncio.to_thread(client.call_api, **kw), timeout=IMAGE_STYLE_LLM_TIMEOUT+10)` 包装。
     - 仅 OpenAI 兼容系列（含 doubao）支持 `request_timeout` 形参；Gemini 等原生 client 不支持，
       故先 `inspect.signature` 探测后条件传入，避免 `TypeError`。
  4. 容错解析 JSON（先整体 `json.loads`，失败则正则抓 ```` ```json ... ``` ```` 或首个 `{...}`）。
- 提示词要点（对齐 `script_writer_core/skills/plot-analyzer/SKILL.md` 视觉风格字段规范）：
  - 仅返回
    `{"visual_style":"...", "composition_preference":"..."}`。
  - **visual_style**：先判定画风大类（写实风格类 / 动漫·漫画风格类），再写**精简风格关键词**
    （约 8~20 字）。正确示例：`现代都市写实风格`、`电影级写实风格`、`日系新海诚动漫风格`。
    禁止混入色彩、镜头、剧情内容；写实与动漫关键词不得交叉。
  - **composition_preference**：仅镜头角度 / 构图方式 / 景别 / 镜头运动。
    正确示例：`低角度镜头营造压迫感`、`竖屏平视中近景，主体居中`。
    禁止多宫格/分镜图/对比图，禁止与画风大类矛盾的术语。
  - 不输出 `color_language`（色彩另字段，识别结果不写入）。
- 返回：
  ```json
  {"success": true, "visual_style": "...", "composition_preference": "...",
   "model": "doubao-seed-2-0-pro", "vendor_id": 3}
  ```
  解析失败：`{"success": false, "error": "...", "raw": "<模型原文>"}`（422）。

### 4. 应用到 world.json — `POST /api/world-style`

- 权限：`world:save_files`
- 请求体：
  ```json
  {
    "user_id": "1", "world_id": "1", "auth_token": "xxx",
    "visual_style": "...", "composition_preference": "...",
    "image_url": "http://host/upload/style/pic/xxx.png",
    "model": "doubao-seed-2-0-pro", "vendor_id": 3
  }
  ```
- 处理：读取 `world_<id>.json` → 更新 `visual_style` / `composition_preference` → 在 `style_history` 数组**追加一条记录** → `file_manager.save_world` 写盘。
- 仅写文件；DB 同步沿用既有的「提交到数据库」按钮（`POST /api/submit-to-database` 已会回写
  `visual_style` / `composition_preference`，无需改动）。

## 三、`world.json` 新增字段：`style_history`

```jsonc
{
  "name": "...",
  "visual_style": "...",                  // 画面风格（被识别结果覆盖）
  "composition_preference": "...",        // 构图倾向（被识别结果覆盖）
  "style_history": [                      // 新增：每次识别确认后追加一条
    {
      "time": "2026-08-03T10:00:00",
      "model": "doubao-seed-2-0-pro",
      "vendor_id": 3,
      "image_url": "http://host/upload/style/pic/xxx.png",
      "visual_style": "...",
      "composition_preference": "..."
    }
  ]
}
```

> 不新建数据库表（记录仅落在 `world.json` 内）。

## 四、常量（`config/constant.py`）

| 常量 | 值 | 含义 |
|------|----|------|
| `IMAGE_STYLE_COMPRESS_TIMEOUT` | 30 | 图片压缩转 base64 的 `asyncio.wait_for` 超时（秒） |
| `IMAGE_STYLE_LLM_TIMEOUT` | 120 | 单次 vl 模型识别调用超时（秒），同时作为 transport 超时传入 `call_api` |
| `IMAGE_STYLE_PREFERRED_VENDOR` | `volcengine` | 画风识别默认推荐供应商 |
| `IMAGE_STYLE_PREFERRED_MODEL` | `doubao-seed-2-0-lite` | 画风识别默认推荐模型名（子串匹配） |

## 五、前端交互流程

1. 进入「世界」tab → 区块 `#styleRecognizeSection` 显示 → 首次懒加载模型列表（`loadStyleModels`）。
   - 标题旁角标「限时免费」：仅开源/社区版（`/api/edition` 的 `mode === 'community'`）显示；商业版不展示（`updateStyleRecognizeEditionBadge`）。
   - 标题行右侧提供外链「查看更多画风」→ `https://jimeng.jianying.com/ai-tool/home/`（`target="_blank"` 新开标签页，`rel="noopener noreferrer"`）。
2. **拖入图片**到 `#styleDropZone`，或**点击**拖放区打开文件选择（`item_type=4`）→ 上传成功后显示预览，并**自动**调用 `autoRecognizeStyleAfterUpload` → `recognizeStyle`。
3. 识别模型下拉按供应商分组；默认优先选中 **火山引擎 `doubao-seed-2-0-lite`**（须已配置密钥，否则列表中不会出现）。
4. 识别成功后直接弹出确认框（两字段可编辑）。换模型后仍可手动点「识别画风」重跑。
5. 用户点「确认写入」→ `POST /api/world-style` → 成功后 `showSuccess` 提醒
   「已更新世界画风设定，本次识别已记录」+ 自动刷新世界文件列表。
