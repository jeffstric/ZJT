# 首帧参考混合收成参考生实现方——详细实现方案

状态：已实现（develop_f1186）。上游决定见 [h3_keyframe_ref_as_reference_implementation.md](h3_keyframe_ref_as_reference_implementation.md)（下称「决定文档」）。

实现与设计的差异（实现期发现）：
- `DriverInputProbe.image_mode` 改为 `extra_config`（JSON 字符串）字段——AIToolsModel 上 image_mode 存于 extra_config，钩子统一走 `parse_image_mode`，probe 与 ORM 行完全同形态。
- 兼容判定与裁图同时认「图N是首帧/尾帧」锚点句与 `@首帧图/@尾帧图` token（`prompt_marks_first_or_last_frame` / `effective_frame_flags`，正则统一维护在 h3_prompt_optimize_util）：scene_ai_chat 链路排图改写后的提示词不回传，最终提交原文保留 @token，只认锚点句会漏判。
- 裁图函数 `trim_reference_images_for_implementation` 同步重写提示词：删除被裁参考图的「图K是…」图例句并重排保留序号（画布链路图例句在前端拼好，服务端裁图必须同步清理，否则序号错位）。
- 提交划分调整为 C1（驱动钩子+工厂探测，纯增量）/ C2（原子业务切换：配置+server+storyboard+优化+前端同一 commit，避免「类型 50 禁用但 use_kfr 仍在」的退化窗口）/ C3（enterprise）/ C4（文档）。
- `estimate_scene_video_power` 未带探测（请求体无 prompt，拿不到点名标记）：当前混合实现方与默认参考生同价，估价与扣费无实际分叉；若混合实现方独立调价，需把 prompt 纳入估价请求体。

分支：`develop_f1186`（基于 `origin/develop` @ 6efddeb5f）。

调研基线：`be243a94`（参考生点名首帧时改交 RunningHub）已合入 develop，本方案**推翻**其「改交类型 50」路线，改为「类型 37 + 实现方选择」。

## 0. 现状摘要（调研结论）

| 项 | 现状 | 位置 |
| --- | --- | --- |
| 类型 37 参考生 | implementations=[RH 参考生(id 67, sort 5205), AutoDL 参考生(id 108, sort 5208)]，default=RH，max_multi_ref_images=9 | `config/unified_config.py:2851-2888` |
| 类型 50 kfr | hidden=True、单实现方 KFR(id 100, sort 5207)、max_multi_ref_images=3、未设 enabled=False | `config/unified_config.py:2921-2952` |
| KFR 驱动 | 继承 RH 参考生驱动，仅覆写 `__init__` + `build_create_request`（webapp 2108549232725680129，3 图槽+2 音频），**无** `validate_input_compatibility` | `task/visual_drivers/minimax_h3_keyframe_ref_runninghub_v1_driver.py` |
| 兼容钩子 | 基类默认恒兼容；3 处覆写（chenyu / autodl 参考生 / autodl 首尾帧）；**唯一生产调用点在失败重试候选选择** | `task/visual_drivers/base_video_driver.py:575-594`、`task/pipeline_drivers/__init__.py:462-477` |
| 工厂选择 | `get_implementation_for_user(task_type, user_id)` → `_get_implementation_for_user` 三层：偏好→sort_order 首个可用→默认；锁定偏好不可用=失败+清偏好 | `task/visual_drivers/driver_factory.py:225,288-397` |
| 改 task_type→50 共 4 处 | ①单分镜 `api/storyboard.py:4823-4831` ②AI-chat `api/storyboard.py:5578-5588` ③批量 `services/storyboard_agent_cli_service.py:1183-1191` ④画布前端 `web/js/shot_frame_video_generator.js:427-436` | — |
| 路由开关 | `H3_KEYFRAME_REF_ROUTE_ENABLED`（constant.py:1287，Python 消费仅 `services/storyboard_frame_mention.py:61`；前端两处镜像常量手工同步） | — |
| 排图/裁图 | `prepare_frame_mentions`（storyboard_frame_mention.py:120-193）排图+裁图一体，max_images 由 use_kfr 决定（kfr=3 / 37=9）；前端 `placeShotFrameMentionImages` 同构且预裁 3 | — |
| 变体判定 | `resolve_h3_prompt_variant` 按 task_key 判 KFRef/Ref2VA（KFRef 必须最先判） | `task/pipeline_drivers/h3_prompt_optimize_util.py:206-238` |
| image_prompt_note | 写入条件 `task_type == 50`（api/storyboard.py:5033-5038，全链路唯一按 type==50 门控的写入点） | — |
| 扣费 | `/api/ai-app-run-image` 与 `generate_scene_video` 均已按 `get_implementation_for_user` 解析后的实现方查表（事故 13452 修复，27e91b77）；两表当前同价 | `server.py:3092-3093,3318-3322`、`api/storyboard.py:4950-4977` |
| 估价 | `estimate_scene_video_power` 不感知 kfr（当前同价暂无分叉） | `api/storyboard.py:5092-5187` |
| enterprise 侧 | `_get_video_task_id` 有 `allow_hidden_kfr` 例外（唯一显式放行隐藏 50 的地方） | `enterprise/tools/video_tools.py:645-670` |

## 1. 目标数据流（改造后统一口径）

```
排图（@首帧图/@尾帧图 → 参考图两端 + 提示词改写为「图N是首帧/图N是尾帧」；不做上限裁剪）
  ↓
构造探测对象 DriverInputProbe（prompt / image_mode / reference_images / video …）
  ↓
VideoDriverFactory.get_implementation_for_user(37, user_id, input_probe=probe)
  三层（偏好→sort_order→默认）每层对候选调 validate_input_compatibility
  锁定偏好不兼容 → 快速失败（不静默换供应商，清偏好）
  ↓（失败则提交终止，不扣费不建行）
按选出的实现方裁图：KFR → 3 张（两端保留裁中间）+ 音频 2 路；其他 → 任务级 9 张
  ↓
扣费 get_computing_power(duration, implementation=实际实现方)
  ↓
建 ai_tools 行：type=37、implementation=选出的实现方 id
  ↓
执行：create_driver_by_implementation(implementation) —— 无行为变化
```

四条验收路径（决定文档）：
1. 点名首帧 + 固定 AutoDL → `type=37`、impl=`minimax_h3_reference_autodl_v1`、图不裁 3。
2. 点名首帧 + 无偏好 → impl=`minimax_h3_keyframe_ref_runninghub_v1`（sort 5204 最前且兼容）、图≤3、首帧第一张。
3. 无点名 + 无偏好 → impl=`minimax_h3_reference_runninghub_v1`（KFR 不兼容被跳过）。
4. 固定 KFR + 无点名 → 提交失败（FIXED_IMPLEMENTATION_UNAVAILABLE + 清偏好），不改走 AutoDL。

## 2. 分步实现

### Step 1 配置层

`config/unified_config.py`：
- 类型 37 的 `implementations` 列表加入 `MINIMAX_H3_KEYFRAME_REF_RUNNINGHUB_V1`，顺序 `[KFR, RH_REF, AUTODL_REF]`（与 sort 一致）。
- KFR 实现方（4397-4411 行处）：`sort_order` 5207.0 → **5204.0**（没偏好且点名时默认走锁帧混合模型）；`display_name` `'RunningHub'` → `'RunningHub（首帧参考）'`；description 保留 webapp/3 图槽/2 音频说明。
- 类型 50：`hidden=True` 保持，追加 **`enabled=False`**（参照 `minimax_h3_first_last_autodl_v1` 行 4418-4420 的代码级硬禁用写法与注释风格：enabled=False 不能被 implementation_power_config 重开）。任务 50 的 `implementation=KFR`、枚举、`DriverKey`、驱动类、实现方 id=100 全部保留。

`config/constant.py`：
- 删除 `H3_KEYFRAME_REF_ROUTE_ENABLED`（1281-1287 行，含「三处同步」注释）。
- `DRIVER_IMPLEMENTATION_MAPPING`（1068 行起）：类型 37 列表（1143-1147）补 KFR；类型 50 **不挂映射条目**（2026-11-11 追加调整：映射是 `api/admin.py` implementation-configs 分组的来源之一，挂了会在实现方管理页渲染出冗余的 `minimax_h3_keyframe_ref_to_video` 分组；历史在途行找驱动走 `create_driver_by_implementation` 按实现方名解析，不依赖该映射）。

不涉及表结构变化，**无 alembic 迁移**。

### Step 2 探测对象 + KFR 驱动兼容钩子

`task/visual_drivers/base_video_driver.py` 新增 dataclass（紧邻 `validate_input_compatibility`，字段名与 `AIToolsModel` 同名，钩子代码对 ORM 行与 probe 通用）：

```python
@dataclass
class DriverInputProbe:
    """实现方兼容性探测对象：提交期未建库前探测输入用，字段语义同 AIToolsModel。"""
    prompt: str = ""
    image_mode: str = ""
    reference_images: Optional[str] = None   # JSON 数组字符串，同 AIToolsModel.reference_images
    image_path: Optional[str] = None
    audio_path: Optional[str] = None
    video_path: Optional[str] = None
```

`task/visual_drivers/minimax_h3_keyframe_ref_runninghub_v1_driver.py` 实现钩子（正则从 `h3_prompt_optimize_util` **模块顶部 import**，与 `ref2va_marked_frame_clauses` 同源，保证「判定兼容」与「EXACT 锚点校验」口径一致；遵守 AGENTS R11）：

```python
def validate_input_compatibility(self, ai_tool) -> tuple[bool, Optional[str]]:
    mode = str(getattr(ai_tool, "image_mode", "") or "")
    prompt = str(getattr(ai_tool, "prompt", "") or "")
    if mode != "multi_reference":
        return False, "首帧参考混合模型仅支持参考模式"
    if not self.get_reference_images(ai_tool):
        return False, "首帧参考混合模型需要至少一张参考图"
    if not (_H3_FIRST_FRAME_MARK_RE.search(prompt) or _H3_LAST_FRAME_MARK_RE.search(prompt)):
        return False, "提示词未点名「图N是首帧/图N是尾帧」，不适用首帧参考混合模型"
    return True, None
```

说明：探测发生在排图改写**之后**（所有链路先排图，提示词已是「图1是首帧」形式），故只认「图N」形式即可，不认 `@首帧图`（决定文档口径）。RH 参考生与 AutoDL 参考生不新增钩子（默认恒兼容；AutoDL 参考生已有「无参考视频槽」钩子继续生效）。

### Step 3 工厂 probe 化

`task/visual_drivers/driver_factory.py`：
- 公开版 `get_implementation_for_user(cls, task_type, user_id=None)`（225 行）与 `_get_implementation_for_user`（288 行）都加可选参数 `input_probe=None`。**不传时行为完全不变**（其余 7 处调用方零改动）。
- 新增私有助手：

```python
@classmethod
def _candidate_input_compatible(cls, impl_name: str, input_probe) -> bool:
    # input_probe 为 None：不探测（保持旧行为，避免误伤其他任务）
    # 驱动无 validate_input_compatibility：视为兼容
    # 钩子抛异常：视为不兼容（跳过该候选）
```

- 三层接入（每层在既有 `_is_driver_available` + `_is_impl_enabled` 双校验通过后追加兼容检查）：
  - **偏好层**（312-357）：锁定偏好不兼容 → 并入现有 `locked_pref_failed` 分支（reason=`DRIVER_ERROR_FIXED_IMPLEMENTATION_UNAVAILABLE`，message 拼接不兼容原因），**清偏好、不降级**；未锁定偏好不兼容 → warning，继续自动选择。
  - **排序层**（360-366）：`_get_implementations_info()` 顺序遍历，取第一个「可用且兼容」的。
  - **默认层**（370-388）：`config.implementation` 追加兼容检查；不兼容则落入 `DRIVER_ERROR_NO_IMPLEMENTATION_AVAILABLE`。
- `create_driver_by_type`（119 行）透传 `input_probe`（参数从调用方传入，默认 None）。

### Step 4 server.py `/api/ai-app-run-image`

`server.py:3032-3486`：
1. **旧 task_id 翻译**（在 `get_by_id(task_id)` 之前）：`task_id == 50` 时 `logger.warning("legacy minimax_h3_kfr submit, re-recording as type 37 + keyframe_ref implementation")`，改 `task_id=37`，并记 `force_keyframe_ref_impl=True`。
2. **实现方解析移位**：删除 3092-3093 的提前解析；在图片归位（3169-3196）与音频归位（3199-3212）**之后**，构造 `DriverInputProbe(prompt=prompt, image_mode=image_mode, reference_images=json.dumps(reference_images 或解析后的 url 列表), video_path=...)`，调 `get_implementation_for_user(task_id, user_id, input_probe=probe)`；`force_keyframe_ref_impl` 时直接 `actual_impl = MINIMAX_H3_KEYFRAME_REF_RUNNINGHUB_V1`（旧行为等价：必走混合模型，跳过偏好）。
3. **快速失败**：`actual_impl is None` 且 `_last_create_error.reason == DRIVER_ERROR_FIXED_IMPLEMENTATION_UNAVAILABLE` → 返回业务错误（不扣费不建行，错误文案用 `_last_create_error.message`）。
4. **按实现方裁图**：`actual_impl == KFR` 且 `len(reference_images) > 3` → 两端保留裁中间（复用 Step 5 抽出的公共函数）；音频链路已由 `MAX_VOICE_REFERENCE_AUDIOS=2` + 驱动软截断兜底，不改。
5. 扣费（3318-3322）与建行（3386、3423-3457）逻辑不变——`implementation=impl_id` 本就写 `actual_impl`，此时已天然正确。

检查项：确认 3092-3318 之间 `actual_impl` 无其他消费者（若有，随移位一并处理）。

### Step 5 故事板三文件：排图/裁图拆分 + 删 use_kfr

`services/storyboard_frame_mention.py`：
- `prepare_frame_mentions` 拆分：**排图**（点名帧移两端 + 去重 + 提示词改写「图1/图N」）保留；**裁图**（reserved 判定 + `middle_urls[:limit-reserved]`）抽为公共函数：

```python
def trim_reference_images_to_limit(urls: list[str], prompt: str, max_images: int) -> list[str]:
    """按上限裁参考图：prompt 点名首/尾帧时两端保留、从中间参考的尾部裁；未点名裁尾部。"""
```

- 删除 `should_use_h3_keyframe_ref`、`H3_KEYFRAME_REF_ROUTE_ENABLED` import、`h3_keyframe_ref_task_id`（若无他处引用；`H3_KEYFRAME_REF_MAX_IMAGES=3` 保留，供裁图上限用）。

`services/storyboard_agent_cli_service.py`：
- `apply_collected_frame_mentions`（4688-4746）：删 `use_kfr` 判定，不再返回第 4 个值（返回 `(rewritten, next_urls, next_items)`）；排图不裁，max_images 不再传入。
- `generate_video`（1102-1119、1183-1191）：删 `task_type = h3_keyframe_ref_task_id()` 与 snapshot 克隆；建行前按 Step 4 同口径构造 probe → `get_implementation_for_user(37, user_id, input_probe=probe)` → 裁图（KFR→3）→ `implementation=impl_id` 写入建行参数（实现时追批量链路建行点，确保 implementation 落到 ai_tools 行）。
- 音色跳过/说话人过滤（1201-1238）：`task_type in (50, 37)` 双列 → 只判 37。

`api/storyboard.py`：
- `generate_scene_video`：删 4643-4646 的「显式传 50 按未指定」与 4823-4831 的 use_kfr 换绑；流程重排为「排图（不裁）→ probe 选实现方（4960 处改为带 probe）→ 裁图 → 扣费（不变，传 actual_impl）→ 建行 type=37」。
- `scene_ai_chat`：删 5393/5419-5438 的 use_kfr 判定与 5578-5588 的 snapshot 换绑；提交参数带 implementation（同上口径）。
- 音色双列（4843/4850）→ 只判 37。
- `image_prompt_note`（5033-5038）：条件 `task_type == 50` → `actual_impl_name == MINIMAX_H3_KEYFRAME_REF_RUNNINGHUB_V1`。
- `estimate_scene_video_power`（5092-5187）：同样构造 probe 解析实现方后查表（当前两表同价，改后口径统一、防未来分叉；注释「估价=扣费=执行」）。
- 快速失败：同 Step 4.3（锁定 KFR 无点名 → 4xx 返回 `_last_create_error.message`）。

### Step 6 提示词优化按实现方判变体

`task/pipeline_drivers/h3_prompt_optimize_util.py:206-238` `resolve_h3_prompt_variant`：
1. 先读 `ai_tool.implementation`（int id）→ 反查实现方名（`config/unified_config` 已有 `IMPLEMENTATION_TO_ID`（1845 行），若无现成反查函数则模块内新增 `ID_TO_IMPLEMENTATION` 反转 dict + `get_implementation_name(impl_id)`）；id=0/未注册 → 忽略走 task_key。
2. `impl_name == KFR` → KFRef 分支（需 images 或 audios）；**优先于 task_key 判定**。
3. task_key 兜底链保持：`==50` → KFRef（历史在途行 implementation 也=100，双保险）；`==37` → Ref2VA。

`_H3_PROMPT_OPTIMIZE_KEYS`（含 37/50）与 `needs_h3_atomic_param_prepare` 不变。EXACT 锚点/无对白删 audio 整句（be243a94）不动。`build_h3_prompt_optimize_step_configs`（`task/pipeline_drivers/__init__.py:256-308`）无需改——variant 由上面函数返回，KFREF 分支的 keyframe_slots/image_prompt_note 读取自动生效。

### Step 7 前端

`web/js/shot_frame_video_generator.js`：
- 删常量 `H3_KEYFRAME_REF_SHORT_KEY`、`H3_KEYFRAME_REF_ROUTE_ENABLED`（160-166，保留 `H3_KEYFRAME_REF_MAX_IMAGES`？不保留——前端不再预裁）；删 `shouldUseH3KeyframeRefModel`、`resolveShotFrameReferenceSubmitModel`、`shotFrameMentionImageLimit` 的 3 分支（上限回到模型 `max_multi_ref_images`）。
- `generateShotFrameVideo`：`submitModel` 恒为 `videoModel`（427-436 简化）；删「未找到 minimax_h3_kfr 配置」报错与 471-472 kfr toast。
- **保留**：`isH3ReferenceVideoModel`、`placeShotFrameMentionImages` 排图两端+序号顺延+提示词改写、`ensureShotFrameMentionTokens`/`syncShotFrameAutoPrompt`（首帧自动带入是点名来源）、`resolveMentionLastFrameUrl`。张数超限由服务端按实现方裁。

`web/js/storyboard/frame_mention.js`：删 `H3_KEYFRAME_REF_ROUTE_ENABLED`、`shouldUseH3KeyframeRef` 及 `findFrameMentionError` 的 3 上限分支（上限回到 `model.max_multi_ref_images`）。
`web/js/storyboard/events.js:1125-1145` `guardFrameMentions`：删 `msg_h3_keyframe_ref_route` toast 分支；i18n 词条 `msg_h3_keyframe_ref_route`（en/storyboard.json:455 及各语言）删除。
`web/js/voice_reference.js:100-104` 的 kfr key **保留**（音色指纹注入用，与路由无关）。

### Step 8 enterprise 仓（单独提交）

`enterprise/tools/video_tools.py:645-670`：删除 `allow_hidden_kfr` 例外块，回归「隐藏任务一律拒绝」——类型 50 `enabled=False` 后 `cfg.enabled` 检查天然拦截显式传 50，回退偏好/默认（37）。enterprise 基于其 `origin/develop`（当前 a362e59）建同名 `develop_f1186` 分支提交。

## 3. 兼容与迁移

| 项 | 处理 |
| --- | --- |
| 在途 type=50 行（状态查询/优化/重试） | 状态查询优先 `create_driver_by_implementation(100)`（历史行 implementation=100，不走任务级 enabled 拦截）；重试候选走类型 37 配置的 `implementations` 声明；`needs_h3_atomic_param_prepare(50)` 仍 True；`resolve_h3_prompt_variant` 的 task_key==50 兜底保留 |
| 实现方管理页分组 | KFR 不再单独成组（映射条目已删 + admin 兜底扫描跳过 `enabled=False` 条目）；KFR 实现方在 `minimax_h3_reference_to_video`（参考生）组内管理，算力/排序/启用配置键 `(kfr, driver_key=type37)` 不变 |
| 旧页面仍 POST task_id=50 | server.py 翻译为 37 + 强制 KFR 实现 + 警告日志（Step 4.1） |
| 管理页 `implementation_power_config` 旧行 | 旧行 `(kfr, driver_key=type50)` 对不上新键 `(kfr, driver_key=type37)`，**不迁移不抄**；新键无记录用代码默认（sort 5204 / enabled True） |
| 用户偏好键 | 偏好一直存 `minimax_h3_reference_to_video` 下，无需迁移；固定 AutoDL/RH 参考生的行为不变（兼容矩阵两条「兼容」） |
| 固定 KFR 的存量偏好 | 此前 50 不进偏好槽位，不存在该键存量；新固定语义=无点名提交快速失败并清偏好 |

## 4. 测试计划

新增（后端，建议 `tests/task/test_h3_kfr_implementation_selection.py` + 驱动测试扩展）：
1. 固定 AutoDL + 点名首帧 → impl=autodl_ref，参考图不裁 3（决定文档验收 1）。
2. 无偏好 + 点名首帧 → impl=kfr，图裁 3、首帧第一张（验收 2）。
3. 无点名 + 无偏好 → impl=rh_ref（kfr 被 probe 跳过，验收 3）。
4. 固定 kfr + 无点名 → 返回 None + `_last_create_error.reason=FIXED_IMPLEMENTATION_UNAVAILABLE`，偏好被清（验收 4）。
5. `input_probe=None` → 行为与现状完全一致（回归保护）。
6. KFR 驱动 `validate_input_compatibility` 单测：multi_reference+点名→兼容；无点名 / first_last_frame 模式 / 无参考图→不兼容。
7. `resolve_h3_prompt_variant`：type=37+implementation=100→KFRef；type=50+implementation=100→KFRef（历史兜底）；type=37+implementation=0→Ref2VA。
8. server.py 收 task_id=50 → 行 type=37、implementation=100、有警告日志。

改造存量：
- `tests/storyboard/test_storyboard_agent_cli_service.py:2881-2945`：断言 `task_type==50` → `type==37` + `implementation==100` + 3 张裁剪 + 首尾两端 + snapshot 不含 50。
- `tests/storyboard/test_storyboard_frame_mention.py`：118-139 门控测试删（flag 不存在）；142-150 改为「50 enabled=False 后 `_get_video_task_id(preferred=50)` 回退 37」（enterprise 侧例外删除）。
- `tests/task/test_h3_prompt_optimize.py:522-533`：KFRef 变体用例改为按实现方触发；补 type=50 历史兜底。
- `tests/drivers/test_pipeline_drivers.py`：补「兼容性 False 候选被跳过、选下一个」的工厂层用例（现只有 mock True 的用例）。
- `web/tests/shot_frame_h3_keyframe_ref.test.js`：删换绑断言，改「提交模型保持原值、上限回到模型 max_multi_ref_images」；`shot_frame_ref_mentions.test.js` 排图用例保留（逻辑未变）。
- `web/tests/storyboard_frame_mention.test.js`：`over_capacity` 断言改按模型上限。
- `tests/task/test_pipeline_processor.py:478`：KFRef(50) `needs_h3_atomic_param_prepare` 不变，保留。

## 5. 风险与验证点

1. **在途 50 状态查询回归**：任务级 enabled=False 后跑一次历史 50 行 `check_status`（走 implementation=100 路径）；`create_driver_by_type(50)` 若被任务级 enabled 拦截需确认查询链路不经过（调研显示查询优先按 implementation 建驱动）。
2. **快速失败路径**：此前 `actual_impl=None` 时提交链路静默继续（implementation=0），现在要显式拒绝——确认两个入口（run-image、generate_scene_video）的返回码与文案。
3. **probe 与 ORM 字段形态一致**：`reference_images` 必须是 JSON 字符串（同 AIToolsModel），否则 `get_reference_images` 解析失败导致误判不兼容。
4. **排序层性能**：每层候选实例化驱动做探测（与既有 `_is_driver_available` 同量级），无额外 I/O，可接受。
5. **批量链路建行点**：`storyboard_agent_cli_service.generate_video` 最终建 ai_tools 行的代码路径需实现时确认 implementation 传到位（调研未覆盖到最终 INSERT 点）。
6. **正则同源**：兼容判定必须 import `h3_prompt_optimize_util` 的 `_H3_FIRST_FRAME_MARK_RE/_H3_LAST_FRAME_MARK_RE`，禁止复制副本（与锚点校验口径漂移风险）。

## 6. 提交顺序（建议 8 个 commit）

1. `refactor(config): KFR 实现方挂进类型 37，类型 50 硬禁用`（unified_config + constant + 配置测试）
2. `feat(drivers): DriverInputProbe + KFR 驱动 validate_input_compatibility`（含驱动单测）
3. `feat(factory): 实现方选择三层接入兼容探测`（probe 参数默认 None，旧行为不变 + 工厂测试）
4. `feat(server): run-image 提交按实现方探测/裁图，旧 50 翻译为 37`（含端点测试）
5. `refactor(storyboard): 删 use_kfr 改 task_type，排图/裁图拆分按实现方裁`（三文件 + estimate 同口径）
6. `refactor(optimize): 提示词优化变体先看实现方再看任务键`
7. `refactor(web): 删前端 kfr 换绑与 3 张预裁`（两 JS + i18n + web 测试）
8. `docs: 同步 6 份文档，删「改交隐藏任务 50」说法`（见下）

文档同步清单：`docs/video/shot_frame_video_mode.md`、`docs/storyboard/storyboard_reference_to_video.md`、`docs/storyboard/storyboard_auto_missing_videos.md`、`docs/drivers/minimax_h3_keyframe_ref_runninghub_v1_driver.md`、`docs/drivers/minimax_h3_reference_runninghub_v1_driver.md`、`docs/backend/pipeline_steps.md`；决定文档 `h3_keyframe_ref_as_reference_implementation.md` 状态改为「已实现」。

enterprise 仓单独一个 commit：`refactor(video_tools): 删隐藏任务 50 显式放行例外`。
