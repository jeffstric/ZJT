# 时间轴柱子系统文档

## 概述

时间轴柱子系统是视频工作流时间轴的核心架构，用于实现基于分镜的时间区域管理。每个柱子对应一个分镜(shot)，作为视频轴和音频轴的占位符和分区。

## 核心概念

### 1. 柱子(Pillar)

柱子是时间轴的基本分区单位，每个柱子对应剧本中的一个分镜。

**柱子标识格式**: `{scriptId}_{shotNumber}`

例如：
- `123_1` 表示剧本节点ID为123的第1个分镜
- `123_2` 表示剧本节点ID为123的第2个分镜

### 2. 柱子数据结构

```javascript
{
  id: "123_1",              // 柱子标识: {scriptId}_{shotNumber}
  scriptId: 123,            // 剧本节点ID
  shotNumber: 1,            // 分镜编号
  defaultDuration: 15,      // 默认时长（秒），等于分镜组最长时长
  videoClipIds: [1, 2],     // 该柱子内的视频片段ID列表
  audioClipIds: [3, 4]      // 该柱子内的音频片段ID列表
}
```

### 3. 柱子的默认时长

柱子的默认时长等于其所属分镜组的最长时长（来自剧本解析）。这个时长来自 `script_parser.py` 返回的 `max_group_duration` 参数。

### 4. 柱子的实际时长

柱子的实际时长根据是否有媒体内容来决定：

**有媒体时**（视频或音频至少有一个）：
```
实际时长 = max(视频轨道总时长, 音频轨道总时长)
```

**无媒体时**（既没有视频也没有音频）：
```
实际时长 = 默认时长
```

**实现逻辑**：
```javascript
function getPillarActualDuration(pillar) {
  // 计算视频轨道总时长
  let videoTrackDuration = 0;
  pillar.videoClipIds.forEach(clipId => {
    const clip = state.timeline.clips.find(c => c.id === clipId);
    if (clip) {
      const actualDuration = (clip.endTime || clip.duration) - (clip.startTime || 0);
      videoTrackDuration += actualDuration;
    }
  });
  
  // 计算音频轨道总时长
  let audioTrackDuration = 0;
  pillar.audioClipIds.forEach(clipId => {
    const clip = state.timeline.audioClips.find(c => c.id === clipId);
    if (clip) {
      const actualDuration = (clip.endTime || clip.duration) - (clip.startTime || 0);
      audioTrackDuration += actualDuration;
    }
  });
  
  // 优先使用实际媒体时长，只有在完全没有媒体时才使用默认时长
  if (videoTrackDuration > 0 || audioTrackDuration > 0) {
    return Math.max(videoTrackDuration, audioTrackDuration);
  }
  return pillar.defaultDuration;
}
```

**设计理由**：
- 默认时长只是占位用途，当有实际媒体时应该使用媒体的真实时长
- 例如：柱子默认5秒，但添加了15秒的视频，柱子实际时长应该是15秒而不是15秒和5秒的最大值

## 工作原理

### 1. 柱子的预创建

**关键机制**：柱子在剧本解析时预先创建，而不是在片段加入时才创建。

当用户点击"拆分剧本"按钮并成功解析剧本后，系统会：

1. 遍历剧本中的所有 `shot_groups` 和 `shots`
2. 为每个分镜预先创建对应的柱子
3. 柱子按 `shot_number` 顺序排列
4. 即使某些镜头的视频还未生成，柱子也已经存在
5. 自动显示时间轴，展示所有空柱子

**这样设计的好处**：
- **保证顺序**：即使先加入镜头2的视频，镜头1的空白区域也会正确显示
- **可视化结构**：用户可以看到完整的时间轴结构，了解有多少个镜头
- **避免混乱**：片段只能加入到预先存在的柱子中，不会出现位置错乱

**示例**：
```javascript
// 剧本解析时预创建柱子
result.data.shot_groups.forEach((shotGroup) => {
  shotGroup.shots.forEach((shot) => {
    createOrUpdatePillar(scriptId, shot.shot_number, shot.duration);
  });
});

// 后续添加片段时，直接关联到已存在的柱子
const pillar = getPillarForNode(nodeId);
addClipToPillar(pillar, clipId, 'video');
```

### 2. 柱子的匹配逻辑

**分镜节点**：
- 通过 `node.data.shotData.shot_number` 获取分镜编号
- 向上查找父分镜组节点，再查找祖父剧本节点
- 组合 `{scriptId}_{shotNumber}` 作为柱子标识

**对话组节点**：
- 通过 `node.data.shotNumber` 获取分镜编号
- 查找关联的分镜节点，获取其柱子信息
- 使用相同的柱子标识

### 3. 时间轴渲染

时间轴按柱子顺序渲染，每个柱子：

1. **按 shotNumber 排序**：确保分镜按顺序显示
2. **计算累计位置**：每个柱子的起始位置 = 前面所有柱子的实际时长之和
3. **渲染柱子背景**：使用交替颜色区分不同柱子
4. **渲染片段**：在柱子内按 order 排序渲染视频和音频片段

**渲染示例**：
```
时间轴: [柱子1: 15秒] [柱子2: 20秒] [柱子3: 15秒]
位置:   0-15秒        15-35秒        35-50秒
```

### 3. UI 轨道高度

- 视频轨道容器 `timeline-track-container-video` 维持 112px 的最小高度，用于展示缩略图。
- 音频轨道容器 `timeline-track-container-audio` 采用 48px 的最小高度（约为视频的 1/3），并将波形与文本排列为紧凑横向布局，以便节省垂直空间。
- 时间轴整体容器 `timeline-container` 高度从 280px 调整为 220px，以适应音频轨道高度的减少。

### 4. 时间轴刻度尺

**刻度尺结构**：
- 刻度尺包含60px左侧占位，与轨道标签（"视频"/"音频"）宽度一致
- 刻度内容区域使用相对定位，与轨道内容区域对齐

**刻度类型**：
- **主刻度**：显示时间标签（如 0:00、0:05、0:10），刻度线高度12px
- **次刻度**：只显示刻度线，无标签，刻度线高度6px
- 主刻度间隔：总时长>60秒时为10秒，否则为5秒
- 次刻度间隔：主刻度为10秒时，次刻度为2秒；主刻度为5秒时，次刻度为1秒

**样式特性**：
- 刻度线 `z-index: 10`，显示在视频片段上方
- 刻度线 `pointer-events: none`，不阻挡鼠标事件
- 刻度标记左对齐（`align-items: flex-start`），确保刻度线与片段边缘精确对齐

**DOM结构**：
```html
<div class="timeline-ruler">
  <div style="display: flex;">
    <div style="width: 60px;"><!-- 左侧占位 --></div>
    <div style="position: relative; flex: 1;">
      <!-- 主刻度 -->
      <div class="ruler-mark" style="left: 0px;">
        <div class="ruler-tick ruler-tick-major"></div>
        <div class="ruler-label">0:00</div>
      </div>
      <!-- 次刻度 -->
      <div class="ruler-mark-minor" style="left: 10px;">
        <div class="ruler-tick ruler-tick-minor"></div>
      </div>
      ...
    </div>
  </div>
</div>
```

### 移动约束

**核心规则**：视频和音频片段只能在对应的柱子内移动，不允许跨柱子移动。

**实现方式**：
- 在拖拽事件中检查源片段和目标片段是否属于同一个柱子
- 如果不属于同一个柱子，禁止拖放操作并显示提示

```javascript
// 检查是否可以移动
if (!canMoveClipTo(draggedClipId, targetClipId, 'video')) {
  showToast('不能跨柱子移动视频片段', 'warning');
  return;
}
```

### 5. 动态时长调整

当柱子内添加或删除片段时：

1. **重新计算柱子实际时长**：取默认时长、视频轨道总时长、音频轨道总时长的最大值
2. **后续柱子自动后移**：后续所有柱子的起始位置自动调整
3. **保持连续性**：确保时间轴没有空隙

**示例**：
```
初始状态:
柱子1(默认15秒) | 柱子2(默认15秒)
0-15秒          | 15-30秒

添加30秒视频到柱子1后:
柱子1(实际30秒) | 柱子2(默认15秒)
0-30秒          | 30-45秒  <- 自动后移15秒
```

## API 函数

### 柱子管理

#### `createOrUpdatePillar(scriptId, shotNumber, defaultDuration)`
创建或更新柱子。

**参数**：
- `scriptId`: 剧本节点ID
- `shotNumber`: 分镜编号
- `defaultDuration`: 默认时长（秒）

**返回**：柱子对象

#### `getPillarActualDuration(pillar)`
获取柱子的实际时长。

**参数**：
- `pillar`: 柱子对象

**返回**：实际时长（秒）

#### `getPillarForNode(nodeId)`
根据节点ID获取对应的柱子。

**参数**：
- `nodeId`: 节点ID

**返回**：柱子对象或null

### 片段管理

#### `addClipToPillar(pillar, clipId, trackType)`
将片段添加到柱子。

**参数**：
- `pillar`: 柱子对象
- `clipId`: 片段ID
- `trackType`: 轨道类型 ('video' 或 'audio')

#### `removeClipFromPillar(clipId, trackType)`
从柱子移除片段。

**参数**：
- `clipId`: 片段ID
- `trackType`: 轨道类型 ('video' 或 'audio')

#### `getPillarForClip(clipId, trackType)`
获取片段所属的柱子。

**参数**：
- `clipId`: 片段ID
- `trackType`: 轨道类型 ('video' 或 'audio')

**返回**：柱子对象或null

### 约束检查

#### `canMoveClipTo(clipId, targetClipId, trackType)`
检查片段是否可以移动到目标位置。

**参数**：
- `clipId`: 源片段ID
- `targetClipId`: 目标片段ID
- `trackType`: 轨道类型 ('video' 或 'audio')

**返回**：布尔值，true表示允许移动

## 使用场景

### 场景1：解析剧本并预创建柱子

```javascript
// 1. 用户点击"拆分剧本"按钮
// 2. 系统调用后端API解析剧本
// 3. 解析成功后，遍历所有分镜并预创建柱子
result.data.shot_groups.forEach((shotGroup) => {
  shotGroup.shots.forEach((shot) => {
    createOrUpdatePillar(scriptId, shot.shot_number, shot.duration);
  });
});

// 4. 自动显示时间轴（即使还没有片段）
state.timeline.visible = true;
renderTimeline();

// 结果：时间轴显示所有空柱子，等待用户添加视频/音频
```

### 场景2：添加视频到时间轴

```javascript
// 1. 用户点击"加时间轴"按钮
// 2. 系统调用 addToTimeline(nodeId)
// 3. 系统查找节点对应的柱子（柱子已预先创建）
const pillar = getPillarForNode(nodeId);

// 4. 如果找不到柱子，提示用户先解析剧本
if (!pillar) {
  showToast('请先解析剧本以创建时间轴结构', 'warning');
  return;
}

// 5. 创建视频片段并关联到柱子
const clip = {
  id: state.timeline.nextClipId++,
  nodeId: nodeId,
  url: node.data.url,
  pillarId: pillar.id,
  order: pillar.videoClipIds.length, // 在柱子内的顺序
  // ... 其他属性
};

// 6. 将片段添加到柱子
addClipToPillar(pillar, clip.id, 'video');

// 7. 渲染时间轴（片段会出现在对应柱子的位置）
renderTimeline();
```

### 场景3：拖拽片段重新排序

```javascript
// 1. 用户拖拽片段A到片段B的位置
// 2. 系统检查是否属于同一个柱子
if (!canMoveClipTo(clipA.id, clipB.id, 'video')) {
  showToast('不能跨柱子移动视频片段', 'warning');
  return;
}

// 3. 允许移动，更新order
moveTimelineClipToPosition(clipA.id, newPosition);

// 4. 重新渲染
renderTimeline();
```

### 场景4：删除片段

```javascript
// 1. 用户点击删除按钮
// 2. 从柱子中移除片段
removeClipFromPillar(clipId, 'video');

// 3. 从clips数组中移除
state.timeline.clips = state.timeline.clips.filter(c => c.id !== clipId);

// 4. 重新计算柱子时长并渲染
renderTimeline();
```

## 向后兼容

系统保持向后兼容，支持两种模式：

### 柱子模式
- 当 `state.timeline.pillars.length > 0` 时启用
- 使用 `renderTimelineWithPillars()` 渲染
- 应用柱子约束

### 经典模式
- 当 `state.timeline.pillars.length === 0` 时启用
- 使用 `renderTimelineClassic()` 渲染
- 无柱子约束，自由移动

## 数据持久化

柱子数据会随工作流一起保存和恢复：

```javascript
// 序列化
timeline: {
  clips: [...],
  audioClips: [...],
  pillars: [...]  // 柱子数据
}

// 恢复
state.timeline.pillars = data.timeline.pillars || [];
```

## 历史数据自动迁移

为了兼容旧版工作流，系统实现了自动迁移机制。

### 迁移时机

自动迁移会在以下情况触发：

1. **添加片段时**：当用户点击"加时间轴"按钮，但系统检测到没有柱子数据时
2. **恢复工作流时**：加载旧版工作流，检测到有片段但没有柱子数据时

### 迁移逻辑

```javascript
function autoMigratePillars() {
  // 1. 检查是否已有柱子数据
  if (state.timeline.pillars.length > 0) return false;
  
  // 2. 扫描画布上所有已解析的剧本节点
  const scriptNodes = state.nodes.filter(n => 
    n.type === 'script' && n.data.parsedData
  );
  
  // 3. 基于剧本的 parsedData 重建柱子
  scriptNodes.forEach(scriptNode => {
    const parsedData = scriptNode.data.parsedData;
    parsedData.shot_groups.forEach(shotGroup => {
      shotGroup.shots.forEach(shot => {
        createOrUpdatePillar(scriptId, shot.shot_number, shot.duration);
      });
    });
  });
  
  // 4. 自动显示时间轴
  state.timeline.visible = true;
  return true;
}
```

### 迁移效果

- **无感知迁移**：用户首次点击"加时间轴"时自动完成迁移
- **提示信息**：显示"已自动迁移历史数据到新时间轴结构"
- **自动保存**：迁移完成后自动保存工作流，下次加载时不再需要迁移

### 迁移条件

迁移需要满足以下条件：

1. 画布上存在已解析的剧本节点（`node.type === 'script'`）
2. 剧本节点包含 `parsedData`（已执行过"拆分剧本"操作）
3. `parsedData` 中包含 `shot_groups` 和 `shots` 数据

### 无法迁移的情况

如果出现以下情况，无法自动迁移：

- 剧本节点已被删除
- 剧本节点未执行过"拆分剧本"操作
- 视频节点不是通过剧本分镜生成的（独立上传的视频）

此时会提示："该视频节点未关联到剧本分镜，请先解析剧本"

## 时间轴点击跳转

### 1. 点击视频片段跳转到视频节点

点击时间轴中的视频片段时，画布会自动平移并居中到该片段对应的视频节点，同时选中并高亮该节点。

**实现方式**：
- 时间轴片段的 `click` 事件中调用 `focusOnNode(clip.nodeId)`
- `focusOnNode` 函数定义在 `canvas.js` 中，负责计算视口位置并平移画布
- 节点会显示蓝色光晕闪烁动画（持续约0.8秒），帮助用户快速定位

### 2. 点击空柱子跳转到分镜节点

当某个镜头还没有视频片段时，点击该柱子的空白区域，画布会跳转到对应的分镜节点。

**实现方式**：
- 柱子背景 `.timeline-pillar-bg` 上绑定 `click` 事件
- 通过 `data-script-id` 和 `data-shot-number` 属性定位柱子对应的剧本和分镜编号
- 调用 `getShotFrameNodeForPillar(scriptId, shotNumber)` 查找分镜节点
- 找到后调用 `focusOnNode(shotFrameNode.id)` 跳转

**相关函数**：
- `focusOnNode(nodeId)` — 将画布视口居中到指定节点，选中并高亮
- `getShotFrameNodeForPillar(scriptId, shotNumber)` — 根据柱子的剧本ID和分镜编号查找对应的分镜节点
- `bindPillarClickEvents()` — 绑定柱子背景的点击事件
- `bindTimelineClipEvents()` — 绑定视频片段的点击事件

## 注意事项

1. **柱子标识唯一性**：同一个剧本的同一个分镜只有一个柱子
2. **时长动态性**：柱子时长会随内容变化而自动调整
3. **移动约束**：严格限制片段只能在柱子内移动
4. **空柱子**：即使柱子内没有片段，也会占据默认时长的空间
5. **前置空元素**：新片段会自动放入对应柱子，前面用空元素占位
6. **历史兼容**：旧版工作流会自动迁移到新的柱子系统

## 调试信息

系统会在控制台输出详细的柱子操作日志：

```
[柱子系统] 创建柱子: 123_1, 默认时长: 15秒
[时间轴] 视频片段 1 已关联到柱子 123_1
[恢复工作流] 恢复了 5 个柱子
```

## 未来扩展

可能的扩展方向：

1. **柱子合并**：允许合并相邻的柱子
2. **柱子分割**：将一个柱子分割为多个
3. **柱子锁定**：锁定柱子时长，不允许自动扩展
4. **柱子颜色自定义**：允许用户自定义柱子背景颜色
5. **柱子标签**：在柱子上显示更多信息（场景、角色等）
