# Storyboard 九宫格 i2i 子场景参考图生成

## 目标

在分镜首帧生成前，先用父场景图作为图生图（i2i）输入，一次合成 3x3 共 9 个子场景参考图，切图后按子场景 `location.id` 回写 `reference_image`。

## 背景：原四宫格与 i2i 缺失

原系统只有 **2x2 四宫格**（纯文生图）：
- `generate_4grid_images()`（`script_writer_core/mcp_tool.py`）→ `generate_text_to_image(is_grid=True)`
- 切图逻辑硬编码 4 格，分布在 4 处路径。
- 宫格链路**完全没有图生图能力**（`generate_text_to_image` 的 `request_data` 无图片字段）。

九宫格 i2i 是在保留四宫格 t2i 的基础上新增的：

| | 四宫格 t2i（原） | 九宫格 i2i（新） |
|---|---|---|
| 端点 | `/api/text-to-image` | `/api/image-edit` |
| 字段名 | `aspect_ratio` | `ratio` |
| 图片输入 | 无 | `ref_image_urls`（逗号串，父场景图） |
| 模型类别 | t2i 模型 | IMAGE_EDIT 模型（含 fallback） |
| grid_size | 4 | 9 |

## Phase 3：通用切图器 + 独立 grid submitter

### 3.1 切图器（`script_writer_core/image_grid_splitter.py`）
新增通用 `split_grid(grid_image_path, output_dir, grid_size, output_names, output_format)`：
- `grid_size ∈ GridConfig.VALID_SIZES (4, 9)`
- 按 `int(sqrt(grid_size))` 推导行列（4→2, 9→3），行优先切分
- `split_2x2_grid` / `split_3x3_grid` 均为 `split_grid` 的便捷包装

### 3.2 独立提交函数（`script_writer_core/mcp_tool.py`）
**不污染 `generate_text_to_image()` 主路径**（修订 B）。新增：

```python
def submit_grid_image_task(user_id, world_id, auth_token, item_names, prompts,
                           item_type, grid_size, mode="text_to_image",
                           target_entity_ids=None) -> Dict
```

两个干净分支：
- `mode="text_to_image"`：复用 `generate_text_to_image`（内部创建 grid task）。
- `mode="image_edit"`：自行发请求到 `/api/image-edit`（复用 `edit_image` 的模型选择/URL 校验逻辑），拿到 project_id 后**显式创建带 grid_type 的 task 记录**（轮询器才能触发宫格切图）。

向后兼容：
- `generate_4grid_images` → `submit_grid_image_task(grid_size=4, mode="text_to_image")`
- `generate_9grid_location_images` → `submit_grid_image_task(grid_size=9, item_type=5, mode="image_edit", target_entity_ids=...)`

### target_entity_ids 贯穿（关键）
`target_entity_ids`（与 `item_names` 等长，placeholder 位为 `None`）是九宫格回写的命脉：
- `submit_grid_image_task` 接收 → 过滤 None 后写入 `target_entity_ids_json`。
- `GridImageTasksModel.has_running_grid_for_entity(id)` 用 `JSON_CONTAINS` 查它 → 决定首帧是否等待。
- 回写阶段（`task/grid_image_task.py` item_type=5）按有效 id 与非 placeholder 名称**按序对齐**回写 `location.reference_image`。
- **不传 target_entity_ids 会导致等待失效 + 回写无法按 id**。

### item_name 列改用展示短 key
`item_name` varchar(255) 不再存 9 个中文名逗号拼接（会超长）。改存短 key：
- 有 target_entity_ids：`loc#100,101,#,103,...`（placeholder 位用 `#`）
- 无（四宫格 t2i）：名称首 8 字符拼接

真实名称落 `item_names_json`，切图/回写统一通过 `GridImageTask.get_item_names_list()` 读取。

### i2i 入库失败语义
i2i 分支 `GridImageTasksModel.create` 失败时**返回 `success=False`**（不再只 warning）。否则上层误认为已提交，但后台无任务记录 → 无法轮询/切图/回写。

### i2i 关键点
- 模型选择：`_resolve_image_edit_task_id()` 复用 `edit_image` 逻辑，用户当前模型不支持 IMAGE_EDIT 时 fallback 到默认 IMAGE_EDIT 模型（id=7）。
- 父图 URL：`_to_public_http_url()` 把本地 `/upload/...` 路径转为公开 http URL（`edit_image` 仅接受 http/https，防 SSRF）。

## Phase 4：grid_image_tasks 表扩展

### 新增列（迁移 `no_111_20260706_grid_tasks_3x3_columns.py`）
| 列 | 类型 | 说明 |
|---|---|---|
| `grid_size` | TINYINT DEFAULT 4 | 宫格总数（4=2x2, 9=3x3） |
| `grid_layout` | VARCHAR(8) DEFAULT '2x2' | 布局描述 |
| `item_names_json` | JSON NULL | 结构化名称列表（真实名称，回写时读取） |
| `target_entity_ids_json` | JSON NULL | 切图回写目标 DB id 列表（过滤 None 后的纯 id，**强制按 id 回写**） |
| `parent_reference_image` | VARCHAR(1000) | i2i 父场景参考图 URL（重试复原） |

旧记录 `grid_size` 默认 4，`grid_layout` 默认 '2x2'，向后兼容。

### task_key 重做
原 `generate_task_key(item_type, item_name)` 把全部名称拼进唯一键，9 名会超长/撞键。九宫格 i2i 用 `grid:{user_id}:{world_id}:{project_id}` 短键（project_id 天然唯一）。四宫格路径保留原 task_key。

### 四条切图路径去硬编码
1. `script_writer_core/image_grid_splitter.py` — 通用 `split_grid`（3.1）
2. `task/grid_image_task.py` `_handle_task_success` — 活跃 DB 轮询器：`grid_size = task.grid_size or 4`，调 `split_grid`，按 `target_entity_ids_json` 的 DB id 回写 location。
3. `script_writer_core/cron_task_manager.py` `_handle_success` — 遗留内存路径：按 item_names 数量推断 grid_size。
4. `server.py` 按需切图端点 — 统一为 `split_grid` 调用。

magic `4` 全部替换。placeholder 格子（`GridConfig.is_placeholder`）跳过回写。

### item_type=5 回写按 id 对齐
回写阶段统一通过 `task.get_item_names_list()`（优先 `item_names_json`）读取真实名称，**不再** `task.item_name.split(',')`（item_name 已是短 key）。`target_entity_ids_json` 在 create 时已过滤 placeholder 的 None，回写时用「有效 id 列表」与「非 placeholder 名称」按序 zip 对齐，逐个调 `LocationModel.update(id, reference_image=url)`。

## Phase 5：按父场景分批提交

`StoryboardLocationBootstrapService.submit_subscene_grids(parsed_data, bootstrap_result, world_id, user_id, auth_token)`：

1. 按父场景分组子场景。
2. **补偿重跑友好（门禁）**：跳过「已有参考图」或「有运行中九宫格任务」的子场景，只提交「缺图且无运行中任务」的。避免重复提交 / 覆盖已生成结果。判定：
   - `_subscene_has_reference_image(db_id, loc)`：查 DB 行 `reference_image`，fallback parsed dict。
   - `_subscene_has_running_grid(db_id)`：`GridImageTasksModel.has_running_grid_for_entity`。
3. 取父 `reference_image` / `reference_images[0].url`；**父无图 → 该批不提交**（标 `missing_parent_reference_image`），子场景后续走 t2i 降级。
4. 不足 9 补 placeholder（不建 location、不回写）；超 9 拆多个 3x3 批。
5. 每子场景 prompt 必含：父场景名/描述/参考图说明 + 子场景名/描述/氛围 + "保持父场景空间结构、色彩、材质、光照连续"。
6. 调 `generate_9grid_location_images(parent_reference_image=<父公开URL>, target_entity_ids=<DB id 列表>)`。

### split 端点门禁
Web（`api/storyboard.py`）与 CLI（`cli_service.py`）入口只需「有 auth_token」即尝试提交（内部精确跳过无需处理的子场景）。**不再用 `created_location_count > 0`** 作为门禁——那样会让「子场景已落库但缺图」的重跑无法补提交。

非阻塞接入 split 端点（`_auto_submit_storyboard_dialogue_voiceovers` 之后），异常不影响主流程。

## 占位符常量

`config/constant.py` 的 `GridConfig`：
```python
PLACEHOLDER_NAMES = frozenset({'placeholder', 'pure black background'})
@classmethod
def is_placeholder(cls, name: str) -> bool
```

切图回写时调用 `GridConfig.is_placeholder(name)` 跳过占位格。
