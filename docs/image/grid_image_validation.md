# 宫格图片几何校验

## 背景

宫格生图结果不能直接按宽高均分切图。模型可能生成“看起来像拼图”的非均匀布局，例如上半部分是 2 列、底部是一张横跨整行的大图。此类图片如果直接按中线切分，会把错误内容写回角色、场景或道具参考图。

为避免误切，切图前新增轻量级几何校验：只判断图片是否为均匀 `2x2` 或 `3x3` 宫格，不做语义理解。

## 实现位置

| 文件 | 说明 |
|---|---|
| `utils/image_grid_validator.py` | 宫格几何校验器，返回 `GridValidationResult` |
| `script_writer_core/image_grid_splitter.py` | `split_grid(..., validate=True)` 在创建输出目录前执行校验 |
| `config/constant.py` | `GridConfig` 中维护校验阈值 |
| `tests/utils/test_image_grid_validator.py` | 合成图单测，覆盖正确 2x2、正确 3x3、伪 2x2 拒绝、切图器拒绝、占位格宫格通过 |

## 判定逻辑（双轨，模式 B）

校验采用**双轨 OR**：先跑严格校验（对全内容宫格图零回归），仅当严格校验失败、且图像确实含占位格时，再尝试占位格友好旁路。两条轨道任一通过即判有效。

### 轨道一：严格校验（`_strict_validate`）

校验器会先把图片最长边缩放到 `GridConfig.VALIDATION_MAX_SCAN_SIZE`，然后只在目标宫格理论分割线附近搜索：

- `2x2`：检测 `x = W/2`、`y = H/2`
- `3x3`：检测 `x = W/3, 2W/3`、`y = H/3, 2H/3`

每条分割线会计算：

- 位置是否落在理论位置附近，容忍比例为 `VALIDATION_POSITION_TOLERANCE_RATIO`
- 分割线证据是否连续贯穿图片，阈值为固定标量 `VALIDATION_MIN_LINE_COVERAGE`（0.75）
- 各 cell 的宽高是否均匀，阈值为固定标量 `VALIDATION_MIN_CELL_UNIFORMITY`（0.90）

分割线证据使用窄线采样，综合白/黑分隔线、亮/暗脊线和两侧对比。采样带内按列取极值（亮线取 max、暗线取 min）而非均值，避免 AI 生成的 1-2px 灰白细线在缩略图上被均值稀释到阈值以下导致误判。

严格校验的阈值**绝不放宽**——它承担拦截"非宫格图"（模型未生成宫格分割线时输出的普通单图）的职责。普通照片的分割线 coverage 本就能达到 0.6~0.8，若降到 0.60 会误放行。占位格的容错只在轨道二（旁路）内体现，旁路用更宽松的 `VALIDATION_PLACEHOLDER_TOLERANT_MIN_COVERAGE`（0.60）/ `VALIDATION_PLACEHOLDER_TOLERANT_MIN_UNIFORMITY`（0.80），且仅对已确认含占位格的图生效，普通照片根本进不了旁路。

### 轨道二：占位格友好旁路（`_validate_with_placeholder_tolerance`）

**背景**：批量生图常凑不满 `grid_size` 个真实场景，缺位用纯黑/纯白占位格补齐（prompt 即要求"纯黑背景占位"）。占位格区域没有分割线特征，原严格校验会把"占位区无线"误判为"宫格不合规"。例如 1 真实内容 + 8 黑色占位的 3x3，横线在占位区检测不到，导致 cell uniformity 0.82 < 0.90 误判失败。

**触发条件**：严格校验失败 + 图像含至少 1 个占位格 + 至少 1 个非占位格（全占位=纯色图仍判失败）。

**占位格识别**：用灰度**中位数**（而非标准差）判定。纯黑占位格 median≈0、纯白 median≈255，阈值 `VALIDATION_PLACEHOLDER_DARK_MAX=15` / `VALIDATION_PLACEHOLDER_BRIGHT_MIN=240`。中位数不受占位格里穿过的白色分割线干扰（分割线像素占比小，不影响中位数），而标准差会被分割线拉高（实测占位格 std 可达 40+），故弃用 std。

**占位区免惩罚**：每条理论分割线按垂直方向 cell 边界分段。段两侧 cell 都是占位 → 该段没有分割线属正常，用理论位置兜底、不计 coverage；段内有内容 → 正常检测并统计 coverage。最终位置取有内容段的检测值（占位段贡献理论值），coverage 取有内容段的均值。全占位的线直接用理论位置视为通过。

旁路通过的 reason 标注 `"passed via placeholder-tolerant path"`，便于日志区分。两条轨道均失败时维持严格校验的失败结论（保留更具体的失败原因）。

## 失败处理

`ImageGridSplitter.split_grid` 默认开启校验。校验失败时会抛出：

```text
ValueError: Invalid grid image: <reason>; confidence=<score>
```

由于校验发生在 `os.makedirs(output_dir)` 和裁切前，失败图片不会生成子图，也不会进入后续 reference_image / storyboard first-frame 回写流程。

`task/grid_image_task.py` 在下载整张宫格图后、调用 `ImageGridSplitter.split_grid()` 前会显式执行 `validate_grid_image(local_file_path, grid_size)`。校验不通过时：

1. 不切图、不创建任何子图 asset，也不写回角色/场景/道具/分镜。
2. 如果该 grid task 仍有重试额度，会调用原图像生成接口重新提交同一个宫格任务，并通过 `GridImageTasksModel.reset_for_retry()` 换新 `project_id`、重置轮询状态。
3. 几何校验失败的重试次数按 item_type 区分：
   - 分镜首帧宫格（`item_type=8`）：由 `GridConfig.STORYBOARD_FIRST_FRAME_VALIDATION_MAX_RETRIES`（默认 2）控制；重试期间对应 `storyboard_image_batch_item` 保持 running。
   - 场景参考图宫格（`item_type=5`）：由 `GridConfig.LOCATION_REFERENCE_VALIDATION_MAX_RETRIES`（默认 2）控制。此项在 `_grid_validation_max_retries` 中兜底（DB 默认 max_retries=0 时也会取常量阈值），避免场景参考图校验失败零重试直接判死刑、导致效果模式首帧因 `location_reference_generation_failed` 全部卡死。
4. 重试耗尽后仍不通过，grid task 标记为 `FAILED`，对应的 `storyboard_image_batch_item` 标记为 `FAILED / grid_first_frame_failed`，让批量任务统计可以收敛结束。

i2i 宫格重试会继续调用 `/api/image-edit`，并复用 `grid_image_tasks.reference_images`、`prompt`、`task_config_id` 和画幅；不会退化成 `/api/text-to-image`。

## 示例结果

> 注：贯穿比例阈值 `VALIDATION_MIN_LINE_COVERAGE` 已从 `0.82` 下调至 `0.75`（配合细线友好的极值采样，真实宫格覆盖率普遍 ≥0.9；普通照片单条线可达 0.7，不宜再低，由 cell 均匀度兜底）。下表为调整前（阈值 0.82、均值采样）的历史结果。

对 2026-07-08 的两张缓存图执行 `2x2` 校验：

| 图片 | 结果 | 原因 |
|---|---|---|
| `upload/cache/2026-07-08/1071_20260708213804_8b38ef92.png` | 不通过 | 纵向分割线贯穿比例约 `0.79`，低于 `0.82`；横向中线证据也不足 |
| `upload/cache/2026-07-08/1073_20260708213810_0bdd0ec6.png` | 通过 | 纵向分割线贯穿比例约 `0.97`，横向分割线贯穿比例约 `1.00` |
