# 剧本与分镜文档

本目录包含与剧本解析、分镜节点相关的功能文档。

## 文档列表

| 文档 | 说明 |
|------|------|
| [script_auto_split_improvement.md](./script_auto_split_improvement.md) | 剧本节点自动拆分分镜功能改进 |
| [shot_frame_references.md](./shot_frame_references.md) | 分镜节点引用显示功能（场景/道具/角色） |
| [auto_submit_feature.md](./auto_submit_feature.md) | 自动提交数据库功能（定时自动保存） |

## 资产完成状态检查 API

### 接口说明

**POST** `/api/check-assets-complete`

检查世界资产完成状态，用于从剧本资产页面跳转到制作工坊前的预检查。

### 请求参数

```json
{
  "world_id": 123
}
```

### 响应格式

```json
{
  "code": 0,
  "data": {
    "has_script": true,
    "missing_assets": [
      {"type": "角色", "items": ["角色名1", "角色名2"]},
      {"type": "场景", "items": ["场景名1"]},
      {"type": "道具", "items": ["道具名1"]}
    ]
  }
}
```

### 检查项

1. **剧本检查**: 检查世界是否存在剧本，如果没有剧本则 `has_script` 为 `false`
2. **角色参考图**: 检查所有角色是否有 `reference_image`
3. **场景参考图**: 检查所有场景是否有 `reference_image`
4. **道具参考图**: 检查所有道具是否有 `reference_image`
