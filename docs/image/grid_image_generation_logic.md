# 4宫格图片生成逻辑（Agent 工具链路）

## 功能概述

本文档描述 AI Agent 通过 MCP 工具批量生成**角色/场景/道具 4宫格参考图**的后端链路。与前端分镜组的宫格生图（`docs/image/grid_image_generation.md`）不同，本链路面向 Agent 工作流：

- **输入**：4 个项目的名称 + 4 条提示词
- **输出**：1 张高分辨率 2x2 大图，后台自动切分为 4 张子图，分别写入对应 JSON 的 `reference_image` 字段
- **用途**：为世界观下的角色、场景、道具快速生成统一的参考图

**核心差异对比**：

| 维度 | Agent 4宫格（本文档） | 前端分镜组宫格（另见文档） |
|---|---|---|
| 入口 | MCP 工具函数（`generate_4grid_character_images` 等） | 前端按钮点击 |
| 目标 | 角色/场景/道具的 `reference_image` | 分镜节点的分镜图 |
| 切分后写入 | JSON 文件（`characters/xxx.json`） | 数据库节点数据 + 文件系统 |
| 状态查询 | `grid_image_tasks` 表轮询 | 前端 `pollVideoStatus` + `pollWorkflowNodeStatus` |

---

## 整体调用链路

```text
Agent (ToolExecutor)
    |
    v
generate_4grid_character_images / generate_4grid_location_images / generate_4grid_prop_images
    |
    v
generate_4grid_images                           -- 构建 2x2 JSON prompt
    |
    v
generate_text_to_image (requests.post)          -- 同步 HTTP 请求
    |
    v
POST /api/text-to-image (server.py)             -- 创建 AI 工具任务
    |
    v
返回 project_ids → 创建 grid_image_tasks 记录
    |
    v
APScheduler 每 10 秒轮询 (task/scheduler.py)
    |
    v
process_grid_image_tasks (task/grid_image_task.py)
    |
    v
GET /api/get-status/{ai_tool_id}
    |
    v
SUCCESS → 下载大图 → ImageGridSplitter 切分 2x2
    |
    v
分别 update_character_json / update_location_json / update_prop_json
    |
    v
更新 JSON 文件的 reference_image 字段
```

---

## MCP 工具函数层

### 0. 算力感知工具（新增）

**位置**：`script_writer_core/mcp_tool.py`

| 函数 | 说明 |
|---|---|
| `get_text_to_image_model_info` | 获取当前用户选中的生图模型信息：名称、算力、支持尺寸、是否支持宫格等 |
| `get_user_computing_power` | 查询用户剩余算力余额 |

这两个工具供 Agent 在生图前预估成本、检查余额，避免提交后因算力不足而失败。

### 1. 角色变体图生成函数

**位置**：`script_writer_core/mcp_tool.py`

| 函数 | item_type | 说明 |
|---|---|---|
| `generate_character_variant_image` | `7`（角色变体图） | 基于主参考图做图片编辑，生成指定造型/服装的三视角变体图 |

**与主图生成的关键差异**：
- **主图走文生图**（`generate_text_to_image` / 4宫格）；**变体图走图生图**（内部调用 `edit_image`，源图为角色 `reference_image`）
- 变体图写入角色的 `reference_images` 数组（而非 `reference_image` 字段）
- `item_name` 使用复合格式 `"角色名|变体标签"`（如 `"豆包|黑化形态"`）
- 前置条件：角色必须已存在且已有主参考图(reference_image)，且 URL 为 http/https
- 变体图不能使用4宫格/文生图批量生成，必须逐个调用，以保证脸部/身份一致性
- **绑定任务必须创建成功**：`edit_image` 在传入 `item_type=7` 时若 `grid_image_tasks` 写入失败会返回 `success=false`（避免图已生成却无回写）
- **回写解析**：`get_character_json` / `update_character_json` 通过 `resolve_character_file_path` 按文件名与 JSON 内 `name` 字段定位角色文件
- 完成后请**重新打开**角色编辑弹窗查看「多形象」列表（异步生成完成时前端不会自动刷新已打开的表单）

**调用链路**：
```text
generate_character_variant_image(character_name, variant_label, variant_prompt)
    |
    v
edit_image(
  prompt=variant_prompt,
  image_url=角色.reference_image,
  item_type=7,
  item_name="角色名|变体标签"
)
    |
    v
POST /api/image-edit → 创建 grid_image_tasks 记录 (item_type=7)
    |
    v
APScheduler 轮询 → SUCCESS → 下载图片
    |
    v
cron_task_manager: item_type==7 分支
    |
    v
解析 item_name → character_name + variant_label
    |
    v
追加 {id, label, url} 到角色 JSON 的 reference_images 数组
```

### 1.1 三个4宫格包装函数

**位置**：`script_writer_core/mcp_tool.py`

| 函数 | 行号 | item_type | 返回字段名 |
|---|---|---|---|
| `generate_4grid_character_images` | `:2829` | `4`（角色四宫格） | `characters` |
| `generate_4grid_location_images` | `:2862` | `5`（场景四宫格） | `locations` |
| `generate_4grid_prop_images` | `:2895` | `6`（道具四宫格） | `props` |

这三个函数是**完全一致的包装逻辑**：
- 验证 `item_names` 和 `prompts` 各为 4 个元素
- 调用 `generate_4grid_images`，传入对应 `item_type`
- 对返回结果做字段名转换（`items` → `characters`/`locations`/`props`）

### 2. generate_4grid_images（核心函数）

**位置**：`script_writer_core/mcp_tool.py:2705`

**关键逻辑**：
1. 参数校验：必须是 4 个名称 + 4 个提示词
2. **防覆盖检查**：遍历 4 个名称，若 JSON 中已有 `reference_image`，直接拒绝（`force_update_exist_image=False`）
   - 例外：名称为 `placeholder` 或 `pure black background` 时跳过检查
3. **构建 JSON prompt**：
   ```json
   {
     "grid_layout": "2x2",
     "grid_aspect_ratio": "16:9",
     "global_watermark": "",
     "shots": [
       {"shot_number": "Shot 1", "prompt_text": "..."},
       {"shot_number": "Shot 2", "prompt_text": "..."},
       {"shot_number": "Shot 3", "prompt_text": "..."},
       {"shot_number": "Shot 4", "prompt_text": "..."}
     ]
   }
   ```
4. 将 4 个名称用逗号拼接为 `combined_item_name`
5. 调用 `generate_text_to_image(is_grid=True, grid_size=GridConfig.SIZE_2X2, grid_layout="2x2", grid_item_names=item_names)`
   - 注意：`grid_size` / `grid_layout` 为数据库 NOT NULL 列，必须显式传入；
     漏传会导致 `None` 穿透到 INSERT，绕过 DB DEFAULT 与模型默认值，触发 `Column 'grid_size' cannot be null`。

> **兜底保障（2026-07 修复）**：`GridImageTasksModel.create`（`model/grid_image_tasks.py`）在构造 INSERT 前对
> `grid_size`/`grid_layout` 做了 `None` 兜底（缺省归一化为 `GridConfig.SIZE_2X2` / `'2x2'`，与 DB DEFAULT 一致）。
> 因此**所有上游路径**（普通单图 item_type=1/2/3、通用任务 item_type=0、宫格 item_type=4/5/6/8、图生图 edit_image）
> 均不再可能写入 NULL，上述报错在底层被彻底拦截。上游调用方仍应显式传参以保持语义清晰，但底层兜底确保即使漏传也不会报错。
> 安全性说明：对普通单图/通用任务兜底为 4 不影响行为——下游切图回写的权威开关是
> `ItemType.is_grid(item_type)`（仅 item_type=4/5/6/8 为宫格），`grid_size` 在非宫格路径上是不参与判断的死值，
> 且 4 本就是这些任务的历史既定值。

### 3. generate_text_to_image（底层生图函数）

**位置**：`script_writer_core/mcp_tool.py:2491`

**流程**：
1. 读取用户配置的生图模型 `task_id`（`_get_text_to_image_task_id`）
2. 校验 `auth_token`、`prompt`、`item_type`（必须是 1-6）
3. 单图类型（1/2/3）且非宫格时，打印警告提示建议使用 4宫格函数
4. 检查是否已有正在进行的任务（`is_item_generating`）
5. 检查是否已存在参考图（除非 `force_update_exist_image=True`）
6. 获取 `comfyui_base_url_inner`（避免内网无法访问问题）
7. **确定 `image_size`**：
   - `is_grid=True`：取模型 `supported_sizes[-1]`（最大尺寸，如 4K/3K/2K）
   - Agent 指定 `image_size`：校验是否在 `supported_sizes` 中
   - 未指定且非宫格：不设置，使用模型默认尺寸
8. **计算预估算力**：通过 `get_computing_power_for_task(task_id, context={'resolution': image_size})`
9. **发起 HTTP 请求**：
   ```python
   request_data = {
       'prompt': prompt,
       'task_id': text_to_image_task_id,
       'aspect_ratio': aspect_ratio,
       'count': count,
       'user_id': user_id,
       'auth_token': auth_token,
       'image_size': ...  # 按上述逻辑确定
   }
   ```
10. 请求成功返回 `project_ids`，返回值包含 `computing_power_required`、`computing_power_total`、`image_size_used`
11. 若指定了 `item_type` 和 `item_name`，调用 `TaskManager.create_image_task` 创建后台任务
12. 请求失败（如算力不足）：解析错误信息，返回结构化的 `computing_power_required`、`computing_power_available`、`shortage`

---

## HTTP 请求与认证

| 项目 | 说明 |
|---|---|
| HTTP 库 | `requests`（**同步调用**） |
| Method | `POST` |
| URL | `{comfyui_base_url_inner}/api/text-to-image` |
| 请求格式 | `Form` 表单（`data=`，非 `json=`） |
| 超时 | 30 秒 |

### 请求参数

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `prompt` | str | 是 | 图片描述，4宫格时为 JSON 字符串 |
| `task_id` | int | 是 | 生图模型配置 ID |
| `aspect_ratio` | str | 否 | 默认 `"16:9"` |
| `count` | int | 否 | 默认 `1` |
| `user_id` | str | 是 | 用户 ID |
| `auth_token` | str | 是 | 认证令牌 |
| `image_size` | str | 否 | 4宫格时自动传入模型最大尺寸；单图时可由 Agent 指定（如 `"1K"`/`"2K"`/`"3K"`/`"4K"`） |

### auth_token 流转

```text
前端传入 → ChatSession 存储 → Agent 执行工具时传入
    → MCP Tool 作为 Form 参数 → 后端 /api/text-to-image
    → 存入 grid_image_tasks 表 → 轮询时作为 query param 调用 /api/get-status
```

**⚠️ 注意**：`generate_text_to_image` 在异步上下文中使用 `requests.post` 同步请求，会阻塞事件循环。这是当前已知实现，后续改造需重点优化。

---

## 后端接口处理

### POST /api/text-to-image

**位置**：`server.py`

**关键参数**（FastAPI Form）：
- `prompt`, `task_id`, `aspect_ratio`, `image_size`, `count`, `user_id`, `auth_token`

**处理流程**：
1. 通过 `UnifiedConfigRegistry.get_by_id(task_id)` 获取模型配置
2. 验证任务分类为 `TEXT_TO_IMAGE`
3. 算力检查与扣除
4. 创建数据库记录：`AIToolsModel.create`、`TasksModel.create`
5. 返回 `{"project_ids": [...]}`

### GET /api/get-status/{ai_tool_id}

**用途**：后台调度器轮询查询任务状态

**请求**：
```
GET {comfyui_base_url}/api/get-status/{ai_tool_id}?auth_token={auth_token}
```

**响应关键字段**：
```json
{
  "tasks": [
    {
      "status": "SUCCESS" | "FAILED",
      "results": [{"file_url": "..."}]
    }
  ]
}
```

---

## 任务系统

### 数据库表：grid_image_tasks

**模型文件**：`model/grid_image_tasks.py`
**迁移文件**：`alembic/versions/20260325_094948_create_grid_image_tasks_table.py`

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | int | 主键 |
| `task_key` | varchar(255) | 唯一键：`{user_id}_{item_type}_{item_name}` |
| `project_id` | varchar(100) | ComfyUI 返回的任务 ID |
| `item_type` | tinyint | `4`=角色四宫格, `5`=场景四宫格, `6`=道具四宫格 |
| `item_name` | varchar(255) | 逗号分隔的 4 个名称 |
| `user_id` / `world_id` | varchar | 用户/世界观 ID |
| `comfyui_base_url` | varchar(500) | ComfyUI 服务地址 |
| `auth_token` | varchar(500) | 认证令牌 |
| `status` | tinyint | `0`=队列中, `1`=处理中, `2`=完成, `-1`=失败, `-2`=超时, `-3`=取消, `-4`=下载失败 |
| `try_count` / `max_attempts` | int | 尝试次数 / 最大尝试次数（默认 60） |
| `result_url` | varchar(1000) | 结果图片 URL |
| `local_file_path` | varchar(1000) | 本地文件路径 |
| `update_success` | tinyint | 是否成功更新到 item |
| `created_at` / `updated_at` / `completed_at` / `failed_at` | datetime | 时间戳 |

### 状态机

```
QUEUED (0) → PROCESSING (1)
                  |
      ┌──────────┼──────────┐
      v          v          v
  COMPLETED   FAILED    TIMEOUT
    (2)        (-1)      (-2)
```

### 任务创建

**位置**：`script_writer_core/mcp_tool.py:2641`

`generate_text_to_image` 在获得 `project_ids` 后，调用：
```python
task_manager.create_image_task(
    project_id=project_ids[0],
    item_type=item_type,
    item_name=item_name,
    comfyui_base_url=comfyui_base_url,
    auth_token=auth_token,
    user_id=user_id,
    world_id=world_id
)
```

实现位于 `script_writer_core/cron_task_manager.py`（`TaskManager` 类）。

---

## 调度器与轮询

### 调度器配置

**位置**：`task/scheduler.py:295`

使用 APScheduler `BackgroundScheduler`，每隔 **10 秒**执行一次：

```python
scheduler.add_job(
    func=process_grid_image_tasks,
    trigger=IntervalTrigger(seconds=10),
    id='process_grid_image_tasks',
    max_instances=1,
    coalesce=True
)
```

调度器通过文件锁（`scheduler.lock`）保证多进程下仅有一个实例运行。

### 任务处理器

**位置**：`task/grid_image_task.py:280`

`process_grid_image_tasks(app)` 的核心逻辑：

1. 从数据库获取 `status IN (0, 1)` 的待处理任务（上限 50）
2. 对每个任务：
   - `try_count += 1`
   - 若 `try_count > max_attempts`（默认 60，约 10 分钟），标记为 `TIMEOUT`
   - 第一次尝试时更新状态为 `PROCESSING`
   - 发送 HTTP GET 查询 `/api/get-status/{ai_tool_id}?auth_token={auth_token}`
   - **SUCCESS** → 调用 `_handle_task_success(task, comfyui_task_data)`
   - **FAILED** → 记录 `reason`，更新为 `FAILED`
   - 网络异常（`requests.RequestException`）→ **不更新状态**，下次轮询继续重试
3. 清理 7 天前的已完成/失败任务

### 成功处理逻辑

**位置**：`task/grid_image_task.py:123`

`_handle_task_success`：
1. 从 `results[0].file_url` 获取图片地址
2. **下载图片**：`_download_and_store_image`
   - 若 `image.enable_download=True`，下载到本地；否则直接使用远程 URL
   - 4宫格类型（4/5/6）强制下载逻辑已存在
   - 原始大图存入 `upload/{character|location|props}/temp`
3. **4宫格切分**：
   - 解析 `item_name` 为 4 个名称
   - 调用 `ImageGridSplitter.split_2x2_grid`
   - 子图保存到 `upload/{character|location|props}/pic`
   - 文件名使用 UUID
4. **更新 JSON**：
   - 依次调用 `mcp_tool.update_character_json` / `update_location_json` / `update_prop_json`
   - 为每个项目写入 `reference_image` 字段
5. 更新数据库状态为 `COMPLETED`
6. 同步状态到文件系统：`{user_id}/{world_id}/task_status/task_status.json`

---

## 图片下载与 4宫格切分

### 下载与存储

**位置**：`task/grid_image_task.py:21`

`_download_and_store_image(file_url, item_type, comfyui_base_url)`：

| item_type | 临时目录（原始大图） |
|---|---|
| `4`（角色四宫格） | `upload/character/temp` |
| `5`（场景四宫格） | `upload/location/temp` |
| `6`（道具四宫格） | `upload/props/temp` |

- 支持本地路径和远程 URL 两种来源
- 本地路径会做安全校验（禁止 `..`、限制在项目根目录内）

### 4宫格切分

**位置**：`script_writer_core/image_grid_splitter.py:14`

`ImageGridSplitter.split_2x2_grid(grid_image_path, output_dir, output_names, output_format)`：

- 使用 PIL 打开大图
- 按宽高各半切分为 4 个子图
- 顺序：**左上（Shot 1）、右上（Shot 2）、左下（Shot 3）、右下（Shot 4）**
- 子图保存为 PNG 格式
- 返回切分后的 4 个文件路径列表

```python
regions = [
    (0, 0, sub_width, sub_height),              # 左上 (Shot 1)
    (sub_width, 0, width, sub_height),          # 右上 (Shot 2)
    (0, sub_height, sub_width, height),         # 左下 (Shot 3)
    (sub_width, sub_height, width, height)      # 右下 (Shot 4)
]
```

---

## 驱动与模型

### 驱动架构

- **基类**：`task/visual_drivers/base_video_driver.py` — `BaseVideoDriver`
- **工厂**：`task/visual_drivers/driver_factory.py` — `VideoDriverFactory`
- **注册位置**：`config/unified_config.py`

### 支持宫格生图的模型

以下模型配置中 `supports_grid_image=True`：

| 模型名称 | task_id | 供应商 | 驱动类 | 同步/异步 |
|---|---|---|---|---|
| nano-banana-Pro (Gemini 3 Pro) | 7 | 多米 | `GeminiDuomiV1Driver` | 异步（需轮询） |
| nano-banana-2 (Gemini 3.1 Flash) | 17 | 多米 | `GeminiDuomiV1Driver` | 异步（需轮询） |
| Seedream 5.0 | 16 | 火山引擎 | `Seedream5VolcengineV1Driver` | 同步 |
| Seedream 4.5 | 18 | 火山引擎 | `Seedream5VolcengineV1Driver` | 同步 |
| GPT Image 2 | 25/26 | 多米/聚合 | `GptImageDuomiV1Driver` | 视站点而定 |

**驱动差异**：
- **Gemini**：异步 API，提交后返回 `task_id`，需通过 `check_status` 轮询
- **Seedream**：同步 API，一次请求直接返回图片 URL
- **GPT Image 2**：根据具体站点配置，可能同步或异步

4宫格生图通过 `is_grid=True` 自动传入 `image_size` 为模型支持的最大尺寸（如 4K/3K/2K，取决于所选模型），确保大图有足够分辨率供切分。

---

## 类型常量

**位置**：`script_writer_core/constant.py:7`

```python
class ItemType:
    CHARACTER = 1       # 角色
    LOCATION = 2        # 场景
    PROP = 3            # 道具
    CHARACTER_GRID = 4  # 角色四宫格
    LOCATION_GRID = 5   # 场景四宫格
    PROP_GRID = 6       # 道具四宫格
    CHARACTER_VARIANT = 7  # 角色变体图

    GRID_MAP = {
        4: {'name': 'character_grid', 'name_cn': '角色四宫格', 'base_type': 1},
        5: {'name': 'location_grid', 'name_cn': '场景四宫格', 'base_type': 2},
        6: {'name': 'prop_grid',   'name_cn': '道具四宫格', 'base_type': 3},
    }
```

`base_type` 用于映射宫格类型到单图类型，以便在 `_handle_task_success` 中调用对应的 `update_xxx_json`。

---

## 任务状态查询

### get_task_status

**位置**：`script_writer_core/mcp_tool.py:93`

```python
def get_task_status(user_id, world_id, auth_token, item_type, item_name)
```

**⚠️ 重要限制**：该函数仅支持**单图生成任务**（`generate_text_to_image` 生成单张角色/场景/道具图）的状态查询，**不支持 4宫格任务查询**。

**原理**：
- 读取文件系统状态：`{user_id}/{world_id}/task_status/task_status.json`
- 查找指定 `item_type` + `item_name` 的状态记录

4宫格任务的状态需直接查询 `grid_image_tasks` 表，或通过观察 JSON 文件中 `reference_image` 字段是否被更新来判断。

---

## 自动重试机制

### 概述

宫格生图支持两级重试机制：

1. **实现方切换**（企业版）：当一个实现方（供应商）失败时，自动尝试下一个可用实现方。复用 `visual_task.py` 的 enterprise retry pipeline（`retry_handler.py` → `implementation_retry_driver.py`），无需额外配置。
2. **任务重试**（兜底）：当所有实现方都失败后，`process_grid_image_tasks` 自动创建新的 ai_tools 重新提交，直到达到最大重试次数。

### 重试流程

```
ai_tools 失败
    ↓
visual_task.py: _check_task_status → _handle_task_failure → enterprise handler
    ↓ 有替代实现方?
YES → 创建 before_finish pipeline steps
    → ai_tools.status = WAITING_BEFORE_FINISH
    → implementation_retry_driver 切换实现方
    → ai_tools.status = PENDING → 重新提交
    ↓
grid_image_task.py 轮询 → 检测到 WAITING_BEFORE_FINISH → 跳过（避免竞争）
    ↓ 新实现方成功
grid_image_task.py 轮询到 SUCCESS → 更新 JSON 文件
    ↓ 所有实现方都失败
_handle_task_failure 直接标记 FAILED + 退费
    ↓
grid_image_task.py 检测到 FAILED（非 WAITING_BEFORE_FINISH）
    ↓ retry_count < max_retries 且 prompt/task_config_id 存在?
YES → _resubmit_image_request → POST /api/text-to-image → 新建 ai_tools（扣费）
    → grid_image_tasks.reset_for_retry(new_project_id)
    → 继续监控新 ai_tools
    ↓ NO
grid_image_tasks 标记为终态 FAILED
```

### 两个调度器的竞争处理

`visual_task.py`（每5秒）和 `grid_image_task.py`（每10秒）都轮询同一任务。当任务 FAILED 时：
- `visual_task.py` 先检测到 → 触发 enterprise retry → `ai_tools.status = WAITING_BEFORE_FINISH`
- `grid_image_task.py` 后检测到 → 检查 `ai_tools.status == WAITING_BEFORE_FINISH` → 跳过处理

### 数据库字段（迁移：`no_93_20260604_add_image_auto_retry.py`）

| 字段 | 类型 | 说明 |
|---|---|---|
| `prompt` | text | 生图提示词（用于重试时重新提交） |
| `task_config_id` | varchar(100) | 生图模型配置 ID |
| `aspect_ratio` | varchar(20) | 图片宽高比 |
| `image_size` | varchar(20) | 图片尺寸 |
| `is_grid` | tinyint | 是否为宫格生成（0/1） |
| `retry_count` | int | 已重试次数（默认 0） |
| `max_retries` | int | 最大重试次数（默认 0=不重试） |

### 相关代码

| 文件 | 函数/方法 | 说明 |
|---|---|---|
| `enterprise/task/retry_handler.py` | `handle_failure_with_retry` | 企业版失败处理器，创建 before_finish 重试步骤 |
| `task/pipeline_drivers/implementation_retry_driver.py` | `execute` | 切换实现方并重置 ai_tools 状态 |
| `task/grid_image_task.py` | `_resubmit_image_request` | 调用 `/api/text-to-image` 创建新 ai_tools（兜底重试） |
| `task/grid_image_task.py` | `process_grid_image_tasks` | 检测 FAILED 并触发重试；检测 WAITING_BEFORE_FINISH 时跳过 |
| `model/grid_image_tasks.py` | `reset_for_retry` | 重置任务状态、更新 project_id |
| `task/visual_task.py` | `_handle_task_failure` | 统一失败处理入口 |

---

## 注意事项与已知问题

1. **同步阻塞风险**：`generate_text_to_image` 使用 `requests.post` 同步发起 HTTP 请求。若该 MCP 工具在异步事件循环中被调用，会阻塞整个事件循环。这是后续改造的首要优化点。

2. **状态查询局限**：`get_task_status` 不支持 4宫格任务，Agent 无法通过现有工具查询 4宫格生成进度。

3. **覆盖保护**：4宫格入口中 `force_update_exist_image` 固定为 `False`。若 4 个项目中任意一个已有 `reference_image`，整个请求会被拒绝，需人工确认后通过单图接口强制更新。

4. **占位符跳过**：名称为 `placeholder` 或 `pure black background` 的项目在覆盖检查中被跳过，允许后续替换。

5. **图片下载配置**：`image.enable_download` 默认关闭，但 4宫格类型强制启用下载（否则无法本地切分）。

6. **单进程调度**：`task/scheduler.py` 使用文件锁确保多进程部署时只有一个 scheduler 实例运行宫格任务轮询。

7. **Agent 算力感知**：Agent 在生图前应调用 `get_text_to_image_model_info` 和 `get_user_computing_power` 预估成本。生成成功后返回值包含 `computing_power_required` 和 `computing_power_total`；算力不足时返回结构化的 `shortage` 信息。

8. **模型动态切换**：用户可在前端切换生图模型（如 GPT Image 2 → Seedream 5.0），不同模型的算力价格和支持尺寸不同。`generate_text_to_image` 通过 `_get_text_to_image_task_id` 动态读取用户选择。

---

## 相关文件清单

### 核心代码

| 文件 | 说明 |
|---|---|
| `script_writer_core/mcp_tool.py:2829` | `generate_4grid_character_images` |
| `script_writer_core/mcp_tool.py:2862` | `generate_4grid_location_images` |
| `script_writer_core/mcp_tool.py:2895` | `generate_4grid_prop_images` |
| `script_writer_core/mcp_tool.py:2705` | `generate_4grid_images`（核心函数） |
| `script_writer_core/mcp_tool.py:2491` | `generate_text_to_image`（底层生图） |
| `script_writer_core/mcp_tool.py` | `generate_character_variant_image`（角色变体图生成） |
| `script_writer_core/mcp_tool.py:93` | `get_task_status`（状态查询，不支持4宫格） |
| `script_writer_core/mcp_tool.py` | `get_text_to_image_model_info`（模型信息查询） |
| `script_writer_core/mcp_tool.py` | `get_user_computing_power`（用户算力余额查询） |
| `script_writer_core/agents/tool_executor.py` | 工具执行器，工具名到函数映射 |
| `script_writer_core/constant.py:7` | `ItemType` 常量定义 |
| `script_writer_core/image_grid_splitter.py:14` | `ImageGridSplitter` 切分工具 |
| `script_writer_core/cron_task_manager.py` | `TaskManager` 任务创建与管理 |

### 任务调度

| 文件 | 说明 |
|---|---|
| `task/scheduler.py:295` | APScheduler 配置，每 10 秒轮询宫格任务 |
| `task/grid_image_task.py:280` | `process_grid_image_tasks` 处理器 |
| `task/grid_image_task.py:123` | `_handle_task_success` 成功回调 |
| `task/grid_image_task.py:21` | `_download_and_store_image` 下载逻辑 |

### 后端接口

| 文件 | 说明 |
|---|---|
| `server.py` | `POST /api/text-to-image`、`GET /api/get-status/{ai_tool_id}` |
| `api/script_writer.py` | FastAPI Router，Agent 任务入口 |

### 数据模型

| 文件 | 说明 |
|---|---|
| `model/grid_image_tasks.py` | `GridImageTasksModel` 数据库模型 |
| `alembic/versions/20260325_094948_create_grid_image_tasks_table.py` | 迁移脚本 |

### 驱动与配置

| 文件 | 说明 |
|---|---|
| `config/unified_config.py` | 模型配置、算力、驱动映射 |
| `task/visual_drivers/base_video_driver.py` | 驱动基类 |
| `task/visual_drivers/driver_factory.py` | 驱动工厂 |
| `task/visual_drivers/gemini_duomi_v1_driver.py` | Gemini 驱动 |
| `task/visual_drivers/seedream_volcengine_v1_driver.py` | Seedream 驱动 |
| `task/visual_drivers/gpt_image_duomi_v1_driver.py` | GPT Image 2 驱动 |

---

## 更新记录

- **2026-05-06**：初版文档，整理 Agent 4宫格生图完整链路
- **2026-05-06**：新增算力感知工具（`get_text_to_image_model_info`、`get_user_computing_power`），更新 `generate_text_to_image` 支持 `image_size` 参数和算力返回，修正 "4k" 硬编码描述
- **2026-06-04**：新增自动重试机制文档；grid image 跳过 pipeline before_finish 重试，由 `process_grid_image_tasks` 独立管理
- **2026-06-08**：移除 grid image 跳过逻辑，宫格生图现在支持失败后自动切换实现方；增加两个调度器竞争处理说明
