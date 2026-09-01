# 360全景图节点（Panorama Node）

## 概述

360全景图节点用于 AI 视频制作中的「画布 · 360度全景图」能力：输入一段场景描述（可选参考图），生成 **equirectangular 等距圆柱投影全景图**，并在节点内直接以可交互全景查看器呈现——按住拖拽即可环顾 360° 任意角度，支持惯性、自动旋转、视角复位与全屏沉浸查看。

生成结果同时会创建标准图片节点（每张一个），可被下游节点（图生视频、图片编辑等）正常复用。

## 技术选型

| 候选方案 | 结论 |
|---------|------|
| cloudimage-360-view | ❌ 排除。它是**多帧序列图**查看器（36~72 张不同角度照片逐帧切换），不适用于 AI 生成的单张全景图 |
| **Pannellum 2.5.7** | ✅ 采用。原生 equirectangular 支持、零依赖、仅 ~19KB gzip（JS+CSS）、内置拖拽/惯性/缩放/自动旋转 |
| Three.js 手写球体 | 备选未采用。体积 8 倍且交互需全部手写 |
| photo-sphere-viewer | 备选未采用。强依赖 three@0.147，三文件版本耦合 |

- 本地 vendor 引入：`web/js/vendor/pannellum.min.js` + `web/css/pannellum.css`（无外网依赖，MIT 协议）
- 项目首页：https://github.com/mpetroff/pannellum

## 文件清单

| 文件 | 职责 |
|------|------|
| `web/js/panorama_node.js` | 节点定义：模板库、提示词拼接、生成流程、查看器管理、全屏弹层、重载复原 |
| `web/js/vendor/pannellum.min.js` | Pannellum 2.5.7（vendor） |
| `web/css/pannellum.css` | Pannellum 样式（vendor） |
| `web/css/video_workflow.css` | 节点样式与全屏弹层样式（文件末尾 panorama 段落） |
| `web/js/canvas.js` | `removeNode` 新增 `node.onDestroy()` 通用清理钩子 |
| `web/js/node_base.js` | `connectToRegisteredImagePort` 支持 `connectionType: 'connections'`（id 计数器按连接数组选择、`renderAllConnections` 渲染、`allowMissingImage` 跳过参考图检查） |
| `web/js/nodes.js` | `removeConnection` 断开 `panorama-source` 连线时复位参考图缩略图 |
| `web/js/image_node.js` | `createImageNode` 支持 `opts.data` 初始数据（结果节点携带生成提示词） |
| `web/js/shot_frame_generator.js` | 分镜图结果节点回填 `finalPrompt` |
| `services/image_describe.py` | VL 识图业务：360° 全景导向提示词与描述清洗（模型挑选/图片获取/VL 调用由 `services/vl_gateway.py` 共享网关提供，与画风识别、导演台估参复用同一实现） |
| `server.py` | `POST /api/video-workflow/describe-image` 路由（Header 鉴权，LLM token 计费） |
| `config/constant.py` | `IMAGE_DESCRIBE_*` 常量（超时/推荐模型） |
| `web/js/workflow.js` | `restoreWorkflow` 切换工作流时调用 `PanoramaViewerRegistry.destroyAll()` |
| `web/js/events.js` | 添加菜单项 `#menuAddPanorama` 点击绑定 |
| `web/video_workflow.html` | 菜单项、`pannellum.css`/`pannellum.min.js`/`panorama_node.js` 引入 |
| `web/i18n/locales/{zh-CN,en}/video_workflow.json` | `panorama_*` 文案 |

## 节点结构

- **输入端口**（`.port.input.panorama-source-port`，经 `registerInputPorts('panorama', ...)` 注册到连接吸附注册表）：`image` / `location` 类型（可选）。从图片/场景节点拖线到全景节点附近（50px 吸附）即可建立连接，端口绿色高亮提示；连接后走「图生全景」（`/api/image-edit` + `ref_image_urls`）；不连接走纯文生全景（`/api/text-to-image` + `aspect_ratio`）。源节点无参考图也允许连接（`allowMissingImage`），生成时自动降级为纯文生全景。
  - 连接**图片节点**时：参考图取图片节点的 `url`；若全景提示词为空，按以下优先级自动填入（不覆盖用户已输入内容）：
    1. 图片节点自带提示词（`data.prompt`，含生成结果节点回填的生成提示词——图片编辑结果携带原节点提示词、分镜图携带分镜生图 `finalPrompt`、全景结果节点携带含 360° 后缀的 `finalPrompt`、全景截图携带场景描述）；
    2. **任意图片（上传图等无提示词）→ VL 识图**：前端调用 `POST /api/video-workflow/describe-image`（`services/image_describe.py`，复用已配置密钥的 VL 模型，默认优先 `volcengine/doubao-seed-2-0-lite`），生成 360° 全景导向的场景描述填入并 toast 提示。识图期间**提示词框 placeholder 显示动态省略号 loading**（"正在识图生成场景描述.→..→..."，识图仅在提示词为空时触发、placeholder 恰好可见），节点状态行同步提示；完成/失败后恢复原 placeholder，失败降级为提示手动输入。仅**新连线**触发识图（工作流重载恢复不触发、不重复扣费），成功后提示词非空、断开重连不会重复识图；等待期间用户手动输入的内容不会被覆盖。支持本站 `upload/` 路径与 http(s) 远程 URL。走 LLM token 计费。
  - 连接**场景节点**时：参考图自动取场景的 `reference_image`；若提示词为空，自动按「场景名，场景描述」填充提示词（不覆盖用户已输入内容），点击生成即得到该场景的 360 全景图。
  - 断开参考连线（连接 `portType: 'panorama-source'`）时自动复位节点内参考图缩略图；提示词保留不回滚。
- **输出端口**：全景结果。生成后自动为每张结果创建标准图片节点并连接（全景节点 → 图片节点）。
- **节点数据**（`node.data`，全部可序列化）：

```js
{
  prompt: '',        // 用户场景描述
  url: '',           // 生成结果 URL（equirectangular 全景图）
  preview: '',       // 同 url
  model: 'seedream-5.0',
  ratio: '21:9',     // 全景比例（宽比优先，21:9 时水平完整 360°）
  drawCount: 1,      // 抽卡次数 X1~X3
  project_ids: null, // 生成中任务 ID 数组（重载恢复轮询用）
  yaw: 0, pitch: 0, hfov: 100  // 查看器视角状态（随工作流保存）
}
```

## 生成流程

1. 门禁：提示词非空；`TaskConfig.getTaskIdByKey(model, category)` 存在。
2. 算力预检（`/api/user/computing_power`，失败不阻塞）。
3. 提交：有参考图 → `POST /api/image-edit`；无参考图 → `POST /api/text-to-image`（比例作为 `aspect_ratio`）。
4. 提交成功后立即为每个 `project_id` 创建图片节点（持有 `project_id`，可被全局轮询恢复），并连接 全景节点 → 图片节点。
5. `pollVideoStatus` 轮询结果：第一张写入 `node.data.url` 并点亮节点内查看器；其余结果回填到对应图片节点（若全局轮询尚未回填）。
6. `safeAutoSave()` 落盘。

## 全景查看器

- 视场计算：等距圆柱投影度/像素均匀。`computePanoramaFov(ratio)`：
  - 宽比 ≥ 2:1（如 21:9）→ `haov: 360`，`vaov: 360×h/w`（21:9 ≈ 154.3°，上下极区不可见，符合宽幅全景常态）；
  - 宽比 < 2:1（如 16:9）→ `vaov: 180`，`haov: 180×w/h`（水平非完整 360°，无接缝落差）。
- 图片一律经 `proxyImageUrl()` 同源代理后交给 Pannellum（WebGL 纹理要求跨域可控）。
- **事件隔离**（与画布冲突处理）：查看器容器 `mousedown`/`wheel`/`touchstart` 均 `stopPropagation()`——节点内拖全景不触发画布平移、滚轮不缩放画布；节点本体拖拽仅从 header 发起（`node_base.js` 惯例），互不干扰。
- 交互：拖拽改 yaw/pitch（带惯性 `friction: 0.15`）；节点内禁用滚轮缩放（避免误触画布习惯），全屏弹层内启用。
- 视角持久化：`mouseup`/`animatefinished` 时把 `yaw/pitch/hfov` 写回 `node.data`（`safeAutoSave` 防抖落盘）。
- WebGL 上下文管理：`window.PanoramaViewerRegistry` 按 nodeId 登记；节点删除（`canvas.js removeNode` → `node.onDestroy()`）与工作流切换（`restoreWorkflow` → `destroyAll()`）时销毁，防止上下文泄漏。
- 降级：`pannellum` 未加载时退回平面 `<img>` 预览并 toast 提示。

## 视角截图（Snapshot）

在全景预览（节点内或全屏弹层）中拖拽到任意视角后，可一键截图并自动生成图片节点：

- **入口**：节点工具栏「截图」按钮（弹出画质/比例设置）或全屏弹层顶栏（画质/比例选择器 + 截图按钮）。
- **画质**：默认 **1K**（长边 1024px），可选 2K（长边 2048px）。
- **比例**：默认跟随工作流比例（`state.ratio`），可选 16:9 / 9:16 / 1:1 / 4:3 / 3:4 / 2:1 / 21:9；设置随工作流保存复原（`node.data.snapshot`）。
- **实现原理**：截图不受屏幕上查看器尺寸限制——用同一张全景图新建一个**离屏 pannellum 查看器**（容器尺寸=目标分辨率），复位当前 yaw/pitch/hfov 渲染首帧后 `toDataURL` 导出 JPEG。
- **WebGL 前置补丁**：Pannellum 创建 WebGL 上下文未传 `preserveDrawingBuffer`，渲染帧合成后 `toDataURL` 会得到空白图。`panorama_node.js` 在脚本加载时对 `HTMLCanvasElement.prototype.getContext` 注入 `preserveDrawingBuffer: true`（本页面无其他 WebGL 使用方，无副作用）。
- **产物链路**：JPEG dataURL → Blob → `uploadFile`（`POST /api/video-workflow/upload`）→ 自动创建标准图片节点并连线（全景节点 → 图片节点，图片节点 `data.ratio` 同步为截图比例），可直接接图生视频等下游节点。
- **失败保护**：离屏加载 20s 超时；截图过程中按钮置 busy 防重复提交；全屏弹层内通过顶栏 flash 提示进度/结果（普通 toast 会被弹层遮挡）。

## 重载复原（对应 AGENTS.md 第 4 条）

`createNodeWithDataFactory(createPanoramaNode, restoreDomFn)`：

- `restoreDomFn` → `el._restorePanoramaState()`：
  - 重新同步模型/比例下拉框（`onCreated` 先于 `Object.assign(node.data)` 执行，需在恢复时重选保存值）；
  - 回填提示词、抽卡次数、参考图缩略图；
  - 有 `url` → 重建查看器并复原保存的 `yaw/pitch/hfov`（`lookAt(pitch, yaw, hfov, 0)` 瞬时无动画）；
  - 无 `url` 但有 `project_ids` → 恢复轮询，完成后自动点亮查看器。

## 360 全景提示词指南（目标二）

节点内置两层提示词能力：

1. **8 类场景模板**（「模板 ▾」下拉，一键填充）：雪山湖泊/赛博都市/现代客厅/太空站/魔法森林/热带海滩/星空沙漠/雪山小镇。模板正文聚焦场景的**环绕式描述**（四周各方向可见内容），投影技术词不重复书写。
2. **技术后缀自动拼接**（`buildPanoramaPrompt`，导出为 `window.buildPanoramaPrompt`）：
   - 用户提示词缺少格式关键词（`equirectangular / 360 degree / panorama / spherical`）时自动追加：
     - 宽比 ≥ 2:1：`360 degree equirectangular panorama, spherical projection, seamless horizontal wrap, horizon at the vertical center, VR ready`
     - 宽比 < 2:1：`ultra wide panoramic view, equirectangular projection, seamless horizontal wrap, VR ready`
   - 已有格式词但缺 `seamless` 时仅补 `seamless horizontal wrap`；
   - 工作流设置画风（`state.style.name`）时追加画风名（与图片节点惯例一致）。

### 手写全景提示词最佳实践

1. **显式投影格式词**：必须包含 `360 degree equirectangular panorama`（或 `spherical projection`），否则模型倾向输出普通透视图。
2. **环绕式环境描述**：不要只描述"正前方"，按 前/后/左/右/头顶/脚下 分方向组织内容，全景的一致性来自四周描述。
3. **光照一致性**：说明统一的光源方向与时段（如 golden hour、soft volumetric light），避免不同角度光照互相矛盾。
4. **接缝缓解**：加入 `seamless horizontal wrap`，减少左右边缘拼接缝（极点拉伸是等距投影固有特性，提示词无法完全消除）。
5. **比例配合**：优先选 21:9 等宽比例，接近 2:1 全景标准；提示词中的环境描述越完整，宽幅产出越稳定。
