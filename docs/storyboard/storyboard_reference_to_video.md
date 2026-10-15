# 故事板参考生视频（无需分镜图）

对照工作流分镜节点「参考图模式」（`docs/video/shot_frame_video_mode.md`）：故事板「全能参考」可不先生成分镜图，直接用角色 / 场景 / 道具参考图生成视频。

## 模式

| `videoImageMode` | 是否要分镜图 | 输入 |
|------------------|--------------|------|
| `first_last_frame` | 要 | 选中首帧（可选尾帧） |
| `multi_reference`（全能参考） | **不要** | 选中首帧（可选）+ 尾帧槽（可选）+ 角色/场景/道具 + 画风参考 + 用户上传；无任何图且提示词没有 `@首帧图` / `@尾帧图` 时，单镜回退文生视频 |

不新增第三种 `videoImageMode`。对口型分镜仍要求形象图 / 首帧 + 成片配音。

## 参考图顺序（去重保序）

后端 `StoryboardAgentCliService._collect_video_reference_bundle`：

1. 若已有选中首帧 → 图1（主参考，图例类型「分镜图」）
2. 角色 / 场景 / 道具（`scene_context` → `_collect_reference_image_items`）
3. 全局画风 `style_reference_image`
4. 用户在媒体槽额外上传的图

没有 `@首帧图` / `@尾帧图` 时顺序就是上面这样。提示词在全能参考下追加「图N是…」图例，以及画风 / 构图（`append_storyboard_visual_suffix`）。

### 参考模式里的 `@首帧图` / `@尾帧图`

与画布分镜节点同一套规则（`services/storyboard_frame_mention.py`，前端只做缺图拦截）：

- 参考模式的媒体槽按「首帧、尾帧、之后才是参考图」填入。尾帧不看模型的 `supports_last_frame`。界面角标统一按槽位顺序编号「图1/图2/…」（含首尾帧槽；槽位内部仍保留首帧/尾帧角色，供 `@首帧图` / `@尾帧图` 路由与提交链路使用）。
- 视频提示词和底部发送框可以插入字面量 `@首帧图`、`@尾帧图`。这两项只在「视频生成」或「AI生视频」的全能参考里出现，首帧模式和对话改图不出现。当前分镜已有首帧图或尾帧图就够，不必先放进媒体槽；槽位里另有一张图时，菜单和提交都用槽位里的那张。分镜助手输入框按下 `@` 会打开与工具栏 `@` 按钮相同的提及框，首尾帧在角色列表上方，按媒体槽顺序显示为「图1/图2/…」（与左侧媒体槽角标一致），角色/场景/道具条目与首尾帧按钮悬停可放大预览。选中项插在光标处；插入的标记自带图片唯一短 id 后缀（`@首帧图:1c88f7a9`），前后端正则按前缀语义整体消费、不留残渣。标记在分镜助手输入框里由镜像层渲染成「缩略图 + 唯一短id」胶囊（`chat_mention_chips.js`，胶囊宽度锁定为标记占位宽、不遮盖正文；悬停胶囊同样放大预览）。标记是原子单位：光标不能落在标记中间编辑，删除一律整枚删除；标记落在行尾被折行截断时，输入框自动在标记前强制换行，让标记独占一行（避免胶囊跨行定位被裁切、裸文本外露）。
- 点名了首帧：该图成为图1，图例是「图1是首帧」，不再同时作为中间的「分镜图」。点名了尾帧：该图排到最后，图例是「图N是尾帧」。只点尾帧时，选中首帧仍作为「分镜图」留在中间。没被点名的帧不会新增成首帧或尾帧。
- 标记在但对应图片没有：拒绝提交（400 / 前端 toast），不回退文生视频。
- 当前下拉模型是 MiniMax H3 参考生视频（`minimax_h3_r2v`）时，这次提交改交隐藏任务 `minimax_h3_kfr`，图片按 3 张裁中间参考。`image_mode` 仍是 `multi_reference`。分镜齿轮和用户偏好仍保存下拉里的参考模型，不写成 50。其他参考模型只重排图片，不换模型。
- 直连 `POST /scene/{id}/generate-video` 额外传 `frame_first_url` / `frame_last_url`。字段在请求里时以传入值为准。全能参考下，槽位有图用槽位；槽位空且提示词点名了该帧时，前端改传分镜上的对应图片；没点名时仍传空字符串，服务端不会把分镜图当成关键帧。字段不在请求里时，服务端用分镜已选首尾帧。批量补视频不单独解析标记，走 `generate_video` 读 `scene.video_prompt`。

## 入口

| 入口 | 行为 |
|------|------|
| 分镜智能体面板 → 视频图片模式下拉 | 可选项取「全部视频模型支持模式」的并集（`getAvailableVideoImageModes`），而非当前模式选中模型的能力——否则首帧模式（尤其无输入图时解析到文生视频模型）下只剩首尾帧，参考生视频入口永不出现；选中后按槽位锁定模型（参考模式 → `video.reference_to_video` 槽） |
| 直连「视频生成」`POST /scene/{id}/generate-video` | 传 `image_mode`；社区版走 `AITools.create`（`reference_images` + extra_config.`image_mode`）；无图回退文生 |
| 智能体 AI 生视频 | 全能参考时后端把自动收集的 URL 写入【视频输入说明】 |
| 时间轴「逐个生成视频」批量 | 全能参考不要求首帧；无参考图的分镜 `skipped / missing_references`（批次不混文生模型） |

## 模式持久化与恢复

- 拆分时按所选「视频生成方式」把 `videoImageMode` 持久化进 storyboard `config_json`（后端 `StoryboardModel.patch_config_json` + 前端 `persistUiConfig` 双写）
- 重新进入故事板时 `restoreUiConfig(config_json)` 恢复该模式；进入「视频生成」助手模式触发的 `ensureVideoImageModeSupported()` 按**参考视频槽模型**校验能力（`getSelectedVideoModel` 在参考模式下固定解析参考槽，不因「尚无输入图」落到文生视频模型），参考生视频模式不会被误重置回首尾帧
- 行为级回归见 `web/tests/storyboard_reference_mode_restore.test.js`

## 参考模式下分镜图的状态展示

参考生视频模式下分镜图**非必需**（拆分时也不自动补全首帧），为避免「待生成」误导用户必须补图：

- 分镜卡片角标 / 预览占位 / 时间轴缩略图：缺失分镜图展示「免分镜图」（`getFirstFrameStatusLabel` 对 `missing` 的文案分支）
- 顶部统计：不再展示图片「N 个待生成」，改为追加「参考生视频免分镜图」
- 批量补全按钮：文案为「补全分镜图（可选）」——补全仅是可选增强，有图会作为主参考一并注入

拆分弹窗若锁定参考生视频，会在发布前把同一场内的短镜头合并成接近模型上限的单条分镜（`pack_shots_for_reference_video`），因此一镜仍对应一条视频，导出不用 clip 窗口。

## Beta 标识

参考生视频仍在灰度验证期，`Beta` 徽标只放在空间充足的入口（`web/js/storyboard/render.js` 的 `REF_VIDEO_BETA_TAG`，样式 `web/css/storyboard.css` 的 `.beta-tag`，与 `web/css/index.css` 同名样式保持一致）：

- 「从剧本拆分」弹窗 → 视频生成方式 →「参考生视频」chip
- 分镜智能体面板 → 视频图片模式下拉面板 →「全能参考」选项

收起态模式下拉按钮 / 单选项静态标签**不带** Beta：工具栏区域狭小，徽标冗余（截图反馈优化）。

功能转正时删除该常量与两处 `beta: true` 声明即可（有 `web/tests/storyboard_split_video_gen_mode.test.js` 断言兜底）。

## 角色音色参考（音色保持）

参考生视频支持音色参考的视频模型（能力位 `supports_voice_input`）会在提交时**自动**把分镜角色的默认音色（`character.default_voice` 克隆源音频）带入生成请求，让生成视频里角色说话保持与角色库同音色：

- **注入内容**：① 参考音频——角色 `default_voice` 并入参考音频通道（seedance 走 `reference_audio` 自动上传 CDN，MiniMax H3 走 LoadAudio 槽位）；② 提示词说明——尾部追加「参考音频说明：音频N是角色：XX的音色样本，角色说话时请保持相同音色。」（与参考图图例同构，幂等追加）
- **注入条件**（全部满足）：`multi_reference` 模式 + 模型 `supports_voice_input=True` + 角色有默认音色；无音色角色跳过，与用户手动携带音频按 URL 去重，最多注入 2 条（`MAX_VOICE_REFERENCE_AUDIOS`，受 MiniMax H3 LoadAudio 硬上限约束）
- **KFRef 混合模型无对白镜头不注入**：本次提交切成 KFRef 隐藏任务（`minimax_h3_kfr`）且镜头原文无引号台词（`has_quoted_dialogue`，引号包裹的 CJK 片段）时，跳过音频合并与「保持相同音色」说明追加——`<Audio N>` 只有绑到要说新台词的角色身上才是音色参考，无对白时连上的语音会被当成成片声音。分镜直连（`api/storyboard.py`）与批量补视频（`storyboard_agent_cli_service`）两处同口径。注入侧用正则是「提交时等不了 LLM」的权宜，其误判由驱动侧读优化 LLM 的语义标记（`extra_config.h3_prompt_optimize.has_dialogue`，能识别无引号台词、排除引号店名）纠正；驱动无标记时（旧任务/优化禁用/回退原文）回退正则。Ref2VA/I2VA/FL2VA 不受影响
- **H3 有台词镜头按说话人过滤注入（37/50）**：只注入**开口说话角色**的音色（`extract_speaking_character_ids` 从分镜对话记录取 `text` 非空的角色，`collect_character_voice_references` 按 `speaking_character_ids` 过滤）。单人说话镜头不再带非说话人的音色——无声明目标的人声挂槽会被 H3 错配给画面人物或混入成片（server8 分镜 2 事故：单人近景 + 两路音色全传，说话串成别人的声音）。对话记录为空时不过滤（KFRef 无对白由上条拦截、Ref2VA 无对白维持现状）；seedance 等非 H3 链路不过滤。画布链路由 KFRef 驱动「按 `<Audio N>` 声明数上传」兜底收敛到同一终态。有引号台词的镜头维持注入 + 绑定句（lip-sync pacing）不变
- **时长预算兜底**（seedance 系列）：角色音色源音频上传时裁到 20s（TTS 克隆需要），而火山 r2v 限制音频总时长 2.0 系列 ≤15s / 2.5 ≤30s。seedance 驱动（火山国内/海外/kkidc/huimengi）提交前按「(总上限-0.5s 余量)/条数」均分配额自动截断超长音频到临时文件（不修改角色原音频），详见 `docs/drivers/seedance_volcengine_v1_driver.md`「参考音频总时长预算与自动截断」；MiniMax H3 不受此限制
- **不支持的模型**（grok / kling / vidu / veo3 / wan3 等默认 False）：不注入音频也不追加文字，行为零变化
- **能力位配置**：`config/unified_config.py` `UnifiedTaskConfig.supports_voice_input`（`to_frontend_dict` 同步下发前端）；当前 True：`seedance_2_0` / `seedance_2_0_fast` / `seedance_2_0_mini` / `seedance_2_5` / `minimax_h3_r2v`

注入点分两条链路：

| 链路 | 入口 | 注入位置 |
| --- | --- | --- |
| storyboard.html（分镜直连 / 批量补视频 / 智能体） | `api/storyboard.py` generate-video；`storyboard_agent_cli_service.generate_video` | 后端：`collect_character_voice_references`（`services/storyboard_reference_prompt_service.py`），在 generation_snapshot/媒体模式判定**之后**注入，避免改变模式与槽位判定 |
| video_workflow 画布（生视频节点 / 分镜节点 / 分镜组节点） | `/api/ai-app-run-image` | 前端：`web/js/voice_reference.js` 的 `collectVoiceReferences`（角色数据只存在于前端节点/查询结果）；`audio_urls` 通道复用后端现有透传 |

MiniMax H3 的提示词优化 pipeline（ref2va）改写时会统计 `ai_tool.audio_path` 参考音频数量并写为 `<audio_N>` 引用，注入的音色自然进入最终提示词。注入为提交期行为，不产生节点持久化状态，工作流重载复原不受影响。

## 角色音色指纹（voice_desc，仅 MiniMax H3）

> 背景：2026-10-14 消融实验（同 seed 删性别提示词即失效）证明 H3 的参考音频只是弱微调——音色的宏观属性（性别/年龄感）由提示词文字决定，音频只在文字划定的范围内微调。音色一致性因此改由**文字指纹**承担，参考音频降级为可选增强。

- **字段**：`character.voice_desc`（varchar(1000)，迁移 `no_150_20261014_character_voice_desc`）——角色声学音色指纹，**只写恒定的声学基色**（性别年龄段/音高/质感/音量/语速，30~60 字）。严禁写入：体型外貌与肢体动作（"微胖""叉腰挺肚"）、录音质感（TTS 专用要素）、按对象/情境切换的说话方式（"对下属嗓门拔高、对领导谄媚"）、口头禅台词——这些交给每场戏的剧本与提示词现场决定；写进指纹会导致提示词冗长、注意力分散、跨镜头音色漂移
- **生成**：与参考音频同源但**双字段解耦**。LLM 音色分析（`task/audio_task.py` `analyze_character_voice`）一次产出两份：`voice_description`（60~100 字 TTS 丰富版，含录音质感收尾，给 VoxCPM2 声音设计模型）与 `voice_desc`（30~60 字纯声学指纹，给 H3 注入）。① script_writer「生成参考音频」响应回填 `voice_desc`；② 角色编辑页「音色描述」字段的「自动生成」按钮（有参考音频才可点击，接口 `POST /script-writer/characters/reference-audio` 旁的 `/script-writer/characters/voice-desc`）；③ 用户可手动改，手改后不重新生成音频就不会被覆盖。两条红线贯穿两个字段：音色与外观一致、情绪克制
- **情境语气分层**：指纹（基色，恒定）与情境语气（每场戏变化）是两层——"对下属拔高嗓门、对领导压低谄媚"这类按对象/情绪的说话方式，由提示词优化 LLM 拿着完整剧本在写台词句时现场判断叠加（如 `says in a deep hoarse voice, obsequious and fawning`），不进指纹。指纹若带情境变化，每场戏描述都变，音色一致性即漂移
- **注入**（仅 H3 系列，`PipelineDriverFactory.is_h3_prompt_optimize_type` 门控）：提示词尾部追加「角色音色说明：XX的音色特征：…；…。描述这些角色说话的声音时必须遵循对应音色特征。」（`build_voice_casting_note`/`append_voice_casting_note`，幂等，`H3_VOICE_CASTING_NOTE_MAX_CHARS` 截断）。KFRef 无对白镜头与音频注入同口径跳过（音色说明会诱导模型给无对白镜头配音）。seedance 等其他模型零变化（它们的音频参考走 TTS 克隆，工作正常）
- **渲染**：三个 H3 优化模板（I2VA/FL2VA base、Ref2VA、KFRef）都有 Voice casting 段：有台词角色的说话句必须融入其指纹特征的英文转写（全部声学特征语义保留、禁止增删改写——文本恒定是跨镜头音色一致性的根基），不说话的角色忽略其指纹；说明块本身不抄进最终提示词。原文带指纹块时优化指令再追加一条条件指令强化遵守
- **与参考音频的关系**：并存不互斥。指纹是主保证；`default_voice` 音频照常上传（LoadAudio 槽）当盆地内微调——两者同源（指纹由生成音频时的同一分析产出），不会冲突。H3 参考音频每条 2–15s 的官方约束暂未实施裁剪（两个 H3 驱动有 TODO 注释：音频参考本身弱，裁剪也未必有效）
- **链路覆盖**：分镜直连（`api/storyboard.py`）+ 批量补视频（`storyboard_agent_cli_service`）已注入；video_workflow 画布走前端注入（`voice_reference.js`），指纹暂未接入（后续工作）；存量角色无指纹自然降级（注入为空跳过），在角色编辑页点「自动生成」即可补
- **一致性边界**：指纹是"描述性声音"而非克隆——同角色跨镜头一致靠文本逐字恒定；不能复刻某个特定真人的音色（那是 TTS/克隆的领域）

## 回退

- 单镜全能参考且一张图都没有 → `text_to_video`，使用文生视频槽模型
- 批量全能参考且该镜无图 → 跳过 `missing_references`，不在同一批次回退文生

## 相关文件

- `services/storyboard_agent_cli_service.py` — 收集、图例、批量规划、CLI `generate_video`（音色注入 + 指纹注入）
- `api/storyboard.py` — 直连 generate-video、智能体上下文（音色注入 + 指纹注入）
- `web/js/voice_reference.js` — 画布三类节点共用的角色音色注入工具（能力位门控）
- `web/js/script_writer.js` / `web/script_writer.html` — 角色编辑页音色描述字段与「自动生成」按钮
- `task/audio_task.py` — `analyze_character_voice`（音色指纹生成，与 TTS 风格提示词同源）
- `api/script_writer.py` — `POST /script-writer/characters/voice-desc`（指纹生成接口）
- `web/js/storyboard/events.js` / `auto_missing_videos_state.js` / `render.js`
- `web/js/storyboard/state.js` — `getAvailableVideoImageModes`（模式下拉可选项并集）、`getSelectedVideoModel`（参考模式固定解析参考视频槽）
