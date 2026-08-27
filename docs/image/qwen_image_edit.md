# Qwen Image Edit

空壳图片编辑任务类型。本阶段只注册 `task_type`，不接入供应商驱动。

与隐藏任务 `qwen-multi-angle`（`TaskTypeId=24`，RunningHub 多角度工作流）不是同一个模型。

## 任务配置

| 字段 | 值 |
|------|-----|
| `TaskTypeId` | `38`（`TaskTypeId.QWEN_IMAGE_EDIT`） |
| `key` / `short_key` | `qwen-image-edit` |
| `name` | Qwen Image Edit |
| `category` | `image_edit`（不支持文生图） |
| `driver_name` | `qwen_image_edit` |
| `implementation` | `qwen_image_edit_pending`（占位字符串，未注册驱动） |
| `implementations` | `[]` |
| 算力 | `1`（扣费不能为 0；可在实现方管理调整） |
| 比例 | 无（跟随原图，工作流无比例节点） |
| 分辨率 | 无（`ImageScaleToTotalPixels` 固定约 1MP） |
| 参考图 | 最多 3 张 |

定义在 `config/unified_config.py` 的 `ALL_TASK_CONFIGS`。`config/constant.py` 的 `DRIVER_IMPLEMENTATION_MAPPING` 对该 DriverKey 为空列表。

参考 ComfyUI 工作流 `qwen_image_edit_api_0824.json`：输入图经 `ImageScaleToTotalPixels(megapixels=1)` 按原图比例缩到约 100 万像素，没有独立的比例或分辨率参数，因此 `supported_ratios` / `supported_sizes` 均为空。前端在空列表时隐藏对应选择器，不回落到 1K/2K 或常见比例。

## 当前行为

- `/api/system/task-configs` 会返回该任务，图片编辑模型列表可见。
- 无已注册驱动时，`get_driver_availability` 标记为不可用，前端显示「未配置」并禁用提交。
- `POST /api/image-edit` 接受 `task_id=38`。未绑定实现方时扣 1 点算力；绑定接口模块后由该实现方出图。

## 后续接入实现方

不要在 `task/visual_drivers/` 写死 Qwen 核心驱动。用后台 **接口模块 → 本地 ComfyUI**：

1. 对接类型选「本地 ComfyUI」
2. 填写该 GPU 机器的 ComfyUI 地址（默认 `http://localhost:8188/`）
3. 选择 `qwen_image_edit_api_0824.json`（ComfyUI Save API Format）
4. 审批并激活模块后，在「模型接入」把 `image_edit` 绑到本任务（task_id=38）

当前工作流只有 1 个 `LoadImage`，绑定时注意参考图数量；需要 2～3 张图时换一份带多个 LoadImage 的 API JSON 再生成一个模块。
