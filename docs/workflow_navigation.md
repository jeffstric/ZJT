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
- 点击"制作工坊"步骤触发（`goToWorkflowCanvas()`）
- 流程：
  1. 提交当前剧本数据（`submitToDatabase()`）
  2. 检查资产完成状态（角色、场景、道具图片）（`checkAssetsComplete()`）
  3. 如有未完成资产，弹出确认提示（`showAssetConfirmModal()`）
  4. 跳转到 `/video-workflow?id={workflowId}&from_world_id={worldId}&auto_load_script=true`
  5. 如果没有关联工作流，提示并跳转到工作流列表页

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
- 提交流程：调用 `POST /api/video-workflow/create` 创建工作流（带 `workflow_ratio` / `default_world_id`），成功后跳转 `/video-workflow?workflow_id={newId}` 进入新画布
- 实现文件：`web/js/create_workflow_modal.js`（在 `world.js` 之后加载）
- 入口绑定：`world.js` 的 `initWorldSelector()` 内统一绑定 `#createWorkflowBtn` click，调用 `window.openCreateWorkflowModal()`
- 注意：左上角原有的「新建/编辑/删除世界」三个按钮（`#createWorldBtn` / `#editWorldBtn` / `#deleteWorldBtn`）已移除，世界增删改走剧本创作系统或世界管理入口

## URL参数

### 剧本创作系统
- `workflow_id` 或 `id`：工作流ID（兼容两种参数名）
- `user_id`：用户ID
- `world_id`：世界ID

### 工作流画布
- `id`：工作流ID
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
- `goToWorkflowCanvas()`：跳转到工作流画布
- `submitToDatabase()`：提交当前数据到数据库

### video_workflow.html
- `goToScriptWriter()`：跳转到剧本创作系统（保存工作流后跳转）

### create_workflow_modal.js（新建画布弹窗）
- `openCreateWorkflowModal()`：打开新建画布弹窗（暴露到 `window` 供 `world.js` 调用）
- `closeCreateWorkflowModal()`：关闭弹窗
- `submitCreateWorkflow()`：收集表单 → 校验 → 调用 `POST /api/video-workflow/create` → 成功后跳转 `/video-workflow?workflow_id={id}`
- `populateWorkflowWorldOptions()`：复用 `world.js` 的 `worldListCache` 填充世界下拉
- `updateWorkflowRatioStyles()`：兼容不支持 `:has()` 的浏览器，同步比例卡片选中态
