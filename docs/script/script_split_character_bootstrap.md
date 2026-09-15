# 剧本拆分角色自动入库（character bootstrap）与幽灵角色治理

## 背景

剧本拆分（`llm/script_parser`）允许剧本新角色以 `character_db_id=null` 输出。历史上这些角色不会落库，导致：

- 分镜提示词携带 `【【角色名】】` 标记，但世界角色库中查无此角色（**幽灵角色**）；
- 前端（storyboard.html）场景卡片照样渲染角色框，视觉上与真实角色无差别；
- 点击"生成分镜图"时后端参考图解析静默跳过该角色；点击角色框/参考图选择时报"该角色不存在"。

与地点（location）不同（发布时由 `StoryboardLocationBootstrapService` 自动资产化），角色此前没有对应的 bootstrap 机制。

## 治理方案（四层防护）

### 1. 发布时角色自动入库（治本）

`services/storyboard_character_bootstrap_service.py`，在 `script_split_engine.step_publish` 的
发布硬门禁之后、location bootstrap 之前执行（`asyncio.to_thread` 包装，纯同步 DB 操作）：

- 已携带 `character_db_id` 的角色直接复用，不重复入库；
- **短名归一化**：LLM 输出短名（如 `奶昔`）且库内存在唯一受控别名目标
  （`奶昔_Milkshake`，复用 `script_split_character_contract._controlled_alias` 的
  `中文名_English` 命名约定）时，回填既有 db_id、把 parsed 角色 `name` 改写为完整名，
  并把 shot 文本字段（`opening_frame_description`/`scene_detail`/`description`/`action`/对白）
  中的 `【【短名】】` 标记同步替换为 `【【完整名】】`，保证生图按名查找能命中；
- 其余新角色用 `CharacterModel.create(source='script_split')` 建库，LLM 输出的
  `description→appearance`、`role→identity`、`gender/age_range→age` 随行落库，
  `other_info` 写入自动创建提示文案；
- 多义短名（对应多个库内角色）不自动入库，记 warning；
- 单角色失败仅记 warning 不阻塞发布；整体异常放行（角色按未入库处理）。

幂等性：按 `(world_id, name)` 先查后建；同名既有行复用 id 且**不覆盖任何字段**
（保护用户已补的参考图与设定）。

回填 `character_db_id` 后，`build_storyboard_scenes_from_parsed_script` 中的
`_dialogue_character_id` 对新角色对白也能拿到真实 id，配音/对白归属正常。

### 2. character 表新增 `source` 字段

迁移 `alembic/versions/no_130_20260907_character_source_field.py`：

```sql
ALTER TABLE `character` ADD COLUMN `source` varchar(32) NOT NULL DEFAULT 'manual'
  COMMENT '角色来源: manual=手动创建, script_split=剧本拆分自动入库' AFTER `sora_character`;
```

- 取值见 `config/constant.py` 的 `CharacterConstants`（`SOURCE_MANUAL` / `SOURCE_SCRIPT_SPLIT`）；
- `CharacterModel.create/create_or_update` 支持 `source` 参数；
- `create_or_update` 的 `ON DUPLICATE KEY UPDATE` **不更新 source**（保留既有行的来源）。

### 3. 前端"未入库/缺参考图"识别（storyboard.html）

`web/js/storyboard/render.js`：

- `resolveSceneCharacters` 对匹配失败的名字附 `missing: true`（未入库）、
  `missingRef: true`（在库但无任何参考图），不再伪装成正常角色；
- `renderGridCharactersRow`：未入库占位头像为橙色虚线警示（`is-missing`），
  缺参考图为黄色虚线（`is-no-ref`），名字后缀 `?`，title 说明原因；
- `renderPromptWithInlineRoles`：未入库角色 chip 用 `role-chip.is-missing` 警示样式，
  不挂 `select-character-reference` 点击行为，title 提示"请先在角色管理中创建"。

样式位于 `web/css/storyboard.css`。

### 4. 生成分镜图的可见降级提示（不再静默）

后端 `services/storyboard_agent_cli_service.py`：

- `scene_context` 返回 `missing_characters`（提示词标记但库中查无）与
  `characters_without_reference`（在库但无可用参考图）；
- `generate_image` 的响应透传这两个名单（非空才带）；
- 前端 `sendDirectImage`（events.js）提交后 notify
  "部分角色参考未生效：「xxx」未在角色库中；「yyy」缺参考图…"。

video_workflow 旧页（`web/js/shot_frame_generator.js`）：

- 移除 `|| characters[0]` 模糊兜底（keyword LIKE 命中第一条就当匹配，会挂错参考图），
  改为全名精确匹配；用户手选参考图仍优先；
- 收集到未匹配角色时 toast 可见提示（此前仅静默剥标记）。

### 5. 拆分完成后刷新前端角色库缓存

`web/js/storyboard/events.js` 的 `attachGenerateFromScriptPolling.onComplete`：
拆分完成后除 `loadStoryboardData` 外，同步 `fetchCharacters/fetchLocations/fetchProps`
刷新 `state` 资产缓存（发布可能自动创建了新角色）。

## 相关测试

- `tests/services/test_storyboard_character_bootstrap_service.py`：新角色入库、
  已有 db_id 复用、同名复用、短名归一化（含 shot 标记改写）、多义短名、单角色失败韧性。
