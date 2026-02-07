# 轮询接口同步世界数据

## 概述

`/api/video-workflow/{workflow_id}/poll-status` 接口在轮询节点生成状态的同时，会返回当前工作流所属世界的角色、道具、场景列表。前端将这些数据保存到 `state` 全局变量中，供各节点使用。

## 后端接口

### `GET /api/video-workflow/{workflow_id}/poll-status`

**返回数据结构：**

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "updated_nodes": [...],
    "total": 0,
    "characters": [...],
    "props": [...],
    "locations": [...]
  }
}
```

**字段说明：**

- `updated_nodes`: 有状态更新的节点列表（原有功能）
- `total`: 更新节点数量
- `characters`: 当前世界的角色列表（基于 `workflow.default_world_id` 查询，最多200条）
- `props`: 当前世界的道具列表（最多200条）
- `locations`: 当前世界的场景列表（最多200条）

**逻辑：**

1. 根据 `workflow_id` 获取工作流记录
2. 从工作流的 `default_world_id` 字段获取世界ID
3. 分别调用 `CharacterModel.list_by_world()`、`PropsModel.list_by_world()`、`LocationModel.list_by_world()` 查询数据
4. 如果 `default_world_id` 为空，三个列表返回空数组

## 前端全局变量

在 `web/js/state.js` 中的 `state` 对象新增三个字段：

```javascript
state.worldCharacters  // 当前世界的角色列表
state.worldProps       // 当前世界的道具列表
state.worldLocations   // 当前世界的场景列表
```

## 前端轮询逻辑

在 `web/js/workflow.js` 的 `pollWorkflowNodeStatus()` 函数中：

1. 每60秒请求一次 `/api/video-workflow/{workflow_id}/poll-status`
2. 请求成功后，将返回的 `characters`、`props`、`locations` 分别赋值给 `state.worldCharacters`、`state.worldProps`、`state.worldLocations`
3. 页面加载完成后立即执行一次轮询
4. 页面卸载时停止轮询

## 分镜节点使用世界数据

分镜节点（`createShotFrameNode`）中的场景、道具、角色选择均从 `state` 全局变量获取数据：

### 场景选择
- 数据源：`state.worldLocations`（替代原来的 `shotJson.scriptData.locations`）
- 选择后保存为 `node.data.refScene = { id, name, pic }`
- 生图时从 `state.worldLocations` 查找最新的 `reference_image`

### 道具选择
- 数据源：`state.worldProps`（替代原来的 `shotJson.scriptData.props`）
- 选择后保存 `{ id, name, props_db_id, reference_image }`
- 生图时优先从 `state.worldProps` 获取最新 `reference_image`，确保新建道具图片能正确传递

### 角色列表（/触发）
- 数据源：`state.worldCharacters`（替代原来的 API 调用）
- 角色标签只显示 `state.worldCharacters` 中真正存在的角色
- 无参考图片的角色标红并显示 ⚠ 提示

### 数据时效性
- 轮询间隔为60秒，新建的道具/场景/角色最多60秒后出现在选择列表中
- 生图时从 `state.worldProps`/`state.worldLocations` 获取最新数据，避免使用过期的 `reference_image`

## 分镜节点 UI 优化

### 布局调整
- 视频首帧区域（含"选择图片"按钮）移至分镜图显示区域上方，方便查看

### 提示词编辑
- 图片提示词和视频提示词 textarea 设为 readonly，点击直接打开放大编辑窗口
- 图片提示词区域显示"点击编辑 | 按 / 选择角色"提示
- 放大窗口底部显示"按 / 可选择角色插入到提示词中"提示（仅图片提示词）

### 图片选择增强
- "选择图片"菜单递归查找所有相连的图片节点（包括子图片和嵌套子图片）
- hover 菜单选项时，在右侧显示 120×120 缩略图预览

## 相关文件

- **后端**: `server.py` — `poll_workflow_node_status` 函数
- **前端状态**: `web/js/state.js` — `state.worldCharacters`、`state.worldProps`、`state.worldLocations`
- **前端轮询**: `web/js/workflow.js` — `pollWorkflowNodeStatus()` 函数
- **分镜节点**: `web/js/nodes.js` — `createShotFrameNode`、`showCharacterDropdownForImagePrompt`
- **生图逻辑**: `web/js/shot_frame_generator.js` — `generateShotFrameImage`
- **模型**: `model/character.py`、`model/props.py`、`model/location.py`
