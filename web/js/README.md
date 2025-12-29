# JavaScript 模块化结构说明

## 模块拆分概览

原始的 `video_workflow.js` (6247 行, 243KB) 已拆分为 8 个逻辑模块：

### 1. state.js (154 行, ~5KB)
**功能**: 全局状态管理和工具函数
- 全局 `state` 对象
- URL 处理函数 (`normalizeVideoUrl`, `proxyImageUrl`, `proxyDownloadUrl`)
- 数据提取函数 (`extractResultsArray`)
- 认证函数 (`getAuthToken`, `getUserId`)
- Toast 提示函数 (`showToast`)
- DOM 元素引用（canvas、modal 等）
- 常量定义（TEST_MODE、MINIMAP 尺寸）
- 新增 `defaultWorldId` 字段用于存储默认选择的世界ID

### 2. api.js (159 行, ~6KB)
**功能**: API 调用和数据处理
- 文件上传 (`uploadFile`)
- 视频生成 (`generateVideoFromImage`)
- 状态查询 (`checkVideoStatus`)
- 测试模式支持

### 3. timeline.js (851 行, ~34KB)
**功能**: 时间轴完整功能
- 添加/移除视频片段
- 时间轴渲染 (`renderTimeline`, `renderTimelineRuler`)
- 片段拖拽排序和替换
- 视频剪切对话框 (`openTrimDialog`)
- 视频时长获取
- 缩略图生成

### 4. workflow.js (750 行, ~30KB)
**功能**: 工作流保存和加载
- 轮询视频状态 (`pollVideoStatus`)
- 工作流序列化 (`serializeWorkflow`)
- 工作流保存 (`saveWorkflow`, `autoSaveWorkflow`)
- 工作流加载 (`loadWorkflow`, `restoreWorkflow`)
- 节点数据恢复函数（所有类型节点）
- 自动保存定时器管理
- 画风设置管理
- 图片编辑 API
- 加载和保存默认世界

### 5. canvas.js (147 行, ~6KB)
**功能**: 画布渲染和交互
- 小地图渲染 (`renderMinimap`)
- 画布变换 (`applyTransform`)
- 缩放控制 (`zoomIn`, `zoomOut`)
- 节点选择 (`setSelected`, `clearSelection`)
- 节点删除 (`removeNode`)

### 6. nodes.js (2588 行, ~105KB)
**功能**: 节点创建和管理（最大模块）
- 视频节点 (`createVideoNode`)
- 图生视频节点 (`createImageToVideoNode`)
- 图片节点 (`createImageNode`)
- 剧本节点 (`createScriptNode`)
- 分镜组节点 (`createShotGroupNode`)
- 角色节点 (`createCharacterNode`)
- 场景节点 (`createLocationNode`)
- 所有模态框函数（分镜组、角色、场景等）

### 7. events.js (1597 行, ~64KB)
**功能**: 事件绑定和初始化
- 菜单按钮事件绑定
- 连接线渲染 (`renderConnections`, `renderImageConnections`)
- 画布交互事件（拖拽、平移、缩放）
- 键盘快捷键（删除、缩放）
- 角色/场景管理功能
- 页面初始化
- 角色/场景模态框自动选择默认世界

### 8. world.js (新模块)
**功能**: 世界管理
- `loadWorlds()` - 加载世界列表
- `populateWorldSelector()` - 填充世界选择器下拉框
- `handleWorldSelectionChange(worldId)` - 处理世界选择变化
- `saveDefaultWorld(workflowId, worldId)` - 保存默认世界到工作流
- `initWorldSelector()` - 初始化世界选择器

## 加载顺序

HTML 中按以下顺序加载模块（依赖关系）：

```html
<script src="/js/state.js"></script>      <!-- 1. 基础状态和工具 -->
<script src="/js/api.js"></script>        <!-- 2. API 调用 -->
<script src="/js/timeline.js"></script>   <!-- 3. 时间轴功能 -->
<script src="/js/workflow.js"></script>   <!-- 4. 工作流管理 -->
<script src="/js/canvas.js"></script>     <!-- 5. 画布渲染 -->
<script src="/js/nodes.js"></script>      <!-- 6. 节点创建和模态框 -->
<script src="/js/world.js"></script>      <!-- 7. 世界管理 -->
<script src="/js/events.js"></script>     <!-- 8. 事件和初始化 -->
```

## 优势

1. **模块化清晰**: 每个模块职责单一，便于维护
2. **代码复用**: 各模块可独立修改和测试
3. **降低 token 消耗**: 修改特定功能时只需加载相关模块
4. **提升可读性**: 每个文件大小适中（147-2692 行）
5. **便于协作**: 多人可同时修改不同模块

## 注意事项

- 所有模块共享全局 `state` 对象
- 模块间通过函数调用通信，无需额外的模块加载器
- 保持加载顺序以确保依赖关系正确
