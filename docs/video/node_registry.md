# 节点注册表系统

## 概述

节点注册表系统是工作流中节点类型管理的核心机制。它负责节点类型的注册、创建和恢复，确保工作流的正确加载和运行。

## 架构设计

### 核心组件

| 组件 | 文件 | 职责 |
|------|------|------|
| 节点注册表 | node_registry.js | 中央类型分发注册表 |
| 节点基类工厂 | node_base.js | 通用节点创建工厂 |
| 输入端口注册 | node_base.js | 输入端口配置管理 |
| 各节点文件 | *_node.js | 具体节点类型实现 |

### 注册表结构

```javascript
// node_registry.js
var nodeRegistry = {};

function registerNodeType(type, entry) {
  nodeRegistry[type] = entry;
}

function restoreNodeByRegistry(nodeData) {
  var entry = nodeRegistry[nodeData.type];
  if (entry && entry.createWithDataFn) {
    entry.createWithDataFn(nodeData);
    return true;
  }
  return false;
}
```

每个注册项包含：

- `createFn` — 创建新节点的函数
- `createWithDataFn` — 从保存数据恢复节点的函数

## 节点基类工厂

### createNodeBase

通用节点创建工厂，处理所有节点类型的通用逻辑：

```javascript
createNodeBase({
  type: 'node_type',           // 节点类型标识
  title: '节点标题',           // 默认标题或函数
  defaultData: { ... },        // 默认数据对象或函数
  ports: [ ... ],              // 输入输出端口配置
  cssClass: 'extra-class',     // 额外 CSS 类
  width: 300,                  // 节点宽度
  height: 200,                 // 节点高度
  bodyHtml: '<div>...</div>',  // 节点体 HTML 或函数
  titleIcon: '<svg>...</svg>', // 标题图标 SVG
  onCreated: function(node, el, opts) { ... }  // 创建后回调
}, opts);
```

处理流程：

1. 分配唯一节点 ID
2. 计算位置（避免重叠）
3. 创建 DOM 结构
4. 绑定事件处理
5. 添加调试按钮
6. 执行 i18n 扫描
7. 调用 onCreated 回调

### createNodeWithDataFactory

高阶函数，包装创建函数以支持工作流恢复：

```javascript
var createXxxNodeWithData = createNodeWithDataFactory(
  createXxxNode,                          // 原始创建函数
  function(el, node, nodeData) { ... }    // DOM 恢复逻辑
);
```

恢复流程：

1. 保存当前 nextNodeId 状态
2. 恢复保存的 nextNodeId
3. 调用原始创建函数
4. 合并保存的数据到节点
5. 调用 DOM 恢复函数
6. 恢复 nextNodeId 状态

## 输入端口注册

### 端口注册机制

```javascript
// 注册输入端口
registerInputPorts('node_type', [
  { type: 'video', label: '视频输入' },
  { type: 'audio', label: '音频输入' }
]);

// 获取端口配置
var ports = getInputPorts('node_type');
```

### 预设端口类型

```javascript
PORT_PRESETS = {
  VIDEO_INPUT: { type: 'video', label: '视频输入' },
  AUDIO_INPUT: { type: 'audio', label: '音频输入' },
  IMAGE_INPUT: { type: 'image', label: '图片输入' }
}
```

### 端口发现

连接系统通过 `findNearestConnectablePort` 自动发现可连接的端口：

- 根据鼠标位置查找最近的端口
- 检查端口类型兼容性
- 支持跨节点类型的自动匹配

## 注册的节点类型

### 新式节点（使用 createNodeBase）

| 类型 | 文件 | 说明 |
|------|------|------|
| text | text_node.js | 文本注释节点 |
| text_to_speech | text_to_speech_node.js | 文字转语音节点 |
| camera_control | camera_control_node.js | 相机控制节点 |
| dialogue_group | dialogue_group_node.js | 对话组节点 |
| digital_human | digital_human_node.js | 数字人节点 |
| extract_frame | extract_frame_node.js | 提取帧节点 |

### 旧式节点（手动 DOM）

| 类型 | 文件 | 说明 |
|------|------|------|
| video | video_node.js | 视频节点 |
| image | image_node.js | 图片节点 |
| audio | audio_node.js | 音频节点 |
| script | script_node.js | 剧本节点 |
| shot_group | shot_group_node.js | 分镜组节点 |
| shot_frame | shot_frame_node.js | 分镜帧节点 |
| image_to_video | image_to_video_node.js | 图生视频节点 |

## 工作流恢复流程

### 恢复入口

```javascript
// workflow.js
function restoreNode(nodeData) {
  // 优先使用注册表恢复
  if (typeof restoreNodeByRegistry === 'function' && restoreNodeByRegistry(nodeData)) {
    return;
  }

  // 回退到旧式手动恢复
  switch (nodeData.type) {
    case 'video': createVideoNodeWithData(nodeData); break;
    case 'image': createImageNodeWithData(nodeData); break;
    // ...
  }
}
```

### 恢复顺序

1. 检查节点是否在注册表中注册
2. 如果已注册，调用 `createWithDataFn`
3. 如果未注册，使用 if-else 链手动恢复
4. 合并保存的数据到新创建的节点
5. 恢复 DOM 状态和事件绑定

## 新式节点开发模式

### 标准模板

```javascript
(function() {
  // 1. 定义端口配置
  var NODE_PORTS = [
    { type: 'video', label: '视频输入', side: 'left' },
    { type: 'video', label: '视频输出', side: 'right' }
  ];

  // 2. 定义创建函数
  function createXxxNode(opts) {
    return createNodeBase({
      type: 'xxx',
      title: 'XXX 节点',
      defaultData: { key: 'value' },
      ports: NODE_PORTS,
      width: 300,
      height: 200,
      bodyHtml: function(node) {
        return '<div>...</div>';
      },
      onCreated: function(node, el, opts) {
        // 初始化逻辑
      }
    }, opts);
  }

  // 3. 定义数据恢复工厂
  var createXxxNodeWithData = createNodeWithDataFactory(
    createXxxNode,
    function(el, node, nodeData) {
      // DOM 恢复逻辑
    }
  );

  // 4. 暴露到全局并注册
  window.createXxxNode = createXxxNode;
  registerNodeType('xxx', {
    createFn: createXxxNode,
    createWithDataFn: createXxxNodeWithData
  });
})();
```

## 注意事项

- 新开发的节点应使用新式注册模式
- 旧式节点正在逐步迁移到新式模式
- 注册表确保节点类型的一致性和可扩展性
- 输入端口注册支持连接系统的自动发现
- 工作流恢复优先使用注册表，确保向前兼容
