# 分镜节点引用显示功能

## 功能概述

分镜节点（shot_frame）在图片提示词上方新增了引用显示区域，展示当前分镜引用的**场景**、**道具**和**角色**信息。

- **场景**：单选，支持手动切换，从 `shotJson.allLocationInfo` 初始匹配
- **道具**：多选，支持手动添加/移除，从 `shotJson.props_present` + `shotJson.scriptData.props` 初始匹配
- **角色**：只读，自动从图片提示词中的 `【【角色名】】` 模式提取

## 数据来源

### 场景匹配
- 初始值来自 `shotData.allLocationInfo`（由分镜组节点创建分镜时传入）
- 支持对象或数组格式
- 存储结构：`node.data.refScene = { id, name, pic }`

### 道具匹配
- 脚本道具：从 `shotData.props_present`（道具ID数组，如 `['prop_001', 'prop_002']`）通过ID在 `shotData.scriptData.props` 中查找
- 用户手动添加的道具：从 `shotData.props` 数组合并（用户在分镜组中通过「选择道具」添加的参考道具）
- 去重规则：通过 `props_db_id` 或 `name` 判断是否已存在
- 存储结构：`node.data.refProps = [{ id, name, props_db_id }]`

### 角色匹配
- 自动从 `node.data.imagePrompt` 中提取 `【【角色名】】` 模式
- 存储结构：`node.data.refCharacters = ['角色名1', '角色名2']`

## 用户交互

### 场景编辑（单选）
- 点击场景标签或 `+` 按钮打开下拉菜单
- 可用场景列表从 `shotJson.scriptData.locations` 或父级分镜组节点的 `scriptData.locations` 获取
- 点击 `×` 按钮移除当前场景
- 同一时间只能选择一个场景

### 道具编辑（多选）
- 点击 `+` 按钮打开下拉菜单，已选道具前显示 `✓`
- 可用道具列表从 `shotJson.scriptData.props` 或父级分镜组节点的 `scriptData.props` 获取
- 点击 `×` 按钮移除单个道具
- 支持选择多个道具

### 角色显示（只读）
- 自动从图片提示词中匹配 `【【角色名】】` 模式
- 修改图片提示词后自动更新
- 无角色时显示提示文字

## 自动重新匹配

以下操作会触发引用重新匹配：
1. 在图片提示词 textarea 中输入内容（`input` 事件）
2. 通过放大编辑弹窗修改图片提示词
3. 通过 `/` 快捷键插入角色后（`insertCharacterAtCursorForImagePrompt` 会 dispatch `input` 事件）

重新匹配时只更新角色（因为角色是从提示词自动提取的），场景和道具保持用户手动设置的值。

### `/` 快捷键行为
- 在图片提示词 textarea 中按下 `/` 键时，通过 `keydown` 事件拦截并 `preventDefault()`，**不会**将 `/` 字符输入到文本中
- 拦截后自动弹出角色选择下拉框
- 选择角色后在光标位置插入 `【【角色名】】`，并触发 `input` 事件更新引用标签

## 工作流保存与恢复

引用数据保存在 `node.data` 中：
- `refScene`：场景引用（对象或 null）
- `refProps`：道具引用（数组）
- `refCharacters`：角色引用（数组）

工作流重新加载时，`createShotFrameNodeWithData` 会：
1. 先通过 `createShotFrameNode` 创建节点（初始化引用数据）
2. 用保存的数据覆盖 `node.data`（恢复用户编辑过的引用）
3. 调用 `node.updateReferences()` 重新渲染引用标签

## UI 样式

引用区域位于图片提示词上方，使用标签（tag）样式显示：
- **场景标签**：蓝色系（`#dbeafe` 背景）
- **道具标签**：黄色系（`#fef3c7` 背景）
- **角色标签**：紫色系（`#ede9fe` 背景）

CSS 类名：
- `.shot-ref-section`：引用区域容器
- `.shot-ref-row`：每行（场景/道具/角色）
- `.shot-ref-tag`：标签基础样式
- `.shot-ref-tag.scene/.prop/.character`：各类型标签样式
- `.shot-ref-dropdown`：下拉选择菜单

## 关键函数

| 函数 | 说明 |
|------|------|
| `extractCharacterNames(prompt)` | 从提示词中提取 `【【】】` 包裹的角色名 |
| `getAvailableLocations()` | 获取可用场景列表 |
| `getAvailableProps()` | 获取可用道具列表 |
| `renderSceneTags()` | 渲染场景标签 |
| `renderPropTags()` | 渲染道具标签 |
| `renderCharTags()` | 渲染角色标签 |
| `updateShotReferences()` | 触发全部引用匹配并渲染 |
| `showSceneDropdown()` | 显示场景选择下拉菜单 |
| `showPropDropdown()` | 显示道具选择下拉菜单 |

## 涉及文件

- `web/js/nodes.js`：`createShotFrameNode` 函数中的引用匹配与显示逻辑
- `web/js/workflow.js`：`createShotFrameNodeWithData` 函数中的引用恢复
- `web/css/video_workflow.css`：引用区域样式（`.shot-ref-*` 类名）
