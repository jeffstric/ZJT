# 工作流导航系统

## 概述

本文档描述了平台的工作流导航系统，包括首页布局、剧本创作系统和工作流画布之间的导航流程。

## 页面结构

### 1. 首页 (`index.html`)

#### 模式选择
- 首次访问时弹出模式选择弹窗
- 当前支持：短剧模式、营销模式
- 模式存储在 `localStorage` 的 `creation_mode` 键中
- 未选择模式时默认为短剧模式
- 可通过首页顶部的"切换模式"按钮重新选择

#### 开始创作
- 首页顶部显示"开始创作"大框（根据当前模式显示不同文案）
- 点击后跳转到工作流列表页面并自动打开新建表单（`/video-workflow-list?action=create`）
- 营销模式下跳转到营销智能体页面（`/marketing-agent`）

#### 功能入口卡片
- 首页展示功能入口卡片（仅短剧模式）
- 剧本创作卡片（剧本智能体）：点击跳转到剧本创作系统（`/script-writer`）
- 视频工作流卡片（制作工坊）：点击跳转到工作流列表（`/video-workflow-list`）
- 故事板卡片：点击跳转到故事板列表（`/storyboard-list`），带有 Beta 标识

### 2. 剧本创作系统 (`script_writer.html`)

#### 左侧导览条
- 位置：页面左侧，悬浮模式
- 通过 CSS hover 自动展开/收起，无需 JavaScript 控制
- 步骤：
  1. **剧本资产**（当前页面，高亮显示，带"当前"标记）
  2. **制作工坊**（可点击跳转，带箭头指示）

#### 跳转到工作流画布
- 点击"制作工坊"步骤先弹出模式选择（`showModeSelection()`）。选画布后走 `goToWorkflowCanvas()`，选故事板后走 `goToStoryboard()`
- 跳转**不会**调用 `submitToDatabase()`。入库只来自右上角「提交」按钮或「自动」开关
- 画布流程：
  1. 检查资产完成状态（角色至少一个有图、场景至少一个有图、道具图片）（`checkAssetsComplete()`）
  2. 如有未完成资产，弹出确认提示（`showAssetConfirmModal()`）
  3. 跳转到 `/video-workflow?id={workflowId}&from_world_id={worldId}&auto_load_script=true`
  4. 如果没有关联工作流，提示并跳转到工作流列表页

### 3. 工作流画布 (`video_workflow.html`)

#### 左侧导览条
- 位置：页面左侧，悬浮模式
- 通过 CSS hover 自动展开/收起，无需 JavaScript 控制
- 步骤：
  1. **剧本资产**（可点击返回，带左箭头指示）
  2. **制作工坊**（当前页面，高亮显示，带"当前"标记）

#### 返回剧本创作系统
- 点击"剧本资产"步骤触发（`goToScriptWriter()`）
- 流程：
  1. 自动保存当前工作流（`saveWorkflow()`）
  2. 获取当前选择的世界 ID
  3. 跳转到 `/script-writer?workflow_id={workflowId}&user_id={userId}&world_id={worldId}`

#### 新建画布
- 位置：左上角世界选择器旁的「新建画布」按钮（`#createWorkflowBtn`，带 SVG 图标）
- 点击后打开新建画布弹窗（`#createWorkflowModal`，画布页风格的白底模态框）
- 弹窗字段：
  - 工作流名称（必填）
  - 世界（可选，下拉选择，复用 `world.js` 的 `worldListCache`）
  - 画幅比例（必填，radio 卡片：16:9 横屏 / 9:16 竖屏，默认 16:9）
- 提交流程：调用 `POST /api/video-workflow/create` 创建工作流（带 `workflow_ratio` / `default_world_id`），成功后跳转 `/video-workflow?id={newId}` 进入新画布
- 实现文件：`web/js/create_workflow_modal.js`（在 `world.js` 之后加载）
- 入口绑定：`world.js` 的 `initWorldSelector()` 内统一绑定 `#createWorkflowBtn` click，调用 `window.openCreateWorkflowModal()`
- 注意：左上角原有的「新建/编辑/删除世界」三个按钮（`#createWorldBtn` / `#editWorldBtn` / `#deleteWorldBtn`）已移除，世界增删改走剧本创作系统或世界管理入口

#### 画布文件拖放
- 从文件夹拖拽图片/视频文件到画布任意位置，松开即在落点直接创建对应的图片节点或视频节点，并自动上传（复用节点内 file input 的 change 上传逻辑，上传成功后触发自动保存）
- 多文件批量拖入：按落点依次偏移创建多个节点（碰撞避让走 `findNearestAvailablePosition`）
- 类型白名单与后端 `utils/media_upload.py` 一致：图片 jpg/jpeg/png/webp/gif/bmp/tif/tiff，视频 mp4/mov/webm/avi/mkv；其他类型 toast 提示不支持。tif/tiff 按扩展名识别（部分 Windows 环境 `file.type` 为空，不能只靠 `image/*` MIME）
- 图片大小预检读取 `window.__wfUploadConfig`（`events.js` 拉取的 `/api/config/upload` 配置）；**超限图片自动在前端压缩后上传**（GIF 会丢动画帧不压缩，保持拒绝提示；**TIFF 浏览器解不出，超限直接拒绝，不走 `compressImageFile`**）；未超限 TIFF 交给节点上传，由后端转 PNG。视频与节点内上传行为一致，由后端兜底校验
- 拖到已有图片/视频节点的 file input 上：补派 change 事件让原生 drop 填充的文件生效
- 实现文件：`web/js/canvas_drop.js`（`events.js` 之后加载），高亮样式 `.canvas-container.drag-over`（`css/video_workflow.css`）

#### 图片上传自动压缩（仅 video_workflow 页面）
- 图片超过 `max_image_size_mb`（默认 10MB）时自动在前端压缩后再上传，覆盖两条路径：画布拖放（`canvas_drop.js`）与图片节点「上传图片」input（`image_node.js`）
- 压缩函数 `compressImageFile` 位于 `web/js/utils.js`：优先原格式缩放重编码（png/webp 保留透明），不达标依次尝试 webp 0.9 → jpeg 0.9/0.75/0.6（白底），仍未达标边长减半再跑一轮，返回最优结果（可能仍略超上限，由服务端兜底）；GIF 会丢动画帧不压缩
- 压缩成功 toast 提示（i18n key `image_auto_compressed`），输出文件按实际编码格式改扩展名（如 png → .webp/.jpg）

#### 图片节点分辨率档位
- 图片节点新增「分辨率」下拉（`data.imageSize`，如 1K/2K/4K），选项来自模型统一配置的 `image_sizes` / `default_image_size`（`TaskConfig.getModelConfigs()`），模型未配置时隐藏该字段（与首页图片编辑行为一致）
- 生成走 `/api/image-edit` 的 `image_size` 参数（后端按档位计费）；未选择/旧工作流无该字段时不传参，由后端取默认值
- 模型切换时若当前档位不被新模型支持，自动回落到 `default_image_size`；工作流保存/重载后档位随 `data` 序列化复原（`createImageNodeWithData` 回填）

## URL参数

### 剧本创作系统
- `workflow_id` 或 `id`：工作流ID（兼容两种参数名）
- `user_id`：用户ID
- `world_id`：世界ID

### 工作流画布
- `id`：工作流ID（标准参数，列表页/新建画布跳转均使用此参数）
- `workflow_id`：工作流ID（兼容历史链接；`getWorkflowIdFromUrl` 会在缺少 `id` 时回退读取）
- `from_world_id`：来源世界ID（从剧本创作系统跳转时传递）
- `auto_load_script`：是否自动打开剧本选择框（从剧本创作系统跳转时传递）
- `debug`：Debug模式密码（用于开启调试模式）

## CSS样式

导览条样式定义在：
- `css/script_writer.css`：剧本创作系统导览条样式
- `css/video_workflow.css`：工作流画布导览条样式

主要类名：
- `.step-nav`：导览条容器（悬浮模式，hover 自动展开）
- `.step-nav-content`：导览条内容区
- `.step-nav-title`：导览条标题（"创作流程"）
- `.step-nav-list`：步骤列表容器
- `.step-nav-item`：步骤项
- `.step-nav-item.active`：当前步骤
- `.step-nav-item.clickable`：可点击步骤
- `.step-nav-icon`：步骤图标
- `.step-nav-text`：步骤文本
- `.step-nav-badge.current`：当前步骤标记
- `.step-nav-arrow`：跳转箭头指示
- `.step-nav-connector`：步骤连接线

## localStorage键

| 键名 | 说明 |
|------|------|
| `creation_mode` | 创作模式（short_drama / marketing） |
| `user_id` | 用户ID |

## 关键函数

### index.html
- `checkCreationMode()`：检查并初始化创作模式
- `selectCreationMode(mode)`：选择创作模式
- `handleStartCreation()`：开始创作（跳转到工作流列表或营销智能体）
- `handleVideoWorkflowClick()`：跳转到工作流列表
- `handleScriptWriterClick()`：跳转到剧本创作系统

### script_writer.html
- `checkAssetsComplete()`：检查资产完成状态（调用 `/api/check-assets-complete`）
- `showAssetConfirmModal(hasScript, missingAssets)`：显示资产检查确认弹窗
- `showModeSelection()`：弹出制作工坊模式选择，不提交暂存
- `goToWorkflowCanvas()`：跳转到工作流画布，不提交暂存
- `goToStoryboard()`：跳转到故事板，不提交暂存
- `submitToDatabase()`：仅由「提交」按钮和「自动」开关调用，把暂存写入数据库

### video_workflow.html
- `goToScriptWriter()`：跳转到剧本创作系统（保存工作流后跳转）

### create_workflow_modal.js（新建画布弹窗）
- `openCreateWorkflowModal()`：打开新建画布弹窗（暴露到 `window` 供 `world.js` 调用）
- `closeCreateWorkflowModal()`：关闭弹窗
- `submitCreateWorkflow()`：收集表单 → 校验 → 调用 `POST /api/video-workflow/create` → 成功后跳转 `/video-workflow?id={id}`
- `populateWorkflowWorldOptions()`：复用 `world.js` 的 `worldListCache` 填充世界下拉
- `updateWorkflowRatioStyles()`：兼容不支持 `:has()` 的浏览器，同步比例卡片选中态
