# 剧本节点自动拆分分镜功能改进

## 更新日期
- 2026年2月3日：自动生成分镜功能
- 2026年2月4日：新增"旁白视为对话"功能
- 2026年2月7日：将"旁白视为对话"升级为"解说剧（仅旁白说话）"，新增对话剧本→纯旁白剧本的LLM转换步骤

## 功能概述

优化了剧本节点的"拆分镜组"功能，使其更加智能和便捷。现在点击"拆分镜组"按钮后，系统会自动完成以下操作：

1. **检查重复拆分**：检测剧本节点下是否已有分镜组节点，避免重复拆分
2. **自动生成分镜**：为每个分镜组自动调用"生成分镜"功能，无需手动点击
3. **解说剧（仅旁白说话）**：支持将包含角色对话的剧本先转换为纯旁白解说格式，再进行分镜解析

## 功能改进详情

### 1. 重复拆分检测

**改进前**：
- 用户可以多次点击"拆分镜组"按钮
- 每次点击都会创建新的分镜组节点
- 导致重复的分镜组和混乱的工作流

**改进后**：
- 点击"拆分镜组"前，系统会检查是否已存在分镜组节点
- 如果已有分镜组，显示提示："已有分镜组，请勿重复点击"
- 防止用户误操作导致的重复拆分

**实现逻辑**：
```javascript
// 检查是否已有分镜组节点
const existingShotGroups = state.connections.filter(c => c.from === id);
if(existingShotGroups.length > 0) {
  const hasShotGroupNode = existingShotGroups.some(conn => {
    const targetNode = state.nodes.find(n => n.id === conn.to);
    return targetNode && targetNode.type === 'shot_group';
  });
  
  if(hasShotGroupNode) {
    showToast('已有分镜组，请勿重复点击', 'warning');
    return;
  }
}
```

### 2. 自动生成分镜

**改进前**：
- 拆分镜组后，需要手动点击每个分镜组的"生成分镜"按钮
- 对于包含多个分镜组的剧本，操作繁琐

**改进后**：
- 拆分镜组后，自动为每个分镜组生成分镜节点
- 状态提示实时更新，显示生成进度
- 完成后显示总结信息

**实现逻辑**：
```javascript
// 创建分镜组节点数组
const createdShotGroupNodes = [];
result.data.shot_groups.forEach((shotGroup, index) => {
  const shotGroupNodeId = createShotGroupNode({...});
  if(shotGroupNodeId) {
    createdShotGroupNodes.push(shotGroupNodeId);
  }
});

// 自动为每个分镜组生成分镜
statusEl.textContent = '正在自动生成分镜...';
for(const shotGroupNodeId of createdShotGroupNodes) {
  const shotGroupNode = state.nodes.find(n => n.id === shotGroupNodeId);
  if(shotGroupNode) {
    await generateShotFramesIndependentAsync(shotGroupNodeId, shotGroupNode);
  }
}
statusEl.textContent = `已完成：${createdShotGroupNodes.length}个分镜组，所有分镜已自动生成`;
```

### 3. 新增异步生成函数

为了支持自动批量生成分镜，新增了 `generateShotFramesIndependentAsync` 函数：

**特点**：
- 异步执行，支持在循环中使用 `await`
- 与原有的 `generateShotFramesIndependent` 函数逻辑相同
- 不显示 Toast 提示，避免批量生成时的提示信息过多
- 返回创建的分镜节点数量

**函数签名**：
```javascript
async function generateShotFramesIndependentAsync(shotGroupNodeId, shotGroupNode)
```

## 用户体验改进

### 操作流程对比

**改进前**：
1. 点击"拆分镜组"
2. 等待LLM解析剧本
3. 手动点击第1个分镜组的"生成分镜"
4. 手动点击第2个分镜组的"生成分镜"
5. ...（重复N次）

**改进后**：
1. 点击"拆分镜组"
2. 等待LLM解析剧本
3. 系统自动生成所有分镜
4. 完成！

### 状态提示优化

拆分过程中的状态提示：
- "正在调用LLM解析剧本..."
- "解析成功！共N个分镜组"
- "正在自动生成分镜..."
- "已完成：N个分镜组，所有分镜已自动生成"

最终提示：
- "剧本拆分成功！所有分镜已自动生成"

## 技术实现

### 修改的文件

**`/web/js/nodes.js`**

1. **修改位置**：剧本节点的 `splitBtn` 点击事件处理函数（约3798-3931行）

2. **主要改动**：
   - 添加重复拆分检测逻辑（3806-3818行）
   - 收集创建的分镜组节点ID（3875行）
   - 自动调用生成分镜函数（3908-3917行）
   - 更新状态提示文本（3909、3916-3917、3920行）

3. **新增函数**：`generateShotFramesIndependentAsync`（约4190-4262行）
   - 异步版本的分镜生成函数
   - 用于批量自动生成分镜

### 代码结构

```
剧本节点 (Script Node)
├─ 拆分镜组按钮点击事件
│  ├─ 检查是否已有分镜组 ✨ 新增
│  ├─ 调用API解析剧本
│  ├─ 创建分镜组节点
│  ├─ 自动生成分镜 ✨ 新增
│  │  └─ generateShotFramesIndependentAsync() ✨ 新增
│  └─ 更新状态提示
```

## 注意事项

1. **检测范围**：只检测直接连接到剧本节点的分镜组，不检测间接连接
2. **异步执行**：自动生成分镜是异步执行的，按顺序依次生成每个分镜组
3. **错误处理**：如果某个分镜组生成失败，不会影响其他分镜组的生成
4. **性能考虑**：对于包含大量分镜的剧本，自动生成可能需要较长时间

## 兼容性

- 与现有的手动"生成分镜"功能完全兼容
- 不影响已有的工作流数据
- 支持工作流的保存和加载

## 解说剧（仅旁白说话）功能（2026年2月4日新增，2月7日升级）

### 功能说明

在剧本节点中提供"解说剧（仅旁白说话）"选项。启用后，系统会先通过LLM将包含角色对话的剧本转换为纯旁白解说格式（每个场景包含【画面描述】和【旁白台本】两部分），然后再用转换后的剧本进行正常的分镜解析流程。

### 使用场景

适用于短视频解说类内容的制作：
- 用户提供的剧本可能是传统的角色对话格式
- 但目标产出是"解说剧"风格：画面 + 旁白配音，无角色直接说话
- 系统自动完成格式转换，省去用户手动改写

### 两步处理流程

1. **第一步：剧本格式转换（新增）**
   - 调用LLM（`convert_script_to_narration`函数）将对话剧本转换为纯旁白格式
   - 每个场景输出【画面描述】和【旁白台本】
   - 角色对话转为第三人称旁白叙述
   - 画面描述详细包含人物动作、表情、环境等

2. **第二步：正常分镜解析**
   - 使用转换后的纯旁白剧本进行结构化解析
   - 旁白内容自动创建旁白角色（`char_narrator`）并添加到dialogue数组
   - 后续流程与正常剧本解析完全一致

### 转换示例

**原剧本（角色对话格式）**：
```
场景 1：顶级西餐厅"天瑞阁" - 中午

[环境描述]：极度奢华的装修，每一个餐具都闪烁着金边。

**服务员**（一脸傲慢）："先生，您这一桌消费了0.002元，这笔'巨款'怕是得攒半年吧？"

**林枫**（无奈）："不好意思，这100块你找得开吗？"
```

**转换后（纯旁白格式）**：
```
场景 1：顶级西餐厅"天瑞阁" - 中午

【画面描述】
餐厅内部装修极度奢华，大理石地面映着水晶灯的光芒。一名穿着普通运动服的年轻男子坐在餐桌前，
与周围精致华贵的环境格格不入。服务员一脸傲慢地站在桌前，手中捏着账单...

【旁白台本】
注意看这个穿着运动服的男人，他叫林枫，只是一个刚领到3000元工资的普通打工人。
服务员的傲慢嘲讽都没能让林枫多想，他随手拿出的一张百元大钞，
却在不经意间打破了这个世界的平静...
```

### 前端实现

**位置**：`/web/js/nodes.js`

1. **HTML选项**：
```html
<div class="field field-collapsible">
  <label style="display: flex; align-items: center; gap: 8px; cursor: pointer; font-size: 13px;">
    <input type="checkbox" class="script-narration-as-dialogue" style="cursor: pointer;" />
    <span>解说剧（仅旁白说话）</span>
  </label>
  <div class="gen-meta" style="margin-top: 4px; font-size: 11px; color: #666;">将有角色对话的剧本转换为仅旁白解说的剧本格式</div>
</div>
```

2. **状态提示**：启用时显示"正在将剧本转换为解说剧格式，再解析分镜..."

3. **数据字段**：`node.data.narrationAsDialogue`（布尔值，默认false）

### 后端实现

**位置**：`llm/script_parser.py`

1. **新增函数**：`convert_script_to_narration(script_content, model, temperature, auth_token, vendor_id, model_id)`
   - 使用专门的系统提示词 `NARRATION_CONVERSION_SYSTEM_PROMPT` 进行剧本格式转换
   - 异步调用Gemini API（通过`asyncio.to_thread`包装）
   - 返回转换后的纯旁白格式剧本文本

2. **修改函数**：`parse_script_to_shots`
   - 当`narration_as_dialogue=True`时，在函数开头先调用`convert_script_to_narration`
   - 将转换后的剧本替换原始`script_content`
   - 后续正常走分镜解析流程（包括旁白视为对话的提示词）

3. **日志记录**：
   - `{timestamp}_00_original_script_before_narration_convert.txt`：转换前的原始剧本
   - `{timestamp}_00_converted_narration_script.txt`：转换后的纯旁白剧本
   - `{timestamp}_narration_convert_system_prompt.txt`：转换系统提示词
   - `{timestamp}_narration_convert_user_prompt.txt`：转换用户提示词
   - `{timestamp}_narration_convert_result.txt`：LLM转换结果

### 注意事项

1. **默认关闭**：该选项默认不启用，需要用户手动勾选
2. **两次LLM调用**：启用后会产生两次LLM调用（一次转换 + 一次解析），消耗更多token和时间
3. **与其他选项兼容**：可以与"对话禁止全景"、"不生成背景音乐"、"拆分多人对话镜头"等选项同时使用
4. **旁白角色固定**：解析阶段会自动创建ID为`char_narrator`的旁白角色
5. **配音生成**：旁白对话可以通过"文字转语音"节点生成配音

## 未来优化方向

1. **并行生成**：考虑支持并行生成多个分镜组（需评估服务器负载）
2. **进度条**：添加更详细的进度条显示
3. **取消功能**：支持取消正在进行的自动生成
4. **选择性生成**：允许用户选择要生成的分镜组
5. **旁白音色定制**：支持为旁白角色设置专门的音色和语速
