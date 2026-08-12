# 剧本与分镜文档

本目录包含与剧本解析、分镜节点相关的功能文档。

## 剧本解析系统提示词（skill）

`llm/script_parser.py` 的 **system prompt** 已迁到技能文件，可在 AI 工具箱 → **技能配置** 中按用户自定义：

| 项 | 说明 |
|----|------|
| 默认文件 | `script_writer_core/skills/script-parser/SKILL.md` |
| skill 名 | `script-parser`（`ScriptParserConstants.SKILL_NAME`） |
| 加载方式 | `get_script_parser_system_prompt(user_id)`：用户 DB 自定义 → 文件系统默认 → 内置极简 FALLBACK |
| 调用透传 | 分段拆分引擎传入 `task.user_id`，使自定义对拆分生效 |
| 未迁出部分 | user prompt、条件开关文案、QC/分段动态块仍在 `script_parser.py` 内拼装 |

## 文档列表

| 文档 | 说明 |
|------|------|
| [script_auto_split_improvement.md](./script_auto_split_improvement.md) | 剧本节点自动拆分分镜功能改进 |
| [script_parser_incremental_split_design.md](./script_parser_incremental_split_design.md) | 模型语义分段、逐段拆分、断点续传与异步轮询设计 |
| [shot_frame_references.md](./shot_frame_references.md) | 分镜节点引用显示功能（场景/道具/角色） |
| [auto_submit_feature.md](./auto_submit_feature.md) | 自动提交数据库功能（定时自动保存）与提交按钮环绕 Loading |
| [world_export_import.md](./world_export_import.md) | 世界导出与导入接口说明 |
| [world_soft_delete.md](./world_soft_delete.md) | 世界伪删除（隐藏）/ 恢复显示 |
| [character_matching.md](./character_matching.md) | 剧本解析角色匹配功能 |
| [script_language_sync.md](./script_language_sync.md) | 剧本节点语言联动功能 |
| [script_writer_sse_disconnect.md](./script_writer_sse_disconnect.md) | script_writer SSE 断线恢复；ask_user 选项点击不误清输入框 |
| [location_multi_angle_task.md](./location_multi_angle_task.md) | 场景多角度生图任务：状态机、提交失败重试与终态判定 |

## 剧本诊断日志开关

`logs/script_parser/` 下的详细诊断文件（prompt、原始响应、解析 JSON 等）默认**关闭**，
避免日常运行占满磁盘。排查拆分/规划/质检问题时，在 `config/constant.py` 中按需打开：

| 开关 | 作用 | 文件前缀 |
|------|------|----------|
| `ScriptParserConstants.DIAGNOSTIC_LOGGING_ENABLED` | 第二阶段 script_parser 解析诊断 | `script_parser_{timestamp}_*` |
| `ScriptSplitConstants.PLANNER_DIAGNOSTIC_LOGGING_ENABLED` | 第一阶段语义分段规划诊断 | `script_segment_planner_task_{task_id}_*` |
| `ScriptSplitQcConstants.DIAGNOSTIC_LOGGING_ENABLED` | 段级 QC 诊断 | `script_split_qc_task_{task_id}_*` |

三者默认均为 `False`；日志目录均可分别配置为对应 `*_LOG_DIR` 常量（默认 `logs/script_parser`）。

## 剧本语义小段规划日志

剧本拆分分为两个阶段：第一阶段先规划连续的语义小段，第二阶段才由
`script_parser.py` 把每个小段生成分镜 JSON。开启规划诊断开关后，日志位于：

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
    "character_count": 5,
    "character_image_count": 3,
    "location_count": 4,
    "location_image_count": 2,
    "missing_assets": [
      {"type": "characters", "items": ["角色名1", "角色名2"]},
      {"type": "locations", "items": ["场景名1"]},
      {"type": "props", "items": ["道具名1"]}
    ]
  }
}
```

### 检查项

1. **剧本检查**: 检查世界是否存在剧本，如果没有剧本则 `has_script` 为 `false`
2. **角色参考图**: 只要至少一个角色有参考图（`reference_image` 或 `reference_images`）即通过；仅当所有角色均无图时才列入 `missing_assets`
3. **场景参考图**: 只要至少一个场景有参考图（`reference_image` 或 `reference_images`）即通过；仅当所有场景均无图时才列入 `missing_assets`
4. **道具参考图**: 检查所有道具是否有 `reference_image`，缺图的道具列入 `missing_assets`
