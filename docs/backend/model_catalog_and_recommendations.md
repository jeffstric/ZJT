# 场景模型目录与双档推荐

每个生成/对话场景固定两个推荐槽：**性价比 `value`** 与 **效果 `quality`**。供应商对普通用户默认折叠，系统按目录选路。

推荐只影响列表展示和首次默认，不覆盖已保存偏好或任务快照。

## 场景与双档

| scene | 入口 | 性价比 | 效果 |
|-------|------|--------|------|
| `llm.script_split` | 剧本拆分、分镜拆分弹窗、工作流剧本节点 | `deepseek-v4-flash` | `deepseek-v4-pro` |
| `llm.chat` | 剧本对话、分镜助手 | `deepseek-v4-flash` | `deepseek-v4-pro` |
| `llm.marketing` | 营销智能体对话 | `doubao-seed-2-0-lite` | `doubao-seed-2-0-pro` |
| `llm.style_recognize` | 画风识别 | `doubao-seed-2-0-lite` | `doubao-seed-2-0-pro` |
| `image.text_to_image` | 首页文生图 | GPT Image 2 | GPT Image 2 |
| `image.image_edit` | 改图 | GPT Image 2 | GPT Image 2 |
| `image.script_writer` | 剧本创作生图 | GPT Image 2 | Seedream 5.0 Pro（口中的 seedance2.0 pro；系统无同名生图模型） |
| `video.image_to_video` | 图生视频、工作流视频（首尾帧） | MiniMax H3 | Seedance 2.0 |
| `video.text_to_video` | 文生视频 | MiniMax H3 | Seedance 2.0 |
| `video.reference_to_video` | 参考生视频、多参考图模式 | MiniMax H3 参考生视频（`minimax_h3_r2v`） | Seedance 2.0 |

定义在 `config/model_catalog.py`。营销档位不要套到剧本拆分，deepseek 档位不要套到营销智能体。

剧本创作无偏好时的硬兜底是 `config/constant.py` 的 `DEFAULT_TEXT_TO_IMAGE_TASK_ID`（GPT Image 2，`task_id=26`），不再回落到 nano-banana-Pro。

2026-08 起，`GPT_IMAGE_2_EDIT`（task_id=26）的 `sort_order` 调为 5，成为 IMAGE_EDIT / TEXT_TO_IMAGE 类目列表首项（`config/unified_config.py`），各端"取列表第一项"的默认图片编辑/文生图模型随之变为 GPT Image 2；故事板页图片编辑槽位的 localStorage 记忆键同步升级为 `storyboard_lastSelectedImageEditTaskId_v2`，旧记忆一次性作废。

## 默认解析

```text
用户已保存且仍可用的偏好（含 custom）
  → 该场景指定档位（默认 value）且模型可用
  → 该场景另一档位
  → DEFAULT_TEXT_TO_IMAGE_TASK_ID（GPT Image 2）
  → 列表第一项
```

LLM 同一规范模型的供应商顺序：目录 `preferred_vendors` → 已配置 → 当前单价最低。

## API

- `GET /api/models?scene=llm.chat` 返回 `catalog.tracks` 与每条 `track` / `is_default_route`
- `GET /api/text-to-image-models`、`GET /api/storyboard/models`、`GET /api/system/task-configs` 同样带 catalog
- Agent 工具 `list_llm_models` / `list_video_models` 返回 `tracks`，未指定用 value，用户要效果用 quality

## 前端

`web/js/model_catalog.js` + `web/css/model_catalog.css`：折叠供应商、性价比/效果开关、系列分组。
工作流节点从 `config_json` 恢复已选模型，不被推荐覆盖。
