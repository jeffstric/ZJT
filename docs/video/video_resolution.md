# 视频分辨率选择与算力联动

视频生成入口支持按实现方配置展示分辨率选项。前端提交 `resolution` 后，后端会按实际 implementation 校验，落库到 `ai_tools.extra_config.video_resolution`，并通过 `context.resolution` 参与算力计算和失败退款。

## 支持范围

| 模型 | 支持分辨率 | 默认分辨率 | 驱动参数值 |
| --- | --- | --- | --- |
| Happy Horse | `720P`、`1080P` | `720P` | `720P`、`1080P` |
| Seedance 2.0 Fast | `480P`、`720P`、`1080P` | `720P` | `480p`、`720p`、`1080p` |
| Seedance 2.0 Mini | `480P`、`720P`、`1080P` | `720P` | `480p`、`720p`、`1080p` |
| Seedance 2.0 | `480P`、`720P`、`1080P`、`4K` | `720P` | `480p`、`720p`、`1080p`、`4k` |

国内版和海外版 Seedance 2.0 implementation 使用相同的分辨率选项。

## 定价倍率

现有 Seedance 2.0 系列基础算力按 720P 输入视频情况下的最高价格配置，因此新增分辨率只通过 `PowerModifier(attribute='resolution')` 调整倍率，不改变原 720P 基价。

| 模型 | 480P | 720P | 1080P | 4K |
| --- | ---: | ---: | ---: | ---: |
| Seedance 2.0 Fast | `200880 / 432000 = 0.465` | `1.0` | `2.25` | 不支持 |
| Seedance 2.0 Mini | `200880 / 432000 = 0.465` | `1.0` | `2.25` | 不支持 |
| Seedance 2.0 | `200880 / 432000 = 0.465` | `1.0` | `972000 * 31 / (432000 * 28) ≈ 2.4911` | `3888000 * 16 / (432000 * 28) ≈ 5.1429` |

算力最终仍按统一逻辑向上取整。由于 720P 基础算力本身已经是整数，部分档位会比截图价格直接换算多 1 个算力点，属于不低收的取整结果。

## 配置

- `ImplementationConfig.supported_video_resolutions` 定义前端展示值和驱动实际值。
- `ImplementationConfig.default_video_resolution` 定义默认分辨率。
- `UnifiedTaskConfig.power_modifiers` 使用 `PowerModifier(attribute='resolution')` 承载算力倍率。

## 接口

`/api/ai-app-run` 和 `/api/ai-app-run-image` 接收可选表单字段 `resolution`。

后端处理顺序：

1. 根据用户和任务解析实际使用的 implementation。
2. 通过 implementation 的 `supported_video_resolutions` 校验分辨率。
3. 未传入时使用 implementation 默认分辨率。
4. 非法值降级为默认分辨率并记录日志。
5. 写入 `extra_config.video_resolution`，并作为 `context.resolution` 计算算力。

Seedance 火山驱动优先读取 `extra_config.video_resolution`，兼容旧字段 `extra_config.resolution`，并转换为火山 payload 的 `resolution` 参数。

## 前端

`TaskConfig` 提供：

- `getVideoResolutionOptions(modelKey, implName)`
- `getDefaultVideoResolution(modelKey, implName)`

制作工坊生视频节点会将选择值保存到 `node.data.videoResolution`，工作流重新加载后可恢复。首页和营销智能体仅在当前模型支持分辨率时显示选择器。

## 退款

退款算力通过任务记录恢复：

- `extra_config.video_resolution` 还原到 `context.resolution`
- `ai_tools.implementation` 还原实际 implementation

旧数据没有 `video_resolution` 或 `implementation=0` 时仍按原有兼容逻辑退款。
