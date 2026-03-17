# 工作流导航系统

## 概述

本文档描述了平台的工作流导航系统，包括首页布局、剧本创作系统和工作流画布之间的导航流程。

## 页面结构

### 1. 首页 (`index.html`)

#### 模式选择
- 首次访问时弹出模式选择弹窗
- 当前支持：短剧模式
- 模式存储在 `localStorage` 的 `creation_mode` 键中

#### 开始创作
- 首页顶部显示"开始创作"大框
- 点击后弹出创建工作流表单
- 表单字段：名称、描述、世界、画风、风格参考图
- 创建成功后跳转到剧本创作系统

### 2. 剧本创作系统 (`script_writer.html`)

#### 左侧导览条
- 位置：页面左侧，固定定位
- 可折叠/展开，状态保存在 `localStorage`
- 步骤：
  1. **剧本资产**（当前页面，高亮显示）
  2. **无限画布**（可点击跳转）

#### 跳转到工作流画布
- 点击"无限画布"步骤触发
- 流程：
  1. 提交当前剧本数据
  2. 检查资产完成状态（角色、场景、道具图片）
  3. 如有未完成资产，弹出确认提示
  4. 跳转到 `/video-workflow?id={workflowId}`

### 3. 工作流画布 (`video_workflow.html`)

#### 左侧导览条
- 位置：页面左侧，固定定位
- 可折叠/展开，状态保存在 `localStorage`
- 步骤：
  1. **剧本资产**（可点击返回）
  2. **无限画布**（当前页面，高亮显示）

#### 返回剧本创作系统
- 点击"剧本资产"步骤触发
- 流程：
  1. 自动保存当前工作流
  2. 跳转到 `/script-writer?workflow_id={workflowId}`

## URL参数

### 剧本创作系统
- `workflow_id` 或 `id`：工作流ID（兼容两种参数名）
- `user_id`：用户ID

### 工作流画布
- `id`：工作流ID

## CSS样式

导览条样式定义在：
- `css/script_writer.css`：剧本创作系统导览条样式
- `css/video_workflow.css`：工作流画布导览条样式

主要类名：
- `.step-nav`：导览条容器
- `.step-nav.collapsed`：折叠状态
- `.step-nav-toggle`：折叠/展开按钮
- `.step-nav-item`：步骤项
- `.step-nav-item.active`：当前步骤
- `.step-nav-item.clickable`：可点击步骤

## localStorage键

| 键名 | 说明 |
|------|------|
| `creation_mode` | 创作模式（short_drama） |
| `step_nav_collapsed` | 剧本系统导览条折叠状态 |
| `workflow_step_nav_collapsed` | 工作流画布导览条折叠状态 |

## 关键函数

### script_writer.html
- `toggleStepNav()`：切换导览条展开/收起
- `initStepNav()`：初始化导览条状态
- `checkAssetsComplete()`：检查资产完成状态
- `goToWorkflowCanvas()`：跳转到工作流画布

### video_workflow.html
- `toggleStepNav()`：切换导览条展开/收起
- `initStepNav()`：初始化导览条状态
- `adjustShellLayout()`：调整主内容区域布局
- `goToScriptWriter()`：跳转到剧本创作系统
