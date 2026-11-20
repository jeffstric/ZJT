# Seedream 火山引擎驱动 (seedream_volcengine_v1)

## 概述

`seedream_volcengine_v1_driver.py` 实现了火山引擎 Seedream 系列文生图/图片编辑模型驱动，使用**同步 API**（一次请求直接返回图片 URL，无需轮询）。

## 架构特点

Seedream 采用「**一个 DriverKey + 一个驱动类，靠 `MODEL_MAPPING` 区分模型**」的架构，与 Seedance「一个模型一个实现」不同：

- **DriverKey**：所有 Seedream 模型共用 `seedream_text_to_image`
- **驱动类**：`Seedream5VolcengineV1Driver`（国内）/ `Seedream5VolcengineOverseaV1Driver`（海外，继承国内版）
- **模型区分**：驱动内 `MODEL_MAPPING` 按 `task_type` 选用模型名

因此新增模型时，**无需新建驱动文件、实现方、工厂注册**，只需：
1. 配置层新增 `TaskTypeId` + `UnifiedTaskConfig`
2. 驱动层 `MODEL_MAPPING` 各加一行

## 支持的模型

| Task ID | 模型名称（国内） | 模型名称（海外） | 算力 | 支持尺寸 | 状态 |
|---------|-----------------|-----------------|:----:|---------|------|
| 16 | doubao-seedream-5-0-pro-260628 | seedream-5-0-pro-260628 | 6 | 2K, 3K | **停用**（hidden） |
| 18 | doubao-seedream-5-0-pro-260628 | seedream-5-0-pro-260628 | 8 | 2K, 4K | **停用**（hidden） |
| 33 | doubao-seedream-5-0-pro-260628 | seedream-5-0-pro-260628 | 20 | 2K, 3K, 4K | 在售 |

> 海外版模型名不带 `doubao-` 前缀（海外网关惯例）。

## 2026-11-20 退役模型迁移

方舟下线模型公告：`doubao-seedream-5-0-260128`（Task 16）与
`doubao-seedream-4-5-251128`（Task 18）到期未迁移关停，官方建议统一迁移
`doubao-seedream-5-0-pro-260628`。处理方式：

- **Task 16/18 停用（`hidden=True`）**：任务 ID、key（`seedream-5.0` /
  `seedream-4.5`）、名称（Seedream 5.0 / 4.5）与算力（6/8）全部保持原样，
  前端模型选择器与用户偏好槽位不再显示；历史任务展示与重试仍可用，
  重试经驱动 `MODEL_MAPPING` 兼容映射到在售 5-0-pro-260628（映射旧快照
  必然 ClosedEndpoint 失败）。
- **Task 32（Seedream 5.0 Pro，key `seedream-5.0-pro`）为唯一在售入口**，
  算力 20（成本 8毛 ÷ 0.04 = 20，所有尺寸统一价）。
- `output_format=png` 三个任务类型统一下发（4.5 不支持该参数的问题已随
  停用消失）。

## Seedream 5.0 Pro

- **模型名**：`doubao-seedream-5-0-pro-260628`
- **算力**：固定 20（成本 8毛 ÷ 0.04 = 20，所有尺寸统一价）
- **尺寸**：2K / 3K / 4K 全支持
- **output_format**：`output_format=png`（三个任务类型统一下发，4.5 不支持该参数的问题已随停用消失）
- **宫格生图**：支持（`supports_grid_image=True`）

## 配置

5.0 Pro 完全复用现有 Seedream 的配置，无需新增：

- **API Key**：`volcengine.api_key`（国内）/ `volcengine_oversea.api_key`（海外）
- **Base URL**：`https://ark.cn-beijing.volces.com`（国内，代码内固定）
- **实现方**：`seedream5_volcengine_v1` / `seedream5_volcengine_oversea_v1`（复用，不新增）
- **同步模式**：`sync_mode=True`（同步 API，独立进程池处理，不阻塞事件循环）

## 接口

`POST https://ark.cn-beijing.volces.com/api/v3/images/generations`

```json
{
  "model": "doubao-seedream-5-0-pro-260628",
  "prompt": "提示词",
  "image": ["https://参考图URL"],
  "size": "2048x2048",
  "output_format": "png",
  "watermark": false
}
```

响应（同步直接返回）：
```json
{
  "model": "doubao-seedream-5-0-pro-260628",
  "created": 1772527784,
  "data": [{"url": "https://...", "size": "2048x2048"}],
  "usage": {...}
}
```
