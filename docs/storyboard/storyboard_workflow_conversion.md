# 故事板 ↔ 工作流画布互转

## 目标

`video_workflow.html`（节点画布）与 `storyboard.html`（故事板编辑器）承载同一集内容的两种编辑形态。本文档描述两者的内容互转：用户在任一页面点击切换按钮，即可把当前内容转换到另一形态并跳转。

## 转换语义（首次一次性 + 已关联增量同步）

**首次转换只支持「对方不存在」的情况**：

- 画布 → 故事板：该画布尚无关联故事板时才创建转换（场景/台词/资产全量落库）。
- 故事板 → 画布：该故事板尚无关联画布时才创建转换（剧本/分镜组/分镜帧/资产节点全量生成）。

**已关联时不再"停在转换时刻的快照"**，入口动作触发**增量资产同步**（只增不改不删、选中跟随最后操作端）：

- 故事板 → 画布（已关联）：接口返回既有画布 + 只读资产包 `sync_assets`，由画布前端在 `loadWorkflow` 后合并（`web/js/storyboard_asset_sync.js`）。**必须在前端合并**：画布保存是前端内存态整体覆盖写（content_version 乐观锁 + last_write_id 会话互判 409），后端直写会被下一次 autoSave 静默回滚。
- 画布 → 故事板（已关联）：接口内直接增量落库（`_sync_assets_to_existing_storyboard`）——故事板是分表字段级 CRUD，且跳转后目标页全量加载，后端行级写天然安全、无画布方向的 P0 竞态。
- 已知边界（只增语义）：画布上删除过的节点会再次补回；故事板删除的场景/资产不受影响；匹配不到分镜帧（`source_shot_key` ≠ `shot_id`）跳过。

## 页面入口

| 方向 | 入口 | 行为 |
| --- | --- | --- |
| 工作流 → 故事板 | 画布顶栏「转故事板」图标按钮（`#toStoryboardBtn`，`web/js/workflow_storyboard_switch.js`） | 先 `flushAutoSave()` 落盘挂起的自动保存，`POST /api/storyboard/from-workflow`，成功后跳 `/storyboard?id={storyboard_id}` |
| 故事板 → 工作流 | 编辑器头部「画布」按钮（`handleRoute('canvas')`，`web/js/storyboard/events.js`） | 已关联画布直接跳转；未关联时 `POST /api/storyboard/{id}/to-workflow` 创建画布后跳转 |

## 后端接口

`api/storyboard_conversion.py`（router 前缀 `/api/storyboard`，注册见 `server.py`）。

身份以登录态为准。`X-User-Id` 可省略；若携带则必须与登录用户一致，否则 403。新建故事板或画布记在登录用户名下。

### POST /api/storyboard/from-workflow

Body：`{ "workflow_id": int }`。返回 `{success, storyboard_id, created}`（新建时附 `scene_count`）。

流程（全部同步 DB 操作经 `asyncio.to_thread`）：

1. 读工作流，独立空间模式下校验属主（与 `GET /api/video-workflow/{id}` 一致）。
2. `StoryboardModel.get_by_workflow_id` 幂等：已有故事板 → 直接返回 `{storyboard_id, created: false}`。
3. `_collect_frames_from_workflow`：从 `workflow_data.nodes` 收集 `shot_frame` 节点，经普通 `connections`（`shot_group → shot_frame`）归组；组间按画布位置排序，组内按 `shotJson.shot_number`（缺失按节点 y/x）；未连线帧归入「未分组」。同时收集分镜帧经普通连线下挂的产物节点：
   - `video` 节点（分镜/幕视频生成产物，`data.url`，过滤 blob:/空）；
   - `image` 节点（原生"生成分镜图"产物只写图片节点不写分镜帧，`data.url`，抽卡多张按连线顺序全部收集）；
   - 收集到的 URL 一并相对化（本机绝对地址剥 origin）。
4. `_build_parsed_data_from_frames`：重建 `parse_script_to_shots` 同构的 parsed_data：
   - `characters/locations/props` 优先取剧本节点 `data.parsedData`；剧本节点缺失（或解析数据为空）时回退用分镜组 `scriptData` 携带的角色/道具名册；
   - 剧本节点缺失时用 `shotJson.db_character_info` 追加 `{id: str(db_id), character_db_id, name}` 兜底角色；
   - 台词缺 `character_id`（工作流 shotJson 常只有 `character_name`）按名回填；
   - `characters_present` 含不可解析 id 时退化为 `db_character_info` 的 db id。
   - 同时产出每帧资产映射 `{source_shot_key: {first_frame, selected_first_frame, last_frame, videos[], image_candidates[]}}`（key 规则与场景 payload 一致：`shot_id or scene_{n}`）。首帧候选来源优先级：分镜「视频首帧」槽 `previewImageUrl`（画布选中态）> 分镜帧自带 `imageUrl` > 连线 image 节点；候选全量保留，首位即落库选中。
5. 复用 `build_storyboard_scenes_from_parsed_script`（`api/storyboard.py`）生成场景 payload——与剧本拆分发布完全同一条字段映射链。
6. 守卫：画布无 `default_world_id` → 400「请先选择世界」；无分镜帧 → 400「画布上没有可转换的分镜节点」。
7. 创建故事板：集数 = `max_episode_number + 1`；标题 `{画布名}故事板`；比例/画风继承画布与世界默认；`script_id` 取剧本节点 `data.scriptId`；`workflow_id` 回写关联。
8. `_create_scenes_with_assets` 逐场景创建并迁移资产：
   - 场景 + 台词（`source_shot_key` 落库）；
   - 首帧候选（分镜「视频首帧」槽选中图 + 自带图 + 连线图片节点，抽卡多张全收）→ 逐个建 `first_frame` 资产，**选中 `selected_first_frame`**（画布选中态，候选首位；不在候选中时回退首位）；
   - `lastFrameUrl` → `last_frame` 资产并选中；
   - 下挂视频 → 逐个建 `video` 资产，**选中第一个**（连线序；故事板转来的画布已把选中视频排连线首位，往返选中还原）。
   - 结束 `recalc_total_duration`。

### POST /api/storyboard/{storyboard_id}/to-workflow

返回 `{success, workflow_id, created}`。已关联且画布仍存在 → 直接返回该画布（`created=false`）。否则：

1. 场景+台词全量读取（`list_by_storyboard` 附带选中首帧/尾帧/视频 URL）；关联剧本取正文；世界角色建 `db_id → name` 映射。
2. `_scene_to_shot` 场景 → `shotJson`（`shot_id` 沿用场景 `source_shot_key`，手工场景为 `sb_{scene.id}`），要点：
   - `opening_frame_description` = `perspective + scene_desc + character_desc`（与故事板生图组词对齐）；
   - `description` = `video_prompt`（视频提示词整段迁移）；
   - 台词 → `dialogue[{character_name, text, character_id}]`，角色名经世界角色精确匹配；未匹配为旁白；
   - `db_character_info` / `characters_present` / `scriptData.characters` / `scriptData.props` 由台词角色与 `character_desc` 名单解析，供分镜节点生图参考图匹配；
   - `shot_type/camera_angle/camera_movement` 取自 `video_config_json`。
3. `_build_workflow_data_from_storyboard` 生成 `serializeWorkflow` 同构的 `workflow_data`：
   - 剧本节点（可取到正文时）→ 按 `act_name` 分组的 `shot_group` 节点 → 每场景一个 `shot_frame` 节点；
   - **全量首帧候选图**（`StoryboardSceneAssetModel.list_storyboard_assets`，选中排首位）逐个创建独立 `image` 节点（普通连线 `shot_frame → image`，与画布原生抽卡产物形态一致：纵向 280 排布、多数命名 `分镜N图1/2...`）；选中的候选写 `shot_frame.data.previewImageUrl`（分镜「视频首帧」槽）并补 `firstFrameConnections`（`image → shot_frame`，画到分镜节点「视频首帧」端口，只连选中那张）。`imageUrl` 留空：该字段会在「视频尾帧」控件下方再渲染一张无标题图，看起来像把首帧当成了尾帧；
   - 选中尾帧 → `data.lastFrameUrl`（只在故事板确实有尾帧时写入，不用首帧顶替）；
   - **全量视频**（选中排首位）逐个创建独立 `video` 节点（`data.url/name`，多数命名 `分镜N视频1/2...`）+ 普通连线 `shot_frame → video`。首帧连线指向分镜节点，不指向视频节点（视频节点没有 `.first-frame-port`，线画不出来）；
   - `script → group → frame → image/video` 连线、计数器（含 `nextFirstFrameConnId`）、timeline（含每分镜一格的时间轴柱子，见下节）、默认视口齐备，前端 `restoreNode` 原样可恢复；
   - **资产 URL 相对化**：本机绝对地址（`http://127.0.0.1:{port}` / `http://localhost:{port}`，生成链路会写死当时的 host:port）统一剥掉 origin 转为 `/upload/...` 相对路径——前端按当前页面 origin 补全，画布换端口打开不裂图（相对路径的视频上传产物本就是此形态）；**布局游标累进**：帧间距取固定 960px 与产物列高（纵向 280/个）的较大者、组间额外间隔，多候选图/视频时节点不叠压（叠压会导致拖动图片节点整理布局时误触邻近分镜帧的首帧/尾帧端口，把图片误设为尾帧）。
4. `VideoWorkflowModel.create`（名称 `{故事板标题}画布`，世界/比例/画风继承）+ `StoryboardModel.update(workflow_id)` 回写关联。

## 字段映射速查

| 故事板 scene | 工作流节点 |
| --- | --- |
| `title` | 分镜帧标题（`分镜{shot_number}`） |
| `duration` | `shot.duration` |
| `prompt_json.scene_desc` | `opening_frame_description` / `scene_detail` |
| `prompt_json.perspective` | 拼入 `opening_frame_description`；反向 `video_config.shot_type/camera_angle` |
| `prompt_json.character_desc` | `db_character_info` + `characters_present`（世界角色名精确匹配） |
| `prompt_json.location` | `location_name` / `db_location_id` |
| `prompt_json.props` | `props_present` + `scriptData.props` |
| `video_prompt` | `description`（分镜节点视频提示词由此派生） |
| `video_type`（含手动切换的数字人/视频选择） | `shotJson.video_type`（反向 `resolve_scene_video_type` 经 `_llm_presentation` 优先采信，往返保留手动选择） |
| `dialogues[]` | `dialogue[{character_name, text}]` |
| `act_name` | `shot_group` 分组（分组名） |
| `first_frame` 资产全量（选中标记 `selected_first_frame_id`） | 每候选一个独立 `image` 节点（普通连线）；选中排连线首位并写 `shot_frame.data.previewImageUrl` + `firstFrameConnections`（`image` → 分镜「视频首帧」端口，只连选中）。`imageUrl` 留空 |
| `last_frame_url`（选中尾帧） | `shot_frame.data.lastFrameUrl`（无尾帧时为空，不拿首帧填充） |
| `video` 资产全量（选中标记 `selected_video_id`） | 每资产一个下挂 `video` 节点 `data.url`（普通连线 `shot_frame → video`）；选中排连线首位 |
| `source_shot_key` | `shot.shot_id`（转换沿用场景原 key；手工场景无 key 时为 `sb_{scene.id}`） |
| `prompt_json.three_scene_code` | `shotJson.three_scene_code` + `shotJson.three_scene_seq_start`（3D 空间透传，见下节；反向经共享 builder 原样回写 `prompt_json.three_scene_code`，往返稳定） |

## 资产与选中态双向同步

故事板场景资产（`storyboard_scene_asset`）每场景可有多条 first_frame/video 记录，选中指针在场景行（`selected_first_frame_id` / `selected_video_id`）；画布的对应语义：

| 端 | 选中表达 | 全量表达 |
| --- | --- | --- |
| 故事板 | 场景 `selected_first_frame_id` / `selected_video_id` | `storyboard_scene_asset` 多行 |
| 画布 | 分镜帧 `data.previewImageUrl`（「视频首帧」槽）；视频无显式选中（连线序首位即选中） | 分镜帧连线下挂的多个 `image`/`video` 节点 |

**首次转换契约（往返选中还原）**：

- **S→W**：全量资产各建节点，**选中资产排连线首位**（首帧同时写 `previewImageUrl`、首帧端口只连选中图）。
- **W→S**：首帧候选 = `previewImageUrl`（画布选中）> 自带图 > 连线 image 节点；**落库选中取候选首位**（`selected_first_frame`），不再固定取第一张。视频落库选中取连线第一（S→W 已把选中排首位，往返闭环）；画布原生新生成的视频按连线序自然生效。
- 选中资产 URL 经 `_relativize_asset_url` 后与候选比对，口径一致。

**已关联增量同步**（入口动作触发，选中跟随最后操作端）：

- **S→W 已关联**：`to-workflow` 返回 `sync_assets`（`_assemble_sync_payload`：每场景全量候选 URL + 选中 URL，只读）→ 故事板页 `sessionStorage` 暂存（`StoryboardAssetSync.stash`）→ 画布页 `loadWorkflow` 后 `applyPending` 合并：缺失 URL 补 image/video 节点（纵向 280 追加、URL 去重幂等）、`previewImageUrl`/首帧端口连线指向选中图、选中视频连线重排首位、尾帧有值才覆盖；实际变更检测避免"已最新"时白保存（PUT 全量写放大）。多标签页并发交由既有 409 会话互判机制兜底。
- **W→S 已关联**：`from-workflow` 内 `_sync_assets_to_existing_storyboard` 直接落库：画布产物 URL（同源字符串口径，本机地址剥 origin 归一）按 `source_shot_key` 匹配场景，缺失 INSERT（无 `ai_tool_id` 纯 URL 引用）、选中 `set_selected`（画布有对应产物才覆盖：首帧=选中槽、视频=连线首位、尾帧=lastFrameUrl）；画布行锁串行化 + 幂等可重跑。
- 往返收敛：用户在 A 端改选中后跳 B 端 → 同步以 A 端为准；两边对齐后重复同步无副作用。

## 时间轴柱子（S→W 转换与兜底链）

时间轴以柱子（pillar）为分区单位，每分镜一格；分镜生成的视频/音频加入时间轴时按柱子归位。S→W 转换直接在 `timeline.pillars` 里逐分镜生成柱子，转出画布打开即见完备格子（分镜1/分镜2…），无需等首个片段加入。

柱子 `id` 的 scriptId 维度口径（生成端与查找端一致，三处共用）：

- 有剧本节点 → 剧本节点 id；
- 无剧本（故事板未关联剧本）→ 分镜组节点 id 兜底（`getPillarForNode` 追溯不到剧本节点时同样回退分镜组 id，`autoMigratePillars` 的 `resolveShotGroupPillarScriptId` 同口径）。

前端兜底链（`web/js/timeline.js`）：`autoMigratePillars` 在柱子为空时从两个来源推导——剧本节点 `parsedData`（画布内拆分链路）与画布 `shot_group.data.shots`（转换等无 `parsedData` 产物）；`loadWorkflow` 恢复时柱子为空即触发迁移（不再要求已有片段）。`applyParsedData`/`runGridFlow` 的幂等分支（分镜组已存在，如转换画布上再次拆分）也会补建柱子。

## 3D 空间 → 导演台（分镜帧「打开导演台」按钮）

效果模式分镜的 3D 空间（`three_scene_code`）在 S→W 转换时随 shotJson 透传到分镜帧
节点。分镜帧在携带 3D 代码时显示「🎬 打开导演台（3D 空间）」按钮
（`web/js/director_stage_from_storyboard.js`）：

1. **轻量记录器重放**（不依赖 three.js）：helper 只记录参数，从该帧按
   `shot_number` 往前找最近的 `three_scene_seq_start` 帧，顺序重放到本镜，
   得到该镜最终角色站位与机位（增量链语义与故事板 3D 预览一致）。
2. **映射 directorData**：`makeActor → 人偶 {name, x, z, rotY: facing}`
   （两侧朝向约定一致：度数、0°=+Z、90°=+X）；`setCamera → 镜头1`；
   `makeStage`/`makeProp` 导演台无对应概念，跳过并 toast 提示；环境为空
   （可在导演台手动接全景节点）。**空镜检查**：迁移后计算机位视锥内是否
   有角色（`cameraSeesActors`，与故事板 3D 预览同款逻辑），全部在视野外
   时 toast 警告"机位视野内无角色"——LLM 偶发产出机位背对角色的空镜，
   可在导演台拖拽机位/预设修正。
3. **首次点击**自动在分镜帧右侧创建导演台节点 + 连线，写入 `directorData`
   后打开编辑器；**再次点击**直接打开（帧记住节点 id，不重复创建）。导演台内
   摆位/快照/录制经既有链路持久化，不受故事板后续修改影响。

## 已知边界

- **多候选资产不迁移**：画布侧只迁分镜帧当前展示的首帧图/尾帧图与下挂全部视频（首个选中）；故事板侧只迁「当前选中」的首帧/尾帧/视频（候选列表不迁）。
- **配音资产不迁移**：故事板台词配音（`storyboard_dialogue_audio`）在画布侧无对应形态。
- **纯文本剧本不往返**：画布剧本节点未从剧本库加载（无 `scriptId`）时，故事板只关联 `script_id`，转换后不携带剧本正文——反向转回画布也没有剧本节点（分镜组/分镜帧内容不受影响）。
- **数字人规则边界**：`video_type` 随 shotJson 往返并被推导规则优先采信；但若手动选择违反硬规则（多说话人/多可见角色/强动作），反向仍会被规则判回 `video`。
- **重复转换不会重复创建**：目标已存在时接口直接返回既有对象；如需重新生成，先删除目标（故事板/画布）再转换。
- **并发转换已串行化**：两个方向的转换主体都在行锁内复查关联（S→W 锁 `storyboard` 行、W→S 锁 `video_workflow` 行），并发请求只会创建一个目标对象，其余请求返回既有对象；前端「画布」按钮另有进行中防重复点击保护，转故事板按钮点击期间禁用。
- **关联对象被删除后自动重建**：故事板页「画布」按钮统一走转换接口（不按 `state.workflowId` 短路直跳）——关联画布已被删除时，接口自动重建画布并回写 `workflow_id`，不会再落在「工作流不存在」页。反向（画布→故事板）同理：按 `workflow_id` 查不到故事板时重新创建。
- 工作流无 `default_world_id` 时无法转故事板（故事板强依赖世界），前端提示先选世界。
- 前端「转故事板」前只做 `flushAutoSave()` + 800ms 等待，极端在途请求由 `auto_save_state` 的 IndexedDB 恢复快照兜底。

## 验证

```bash
# 后端模块导入 + 路由注册
comfyui_env=prod python -c "from api.storyboard_conversion import router; print([r.path for r in router.routes])"
# 纯函数单测
comfyui_env=unit python -m pytest tests/api/test_storyboard_conversion.py -v
```

手工路径：

1. 画布拆分剧本、生成首帧图/尾帧、生成视频（视频节点挂分镜帧下）→ 「转故事板」→ 验证场景/台词/首尾帧/视频资产全部落库且选中态正确。
2. 原生"生成分镜图"的画布（图只在连线 image 节点上，分镜帧 imageUrl 为空）→ 「转故事板」→ 验证连线图作为首帧候选迁移。
3. 故事板选中首帧/尾帧/视频 → 「画布」按钮 → 验证画布分镜「视频首帧」是首帧图且有连到该端口的线、尾帧槽只有真正的尾帧（没有尾帧时为空）、独立图片节点挂普通连线下、视频节点挂在分镜下。
4. 对已转换过的对象再次点击转换按钮 → 应直接打开既有对象、不重复创建（数据条数不变）。
