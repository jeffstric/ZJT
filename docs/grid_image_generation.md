# 宫格图片生成功能文档

## 功能概述

宫格图片生成功能允许用户在剧本节点或分镜组节点中一键生成4宫格或9宫格的分镜图片，系统会自动拆分并分配到各个分镜节点。

### 支持的节点类型

1. **剧本节点**: 点击"拆分分镜组 + 宫格生图"按钮，系统会自动解析剧本、创建分镜组和分镜节点，并生成宫格图片
2. **分镜组节点**: 点击"宫格生图"按钮，为该分镜组下的所有分镜节点批量生成宫格图片

## 使用流程

### 1. 准备剧本

在剧本节点中输入或上传剧本内容。

### 2. 选择宫格模型

在剧本节点中选择宫格生图模型：
- **标准版 (4宫格, 2算力/张)**: `gemini-2.5-pro-image-preview`
  - 仅支持4宫格（2x2）
  - 每张图片消耗2算力
  - 适用于分镜数量≤5个的场景
  - 使用默认图片大小
  - **最多支持5张参考图片**
  
- **加强版 (9宫格, 6算力/张)**: `gemini-3-pro-image-preview`
  - 支持9宫格（3x3）
  - 每张图片消耗6算力
  - 适用于分镜数量>5个的场景
  - **自动传入4K图片大小（3840x2160）**，确保高质量输出
  - **最多支持10张参考图片**

### 3. 点击"拆分分镜组 + 宫格生图"

系统会自动执行以下步骤：
1. 调用LLM解析剧本，生成分镜组和分镜节点
2. **收集参考图片**（角色、场景、道具）
3. 统计分镜数量和参考图片数量，决定使用4宫格还是9宫格
4. 计算预计算力消耗
5. 弹出确认对话框，显示生成信息（包括参考图片数量）
6. 并行调用图片编辑API生成宫格图片（如有参考图片则传递）
7. 为每个分镜节点创建分镜图子节点

### 4. 自动同步

系统使用两阶段轮询机制：

**第一阶段：`pollVideoStatus`（每10秒检查一次）**
- 与其他视频/图片生成任务共享同一个轮询队列
- 当AI工具完成生成后，仅标记节点 `status: 'splitting'`，不直接调用拆分接口
- 标记完成后立即触发第二阶段

**第二阶段：`pollWorkflowNodeStatus`（每60秒或立即触发）**
- 检测 `isSplit:true` 且 `url` 为空的宫格节点
- 顺序调用 `/api/ai-tools/{id}/grid-split` 接口拆分图片
- 拆分成功后更新节点的 `url` 和 `preview`
- 如果后端返回 `code:1`（处理中），下次轮询重试

## 分镜组节点宫格生图

### 使用场景

当你已经有分镜组节点时，可以直接使用分镜组节点的宫格生图功能，无需从剧本节点重新开始。

### 使用步骤

1. **选择宫格生图模型**
   - 在分镜组节点中选择宫格生图模型：
     - **智能模式（推荐）**: 系统自动根据分镜数量和参考图片数量选择最合适的模型
     - **标准版 (4宫格, 2算力/张)**: 固定使用4宫格
     - **加强版 (9宫格, 6算力/张)**: 固定使用9宫格

2. **点击"宫格生图"按钮**
   - 系统会自动执行以下步骤：
     - 检查是否已有分镜节点，如果没有则自动生成
     - 收集所有分镜节点的参考图片（角色、场景、道具）
     - 根据选择的模型和分镜数量生成宫格图片
     - 为每个分镜节点创建分镜图子节点

3. **确认生成信息**
   - 系统会弹出确认对话框，显示：
     - 将要生成的宫格图片数量
     - 分镜数量
     - 使用的模型（标准版/加强版）
     - 参考图片数量
     - 预计消耗的算力

4. **等待生成完成**
   - 系统会自动轮询生成状态
   - 生成完成后自动拆分并更新分镜图节点

### 注意事项

- 如果分镜组下还没有分镜节点，系统会先自动生成分镜节点
- 智能模式会根据分镜数量和参考图片数量自动选择最优模型
- 如果参考图片超过5张，系统会自动使用加强版模型

## 参考图片收集

宫格生图会自动收集所有分镜中涉及的参考图片：

1. **角色参考图**: 从分镜提示词中提取用【【】】标记的角色名，查询数据库获取参考图
2. **场景参考图**: 根据分镜关联的场景ID，查询数据库获取场景参考图
3. **道具参考图**: 根据分镜中出现的道具，查询数据库获取道具参考图

**注意事项**：
- 需要先在左上角选择世界，才能正确匹配角色
- 相同的角色/场景/道具只会收集一次，避免重复
- 如果有参考图片，系统会使用图片编辑API（`/api/image-edit`）
- 如果没有参考图片，系统会使用文生图API（`/api/text-to-image`）

## 宫格选择逻辑

系统会根据分镜数量和参考图片数量自动选择模型：

- **1个分镜**: 不生成宫格图片（提示用户）
- **2-5个分镜 且 参考图片≤5张**: 使用4宫格（2x2）+ 标准版
- **>5个分镜 或 参考图片>5张**: 使用9宫格（3x3）+ 加强版
  - 如果用户选择了标准版但参考图片超过5张，系统会**强制升级**到加强版

## 算力计算

```
总算力 = ceil(分镜数量 / 宫格大小) × 单张算力
```

**示例**：
- 3个分镜 + 标准版: `ceil(3/4) × 2 = 2` 算力
- 7个分镜 + 加强版: `ceil(7/9) × 6 = 6` 算力
- 10个分镜 + 加强版: `ceil(10/9) × 6 = 12` 算力

## 提示词格式

系统会将分镜的图片提示词拼接成JSON格式：

### 4宫格示例
```json
{
  "grid_layout": "2x2",
  "grid_aspect_ratio": "16:9",
  "global_watermark": "",
  "style_guidance": "High-quality image grid. Strictly NO TEXT, NO NUMBERS, NO SHOT INDICES in the top-left corner. Clean visual composition only. No watermarks. IMPORTANT: You MUST strictly follow this art style for ALL shots: \"赛博朋克风格\". Every shot must consistently use this exact art style throughout the entire grid.",
  "art_style": "赛博朋克风格",
  "shots": [
    {"shot_number": "Shot 1", "prompt_text": "清晨的城市街道，阳光洒在建筑物上"},
    {"shot_number": "Shot 2", "prompt_text": "咖啡店内部，温暖的灯光"},
    {"shot_number": "Shot 3", "prompt_text": "主角坐在窗边，手持咖啡杯"},
    {"shot_number": "Shot 4", "prompt_text": "窗外的街景，行人匆匆"}
  ]
}
```

### 9宫格示例
```json
{
  "grid_layout": "3x3",
  "grid_aspect_ratio": "16:9",
  "global_watermark": "",
  "style_guidance": "High-quality image grid. Strictly NO TEXT, NO NUMBERS, NO SHOT INDICES in the top-left corner. Clean visual composition only. No watermarks. IMPORTANT: You MUST strictly follow this art style for ALL shots: \"水墨画风格\". Every shot must consistently use this exact art style throughout the entire grid.",
  "art_style": "水墨画风格",
  "shots": [
    {"shot_number": "Shot 1", "prompt_text": "..."},
    {"shot_number": "Shot 2", "prompt_text": "..."},
    ...
    {"shot_number": "Shot 9", "prompt_text": "..."}
  ]
}
```

### 图片填充逻辑

**重要**：当分镜数量不足填满宫格时（例如5个分镜使用4宫格，第二张图只有1个分镜），系统会**自动用全黑占位符填充剩余格子**。

**示例**：5个分镜使用4宫格
- 第1张图：Shot 1, 2, 3, 4（正常）
- 第2张图：Shot 5, Black, Black, Black（用全黑占位符填充）

**全黑占位符提示词**：
```text
"Solid black empty placeholder. Completely dark void. No content, no light, no text."
```

这样可以确保：
1. **减少模型干扰**：全黑画面让模型集中注意力在有效分镜上，避免重复生成相似内容造成的困惑
2. **避免重复**：不再复制最后一个分镜，防止出现重复的镜头画面
3. **尺寸正确**：保持宫格结构完整，确保拆分后的图片尺寸正确

## 节点类型

### 图片节点（宫格生图）

宫格生图现在使用标准的图片节点（`image`类型），拥有完整的图片功能（上传、编辑、下载等）。

**节点数据结构**：
```javascript
{
  type: 'image',
  title: '分镜图 1/4',
  data: {
    name: '分镜图 1/4',
    aiToolsId: 12345,         // 关联的AI工具ID
    project_id: 12345,        // 关联的AI工具ID
    gridIndex: 1,             // 在宫格中的位置（1-4或1-9）
    gridSize: 4,              // 宫格大小（4或9）
    url: '/upload/...',       // 拆分后的图片URL（拆分完成前为空）
    preview: '/upload/...',   // 预览图片URL（拆分完成前为空）
    isSplit: true,            // 宫格拆分节点标记（创建时即为true）
    status: 'completed',      // 状态：pending→splitting→completed/failed
    shotFrameNodeId: 678,     // 父分镜节点ID
    // 标准图片节点属性
    file: null,
    prompt: '',
    ratio: '16:9',
    model: 'gemini-2.5-pro-image-preview',
    drawCount: 1
  }
}
```

**图片节点功能**：
- 上传图片（替换生成的分镜图）
- 编辑图片（基于提示词修改）
- 下载图片
- 图片比例选择
- 连接到图生视频节点

## API接口

### 1. 获取宫格拆分图片

```
GET /api/ai-tools/{ai_tools_id}/grid-split?grid_index={index}&user_id={user_id}
```

**参数**：
- `ai_tools_id`: AI工具ID
- `grid_index`: 宫格位置（1-4或1-9）
- `user_id`: 用户ID

**响应**：

拆分成功：
```json
{
  "code": 0,
  "message": "获取成功",
  "data": {
    "image_url": "/upload/workflow/1/grid_split/12345/1.png",
    "grid_index": 1,
    "grid_size": 4
  }
}
```

处理中（AI 任务进行中，或其他 worker 正在下载/拆分）：
```json
{
  "code": 1,
  "message": "拆分处理中，请稍后重试"
}
```
前端收到 `code:1` 时不计入失败次数，下次轮询自动重试。

### 2. 查询AI工具状态

```
GET /api/ai-tools/{ai_tools_id}/status?user_id={user_id}
```

**响应**：
```json
{
  "code": 0,
  "message": "获取成功",
  "data": {
    "id": 12345,
    "status": 2,           // 0=待处理, 1=处理中, 2=已完成, 3=失败
    "type": 7,             // 1=标准版, 7=加强版
    "result_url": "...",
    "message": null
  }
}
```

## 文件存储路径

- **原始宫格图缓存**: `upload/workflow/{user_id}/grid_cache/{ai_tools_id}/original.png`
- **拆分锁文件**: `upload/workflow/{user_id}/grid_cache/{ai_tools_id}/.lock`
- **拆分后的图片**: `upload/workflow/{user_id}/grid_split/{ai_tools_id}/{grid_index}.png`

拆分后的图片会被缓存，重复请求会直接返回缓存的图片。

## 技术实现

### 轮询与拆分机制

宫格图片生成使用两阶段机制：
- **第一阶段**: `pollVideoStatus` 每 10 秒检查 AI 生图任务是否完成，完成后标记节点为 `splitting`
- **第二阶段**: `pollWorkflowNodeStatus` 每 60 秒检测待拆分节点，**顺序**调用 grid-split 接口
- **防重叠**: `_pollStatusRunning` 标志防止 `pollWorkflowNodeStatus` 并发执行（定时器 + 手动触发可能重叠）
- **失败重试上限**: 前端最多重试 20 次，超过后标记节点为 `failed`；`code:1`（处理中/任务未完成）不计入失败次数
- **并发安全**: 后端使用文件锁（`O_CREAT|O_EXCL`，`utils/file_lock.py`）确保同一 `ai_tools_id` 只有一个 worker 进程执行下载+拆分
- **非阻塞**: PIL 图片验证和拆分全部在 `asyncio.to_thread` 中执行，不阻塞事件循环
- **处理中响应**: AI 任务未完成或锁被其他进程持有时，均返回 `code:1`，前端下次轮询重试

### 图片大小

- **标准版**: 使用默认图片大小
- **加强版**: 自动传入 `image_size=3840x2160`（4K分辨率）

## 注意事项

1. **算力消耗**: 宫格生图会消耗算力，请确保账户有足够的算力
2. **分镜数量**: 只有1个分镜时不会生成宫格图片
3. **模型限制**: 标准版只支持4宫格，分镜数>5时会自动切换到加强版
4. **并行生成**: 多张宫格图片会并行生成，提高效率
5. **自动同步**: 复用现有轮询机制，每10秒检查一次，无需手动刷新
6. **4K输出**: 加强版模型自动使用4K分辨率，确保图片质量
7. **画风传递**: 如果用户设置了画风（`state.style.name`），所有生图入口（分镜节点、分镜组节点、剧本节点）都会自动将画风信息传递到提示词中。分镜节点通过 `图片风格：xxx` 追加到 prompt 末尾，多宫格生图通过 JSON 中的 `art_style` 字段传递

## 分镜节点顺序

当通过"拆分分镜组"或"拆分分镜组 + 宫格生图"功能生成分镜节点时，系统会确保分镜节点按照 `shot_number` 字段从小到大依次排列（从上到下），保证镜头一、镜头二等按顺序显示。

### 实现细节

1. **分镜组 Y 间距动态计算**：创建分镜组节点时，根据每个分镜组内的分镜数量动态计算 Y 偏移量（`cumulativeY += shotCount * 700`），避免不同分镜组的分镜节点在垂直方向交错。

2. **分镜排序**：在 `generateShotFramesIndependentAsync` 函数中，创建分镜节点前对 `shots` 数组按 `shot_number` 排序，确保组内分镜顺序正确。

---

## 故障排查

### 问题：宫格图已生成但未被拆分

**已彻底重构（2026-02-13）**：
- 宫格节点创建时 `isSplit` 直接设为 `true`，`url` 和 `preview` 保持为空
- AI 生图完成后仅标记 `status: 'splitting'`，不再直接调用拆分接口
- `pollWorkflowNodeStatus` 统一驱动拆分，检测 `isSplit:true && !url` 的节点并顺序调用 grid-split
- 后端 `poll-status` 排除宫格节点（`isSplit:true && gridIndex`），避免将原始宫格图 URL 写入节点
- 后端 grid-split 使用文件锁确保跨 worker 进程只有一个实例执行下载+拆分

### 问题：分镜图节点一直显示"等待生成..."

**可能原因**：
1. AI工具生成失败
2. 网络问题导致轮询失败
3. 后端拆分接口异常

**解决方法**：
1. 检查浏览器控制台的错误日志
2. 手动刷新页面重新加载工作流
3. 检查后端日志 `error.log`

### 问题：拆分后的图片无法显示

**可能原因**：
1. 图片路径错误
2. 文件权限问题
3. 原始宫格图不存在

**解决方法**：
1. 检查 `upload/workflow/{user_id}/grid_split/` 目录是否存在
2. 检查文件权限是否正确
3. 查看后端日志确认拆分是否成功

### 问题：图片拆分失败或切分后图片不完整

**根本原因**：
PIL（Pillow）的 `Image.open()` 使用惰性加载，只读取文件头而不加载像素数据。当 `crop()` 时才触发实际像素读取，如果此时出现 IO 问题（并发访问、文件句柄等），像素数据可能不完整，导致切分后的图片只有一半或出现黑色/灰色区域。

**系统处理**（已修复 2026-02-12，2026-02-13 进一步重构）：
1. **强制加载**：在 `Image.open()` 后立即调用 `img.load()` 强制加载全部像素数据到内存，确保 `crop()` 时数据完整
2. **下载验证**：下载原图后使用 `_write_and_validate_image()` 在线程池中执行写入+PIL验证，不阻塞事件循环
3. **原子写入**：下载图片时先写入临时文件，校验通过后再通过 `os.replace()` 原子重命名为目标文件
4. **文件锁保护**：使用 `_try_acquire_file_lock()` 确保同一 `ai_tools_id` 只有一个 worker 进程执行下载+拆分，避免重复下载
5. **损坏清理**：校验失败时自动清理临时文件，不会留下损坏的缓存

**手动解决方法**：
1. 删除损坏的切分缓存：`rm -rf upload/workflow/{user_id}/grid_split/{ai_tools_id}/`
2. 重新访问图片URL或调用拆分接口，系统会自动重新切分

**自动切分机制**：
直接访问图片URL（如 `/upload/workflow/{user_id}/grid_split/{ai_tools_id}/{grid_index}.png`）时，如果文件不存在，系统会自动触发切分逻辑，无需手动调用API。

## 相关文件

- **后端**:
  - `server.py`: API接口实现（`/api/ai-tools/{id}/grid-split`, `/api/get-status/{ai_tool_id}`）
  - `utils/image_grid_splitter.py`: 图片拆分工具
  - `config/constant.py`: 算力配置

- **前端**:
  - `web/js/nodes.js`: 节点创建和宫格生图逻辑（`pollVideoStatus` 仅标记状态）
  - `web/js/workflow.js`: `pollWorkflowNodeStatus` 驱动宫格拆分
  - `web/video_workflow.html`: UI界面

- **文档**:
  - `docs/grid_image_generation.md`: 本文档
