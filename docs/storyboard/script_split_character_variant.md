# 剧本拆分：角色形象变化自动生成变体参考图

> 需求：剧本拆分时，如果判定角色形象需要存在变化（换装、变身、造型持续改变等），
> 自动为角色生成新的形象参考图；后续创建分镜时，分镜生图自动使用角色的新形象。

设计文档配套实现：

- 常量：`config/constant.py` `ScriptSplitConstants.ENABLE_CHARACTER_VARIANT_DEFAULT` 等
- 检测：`llm/script_parser.py`（`enable_character_appearance_changes` 参数 + prompt 块）
- 传播/计划/推进：`services/script_split_character_variant_service.py`
- 编排接入：`services/script_split_engine.py`（merge 末尾传播、publish 分 tick 推进）
- 发布注入：`api/storyboard.py` `build_storyboard_scenes_from_parsed_script`
- 前端：`web/js/storyboard/`（state / render / events）

## 1. 总体链路

```
拆分提交(默认开启 enable_character_variant)
  │
  ├─ 逐段拆分：LLM 在 shot.character_appearance_changes 输出形象"变化点"
  │    （只标记变化开始的镜头；恢复原状输出 revert:true）
  │
  ├─ step_merge 末尾：sanitize_and_propagate_appearance_changes
  │    清洗非法条目 + 沿镜头顺序向前传播持续状态
  │    → shot._effective_appearance_changes（该镜头生效的变体集合）
  │
  ├─ step_publish（新子阶段 phase=character_variant，分 worker tick 幂等推进）
  │    按 (character_db_id, label) 去重建计划 → 复用已有变体 / 提交
  │    item_type=7 角色变体图生图（基于主参考图，保持五官一致；
  │    产物由 grid_image_task 后台任务写回 character.reference_images[]）
  │    → 未全部终态时保持 publishing 让出 tick，崩溃可从 plan 检查点恢复
  │
  └─ build_storyboard_scenes_from_parsed_script(character_variants=ready 映射)
       shot._effective_appearance_changes ∩ 已生成变体
       → prompt_json.reference_selections.characters["{db_id}"] = {url, label}
       → 生图参考图选择（select_reference_variant_for_asset）、前端
         role-chip 变体徽标、变体选择弹层全部自动生效；用户仍可手动改选
```

## 2. LLM 检测协议（shot.character_appearance_changes）

LLM 只输出"变化点"，延续与恢复由代码保证：

```json
"character_appearance_changes": [
  {"character_id": "char_001", "label": "晚礼服",
   "description": "换上深蓝色露肩晚礼服，头发盘起，佩戴珍珠耳环", "revert": false}
]
```

- 仅对数据库已有角色（character_db_id 非空）生效；新角色条目在清洗时剔除。
- `label` ≤ 24 字符（`CHARACTER_VARIANT_LABEL_MAX_LENGTH`），同一种变化全文必须用
  完全相同 label；跨段重复标记由 (db_id, label) 去重兜底。
- 恢复默认：`revert: true`（或 label 为"默认"等约定值）清除该角色的持续状态。
- 临时动作（跑动、转身）、单镜头遮挡（打伞）不算形象变化。
- 关闭开关（`enable_character_variant=false`）时 prompt 不含检测指令，行为与旧版一致。

## 3. 确定性传播（sanitize_and_propagate_appearance_changes）

合并（reorganize/renumber 之后）按最终镜头顺序执行：

- 维护 `current: {internal_char_id: label}`；shot 的显式变化更新 current（revert 移除）。
- `_effective_appearance_changes` = 显式变化 + current 中"在该镜头 characters_present
  里"的延续条目（description 为空，仅供发布期选择参考）。
- 幂等：重复调用结果一致；旧任务（无该字段）为 no-op。

## 4. 变体生成（ensure_character_variants）

发布阶段、在幂等恢复检查之后、场景冲突检查之前执行，同步函数由
`asyncio.to_thread` 包装，每个 worker tick 推进一轮：

| 状态 | 迁移 |
|---|---|
| pending | DB 预检：角色缺失→skipped；已有同 label 变体→ready（复用）；无主参考图→skipped；否则提交 `generate_character_variant_image`（item_type=7）→submitted |
| submitted | 轮询 `grid_image_tasks`（task_key=`{user_id}_7_{角色名}\|{label}`）：COMPLETED→重读 DB 变体 URL→ready；FAILED/TIMEOUT/...→failed；超过 `CHARACTER_VARIANT_TASK_TIMEOUT_SECONDS`→failed |
| ready / failed / skipped | 终态，不再迁移 |

- 每个 tick 最多提交 `CHARACTER_VARIANT_SUBMIT_BATCH_SIZE`(4) 个（edit_image 提交含
  同步 HTTP，限批避免超 worker watchdog）。
- 主参考图在系统内常态存储为 `/upload/...` 相对路径；`generate_character_variant_image`
  内部会按 server 配置（https_host / server.host）补齐为绝对 URL 后再校验
  http/https 并提交 edit_image（见 `_resolve_local_upload_url`），相对路径不再
  导致提交被拒。
- 计划持久化在 `final_result.metadata.character_variant_plan`，跨 tick / 崩溃后
  从检查点恢复；未全部终态时保存 final_result 并 `phase=character_variant` 保持
  publishing（publishing 在 claim_next_task 可领取列表内，租约过期自动回收）。
- 单变体失败/超时/缺主图一律降级（分镜继续使用主参考图），不阻塞拆分任务。
- 全部终态后写 `metadata.character_variant_summary`（不含 URL）供诊断。

## 5. 分镜使用新形象

`build_storyboard_scenes_from_parsed_script(parsed, style, character_variants)`：

- `character_variants` 为 `{str(character_db_id): {label: url}}`（仅 ready 条目）。
- shot 的 `_effective_appearance_changes` 解析出 db_id + label，命中 ready 变体时写入：
  `prompt_json.reference_selections = {"schema_version": 1, "characters": {"{db_id}": {"url", "label"}}}`。
- 键与前端 `characterReferenceSelectionKey`、后端 `select_reference_variant_for_asset`
  的 `_selection_key` 一致（优先 character id）；所选 url 必须仍属于该角色当前
  `reference_image/reference_images`，否则自动回退主图。

## 6. 接口与前端

- `POST /api/storyboard/{id}/generate-from-script`、`POST /api/parse-script` 新增
  `enable_character_variant`（缺省 `ScriptSplitConstants.ENABLE_CHARACTER_VARIANT_DEFAULT=True`，
  `_normalize_request_config` 统一转 bool 参与 active_key 幂等）。
- storyboard 拆分弹窗"拆分选项"新增开关"自动生成角色形象变化参考图"，随
  `persistUiConfig` 记忆。
- 进度弹窗：`phase=character_variant` 归入"发布分镜"步骤，文案
  "正在生成角色形象变化参考图"（`model/script_split_task.py _phase_message`）。
- video_workflow 来源（`/api/parse-script`）不执行发布期变体生成（无发布步骤），
  形象变化标记保留在拆分结果中。

## 7. 注意事项

- 变体生成依赖角色 JSON 文件与 DB 双写管线（grid_image_task 完成时同步两处）；
  角色 JSON 缺失时该变体按 failed 降级。
- 用户在拆分运行期间手动生成同 label 变体：提交返回 `already_has_variant`，
  重读 DB 复用（ready）。
- 生成的变体图与主图同为"三视角"版式（面部特写 + 正/侧/背），提示词模板与
  character-image-designer skill 对齐，保证生图参考一致性。
