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
| `video.text_to_video` | 文生视频 | MiniMax H3 (文生)（`minimax_h3_t2v`） | Seedance 2.0 |
| `video.reference_to_video` | 参考生视频、多参考图模式 | MiniMax H3 参考生视频（`minimax_h3_r2v`） | Seedance 2.0 |

代码默认值定义在 `config/model_catalog.py` 的 `SCENE_RECOS`。营销档位不要套到剧本拆分，deepseek 档位不要套到营销智能体。

**管理员可热更新覆盖（2026-09 起）**：`system_config` 键 `model_catalog.scene_recos`（json，已在 `config/default_configs.py` 注册）按场景/档位覆盖代码默认；读取走 `get_scene_recos_merged()`（DB 优先，缺失/非法条目回退代码默认并告警）。管理端入口：管理后台「模型管理」页顶部「推荐模型档位」区块（`GET/PUT /api/admin/model-recos`，候选来自统一配置/LLM 可用模型，保存时校验 canonical 必须命中候选；LLM 供应商为跟随模型联动的单选下拉，留空则自动选路），也可在「系统配置」页直接编辑该 JSON。

剧本创作页模型选择的恢复优先级：LLM 为 **localStorage 上次选择（`lastSelectedLlmModel`）→ 世界默认 → 系统推荐**（世界默认仅作新会话种子，不覆盖用户显式选择）；生图为 **会话草稿 → localStorage 上次选择（`lastSelectedImageModel`）→ 世界默认**。

剧本创作无偏好时的硬兜底是 `config/constant.py` 的 `DEFAULT_TEXT_TO_IMAGE_TASK_ID`（GPT Image 2，`task_id=26`），不再回落到 nano-banana-Pro。

2026-08 起，`GPT_IMAGE_2_EDIT`（task_id=26）的 `sort_order` 调为 5，成为 IMAGE_EDIT / TEXT_TO_IMAGE 类目列表首项（`config/unified_config.py`），各端"取列表第一项"的默认图片编辑/文生图模型随之变为 GPT Image 2；故事板页图片编辑槽位的 localStorage 记忆键同步升级为 `storyboard_lastSelectedImageEditTaskId_v2`，旧记忆一次性作废。

故事板页（storyboard.html）五类生成槽位（文生图/图片编辑/文生视频/图生视频/参考生视频）2026-10 起无 localStorage 记忆（新用户）时的默认统一取该场景性价比档：`web/js/storyboard/state.js` 的 `pickRememberedTaskId` 优先选列表中 `track === 'value'` 的模型（`GET /api/storyboard/models` 每项的 `track` 由 `annotate_task_models` 标注，联动 `get_scene_recos_merged()` 热更新），再回退槽位显式 preferred（均为 value 档），最后列表第一项。此前图生视频槽位无记忆默认取列表第一项，因 LTX2.3 `sort_order=30` 分类内最小而落选 LTX2.3（文生视频落到 Grok）。已有记忆用户沿用原选择，不重置。

工作流页（video_workflow.html）各视频节点（图生视频/分镜组/分镜帧/剧本节点）的默认视频模型 2026-10 起同样显式取性价比档：`findTaskByTrack(options, scene, TaskConfig.getCatalog(), 'value')` 优先（scene 按生成模式映射，多参考模式为 `video.reference_to_video`），回退 `getModelOptionsForCategory` 排序后的列表第一项。`web/js/task_config.js` 新增 `getCatalog()` 导出后端真实目录（含管理员热更新），上述调用点不再回退前端 FALLBACK 副本。营销智能体页（marketing_agent.html）图片/视频/LLM 默认此前已通过 `modelForMediaSlot`（`findTaskByTrack value`）与 `collapseLlmModels + findCollapsedByTrack('value')` 走性价比档，无需改动。

服务端侧同口径修复（2026-10-12）：`MediaGenerationPreferenceService.default_model` 无偏好默认解析改为**目录性价比档优先**（按槽位映射场景取 value 档，联动 `get_scene_recos_merged()` 热更新），回退 sort_order 第一；`GET /api/storyboard/media-preferences` 的 Storyboard UI 读取改为**不落库**（`get_profile(initialize=False)`），偏好表只存用户显式选择，空槽位由前端性价比档兜底、提交路径按运行时默认冻结进任务快照。事故链：图生视频 sort_order 最小是 LTX2.3(30)，服务端首次初始化偏好按旧口径落库 LTX2.3，从此隐身模式/新浏览器都命中该固化记录，前端 `track === 'value'` 兜底（上文 59009cf3）被短路。详见 `docs/backend/media_generation_preference_scopes.md`。

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
`web/js/task_config.js` 的 `getModelOptionsForCategory` 为每个模型项计算 `track` 并按 value→quality→其它排序，另提供 `getCatalog()` 返回 `/api/system/task-configs` 的真实目录（含管理员热更新），供各页默认选择显式命中 value 档。
工作流节点从 `config_json` 恢复已选模型，不被推荐覆盖。
