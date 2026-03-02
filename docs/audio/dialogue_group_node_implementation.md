# 对话组节点实现文档

## 概述
为视频工作流实现了全新的对话组节点，可以根据分镜中的对话信息自动匹配角色库中的参考音频，批量生成对话语音。

## 功能特性

### 核心功能
1. **自动连接分镜节点**：从分镜节点获取对话数据（dialogue字段）
2. **智能角色匹配**：根据角色名称自动匹配当前世界的角色库
3. **参考音频管理**：
   - 支持在对话组节点中直接上传参考音频（最多6个）
   - 优先使用对话组节点的参考音频，其次使用角色库中的`default_voice`
   - 自动验证音频文件（时长≤20秒，大小≤10MB）
4. **情感控制**：支持三种情感控制方式（与参考音频相同、使用情感参考音频、使用情感向量）
5. **视频连接**：支持从视频节点连接作为情感参考来源
6. **批量生成**：支持单个生成和批量生成全部对话音频
7. **音频管理**：支持在线播放和下载生成的音频

### 节点显示方式
```
对话组
├─ 情感控制方式: [与参考音频相同 ▼]
├─ (当选择"使用情感参考音频"时)
│  ├─ 情感参考音频: [文件选择]
│  ├─ 情感权重: [0.0 - 1.6]
│  └─ 视频输入端口 (可连接视频节点)
├─ 参考音频: [添加音频]
│  ├─ 最多6个音频，每个不超过20秒、10MB
│  ├─ 我判 [播放器] [删除]
│  └─ 龙国观众甲 [播放器] [删除]
├─ 对话列表:
│  ├─ 【陈峰】: "龙国有救了……"
│  │  └─ [生成音频] [播放器] [下载] [添加到时间轴]
│  └─ 【裁判】: "龙国,胜!倭国挑战失败!"
│     └─ [生成音频] [播放器] [下载] [添加到时间轴]
└─ [生成全部]
```

## 技术实现

### 文件修改清单

1. **`/web/video_workflow.html`**
   - 添加"对话组"菜单项（lines 118-124）
   - 引入 `dialogue_group_node.js` 脚本（line 665）

2. **`/web/js/dialogue_group_node.js`**（新建，548行）
   - `createDialogueGroupNode()` - 创建对话组节点
   - `createDialogueGroupNodeWithData()` - 从保存数据恢复节点
   - `generateDialogueAudio()` - 生成单个对话音频
   - `pollDialogueAudioStatus()` - 轮询音频生成状态
   - `fetchCharactersByWorld()` - 获取世界角色列表
   - `findMatchingCharacter()` - 匹配角色名称

3. **`/web/js/events.js`**
   - 添加对话组菜单项事件处理（lines 60-64）

4. **`/web/js/workflow.js`**
   - 在 `restoreNode()` 中添加对话组节点恢复支持（lines 513-514）

## 数据流程

### 1. 连接分镜节点
```javascript
// 从分镜节点获取对话数据
const shotJson = fromNode.data.shotJson;
if(shotJson && shotJson.dialogue){
  node.data.dialogues = shotJson.dialogue;
}
```

### 2. 对话数据结构
```json
{
  "dialogues": [
    {
      "character_id": "char_003",
      "character_name": "【【陈峰】】",
      "text": "龙国有救了……"
    }
  ],
  "audioResults": {
    "0": {
      "audioUrl": "blob:http://..."
    }
  }
}
```

### 3. 参考音频匹配逻辑（优先级）

系统按以下优先级查找参考音频：

```javascript
// 标准化角色名称：去除【】等特殊符号
const normalizeCharacterName = (name) => {
  if(!name) return '';
  return name.replace(/[【】\[\]]/g, '').trim();
};

const normalizedCharacterName = normalizeCharacterName(characterName);
let refAudioFound = false;

// 优先级1: 对话组节点的参考音频
if(node.data.referenceAudios && node.data.referenceAudios.length > 0){
  const matchedRefAudio = node.data.referenceAudios.find(
    audio => normalizeCharacterName(audio.characterName) === normalizedCharacterName
  );
  
  if(matchedRefAudio){
    const voiceBlob = await fetch(matchedRefAudio.url).then(r => r.blob());
    form.append('ref_audio', voiceBlob, 'ref_audio.wav');
    refAudioFound = true;
  }
}

// 优先级2: 角色库的参考音频
if(!refAudioFound){
  const matchedCharacter = await fetchAndMatchCharacter(worldId, characterName);
  
  if(matchedCharacter && matchedCharacter.default_voice){
    const voiceBlob = await fetch(matchedCharacter.default_voice).then(r => r.blob());
    form.append('ref_audio', voiceBlob, 'ref_audio.wav');
    refAudioFound = true;
  }
}

// 如果都没找到，抛出错误
if(!refAudioFound){
  throw new Error(`角色"${characterName}"没有配置参考音频`);
}
```

**匹配规则**：
- 自动去除角色名称中的【】、[] 符号
- 示例：`【龙国观众甲】` 可以匹配 `龙国观众甲`
- 角色名称匹配不区分中英文括号

## API接口

### 使用的API
1. **`GET /api/characters?world_id={worldId}`** - 获取世界角色列表
2. **`POST /api/audio-generate`** - 生成音频
3. **`GET /api/audio-status/{audioId}`** - 查询音频生成状态

### 角色数据结构
```javascript
{
  id: 1,
  name: "陈峰",
  default_voice: "http://example.com/audio.wav",  // 参考音频URL
  world_id: 1,
  // ... 其他字段
}
```

## 使用流程

1. **创建对话组节点**
   - 点击"+"按钮 → "对话组"

2. **连接分镜节点**
   - 从分镜节点的输出端口拖拽到对话组节点的输入端口
   - 自动加载分镜中的对话数据

3. **生成音频**
   - 单个生成：点击每个对话项的"生成音频"按钮
   - 批量生成：点击顶部的"生成全部"按钮

4. **播放和下载**
   - 生成成功后自动显示音频播放器
   - 点击"下载"按钮下载音频文件

## 角色匹配规则

1. **精确匹配**：优先匹配完全相同的角色名称
2. **去符号匹配**：自动去除【】符号后再匹配
3. **无匹配时**：不使用参考音频，仅使用文本生成

示例：
- `【【陈峰】】` → 匹配角色库中的 `陈峰`
- `【裁判】` → 匹配角色库中的 `裁判`

## 参考音频功能详解

### 功能概述

对话组节点支持直接上传参考音频，无需在角色库中预先配置。这对于临时角色、未知角色或需要特定音色的场景非常有用。

### 使用方法

1. **添加参考音频**
   - 点击"添加音频"按钮
   - 选择音频文件（系统会自动验证）
   - 输入该音频对应的角色名称
   - 上传成功后显示在列表中

2. **音频限制**
   - 最多支持 6 个参考音频
   - 每个音频文件大小 ≤ 10MB
   - 每个音频时长 ≤ 20秒
   - 超出限制会显示错误提示

3. **角色名称匹配**
   - 输入的角色名称会自动去除【】符号进行匹配
   - 例如：输入"龙国观众甲"可以匹配对话中的"【龙国观众甲】"
   - 支持中英文括号自动识别

4. **删除参考音频**
   - 点击音频项右侧的"删除"按钮
   - 确认后从列表中移除

### 数据结构

```javascript
node.data.referenceAudios = [
  {
    characterName: "龙国观众甲",
    url: "http://example.com/audio1.wav",
    fileName: "audio1.wav"
  },
  {
    characterName: "我判",
    url: "http://example.com/audio2.wav",
    fileName: "audio2.wav"
  }
]
```

### 优先级说明

生成音频时，系统按以下顺序查找参考音频：

1. **对话组节点参考音频**（最高优先级）
   - 根据角色名称在 `referenceAudios` 中查找
   - 自动去除【】符号进行匹配

2. **角色库参考音频**（次优先级）
   - 如果对话组中未找到，从角色库查找
   - 使用角色的 `default_voice` 字段

3. **无参考音频**
   - 如果两处都未找到，生成失败
   - 显示错误提示："角色XXX没有配置参考音频"

### 数据持久化

- 参考音频数据会随工作流一起保存
- 重新加载工作流时自动恢复显示
- 音频文件已上传到服务器，URL持久有效

### 使用场景

1. **临时角色**：剧本中出现的临时角色，无需在角色库中创建
2. **未知角色**：角色库中不存在的角色
3. **特殊音色**：同一角色在不同场景需要不同音色
4. **快速测试**：测试不同音色效果，找到最合适的再创建角色

## 注意事项

1. **世界选择**：必须先在左上角选择世界，否则无法获取角色列表
2. **参考音频配置**：
   - 优先使用对话组节点的参考音频
   - 其次使用角色库中的参考音频（`default_voice`字段）
   - 两者都没有时会提示错误
3. **登录要求**：需要用户登录后才能使用语音生成功能
4. **生成时间**：每个对话音频生成约需10-30秒，批量生成会依次执行
5. **数据持久化**：生成的音频URL和参考音频数据会保存在节点数据中，支持工作流保存/加载
6. **角色名称匹配**：
   - 系统自动去除【】、[] 等符号进行匹配
   - 对话中的"【龙国观众甲】"可以匹配参考音频中的"龙国观众甲"
7. **音频验证**：
   - 角色库和对话组节点的音频都有相同限制（≤20秒、≤10MB）
   - 验证失败时会显示具体错误信息

## 情感控制功能

### 情感控制方式

对话组节点支持3种情感控制方式，可以灵活控制生成音频的情感色彩：

#### 1. 与参考音频相同 (默认)
- **使用场景**：保持角色原有的情感风格
- **实现方式**：直接使用角色库中的 `default_voice` 作为参考
- **优点**：简单、快捷，无需额外配置
- **数据字段**：`emoControlMethod: 0`

#### 2. 使用情感参考音频
- **使用场景**：需要特定情感色彩，如愤怒、悲伤、兴奋等
- **两种输入方式**：
  1. **上传音频文件**：支持本地音频文件上传
  2. **连接视频节点**：从视频节点自动提取音频作为情感参考
- **情感权重**：可调节 0.0 - 1.6，控制情感强度
- **UI特性**：
  - 情感参考音频区域始终显示，非此模式下变灰色禁用
  - 视频输入端口（蓝色）始终显示，非此模式下禁用连接
  - 支持清除按钮，可删除已上传的音频
- **数据字段**：`emoControlMethod: 1`, `emoWeight`, `emoRefAudioUrl`

#### 3. 使用情感向量
- **使用场景**：精确控制多种情感的混合
- **8种情感维度**：
  - 喜、怒、哀、惧、厌恶、低落、惊喜、平静
- **设置范围**：每个维度 0.0 - 1.5
- **约束条件**：所有维度总和不能超过 1.5
- **数据字段**：`emoControlMethod: 2`, `emoVec: [0,0,0,0,0,0,0,0]`

### 视频连接功能（情感参考音频模式）

#### 功能概述
当选择“使用情感参考音频”模式时，可以将视频节点连接到对话组节点，系统会自动从视频中提取音频作为情感参考。这对于需要保持与视频场景一致的情感色彩非常有用。

#### 使用步骤

1. **准备节点**
   - 创建或选择一个视频节点（已上传视频）
   - 创建或选择一个对话组节点

2. **设置情感控制模式**
   - 在对话组节点中，将“情感控制方式”切换为“使用情感参考音频”
   - 此时视频输入端口（蓝色圆点）会变为可用状态

3. **创建连接**
   - 从视频节点的输出端口拖拽到对话组节点的视频输入端口
   - 连接成功后会显示蓝色连接线
   - 系统提示：“视频已连接作为情感参考”

4. **生成音频**
   - 点击“生成音频”或“生成全部”
   - 系统会自动使用视频URL作为 `emo_ref_video_url` 参数发送给API

#### 技术实现

**端口显示逻辑**：
```javascript
// 视频输入端口始终存在，但根据模式启用/禁用
if(videoInputPort){
  if(node.data.emoControlMethod === 1){
    videoInputPort.classList.remove('disabled');
  } else {
    videoInputPort.classList.add('disabled');
  }
}
```

**连接数据管理**：
```javascript
// 使用 state.videoConnections 数组管理连接
state.videoConnections = [
  {
    id: 1,
    from: videoNodeId,  // 视频节点ID
    to: dialogueGroupNodeId  // 对话组节点ID
  }
];
```

**生成音频时的优先级**：
```javascript
// 1. 查找视频连接
const videoConn = state.videoConnections.find(c => c.to === nodeId);
if(videoConn){
  const videoNode = state.nodes.find(n => n.id === videoConn.from);
  if(videoNode && videoNode.data.url){
    form.append('emo_ref_video_url', videoNode.data.url);
  }
}
// 2. 如果没有视频连接，使用上传的音频文件
else if(node.data.emoRefAudioUrl){
  const audioBlob = await fetch(emoAudioUrl).then(r => r.blob());
  form.append('emo_ref_audio', audioBlob, 'emo_ref_audio.wav');
}
```

#### UI特性

1. **端口样式**
   - 颜色：蓝色 (`#3b82f6`)
   - 位置：节点左侧，`top: 120px`
   - 类名：`.port.video-input-port`

2. **连接线样式**
   - 颜色：蓝色 (`#3b82f6`)
   - 粗细：2px，选中时3px
   - 类型：贝塞尔曲线

3. **状态反馈**
   - 启用状态：端口正常显示，可以连接
   - 禁用状态：端口显示但添加 `disabled` class，无法创建新连接
   - 尝试连接禁用端口时，显示提示：“请先将对话组节点的‘情感控制方式’切换为‘使用情感参考音频’”

4. **模式切换行为**
   - 切换到“使用情感参考音频”：端口启用，情感参考音频区域正常显示
   - 切换到其他模式：端口禁用，情感参考音频区域变灰，但连接线保持显示

#### 注意事项

1. **视频限制**
   - 视频时长：不超过20秒
   - 视频大小：不超过40MB
   - 超出限制时API会返回错误

2. **连接持久化**
   - 视频连接会保存到工作流数据中
   - 重新加载工作流时自动恢复连接和端口状态

3. **删除连接**
   - 点击连接线选中
   - 点击显示的删除按钮
   - 或者按Delete键删除

4. **删除节点**
   - 删除视频节点或对话组节点时，相关的视频连接会自动清除

## 音频时间轴功能

### 功能概述

对话组节点生成的音频现在可以添加到时间轴中，与视频片段一起进行编排和管理。音频时间轴提供了独立的音频轨道，支持拖拽排序、移除等操作。

### 使用方法

#### 1. 添加音频到时间轴

生成音频后，每个对话项会显示"添加到时间轴"按钮：

```
【陈峰】: "龙国有救了……"
└─ [下载] [添加到时间轴]
```

点击按钮后：
- 系统自动获取音频时长
- 将音频添加到时间轴的音频轨道
- 显示成功提示："已添加音频到时间轴"

#### 2. 时间轴布局

时间轴现在包含两个独立轨道：

```
时间轴
├─ 视频轨道
│  └─ [视频片段1] [视频片段2] ...
└─ 音频轨道
   └─ [音频片段1] [音频片段2] ...
```

**轨道特性**：
- **视频轨道**：黑色背景，显示视频缩略图
- **音频轨道**：绿色渐变背景，显示波形图标
- **独立管理**：两个轨道可以独立添加、排序、移除片段
- **时长计算**：总时长取视频和音频中较长的一个

#### 3. 音频片段显示

音频片段包含以下信息：
- **波形图标**：模拟音频波形的SVG图形
- **片段名称**：格式为 `角色名: 对话内容前20字...`
- **时长标签**：显示音频时长（秒）
- **移除按钮**：鼠标悬停时显示，点击可移除

#### 4. 音频片段操作

**选中片段**：
- 点击音频片段可选中
- 选中状态显示绿色边框和阴影

**移除片段**：
- 鼠标悬停在音频片段上
- 点击右上角的"×"按钮
- 确认移除

**拖拽排序**：
- 暂不支持音频片段拖拽（未来版本将支持）

### 技术实现

#### 数据结构

**状态管理** (`state.js`):
```javascript
state.timeline = {
  clips: [],              // 视频片段数组
  audioClips: [],         // 音频片段数组
  nextClipId: 1,
  nextAudioClipId: 1,
  selectedClipId: null,
  selectedAudioClipId: null,
  visible: false,
}
```

**音频片段数据**:
```javascript
{
  id: 1,                    // 片段唯一ID
  nodeId: 5,                // 对话组节点ID
  dialogueIndex: 0,         // 对话索引
  url: "http://...",        // 音频URL
  name: "陈峰: 龙国有救了...",  // 显示名称
  duration: 3.5,            // 音频时长（秒）
  startTime: 0,             // 剪切开始时间
  endTime: 3.5,             // 剪切结束时间
  order: 0,                 // 排序顺序
}
```

#### 核心函数

**添加音频到时间轴** (`timeline.js`):
```javascript
function addAudioToTimeline(nodeId, dialogueIndex, audioUrl, audioName, duration) {
  const clip = {
    id: state.timeline.nextAudioClipId++,
    nodeId: nodeId,
    dialogueIndex: dialogueIndex,
    url: audioUrl,
    name: audioName || '音频',
    duration: duration || 5,
    startTime: 0,
    endTime: duration || 5,
    order: state.timeline.audioClips.length,
  };
  
  state.timeline.audioClips.push(clip);
  state.timeline.visible = true;
  renderTimeline();
}
```

**获取音频时长** (`timeline.js`):
```javascript
function getAudioDuration(url) {
  return new Promise((resolve, reject) => {
    const audio = document.createElement('audio');
    audio.preload = 'metadata';
    
    audio.addEventListener('loadedmetadata', () => {
      if (audio.duration && isFinite(audio.duration)) {
        resolve(Math.round(audio.duration * 10) / 10);
      } else {
        reject(new Error('Invalid duration'));
      }
    }, { once: true });
    
    audio.src = proxyDownloadUrl(url);
  });
}
```

**渲染音频轨道** (`timeline.js`):
```javascript
// 渲染音频片段到时间轴
const sortedAudioClips = [...state.timeline.audioClips].sort((a, b) => a.order - b.order);
let accumulatedAudioTime = 0;

audioTrack.innerHTML = sortedAudioClips.map(clip => {
  const startTime = accumulatedAudioTime;
  const actualDuration = clip.endTime - clip.startTime;
  const width = actualDuration * 10; // 10px per second
  accumulatedAudioTime += actualDuration;
  
  return `
    <div class="timeline-audio-clip" 
         data-audio-clip-id="${clip.id}" 
         style="left: ${startTime * 10}px; width: ${width}px;">
      <!-- 波形图标、名称、时长等 -->
    </div>
  `;
}).join('');
```

#### 样式设计

**音频片段样式** (`video_workflow.css`):
```css
.timeline-audio-clip {
  height: 100px;
  min-width: 50px;
  background: linear-gradient(135deg, #10b981 0%, #059669 100%);
  border-radius: 8px;
  border: 2px solid transparent;
  transition: border-color 0.15s, transform 0.15s;
}

.timeline-audio-clip:hover {
  border-color: #059669;
  transform: translateY(-2px);
}

.timeline-audio-clip.selected {
  border-color: #059669;
  box-shadow: 0 0 0 2px rgba(16, 185, 129, 0.3);
}
```

**轨道布局** (`video_workflow.css`):
```css
.timeline-track-container {
  display: flex;
  align-items: stretch;
  border-bottom: 1px solid var(--border);
  min-height: 112px;
}

.timeline-track-label {
  width: 60px;
  background: #f5f5f5;
  border-right: 1px solid var(--border);
  font-size: 12px;
  font-weight: 700;
  color: var(--muted);
}
```

### 工作流保存

音频时间轴数据会随工作流一起保存：

**序列化** (`workflow.js`):
```javascript
timeline: {
  clips: state.timeline.clips.map(c => ({ ...c })),
  audioClips: state.timeline.audioClips.map(c => ({ ...c })),
  nextClipId: state.timeline.nextClipId,
  nextAudioClipId: state.timeline.nextAudioClipId,
}
```

**恢复** (`workflow.js`):
```javascript
if(data.timeline){
  state.timeline.clips = data.timeline.clips || [];
  state.timeline.audioClips = data.timeline.audioClips || [];
  state.timeline.nextClipId = data.timeline.nextClipId || 1;
  state.timeline.nextAudioClipId = data.timeline.nextAudioClipId || 1;
  state.timeline.visible = state.timeline.clips.length > 0 || 
                          state.timeline.audioClips.length > 0;
  renderTimeline();
}
```

### 时间轴关联机制

对话组节点需要关联到剧本分镜才能添加到时间轴。系统使用"柱子"（Pillar）系统来管理分镜的时间区域，每个柱子对应一个分镜，标识格式为 `{scriptId}_{shotNumber}`。

#### shotNumber 字段

对话组节点通过 `node.data.shotNumber` 字段来标识它对应的分镜编号。这个字段在以下场景中被设置：

1. **从分镜节点创建时**：
```javascript
// nodes.js - 分镜节点创建对话组时
const dialogueGroupId = createDialogueGroupNode({
    x: dialogueGroupX,
    y: dialogueGroupY,
    dialogueData: node.data.shotJson.dialogue,
    shotNumber: node.data.shotJson.shot_number  // 传递分镜编号
});

// 确保shotNumber被正确保存
dialogueGroupNode.data.shotNumber = node.data.shotJson.shot_number;
```

2. **工作流恢复时**：
```javascript
// dialogue_group_node.js - 从保存数据恢复
function createDialogueGroupNodeWithData(nodeData){
    createDialogueGroupNode({ 
        x: nodeData.x, 
        y: nodeData.y,
        dialogueData: nodeData.data.dialogues || [],
        shotNumber: nodeData.data.shotNumber || null  // 恢复shotNumber
    });
}
```

#### 查找柱子逻辑

时间轴系统通过 `getPillarForNode()` 函数查找对话组节点对应的柱子：

```javascript
// timeline.js
if (node.type === 'dialogue_group' && node.data.shotNumber) {
    shotNumber = node.data.shotNumber;
    // 查找关联的剧本节点（通过分镜节点连接）
    const incomingConns = state.connections.filter(c => c.to === nodeId);
    for (const conn of incomingConns) {
        const sourceNode = state.nodes.find(n => n.id === conn.from);
        if (sourceNode && sourceNode.type === 'shot_frame') {
            const pillar = getPillarForNode(sourceNode.id);
            if (pillar) return pillar;
        }
    }
}
```

#### 错误处理

如果对话组节点缺少 `shotNumber` 字段，添加到时间轴时会提示：
> "该音频节点未关联到剧本分镜，请先解析剧本"

**修复历史**：在 2026年1月7日之前，对话组节点创建时没有传递 `shotNumber` 字段，导致无法添加到时间轴。现已修复，确保在新建和恢复两种场景下都能正确保存 `shotNumber`。

### 注意事项

1. **音频格式**：支持所有浏览器支持的音频格式（WAV、MP3等）
2. **时长获取**：首次添加时自动获取音频时长，失败时使用默认值5秒
3. **URL类型**：支持服务器URL和blob URL
4. **时间轴高度**：添加音频轨道后，时间轴高度从200px增加到280px
5. **独立管理**：音频和视频片段独立管理，互不影响
6. **剧本关联**：对话组节点必须从分镜节点创建，才能正确关联到时间轴

### 未来扩展

计划中的功能：
- 音频片段拖拽排序
- 音频剪切功能
- 音频淡入淡出效果
- 音频音量调节
- 导出时支持音频轨道合成

## 扩展功能

未来可以扩展的功能：
- 支持音色微调（根据角色设置调整音色参数）
- 支持对话时序控制（设置对话间隔时间）
- 支持导出完整音频轨道（合并所有对话音频）
