# Storyboard 数字人双模型自动路由设计

## 1. 目标

Storyboard 的 `digital_human` 分镜同时接入 Wan2.2 数字人和 LTX2.3 With Voice，根据该分镜待说台词对应的 TTS 总时长自动选择模型。

本设计统一直接生成接口、Storyboard Agent、Storyboard CLI 和批量补全视频的路由、输入映射、算力扣除及任务元数据，避免各入口分别判断导致模型、参数和计费不一致。

Wan2.2 和 LTX2.3 数字人都只接收“当前分镜已选中的首帧图”，不读取角色参考图、场景参考图、尾帧或多参考图。这里的图片语义与普通图生视频不同。

## 2. 路由规则

路由依据是“该分镜待说台词对应的 TTS 总时长”，不是 Wan2.2 实际使用的参考音频长度。

| TTS 总时长 | 模型 | task type | 路由原因 |
|---|---|---:|---|
| `<= 1.000s` | Wan2.2 数字人 | `TaskTypeId.DIGITAL_HUMAN`（13） | `speech_duration_lte_1s` |
| `> 1.000s` | LTX2.3 With Voice | `TaskTypeId.DIGITAL_HUMAN_LTX2_3_VOICE`（32） | `speech_duration_gt_1s` |
| 无法识别 | LTX2.3 With Voice | 32 | `speech_duration_unknown` |

阈值必须定义在 `config/constant.py`：

```python
WAN_MAX_SPEECH_DURATION_SECONDS = 1.0

class StoryboardTimeouts:
    DIGITAL_HUMAN_AUDIO_MERGE_TIMEOUT_SECONDS = 120

class StoryboardDigitalHumanConstants:
    ERROR_UNSUPPORTED_RATIO = "unsupported_ratio"
```

比较前统一按毫秒精度规整，避免浮点误差导致 `1.000s` 被错误分配给 LTX2.3。

`<= 1.000s` 选择 Wan2.2 是明确的产品路由规则，不是根据 Wan2.2 的文本上限推导出的模型能力结论。Wan 节点支持较长文本不改变本期的路由边界；若后续调整阈值，只修改统一常量和路由测试，不允许各入口自行改变。

## 3. 对白和 TTS 解析

### 3.1 说话角色约束

- 没有有效对白时拒绝生成。
- 仅允许一个有效说话角色。
- 多个说话角色时拒绝生成，并提示拆成单人分镜或切换普通视频模式。
- 旁白或没有 `character_id` 的对白不作为数字人说话输入。

### 3.2 多条对白防御逻辑

正常剧本拆分应避免把多条 TTS 分配到数字人分镜，但服务层必须支持冗余处理：

1. 读取该说话角色的全部有效对白。
2. 按 `sort_order`、`id` 排序。
3. 按顺序拼接对白正文，作为完整讲话内容。
4. 按顺序读取所选 TTS 音频。
5. 路由时累计全部 TTS 时长。

### 3.3 音频时长来源

每段 TTS 按以下顺序解析时长：

1. `storyboard_dialogue_audio.duration`。
2. 数据库时长缺失或无效时，使用 ffprobe 探测所选 `audio_url`。
3. 任意一段仍无法识别时，整体标记为“时长未知”，默认走 LTX2.3。

ffprobe 是同步进程调用，复用 `config.constant.FFPROBE_AUDIO_DURATION_TIMEOUT`。同步领域服务可以调用 ffprobe，但所有处于事件循环中的调用方必须将完整的“解析、探测、准备、提交”同步链路放入 `asyncio.to_thread()`，不得只包装数据库查询。

各入口执行契约：

| 入口 | 执行方式 |
|---|---|
| Web API | `await asyncio.to_thread(orchestrate_digital_human_generation, ...)` |
| 异步批量 Worker | `await asyncio.to_thread(...)`，每个分镜独立调用 |
| 同步 Agent 工具执行器 | 直接调用同步领域服务；不得再套事件循环 |
| 同步 CLI | 直接调用同步领域服务 |

如果 Agent 或 CLI 未来改为异步执行器，同样必须使用 `asyncio.to_thread()` 包装同步领域服务。

## 4. 统一生成计划

新增不可变的数字人生成计划对象，所有入口先生成计划，再扣费和建单：

```python
@dataclass(frozen=True)
class DigitalHumanGenerationPlan:
    model: str
    task_type: int
    speaker_character_id: int
    speech_text: str
    speech_duration: Optional[float]
    first_frame_path: str
    ratio: str
    billable_duration: float
    prompt: str
    audio_input: str
    audio_input_role: str
    routing_reason: str
```

字段含义：

| 字段 | 说明 |
|---|---|
| `model` | `wan2.2` 或 `ltx2.3` |
| `task_type` | 13 或 32 |
| `speech_text` | 按对白顺序拼接的完整讲话内容 |
| `speech_duration` | TTS 总时长；无法识别时为 `None` |
| `first_frame_path` | 当前分镜已选中的首帧图；缺失时拒绝生成 |
| `ratio` | Wan2.2 实际输出比例；LTX2.3 仅作为任务元数据记录 |
| `billable_duration` | 传给实际模型 `get_computing_power(duration=...)` 的计费时长 |
| `prompt` | 根据所选模型生成的最终提示词 |
| `audio_input` | 最终传给驱动的音频 |
| `audio_input_role` | `voice_reference` 或 `speech_audio` |
| `routing_reason` | 可观测的模型选择原因 |

## 5. Wan2.2 输入映射

Wan2.2 适用于 TTS 总时长 `<= 1.000s` 的分镜。

| `ai_tools` 字段 | 值 |
|---|---|
| `type` | 13 |
| `prompt` | 按顺序拼接的对白正文，即角色实际要说的内容 |
| `image_path` | 当前分镜已选中的首帧图 |
| `message` | 角色音色参考音频 |
| `audio_path` | `NULL` |
| `ratio` | Storyboard 的 `workflow_ratio` |

Wan2.2 的提示词只能来自对白正文，不允许使用：

- `scene.video_prompt`；
- Agent 自行编写的动作提示词；
- LTX2.3 固定提示词。

Wan2.2 的音频是音色参考，不是实际讲话内容。参考音频选择规则：

1. 只在当前说话角色已完成且已选中的 TTS 中选择。
2. 多段 TTS 时选择已知时长最长的一段。
3. 不将多段 TTS 合并后传给 Wan2.2。

Wan2.2 的输出比例必须由服务端读取 Storyboard 的 `workflow_ratio`。数字人接口、Agent 或 CLI 传入的 ratio 仅被忽略，不参与兜底；兜底只针对 Storyboard 自身没有设置 `workflow_ratio` 的情况。比例解析以 `UnifiedConfigRegistry.get_by_id(TaskTypeId.DIGITAL_HUMAN).supported_ratios` 为唯一能力契约：

1. `workflow_ratio` 为空时使用模型配置的 `default_ratio`，当前为 `9:16`。
2. `workflow_ratio` 存在且属于 `supported_ratios` 时原样传给驱动。
3. `workflow_ratio` 存在但不属于 `supported_ratios` 时返回 `StoryboardDigitalHumanConstants.ERROR_UNSUPPORTED_RATIO`，其稳定值为 `unsupported_ratio`，不得用调用方 ratio 或默认比例掩盖无效配置。

当前 Wan 驱动内部 `ratio_map` 已支持 `original/custom`，但注册配置的 `supported_ratios` 未声明这两个值。实现时必须先把 `original`、`custom` 补入 Wan2.2 的 `UnifiedTaskConfig.supported_ratios`，因此这两类常见存量 Storyboard 不会生成失败。实现仍以注册配置为准，并应将驱动的未知比例静默回退改为显式报错，避免绕过服务层时产生错误比例。

真正未知的比例值继续硬失败，不采用“回退 9:16 并告警”：用户已要求输出比例与分镜设置一致，静默降级会产生内容可用但画幅错误的成片，比显式失败更难发现和修复。

## 6. LTX2.3 输入映射

LTX2.3 适用于 TTS 总时长 `> 1.000s` 或时长无法识别的分镜。

| `ai_tools` 字段 | 值 |
|---|---|
| `type` | 32 |
| `prompt` | `StoryboardDigitalHumanConstants.DEFAULT_PROMPT` |
| `image_path` | 当前分镜已选中的首帧图 |
| `audio_path` | 实际 TTS 说话音频 |
| `message` | `NULL` |
| `ratio` | Storyboard 的 `workflow_ratio`，同时写入任务元数据 |

LTX2.3 提示词固定，不读取对白正文、分镜视频提示词或 Agent 参数。实现时将 `StoryboardDigitalHumanConstants.DEFAULT_PROMPT` 的值统一修改为 `角色面向镜头深情的说话，固定镜头。`，业务代码和测试只引用常量符号，不再次硬编码该字符串。

当前 LTX2.3 With Voice 驱动不消费 `ratio`。计划中的 ratio 仅写入 `extra_config` 用于审计；实际画幅由首帧和上游工作流决定，不能宣称驱动会按该字段改变输出比例。

### 6.1 多段 TTS 合并

- 单段 TTS 直接使用原始 `audio_url`，不额外转码。
- 多段 TTS 按对白顺序下载并使用 ffmpeg 合并为单个 WAV。
- 合并音频必须位于持久化任务目录，不能放在请求完成后立即删除的临时目录。
- 合并采用统一采样率、声道数和 PCM 编码，避免源格式不一致。
- ffmpeg 调用必须显式传入新增的 `StoryboardTimeouts.DIGITAL_HUMAN_AUDIO_MERGE_TIMEOUT_SECONDS`，不复用导出流程的 `EXPORT_FFMPEG_TIMEOUT_SECONDS`，避免两个业务调整超时时相互影响。
- 合并失败时不得扣费或创建 `ai_tools`、Task、Asset。
- 合并文件在任务完成或失败后由任务清理流程删除。

## 7. 新增服务职责

在现有 `services/storyboard_digital_human_service.py` 中新增以下函数；这些函数当前均不存在，不应在实施计划中描述为已有函数拆分：

```text
resolve_digital_human_dialogues
        ↓
load_digital_human_tts_metadata
        ↓
probe_missing_digital_human_tts_durations
        ↓
build_digital_human_generation_plan
        ↓
prepare_digital_human_audio_input
        ↓
submit_digital_human_plan
```

### 7.1 `resolve_digital_human_dialogues`

校验单说话角色，按顺序返回完整对白文本及对应的所选 TTS 记录。

### 7.2 `load_digital_human_tts_metadata`

只读取数据库中的 TTS URL、选中指针和已保存时长，不下载文件、不运行 ffprobe、不合并音频。

### 7.3 `probe_missing_digital_human_tts_durations`

仅对数据库时长缺失的 TTS 执行 ffprobe，返回补全后的时长元数据；不下载或合并音频。

### 7.4 `build_digital_human_generation_plan`

根据统一阈值选择 Wan2.2 或 LTX2.3，生成模型对应的提示词、音频角色、比例及任务类型。

### 7.5 `prepare_digital_human_audio_input`

Wan2.2 选择最长 TTS 作为音色参考；LTX2.3 在必要时下载并合并多段实际说话音频。所有下载和 ffmpeg IO 只发生在该阶段。

### 7.6 `submit_digital_human_plan`

使用已经确定的计划创建 `ai_tools`、异步 Task 和 `StoryboardSceneAsset(video)`，并维护当前选中视频。

### 7.7 现有图片解析与就绪判定的语义变更

除新增上述流水线外，两个现有函数的语义必须同步修改：

- `resolve_digital_human_image_path`：由“角色参考图优先、回退选中首帧”改为“只使用当前分镜已选中且已生成完成的首帧图”，不再读取 `character.reference_image`，也不回退任何参考图。缺少合格首帧时抛 `ERROR_MISSING_IMAGE`，错误提示文案需同步更新为「对口型需要已生成完成的选中首帧图片」（现行文案「对口型需要角色形象图或选中首帧图片」已具有误导性）。
- `plan_digital_human_ready`：无需单独修改代码。其就绪判定委托给 `resolve_digital_human_image_path`，会随上述语义变更自动收紧：`missing_image` 触发条件从“既无角色图也无选中首帧”变为“无已生成完成的选中首帧”。批量补全的 skip 统计据此变化，存量仅靠角色参考图判定就绪的分镜将被标记为 `missing_image` 跳过。

## 8. 统一入口

以下入口必须调用同一个规划与提交服务：

- `POST /api/storyboard/scene/{scene_id}/generate-video`；
- Storyboard Agent 的 `generate_digital_human`；
- Storyboard CLI 的 `generate_video`；
- 批量补全缺失视频；
- 自动拆分后的数字人生成。

对口型分镜不允许调用方自行指定 `task_type`。为兼容旧客户端，原请求字段可以继续接收，但数字人路径忽略调用方传入的 `task_type`、`prompt`、`duration` 和 `ratio`，以服务端规划结果为准。

Agent 的数字人工具不再要求模型生成 prompt、duration 或 aspect ratio。首帧、对白、TTS、时长、比例和模型均由服务端从当前分镜解析。

### 8.1 CLI 与批量入口计费行为变更

当前 Storyboard CLI 和批量补全数字人路径没有完整执行数字人算力预扣。统一入口后，这两个入口开始按实际路由模型扣费，属于有意的行为变更：

- CLI 必须携带可用 `auth_token`；缺少计费身份时拒绝提交，不再免费建单。
- 批量任务以“每个分镜一个 transaction_id”独立扣费和退款，不使用整个批次共享 transaction_id。
- 某个分镜扣费或提交失败只标记该 item 失败，其余 item 继续执行。
- 批量响应分别汇总 submitted、failed、skipped，不因部分失败回滚已成功提交的分镜。
- 每个 item 必须记录 `task_type`、`computing_power` 和 `transaction_id`，以支持精确退款。

### 8.2 存量 Storyboard 比例兼容

- `workflow_ratio=original/custom`：通过扩充 Wan 注册配置继续支持，不属于 breaking change。
- `workflow_ratio` 为空：继续使用 Wan 默认比例 `9:16`。
- 其它不在 Wan `supported_ratios` 中的历史脏值：生成时返回 `unsupported_ratio`；前端提示用户先修正 Storyboard 画幅，不静默改变输出比例。
- 调用方请求中的 ratio 永远不能修复或覆盖 Storyboard 的无效比例，避免同一分镜从不同入口生成出不同画幅。

## 9. 算力与任务创建顺序

必须先完成模型规划，再根据实际任务类型扣除算力：

```text
生成计划
  → UnifiedConfigRegistry.get_by_id(plan.task_type)
  → 按 plan.billable_duration 计算算力
  → 扣除算力
  → 创建 ai_tools
  → 创建异步 Task
  → 创建并选中视频 Asset
```

不得继续使用固定 LTX2.3 配置预扣算力。多段音频合并等本地准备工作必须在扣费前完成。

`billable_duration` 的计算规则：

1. TTS 总时长已知时，Wan2.2 和 LTX2.3 都使用该总时长。Wan 虽然把音频作为音色参考，但它生成的对白正文与 TTS 文本相同，TTS 总时长是当前系统可获得的输出讲话时长估算。
2. 只有 LTX2.3 可能在时长未知时继续生成；此时使用 `scene.duration`。
3. `scene.duration` 也缺失或无效时，使用所选模型配置的 `default_duration`。
4. 最终时长不得低于模型计费允许的最小值，并由对应 `UnifiedTaskConfig.get_computing_power(duration=...)` 处理档位。

若扣费失败，不创建任何任务数据。建单后发生任务失败时，沿用现有 `transaction_id` 退款机制。

## 10. 任务元数据与响应

`ai_tools.extra_config` 增加可观测字段：

```json
{
  "video_type": "digital_human",
  "digital_human_model": "wan2.2",
  "speech_duration": 0.84,
  "routing_reason": "speech_duration_lte_1s",
  "audio_input_role": "voice_reference",
  "speaker_character_id": 123,
  "ratio": "16:9"
}
```

生成接口、Agent 和 CLI 返回统一字段：

```json
{
  "task_type": 13,
  "model_used": "Wan2.2",
  "speech_duration": 0.84,
  "routing_reason": "speech_duration_lte_1s",
  "audio_input_role": "voice_reference"
}
```

候选列表、任务日志和问题排查可以据此识别实际使用的模型。

字段存储契约必须保持唯一：

- `audio_input_role=voice_reference` 时，音频只写入 `ai_tools.message`，`audio_path=NULL`。
- `audio_input_role=speech_audio` 时，音频只写入 `ai_tools.audio_path`，`message=NULL`。
- `extra_config.audio_input_role` 是字段语义说明，不能与实际落库字段相冲突。

## 11. 声音同出和导出

Wan2.2 和 LTX2.3 产物都包含数字人说话音轨，因此 `digital_human` 分镜继续默认 `audio_embedded=1`：

- 导出时保留视频原音轨；
- 不重复混入该分镜的 TTS；
- 多段 TTS 的 LTX2.3 产物仍按最终合并音频处理。

## 12. 错误处理

| 场景 | 处理 |
|---|---|
| 没有有效对白 | 拒绝生成 |
| 多个说话角色 | 拒绝生成 |
| 没有任何已完成 TTS | 拒绝生成 |
| 没有已选中首帧，或所选首帧尚未生成完成 | 拒绝生成；不得回退到角色参考图 |
| Wan 的 Storyboard 比例不受支持 | 返回 `unsupported_ratio`，不得静默回退 |
| TTS 时长无法识别 | 默认选择 LTX2.3 |
| 多段 TTS 合并失败 | 拒绝提交，不扣费 |
| 所选模型未配置 | 返回对应模型不可用，不自动切换模型 |
| 扣费失败 | 不创建任务 |
| 异步任务失败 | 使用原 transaction ID 退款 |

## 13. 测试设计

### 13.1 路由边界

- `0.999s` 选择 Wan2.2。
- `1.000s` 选择 Wan2.2。
- `1.001s` 选择 LTX2.3。
- 时长未知选择 LTX2.3。
- 两段 TTS 分别为 `0.600s`，累计 `1.200s`，选择 LTX2.3。

### 13.2 Wan2.2 输入

- prompt 等于按顺序拼接的完整对白。
- TTS 参考音频写入 `ai_tools.message`。
- `audio_path` 为空。
- 多段 TTS 选择时长最长的一段作为参考。
- ratio 强制等于 Storyboard `workflow_ratio`。
- ratio 为空时使用 Wan 配置默认值；ratio 不受支持时返回 `unsupported_ratio`。
- `original/custom` 已加入 Wan 注册配置并可原样传给驱动。
- 请求参数 ratio 与 Storyboard ratio 不一致时，仍使用 Storyboard ratio。
- 图片只取当前选中首帧，不读取角色参考图。

### 13.3 LTX2.3 输入

- prompt 等于 `StoryboardDigitalHumanConstants.DEFAULT_PROMPT`，并单独断言该常量配置为产品确认的固定文案。
- 单段 TTS 写入 `ai_tools.audio_path`。
- 多段 TTS 按对白顺序合并。
- 合并失败不扣费、不建任务。
- 时长未知仍使用 LTX2.3。
- 图片只取当前选中首帧，不读取角色参考图。

### 13.4 入口一致性

- 直接 API、Agent、CLI 和批量入口对同一分镜选择相同模型。
- 每个入口按实际选中模型配置计算并扣除算力。
- CLI 缺少计费身份时拒绝提交；批量任务按 item 独立 transaction ID，部分失败不影响其他 item。
- 返回的 `model_used`、`task_type`、`routing_reason` 一致。
- 失败路径不产生孤立 Asset 或重复扣费。

## 14. 驱动兼容说明

`Ltx23WithVoiceRunninghubV1Driver` 当前构造参数 `driver_type=36`，而统一任务类型 `TaskTypeId.DIGITAL_HUMAN_LTX2_3_VOICE=32`。当前路由通过 `UnifiedTaskConfig.implementation` 选择驱动，因此不直接依赖该内部 `driver_type`，本设计不把 36 当成 task type。

实施时增加驱动注册测试，确保 task type 32 始终解析到 `LTX2_3_WITH_VOICE_RUNNINGHUB_V1`。是否进一步统一驱动内部 `driver_type` 需单独评估历史调用方，不能在本功能中直接改值。

## 15. 文档同步范围

实现时同步更新：

- `docs/storyboard/storyboard_digital_human.md`；
- `docs/storyboard/storyboard_design.md`；
- `docs/storyboard/storyboard_auto_missing_videos.md`；
- `docs/storyboard/storyboard_agent_image_chat.md` 中数字人工具说明。
