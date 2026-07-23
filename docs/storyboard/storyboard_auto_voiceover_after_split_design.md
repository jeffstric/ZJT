# 剧本拆分后自动配音未生成：调查与修改方案

## 1. 问题概述

故事板从剧本拆分并发布分镜后，系统预期自动为有对白的分镜提交配音任务。2026-07-16 对故事板 26 的生产监控发现：

- 已成功发布 19 个分镜。
- 已写入 16 条 `storyboard_dialogue`。
- 4 个对白角色均已配置 `character.default_voice`。
- `storyboard_dialogue.selected_audio_id` 全部为空。
- `storyboard_dialogue_audio` 为 0 条。
- 对应 `ai_audio` 和 `tasks(TASK_TYPE_GENERATE_AUDIO)` 均为 0 条。

因此本次问题不是 TTS 模型执行失败，而是配音任务根本没有被提交。

## 2. 根因

### 2.1 异步拆分改造遗漏发布后处理

`POST /api/storyboard/{storyboard_id}/generate-from-script` 已改为只创建持久化拆分任务并返回 202。接口注释说明：

```text
资产化 -> create_scenes -> 配音/宫格提交
```

应由 worker 的 publishing 阶段完成。

但当前 `services/script_split_engine.py::step_publish()` 实际只执行：

1. 场景资产化。
2. 构造 `scenes_payload`。
3. 调用 `StoryboardModel.create_scenes()` 创建分镜和对白。
4. 把拆分任务直接标记为 `completed`。

它没有调用 `_auto_submit_storyboard_dialogue_voiceovers()`。

### 2.2 自动配音函数的数据输入与新发布流程不匹配

`_auto_submit_storyboard_dialogue_voiceovers(scenes, user_id)` 要求输入数据已经包含：

- scene 数据库 ID。
- dialogue 数据库 ID。
- 每个 scene 下的 `dialogues` 列表。

而 `StoryboardModel.create_scenes()` 只返回创建数量，不返回新建的 scene/dialogue ID。发布流程持有的 `scenes_payload` 只是入库前 payload，因此不能直接传给自动配音函数。

### 2.3 发布恢复分支会永久跳过配音

如果 scenes 已全部落库，`step_publish()` 的恢复分支会根据 `existing_count == expected_count` 直接把任务标记完成。

这意味着即便简单地在首次创建后增加自动配音调用，仍存在以下崩溃窗口：

```text
scenes/dialogues 事务提交成功
  -> 进程重启或异常
  -> 尚未提交音频任务
  -> publishing 重试发现 scenes 数量完整
  -> 直接标记 completed
  -> 音频永久遗漏
```

### 2.4 现有单条提交不是原子操作

`submit_storyboard_dialogue_voiceover()` 当前依次执行：

1. 创建 `ai_audio`。
2. 创建 `tasks` 队列记录。
3. 创建 `storyboard_dialogue_audio`。
4. 更新 `storyboard_dialogue.selected_audio_id`。

四步使用独立数据库操作。如果中间失败，可能留下孤立 `ai_audio`、孤立 task 或未选中的 dialogue audio。重试时仅依赖 `selected_audio_id` 判断，会有重复提交风险。

### 2.5 已确认不是音频调度器缺失

音频调度器已经注册：

- 每 13 秒执行 `generate_audio_task()`。
- 读取 `tasks` 中 `TASK_TYPE_GENERATE_AUDIO` 且 queued 的记录。
- 调用 `task/audio_task.py::process_generate_audio()`。

本次数据库中连 queued task 都没有，因此故障发生在“发布后自动提交”阶段，而不是音频 scheduler 或 TTS driver 阶段。

## 3. 目标

1. 剧本拆分发布成功后，所有具备对白和有效声音参考的 dialogue 都可靠进入音频任务队列。
2. 发布首次执行、进程重启恢复、用户点击重试时均保持幂等，不重复创建音频任务。
3. 拆分任务只等待“音频任务已可靠入队”，不等待 TTS 实际生成完成。
4. 单条配音提交必须保证 `ai_audio`、`tasks`、`storyboard_dialogue_audio`、`selected_audio_id` 原子一致。
5. 缺少声音、空文本、旁白无音色等业务跳过必须可观测，不能静默消失。
6. 临时数据库异常必须让 publishing 重试，不能把拆分任务错误标记为 completed。
7. 手动生成配音入口与自动生成入口复用同一套原子提交能力。
8. 所有 Web 异步接口继续通过 `asyncio.to_thread` 执行同步数据库操作，不阻塞事件循环。

## 4. 非目标

- 本方案不修改 TTS 模型、音色克隆算法或音频质量。
- 本方案不要求拆分任务等待所有音频真正生成完成。
- 本方案不处理效果模式严格按幕生图；该问题见独立设计文档。
- 本方案不自动为缺少 `default_voice` 的角色生成声音资产。
- 本方案不覆盖或替换用户已经手动选择的配音。

## 5. 方案比较

### 方案 A：发布末尾重新查询 scenes 后调用现有函数

创建 scenes 后重新执行 `list_by_storyboard()`、`_attach_dialogues()`，再调用 `_auto_submit_storyboard_dialogue_voiceovers()`。

优点：改动少，可快速恢复大部分自动配音。

缺点：

- scenes 提交与音频提交之间仍有崩溃窗口。
- 恢复分支需要额外补丁。
- 单条音频四步写库仍不是原子操作。
- 并发重试可能重复创建任务。

### 方案 B：独立配音引导/对账服务（推荐）

新增 `StoryboardVoiceoverBootstrapService`，按 `script_split_task_id` 查询已落库的真实 scenes/dialogues，对每条 dialogue 做幂等对账，并在事务内创建完整的音频任务链。

优点：

- 同时覆盖首次发布和发布恢复。
- 以数据库真实状态为准，不依赖入库前 payload。
- 可实现单条 dialogue 的原子提交和并发幂等。
- 不要求新增业务任务表。
- 手动生成接口可以复用同一原子提交方法。

缺点：需要增加事务型 repository 方法，并调整 publishing 状态机。

### 方案 C：新增音频 outbox / 批次表

在 scene/dialogue 落库事务中同时写入 audio outbox，由独立 worker 消费。

优点：跨进程一致性最强，天然支持批次进度和审计。

缺点：需要新表、迁移、消费器和历史兼容；当前规模下复杂度较高。

结论：采用方案 B。保留未来把对账服务演进成 outbox 的可能，但本次不引入新表。

## 6. 推荐架构

新增：

```text
services/storyboard_voiceover_bootstrap_service.py
```

核心职责：

- `ensure_for_split_task(split_task_id, user_id, limit)`：对账本次拆分发布出的全部对白。
- `ensure_dialogue_voiceover(dialogue_id, user_id, config)`：事务内确保单条对白存在一个有效的选中音频任务。
- 返回结构化 summary，供发布状态、日志和 API 展示。

建议返回：

```json
{
  "eligible_count": 16,
  "submitted_count": 16,
  "reused_count": 0,
  "skipped_count": 0,
  "failed_count": 0,
  "remaining_count": 0,
  "skipped": [],
  "failures": []
}
```

`api/storyboard.py` 中现有自动/手动配音函数改为调用该服务，避免维护两套提交逻辑。

## 7. 数据查询范围

自动对账不能按整个 storyboard 无条件扫描，必须限制在当前拆分任务：

```sql
SELECT d.*, s.storyboard_id, s.script_split_task_id
FROM storyboard_dialogue d
JOIN storyboard_scene s ON s.id = d.scene_id
WHERE s.script_split_task_id = :split_task_id
ORDER BY s.sort_order, d.sort_order, d.id;
```

这样可以：

- 避免误处理用户手工创建的旧分镜。
- 避免另一次拆分任务的对白混入。
- 支持发布重试按任务精准恢复。

## 8. 单条对白的幂等与原子提交

### 8.1 事务边界

对每条 dialogue 使用一个短事务：

```text
BEGIN
  SELECT storyboard_dialogue ... FOR UPDATE
  检查 selected_audio_id 和现有 dialogue_audio
  校验 text、character、default_voice
  INSERT ai_audio
  INSERT tasks
  INSERT storyboard_dialogue_audio
  UPDATE storyboard_dialogue.selected_audio_id
COMMIT
```

任一步失败都回滚，禁止留下半条任务链。

事务只包含数据库操作，不在事务内调用 TTS、网络请求或文件操作。

### 8.2 幂等判定

持有 dialogue 行锁后按以下顺序判定：

1. `selected_audio_id` 指向有效 `storyboard_dialogue_audio`，且关联 `ai_audio` 为 pending/processing/completed：返回 `reused`。
2. `selected_audio_id` 指向用户上传音频或已有有效 URL：返回 `reused`，绝不覆盖。
3. `selected_audio_id` 指向失败的自动音频：首次发布对账不自动覆盖，交给既有 scheduler 重试或用户显式重试。
4. `selected_audio_id` 为空，但存在同 dialogue 的 pending/processing `dialogue_audio`：恢复选择该记录并返回 `reused`。
5. 都不存在：创建新的完整任务链。

并发执行时，第二个调用会在行锁后看到第一个调用已经写入的 `selected_audio_id`，因此不会重复创建。

## 9. Publishing 状态机接入

### 9.1 首次发布

```text
location bootstrap
  -> create_scenes / dialogues 事务完成
  -> voiceover bootstrap 对账
  -> remaining_count = 0
       -> 标记 split task completed
  -> remaining_count > 0
       -> 保持 publishing，下一个 worker tick 继续对账
  -> 临时系统错误
       -> 抛 voiceover_bootstrap_failed，按现有任务重试机制处理
```

### 9.2 发布恢复

当前 `existing_count == expected_count` 分支不能直接 completed，必须先执行 voiceover bootstrap：

```text
scenes 数量完整
  -> 对账当前 split_task_id 的 dialogues
  -> 所有可提交对白已 submitted/reused/skipped
  -> 才能 completed
```

这会关闭“分镜已提交、音频未提交、进程重启”的恢复漏洞。

### 9.3 不等待音频完成

拆分任务完成条件是：

- scenes/dialogues 已落库。
- 所有符合条件的音频任务已经原子入队，或者有明确业务 skip。

不要求 `ai_audio.status=COMPLETED`。TTS 生成继续由每 13 秒运行的音频 scheduler 异步完成。

## 10. 大量对白的分批提交

现有 `MAX_AUTO_SUBMIT_PER_SPLIT=100` 会把超过上限的对白永久标记为 skip，因为发布随后直接完成。

修改为“单个 publishing step 的批量大小”，而不是整次拆分的永久上限：

```text
AUTO_VOICEOVER_SUBMIT_BATCH_SIZE = 100
```

- 每个 worker step 最多处理 100 条尚未对账的对白。
- 如果 `remaining_count > 0`，任务保持 publishing。
- 下一个 tick 继续处理剩余对白。
- 直到全部对白进入 submitted/reused/skipped 分类后才结束发布。

该常量应维护在 `config/constant.py`。

## 11. 跳过与失败语义

### 11.1 业务跳过，不阻塞发布

| 原因 | code | 行为 |
|---|---|---|
| 台词为空 | `empty_text` | skip，记录 dialogue/scene |
| 角色缺少参考声音 | `missing_reference_audio` | skip，前端提示补声音后可手动生成 |
| 旁白没有默认音色 | `narration_without_voice` | skip |
| 已有选中配音 | `already_has_selected_audio` | reused，不覆盖 |

### 11.2 系统错误，阻止错误完成

以下错误不得静默 skip：

- 数据库连接或事务失败。
- 创建 `ai_audio`、`tasks` 或 `dialogue_audio` 失败。
- dialogue 归属与 user/split task 不一致。
- selected audio 指向不存在记录且无法恢复。

这些错误返回 `voiceover_bootstrap_failed`，让 publishing 重试。达到任务级重试上限后暂停，并保留明确错误信息。

### 11.3 TTS 执行失败

音频成功入队后，后续 TTS 失败由现有 `task/audio_task.py` 管理：

- 增加 `try_count`。
- 设置 `next_trigger` 做退避重试。
- 达到最大重试次数后把 task 和 `ai_audio` 标记失败。
- 失败原因写入 `ai_audio.message`。

这类失败不回滚已经完成的剧本拆分，但必须能在故事板任务状态中显示。

## 12. 状态与日志

### 12.1 发布摘要

将本次对账摘要写入 `final_result.metadata.voiceover_bootstrap`，至少包含：

- enabled。
- eligible/submitted/reused/skipped/failed/remaining 数量。
- skip reason 聚合。
- 最后处理时间。

不在该字段保存 token、声音文件绝对路径或完整台词。

### 12.2 结构化日志

建议日志前缀：`[voiceover-bootstrap]`。

至少记录：

- split_task_id、storyboard_id、dialogue_id、scene_id。
- decision：submitted/reused/skipped/failed。
- audio_id、dialogue_audio_id、task queue id。
- skip/error code。
- 本轮 summary 和 remaining_count。

### 12.3 前端可观测性

`GET /api/storyboard/{storyboard_id}/task-status` 已能返回 dialogue 的选中音频状态。建议拆分完成弹框额外显示：

```text
配音已提交 14 条，跳过 2 条（2 个角色缺少声音）
```

TTS 仍在生成时显示“配音生成中 x/y”，不能把“分镜首帧完成”误认为声音也已完成。

## 13. 手动配音入口复用

`POST /dialogue/{dialogue_id}/generate-voiceover` 应复用同一个事务型 `ensure_dialogue_voiceover()`：

- 自动入口使用 `skip_existing=true`。
- 手动明确重试时可通过配置允许创建新候选并设置为 selected。
- 权限校验仍由 API 层负责。
- 服务层必须再次校验 dialogue 归属的 user_id，避免绕过 API 调用。

## 14. 数据库变更

推荐方案不要求新增表或字段，但需要：

- 在 model/repository 层增加接受现有 transaction connection 的原子创建方法。
- 使用 `SELECT ... FOR UPDATE` 锁定 dialogue。
- 确认 `tasks(task_type, task_id)` 不会因恢复逻辑产生重复记录。

如果实现阶段发现无法在现有 repository 中安全完成跨表事务，再升级为方案 C，并按项目要求增加 Alembic 迁移；不得用多个独立 model create 假装原子提交。

## 15. 测试方案

### 15.1 根因回归测试

1. `step_publish` 创建含对白的 scenes 后，必须产生 `ai_audio`、`tasks`、`storyboard_dialogue_audio` 和 `selected_audio_id`。
2. `existing_count == expected_count` 的恢复分支仍会执行音频对账。
3. 对账完成前不得把 split task 标记 completed。

### 15.2 原子性与幂等测试

1. 同一 dialogue 连续调用两次，只产生一条有效自动配音任务链。
2. 两个并发线程对同一 dialogue 提交，只产生一条任务链。
3. 在四步写库的任一步注入异常，事务回滚后不存在孤立记录。
4. 已有 pending/processing/completed 选中音频时返回 reused。
5. 已有用户上传音频时不覆盖 selected。
6. 存在未选中的 pending dialogue audio 时能够恢复选择，不重复创建。

### 15.3 业务分类测试

1. 空文本返回 `empty_text`。
2. 角色缺少 `default_voice` 返回 `missing_reference_audio`。
3. 无角色旁白返回 `narration_without_voice`。
4. 全部角色有声音时，submitted_count 与 eligible_count 相等。
5. 超过 100 条对白时分多个 publishing tick 全部入队，不永久 skip。

### 15.4 调度器集成测试

1. queued audio task 被 13 秒 scheduler 消费。
2. 成功后回写 `ai_audio.result_url` 和 `storyboard_dialogue_audio.audio_url`。
3. ffprobe 成功后回写 duration，并在场景全部配音完成后重算 scene duration。
4. TTS 失败执行退避重试，达到上限后状态和 message 正确。

### 15.5 非阻塞与回归测试

- Web async 函数中的同步数据库调用全部使用 `asyncio.to_thread`。
- 运行 `scripts/lint_blocking_calls.py`。
- 手动生成配音 API 继续正常工作。
- 无对白剧本正常完成，不创建音频任务。
- 分镜首帧批次不依赖音频完成，不被 TTS 慢任务阻塞。

## 16. 实施步骤

1. 为当前“发布后没有音频记录”增加失败测试。
2. 新增事务型单 dialogue 配音提交 repository/service。
3. 新增 `StoryboardVoiceoverBootstrapService.ensure_for_split_task()`。
4. 在首次发布和幂等恢复两个分支接入对账。
5. 把 100 条限制改为每个 publishing step 的批量大小。
6. 让现有自动和手动配音入口复用原子提交服务。
7. 增加发布摘要、结构化日志和 status 展示。
8. 更新相关 storyboard 文档，删除“worker 已完成配音提交”但代码未实现的错误描述。
9. 运行定向测试、storyboard 回归测试、audio task 测试和阻塞调用检查。
10. 使用独立测试故事板完成一次真实拆分，持续监控到至少一条音频生成完成。

## 17. 验收标准

以下条件必须全部满足：

1. 有 16 条合格对白时，发布结束后数据库存在 16 条 selected dialogue audio 和 16 条 audio queue task。
2. split task 可以先于 TTS 完成，但不能先于所有合格对白可靠入队。
3. 服务在 scenes 创建后重启，恢复 publishing 后仍会补齐缺失音频任务。
4. 同一 dialogue 不会因 scheduler 重入、发布重试或用户重复点击产生重复自动任务。
5. 任一事务步骤失败不会留下孤立 `ai_audio`、task 或 dialogue audio。
6. 缺少角色声音的对白有明确 skip reason，前端和日志均可定位。
7. 音频 scheduler 能把 queued 任务推进到 completed 或明确 failed。
8. 完成音频会回写 URL、duration，并正确联动 scene duration。
9. 无 token、绝对声音路径或完整敏感台词写入诊断摘要。
10. 所有 Web API 保持非阻塞，相关回归测试通过。

## 18. 实施记录（2026-07）

方案 B 已落地，采用「model 加 conn 变体 + conn 封闭在原子函数内」的实现路径。

### 18.1 防腐化事务设计（§8.1 的强化）

为防止后来者在事务里堆积慢操作（网络/文件/TTS/IO）导致行锁长期持有、阻塞并发更新，采用「conn 不外泄」设计：

- `_submit_dialogue_voiceover_atomically`（`services/storyboard_voiceover_bootstrap_service.py`）自包含事务：`with transaction() as conn:` 在函数体内，conn 是局部变量，函数返回即销毁。调用方拿不到 conn，无法在事务中间插入任何代码。
- 业务校验（text 为空、角色无声音）在事务**外**完成，跳过的不进事务，进一步缩短事务窗口。
- 每个 `*_in_transaction` model 方法和原子函数顶部都有 ⚠️ 注释块，明确「禁止网络/文件/TTS，须毫秒级」。
- 批量对账（`ensure_for_split_task`）逐条调用原子函数，每条是独立短事务，不是一个大事务锁多行。

### 18.2 改动文件

| 文件 | 改动 |
|------|------|
| `model/database.py` | 新增 `execute_query_in_transaction`（事务内 SELECT，含 FOR UPDATE） |
| `model/ai_audio.py` | 新增 `create_in_transaction`（⚠️ 注释，SQL 复用） |
| `model/tasks.py` | 新增 `create_in_transaction`（⚠️ 注释，SQL 复用） |
| `model/storyboard_dialogue_audio.py` | 新增 `create_in_transaction` / `set_selected_in_transaction`（⚠️ 注释） |
| `config/constant.py` | 新增 `AUTO_VOICEOVER_SUBMIT_BATCH_SIZE = 100` |
| `services/storyboard_voiceover_bootstrap_service.py` | 新增（conn 封闭的原子函数 + 对账入口） |
| `services/script_split_engine.py` | `step_publish` 接入对账 + 新增 `_reconcile_voiceover_and_finalize` + 恢复分支修复 |
| `api/storyboard.py` | 手动入口 `submit_storyboard_dialogue_voiceover` 复用原子函数；`_auto_submit_storyboard_dialogue_voiceovers` 标记废弃 |
| `tests/storyboard/test_storyboard_voiceover_bootstrap.py` | 新增（7 个测试覆盖原子性/幂等/业务分类/对账） |

### 18.3 关键实现细节

- **恢复分支修复**：原 `existing_count == expected_count` 直接 completed 的分支，改为先调 `_reconcile_voiceover_and_finalize` 对账，关闭 §2.3 的「scenes 已提交、音频未提交、进程重启」漏洞。
- **remaining>0 保持 publishing**：对账未完成时，任务保持 `STATUS_PUBLISHING`（在 `claim_next_task` 的 recoverable 列表内），lease 过期后下个 tick 重新领取继续对账。
- **metadata 摘要**：对账完成后写入 `final_result.metadata.voiceover_bootstrap`（eligible/submitted/reused/skipped/failed/skip_reasons/completed_at），不保存 token/绝对路径/完整台词。
- **TTS 在事务外**：事务只创建 `ai_audio` + `tasks` 入队，真正 TTS 由独立的 13 秒音频调度器（`task/audio_task.py`）异步执行。


