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
                           target_entity_ids=None,
                           global_visual_guidance=None) -> Dict
```

两个干净分支：
- `mode="text_to_image"`：复用 `generate_text_to_image`（内部创建 grid task）。
- `mode="image_edit"`：自行发请求到 `/api/image-edit`（复用 `edit_image` 的模型选择/URL 校验逻辑），拿到 project_id 后**显式创建带 grid_type 的 task 记录**（轮询器才能触发宫格切图）。

向后兼容：
- `generate_4grid_images` → `submit_grid_image_task(grid_size=4, mode="text_to_image")`
- `generate_9grid_location_images` → `submit_grid_image_task(grid_size=9, item_type=5, mode="image_edit", target_entity_ids=...)`

### global_visual_guidance（宫格级视觉约束）

分镜首帧宫格可传入一次性的根级视觉约束：

```json
{
  "global_visual_guidance": {
    "image_style": "皮克斯3D动画风格",
    "composition_preference": "充满张力的动态平衡构图",
    "application_rule": "适用于所有非空格；单格明确指定的机位、景别、主体位置与构图约束优先。"
  },
  "shots": [
    {"prompt_text": "本格镜头内容，不重复全局画风和构图倾向"}
  ]
}
```

- `image_style` / `composition_preference` 只在 grid 根节点出现一次，减少 2x2/3x3 提示词重复。
- `shots[].prompt_text` 只保留单格镜头、动作、空间位置、局部构图和参考图编号。
- 单格明确构图是硬约束，优先于全局构图倾向；全局画风仍作用于所有非 placeholder 格。
- 参数缺省时不输出该根字段，角色、场景、道具等既有宫格模板保持不变。
- 宫格任务重试直接复用数据库保存的完整 `task.prompt`，根级约束无需新增表字段或迁移。

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
- 参考图 URL：`_to_public_http_url()` 把本地 `/upload/...` 路径转为公开 http URL（`edit_image` 仅接受 http/https，防 SSRF）。对参考图列表逐项转换。
- 分辨率（分镜首帧宫格专用）：按 `grid_size` 选择目标分辨率，4宫格→2K、9宫格→4K（映射常量 `GridConfig.GRID_SIZE_IMAGE_SIZE_MAP`）。`_submit_chunk` 按 grid_size 取映射值传入 `submit_grid_image_task(image_size=...)`，i2i 分支用 `_pick_grid_image_size` 按所选 IMAGE_EDIT 模型的 `supported_sizes` 降级到最接近且不超过目标的档位（如模型只支持 2K/3K、目标 4K → 选 3K），再把 `image_size` 透传到 `/api/image-edit` 请求。该值同时写入 `grid_image_tasks.image_size`，i2i 重试分支（`_resubmit_image_request`）复原时一并带上。角色/场景/道具宫格（t2i）不受此映射影响，仍走 `generate_text_to_image` 的强制最大分辨率逻辑。

### reference_images 泛化设计
i2i 输入从"单一父场景图"泛化为**带角色说明的参考图列表** `reference_images: List[Dict]`，每项 `{"url": str, "role_description": str}`：
- `url`：参考图地址（本地路径或 http URL）
- `role_description`：这张图的角色说明（如"父场景的完整俯瞰图，展示整体空间结构"、"分镜首帧，展示角色站位与镜头构图"）

role_description 被拼进 grid_prompt JSON 的全局说明区（`reference_images_legend` 字段），对所有格子生效：
```json
{
  "grid_layout": "3x3",
  "reference_images_legend": "参考图说明：图1是父场景'主厅'的完整场景图...；各格内容需与参考图保持视觉连续性。",
  "shots": [...]
}
```

这个设计适配多种宫格生图场景：
- **当前**：父场景图 → 子场景九宫格（1 张参考图）
- **当前**：分镜首帧宫格（item_type=8）→ 同一幕下缺失首帧的分镜按 2x2/3x3 批量生成，参考图列表可包含角色、道具、场景，各格 prompt 写明本格使用的图号和空间位置
- **其他**：任意"参考图列表 + 宫格生图"场景

### 分镜级参考图变体

Storyboard 分镜可在 `prompt_json.reference_selections` 中保存角色服装和场景角度选择。效果模式首帧宫格（`item_type=8`）构建每格参考图 manifest 时会调用 `services.storyboard_reference_prompt_service.select_reference_variant_for_asset()`：

- 每个分镜独立读取自己的角色/场景选择，不跨分镜继承。
- 选中 URL 必须仍属于对应资产的 `reference_image` 或 `reference_images`，否则自动回退主参考图。
- `role_description` 会带上变体标签，例如“角色：奶昔，商务服装”或“场景：大厅，右侧视角”。
- manifest 仍按最终 URL 去重并分配图号，LLM 只能使用服务层给出的图号，不能自行推测变体。

## Phase 4：grid_image_tasks 表扩展

### 新增列（迁移 `no_111_20260706_grid_tasks_3x3_columns.py`）
| 列 | 类型 | 说明 |
|---|---|---|
| `grid_size` | TINYINT DEFAULT 4 | 宫格总数（4=2x2, 9=3x3） |
| `grid_layout` | VARCHAR(8) DEFAULT '2x2' | 布局描述 |
| `item_names_json` | JSON NULL | 结构化名称列表（真实名称，回写时读取） |
| `target_entity_ids_json` | JSON NULL | 切图回写目标 DB id 列表（过滤 None 后的纯 id，**强制按 id 回写**） |
| `reference_images` | TEXT NULL | i2i 参考图列表 JSON `[{url, role_description}, ...]`（重试复原） |

旧记录 `grid_size` 默认 4，`grid_layout` 默认 '2x2'，向后兼容。若旧迁移已建 `parent_reference_image`(varchar)，本迁移用 `CHANGE COLUMN` 重命名为 `reference_images`(text)。

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

### item_type=8 分镜首帧宫格回写

`storyboard_first_frame_grid` 使用 `item_type=8`，没有对应的单图 base type。提交时：

- `item_names` 长度必须等于 `grid_size`，placeholder 位写占位名称。
- `target_entity_ids` 也必须等于 `grid_size`，真实格写 `storyboard_scene.id`，placeholder 位写 `None`。
- `submit_grid_image_task()` 会把 `None` 过滤后写入 `target_entity_ids_json`，同时为 item_type=8 创建 `ai_tool_pipeline_steps.step_type=storyboard_first_frame_grid_split`。step params 保存 `grid_task_id`、`grid_size`、`grid_layout`，以及每个格子的 `grid_index/scene_id/batch_item_id/placeholder`。
- 宫格 `ai_tools` 成功后，`task/grid_image_task.py` 只负责下载整张宫格图、写入 `ai_tools.result_url`，然后分发 pipeline step。`StoryboardGridSplitPipelineDriver` 切图后跳过 placeholder，每个真实格创建 `storyboard_scene_asset(asset_type="first_frame")`，调用 `set_selected(scene_id, "first_frame", asset_id)`，并优先按 `batch_item_id` 回写 batch item；老记录缺少 `batch_item_id` 时回退到 `grid_task_id + scene_id`。
- 下载后的整张宫格会先通过 `validate_grid_image(local_file_path, grid_size)` 做几何校验。校验失败时不切图、不写回分镜，而是重新提交同一个宫格任务；`item_type=8` 默认最多重试 2 次，仍失败后才把 grid task 和相关 batch item 标记失败。

### item_type=8 asset 与 ai_tool 的 result_url 优先级（防宫格图回显）

宫格拆分场景下，多个 `storyboard_scene_asset`（单格图）共享同一个 `ai_tool`（宫格生图任务）。两张图的 URL 含义不同：

| 字段 | 内容 | 示例 |
|---|---|---|
| `storyboard_scene_asset.result_url` | **拆分后的单格图**（权威值，driver 切图后写入） | `upload/storyboard/first_frame/xxx.png` |
| `ai_tools.result_url` | **整张宫格图**（dispatch 前写入，供 driver 读取） | `upload/storyboard/temp/1084_xxx.png` |

`api/storyboard.py` 的 `_asset_task_info`（task-status 轮询接口）和 `_enrich_scene_asset_result_urls`（候选资产列表接口）返回首帧 URL 时，**必须以 `asset.result_url` 为准**，仅在 asset 缺失 result_url 时才用 `ai_tool.result_url` 兜底。若无条件用 `ai_tool.result_url` 覆盖，前端轮询 task-status 时会把单格图回退成整张宫格图。

前端 `getSceneAssetCandidateUrl`（`web/js/storyboard/events.js`）的优先级与此一致：`asset.result_url` → `ai_tool.result_url`。

### item_type=8 终态失败回写与 step 调度防护

宫格拆分 step（`storyboard_first_frame_grid_split`）的生命周期有两个易卡死的环节，需特别防护：

**1. 预建 step 不被全局 pipeline 调度器过早 dispatch**

`submit_grid_image_task` 在提交宫格任务时就预建了 `before_finish` 阶段的 split step（status=PENDING），但此时宫格图尚未生成、step params 里没有 `grid_image_path`。全局 pipeline 调度器（`PipelineProcessor.process_all_pending_steps`）每 13 秒扫描一次 PENDING 步骤，若不显式跳过，会在宫格图就绪前 dispatch 该 step，导致 driver 因"缺少宫格图片地址"立即失败。

防护：`process_all_pending_steps` 的 PENDING 分发循环和重试循环都**显式跳过** `PipelineStepType.STORYBOARD_FIRST_FRAME_GRID_SPLIT` 类型的步骤——该步骤的唯一分发者是 `task/grid_image_task.py` 的 `_dispatch_storyboard_first_frame_grid_split`（在宫格图下载成功后调用）。

**2. grid task 终态失败时回写 batch item 与 pipeline step**

grid task 进入终态失败有四条路径，每条都必须调用 `_mark_storyboard_grid_batch_items_failed` 把关联的 `storyboard_image_batch_item`（status=RUNNING）回写为 FAILED，否则 batch item 永久卡在 RUNNING、batch job 永远不结束：

| 路径 | 触发条件 | grid task 终态 |
|---|---|---|
| 超时 | `try_count > max_attempts`（轮询次数耗尽） | TIMEOUT(-2) |
| 生成失败 | ComfyUI 返回 FAILED 且重试耗尽/重试提交失败 | FAILED(-1) |
| 异常 | 轮询/处理过程抛未预期异常 | FAILED(-1) |
| 下载/处理失败 | `_handle_task_success` 内下载或写回抛异常 | DOWNLOAD_FAILED(-4) |

前 3 条路径由 `_mark_storyboard_grid_batch_items_failed` 统一回写；DOWNLOAD_FAILED 分支（在 `_handle_task_success` 的 except 中）额外调用 `_fail_pending_grid_split_step_for_task` 单独回写 pipeline step。

`_mark_storyboard_grid_batch_items_failed` 只处理 `item_type=STORYBOARD_FIRST_FRAME_GRID`（不误伤角色/场景/道具宫格），按 `task.get_target_entity_ids_list()` 遍历每个 scene，通过 `find_running_by_grid_task(grid_task_id, scene_id)` 定位 RUNNING 的 batch item 并回写 FAILED。单个 scene 回写异常不影响其余 scene。

回写 batch item 后，该函数**同步终止绑定的 pipeline step**（调 `PipelineStepModel.fail_pending_grid_split_step(ai_tool_id, error_message)`，把同一 `ai_tool_id` 下仍 PENDING 的 `storyboard_first_frame_grid_split` step 标记为 FAILED）。这一步至关重要：若 grid task 失败但 pipeline step 仍 PENDING，全局调度器（每 13s）会反复扫描到它又无条件 skip，导致「Skip storyboard grid split step N」日志永久刷屏。回写是幂等的——只更新 `status=PENDING` 的行，已 COMPLETED/FAILED 的不受影响。

**3. 孤立 step 兜底清理**

即便有了第 2 点的失败回写，仍可能残留历史孤儿（旧版本未回写、或异常路径漏写）：step 仍 PENDING，但绑定的 `grid_image_tasks` 行已进入失败终态。`process_grid_image_tasks`（每 10s）每轮在 `_recover_late_completed_terminal_tasks()` 之后调用 `_cleanup_orphan_grid_split_steps()`：JOIN `ai_tool_pipeline_steps`（PENDING grid split）与 `grid_image_tasks`（`ai_tool_id = CAST(project_id AS UNSIGNED)`），凡是 grid task 已 FAILED/TIMEOUT/DOWNLOAD_FAILED/CANCELLED 的 step，批量调 `PipelineStepModel.fail_steps_by_ids` 标记 FAILED。扫描上限 `GridConfig.GRID_SPLIT_ORPHAN_CLEANUP_LIMIT`（默认 50），异常被吞掉不影响主轮询。部署后存量孤儿会在几分钟内自动清完，日志停止。

**4. dispatch_step 同步完成补阶段完成检查**

`storyboard_first_frame_grid_split` 步骤从 PENDING→PROCESSING→COMPLETED 全程同步发生在一次 `dispatch_step` 调用里，瞬间结束，从不经过全局调度器的 PROCESSING 轮询分支。因此 `dispatch_step` 的"步骤直接完成"分支在标记 COMPLETED 后，需显式调用 `_check_ai_tool_stage_completion(ai_tool_id, stage)`，否则 `before_finish` 阶段完成判定无法触发。


所有 grid 类型（4/5/6/8）在 `task/grid_image_task.py` 中都强制下载原图到本地再切图，不依赖 `image.enable_download`。E2E/mock 路径使用 `ItemType.is_grid()` 判断是否返回 grid mock 图片，避免新增 grid type 拿到单图 mock。

## Phase 5：顶层与子场景分层提交

`StoryboardLocationBootstrapService.submit_subscene_grids(parsed_data, bootstrap_result, world_id, user_id, auth_token)`：

1. 将缺图场景分为顶层场景（`parent_id=null`）与有父级的子场景。
2. 缺图顶层场景按解析顺序每 4 个组成 2x2 文生图宫格，不足 4 个补 `placeholder`；调用 `generate_4grid_location_images(..., target_entity_ids=...)`，使后台切图按数据库 `location.id` 回写 `reference_image`。
3. 按父场景分组子场景，继续走父图 3x3 i2i。
4. **补偿重跑友好（门禁）**：始终跳过「已有参考图」或「有运行中宫格任务」的场景，只提交「缺图且无运行中任务」的。`force_overwrite_subscene_grids` / `force_overwrite=True` 为兼容旧调用保留，但不再生效；已有参考图一律不会被重新提交或覆盖。判定：
   - `_subscene_has_reference_image(db_id, loc)`：查 DB 行 `reference_image`，fallback parsed dict。
   - `_subscene_has_running_grid(db_id)`：`GridImageTasksModel.has_running_grid_for_entity`。
5. 子场景批次取父 `reference_image` / `reference_images[0].url`；父图尚未就绪时标记 `missing_parent_reference_image`，等待后续预检重新推进。
6. 子场景不足 9 个补 `placeholder`（不建 location、不回写）；超过 9 个拆成多个 3x3 批次。
7. 每个子场景 prompt 必含：父场景名/描述/参考图说明 + 子场景名/描述/氛围 + "保持父场景空间结构、色彩、材质、光照连续"。
8. 调 `generate_9grid_location_images(reference_images=[{url, role_description}], target_entity_ids=<DB id 列表>)`。bootstrap 构造的 reference_images 含父场景图，role_description 为"父场景'{name}'的完整场景图，展示整体空间结构、色彩、材质、光照，各子场景需保持与其连续性"。

### split 端点门禁
Web（`api/storyboard.py`）与 CLI（`cli_service.py`）入口只需「有 auth_token」即尝试提交（内部精确跳过无需处理的子场景）。**不再用 `created_location_count > 0`** 作为门禁——那样会让「子场景已落库但缺图」的重跑无法补提交。
Web split 入口会先将 `Authorization: Bearer <token>` 规范化为裸 token，再传给剧本解析与九宫格 i2i；否则内部 `/api/image-edit` 再拼接 `Bearer` 时会变成 `Bearer Bearer <token>`，导致鉴权失败且不会创建 `grid_image_tasks`。

非阻塞接入 split 端点（`_auto_submit_storyboard_dialogue_voiceovers` 之后），异常不影响主流程。

## 占位符常量

`config/constant.py` 的 `GridConfig`：
```python
PLACEHOLDER_NAMES = frozenset({'placeholder', 'pure black background'})
@classmethod
def is_placeholder(cls, name: str) -> bool
```

切图回写时调用 `GridConfig.is_placeholder(name)` 跳过占位格。
