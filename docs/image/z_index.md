# Z-index

空壳生图任务类型。本阶段只注册 `task_type`（模型条目可见），不接入任何实现方与驱动。

## 任务配置

| 字段 | 值 |
|------|-----|
| `TaskTypeId` | `48`（`TaskTypeId.Z_INDEX_IMAGE_EDIT`） |
| `key` / `short_key` | `z-index-image-edit` / `z-index` |
| `name` | Z-index 图片编辑 |
| `model_name` | Z-index |
| `category` | `image_edit`（同时挂 `text_to_image` 类目） |
| `provider` | `local`（占位，接入供应商后再改） |
| `driver_name` | `z_index_image_edit` |
| `implementation` | `z_index_pending`（占位字符串，未注册驱动） |
| `implementations` | `[]` |
| 算力 | `1`（扣费不能为 0；接入供应商后再按实际定价调整） |
| 比例 / 分辨率 | 空（接入实现方后再配置） |

定义在 `config/unified_config.py` 的 `ALL_TASK_CONFIGS`。`config/constant.py` 的 `DRIVER_IMPLEMENTATION_MAPPING` 对该 DriverKey 为空列表（与 Qwen Image Edit 空壳同模式）。

## 当前行为

- `/api/system/task-configs` 会返回该任务，图片编辑 / 文生图模型列表可见。
- 无已注册驱动时，`get_driver_availability` 标记为不可用，前端显示「未配置」并禁用提交。

## 后续接入实现方

接入时补齐以下内容即可：

1. `config/unified_config.py`：新增 `DriverImplementation` / `DriverImplementationId` 与 `ALL_IMPLEMENTATIONS` 配置，填充任务条目的 `implementation` / `implementations`、`supported_ratios` / `supported_sizes`、真实算力
2. `config/constant.py`：`DRIVER_IMPLEMENTATION_MAPPING` 填充该 DriverKey 的实现方列表
3. `task/visual_drivers/`：新增驱动类并在 `driver_factory.py` 注册
4. 供应商接入后把 `provider` 从 `local` 改为实际供应商
