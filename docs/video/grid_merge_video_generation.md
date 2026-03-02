# 分镜组多宫格图片合并 & 视频生成

## 概述

分镜组节点支持将多个分镜的首帧图片合并为 n×n 宫格图，然后以宫格图作为输入进行图生视频。

## 后端 API

### `POST /api/images/merge-grid`

将多张图片合并为宫格布局。

**请求体** (JSON):

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `image_urls` | `string[]` | 是 | 图片URL列表，长度必须等于 `grid_size` |
| `grid_size` | `int` | 是 | 宫格总数，只能是 4、9、16、25 |
| `black_indices` | `int[]` | 否 | 需要保持全黑的位置索引（从0开始），默认 `[]` |

**校验规则**:
- `grid_size` 必须是完全平方数：4(2²)、9(3²)、16(4²)、25(5²)
- `image_urls` 长度必须等于 `grid_size`
- 所有非黑色位置的图片尺寸必须相同
- `black_indices` 中的位置或空URL的位置填充黑色

**响应示例**:
```json
{
  "code": 0,
  "message": "success",
  "data": {
    "image_url": "https://host/upload/merged/202602/merged_xxx.png",
    "grid_size": 4,
    "cell_count": 4,
    "black_cells": [3]
  }
}
```

## 前端交互

### 宫格预览

分镜组节点中包含一个宫格预览区域，使用 CSS Grid 模拟宫格效果：
- 自动根据分镜数量计算宫格大小（≤4→2×2，≤9→3×3，≤16→4×4，≤25→5×5）
- 有图片的宫格显示分镜首帧，无图片的宫格显示黑色
- 分镜图片变化时自动刷新预览

### 视频生成流程

点击「生成视频」按钮时：
1. **单分镜**：直接使用该分镜的首帧图进行图生视频
2. **多分镜**（>1个）：
   - 调用 `/api/images/merge-grid` 合并所有分镜首帧为宫格图
   - 不足的位置填充黑色
   - 使用合并后的宫格图 + 所有分镜的视频提示词拼接 → 调用图生视频 API

## 文件清单

| 文件 | 变更 |
|------|------|
| `utils/image_grid_merger.py` | 新增 `ImageGridMerger` 类 |
| `server.py` | 新增 `POST /api/images/merge-grid` 端点 |
| `web/css/video_workflow.css` | 新增宫格预览 CSS |
| `web/js/nodes.js` | 新增辅助函数、宫格预览 HTML、改造 `generateShotGroupVideo` |
| `web/js/workflow.js` | 宫格预览刷新联动 |

## 数据结构

分镜组节点 `node.data.gridPreview`:
```javascript
{
  currentGridSize: 4,        // 当前宫格大小
  shotFrameNodeIds: [],      // 关联分镜节点ID
  mergedImageUrl: ''         // 合并后的宫格图URL（生成视频时填充）
}
```
