# 剧本与分镜文档

本目录包含与剧本解析、分镜节点相关的功能文档。

## 文档列表

| 文档 | 说明 |
|------|------|
| [script_auto_split_improvement.md](./script_auto_split_improvement.md) | 剧本节点自动拆分分镜功能改进 |
| [script_parser_incremental_split_design.md](./script_parser_incremental_split_design.md) | 模型语义分段、逐段拆分、断点续传与异步轮询设计 |
| [shot_frame_references.md](./shot_frame_references.md) | 分镜节点引用显示功能（场景/道具/角色） |
| [auto_submit_feature.md](./auto_submit_feature.md) | 自动提交数据库功能（定时自动保存） |
| [world_export_import.md](./world_export_import.md) | 世界导出与导入接口说明 |
| [character_matching.md](./character_matching.md) | 剧本解析角色匹配功能 |
| [script_language_sync.md](./script_language_sync.md) | 剧本节点语言联动功能 |

## 剧本语义小段规划日志

剧本拆分分为两个阶段：第一阶段先规划连续的语义小段，第二阶段才由
`script_parser.py` 把每个小段生成分镜 JSON。第一阶段的专用诊断日志位于：

```text
logs/script_parser/
```

调查指定任务时，按以下前缀查找：

```text
script_segment_planner_task_{task_id}_*
```

同一次尝试最多包含 `_01_anchors.json`、`_02_prompt.txt`、
`_03_raw_response.txt`、`_04_parsed_plan.json`、`_05_validation.json` 五个文件。
如果没有 `_04`，表示模型正文未成功解析为 JSON；查看 `_03` 的原始响应和 `_05` 的
错误摘要。如果 `_04` 存在但 `_05.passed=false`，表示 JSON 可解析，但没有通过 block
覆盖、顺序或连续性等业务校验。

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
