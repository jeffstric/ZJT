# 剧本拆分 · 总分镜时长控制 测试文档（移交版）

> 移交对象：负责本功能测试的智能体。
> 被测功能设计文档：[script_split_total_duration_control.md](./script_split_total_duration_control.md)
> 实现分支：`develop_duration_control`（基于 origin/develop）
> 本文档自包含：按 §4 → §5 → §6 → §7 顺序执行即可，§8 是验收标准，§9 是**必须先读**的存量失败基线（避免误报存量问题）。

---

## 1. 功能速览

剧本拆分（两个入口）此前只能控制"每个分镜组时长上限"（`max_group_duration`），分镜总数与总时长由 LLM 自由发挥，实际总时长经常超过剧本朗读时长的 3 倍。本次新增**总分镜时长控制**：

| 概念 | 定义 |
|------|------|
| 剧本基准时长 | 剧本非空白字符数 ÷ 语种混合朗读速率。中文 4.5 字/秒、拉丁 11 字符/秒，按 CJK 占比线性混合；下限 10 秒。270 个汉字 ≈ 60 秒 |
| 倍率 | 用户选择 0（不限制，默认）/ 1 / 2 / 3。目标总时长 = 基准时长 × 倍率 |
| 段级预算 | 目标总时长按各段源文本字符占比分解到逐段 LLM 调用，注入 prompt 硬约束块 |
| 归一化兜底 | 合并阶段把全部镜头总时长确定性压到 目标 × (1+15%) 以内：先等比压缩（单镜头下限 1.5s），仍超则把最短镜头并入同组相邻镜头 |

参数名：`total_duration_multiplier`（前端 `totalDurationMultiplier`）。存于拆分任务 `request_config` JSON 字段，**无数据库迁移**。0 或缺省 = 完全不干预（与旧行为一致）。

关键常量（`config/constant.py` `ScriptSplitConstants`）：`SCRIPT_DURATION_CJK_CHARS_PER_SECOND=4.5`、`SCRIPT_DURATION_LATIN_CHARS_PER_SECOND=11.0`、`SCRIPT_DURATION_MIN_SECONDS=10`、`TOTAL_DURATION_MULTIPLIER_MIN/MAX=0.5/10`、`TOTAL_DURATION_TOLERANCE=0.15`、`TOTAL_DURATION_SHOT_MIN_SECONDS=1.5`、`TOTAL_DURATION_SEGMENT_BUDGET_MIN_SECONDS=3`、`TOTAL_DURATION_MERGE_MAX_ITERATIONS=200`。

**关键公式（估算）**，前后端共三处拷贝，逻辑必须一致（测试时需对拍）：
- 后端：`llm/script_parser.py` → `estimate_script_duration_seconds()`
- 前端：`web/js/storyboard/render.js` → `estimateScriptDurationSeconds()`
- 前端：`web/js/script_node.js` → `estimateScriptDurationSeconds()`

## 2. 变更清单（被测代码）

| 文件 | 变更 |
|------|------|
| `config/constant.py` | 新增 8 个时长控制常量 |
| `llm/script_parser.py` | 新增 `estimate_script_duration_seconds` / `compute_segment_duration_budget_seconds` / `enforce_total_duration_limit` / `_merge_shot_into`；`parse_script_to_shots` 新增 `duration_budget` 参数与 prompt「本段总时长预算·硬性约束」块 |
| `services/script_split_engine.py` | `_safe_duration_multiplier`；`step_generate_segment` 下发段预算；`step_merge` 在 reorganize 之后、renumber 之前调用归一化并写 `metadata.total_duration_control` |
| `api/script_split.py` | `_normalize_request_config` 归一化倍率（float、夹紧 0.5~10、0 保留），保证幂等键稳定 |
| `server.py` | `/api/parse-script` 接收 `total_duration_multiplier` |
| `api/storyboard.py` | `/api/storyboard/{id}/generate-from-script` 接收同参数 |
| `web/js/storyboard/{state,render,events,api}.js` | 拆分弹窗新增「总分镜时长」下拉 + 估算 hint + 懒加载剧本正文 + `config_json` 持久化 + 请求透传 |
| `web/js/{script_node,script_split_task,workflow}.js` | 剧本节点新增下拉 + 实时 hint + 节点数据持久化（工作流序列化/重载恢复）+ 请求透传 |
| `script_writer_core/skills/script-parser/SKILL.md` | 输出要求第 2 条补预算遵从说明（system prompt） |
| `docs/script/script_split_total_duration_control.md`、`docs/script/README.md` | 文档 |
| `tests/llm/test_script_split_total_duration.py` | 新增 14 个单测 |
| `tests/js/test_storyboard_script_split_static.js` | 新增 §10 静态断言 |

## 3. 环境准备

```bash
# 1. 分支
git checkout develop_duration_control   # 本功能实现分支
# 2. Python 依赖按仓库 README 安装；单元测试不需要 config_dev.yml（conftest 注入 stub）
# 3. UI / API 集成测试需要可运行的服务端：python server.py（需 config_dev.yml、数据库）
#    API 调用方式可参考 .agents/skills/storyboard-agent-api/SKILL.md（agent token 换 auth_token）
```

## 4. L1 · 自动化测试（必跑，零环境依赖）

| # | 命令 | 期望 |
|---|------|------|
| 4.1 | `python -m pytest tests/llm/test_script_split_total_duration.py -q` | **14 passed**，0 failed |
| 4.2 | `node tests/js/test_storyboard_script_split_static.js` | 输出 `storyboard script split static tests passed` |
| 4.3 | `node tests/js/test_script_node_split_model_id.js` | 输出 `script node split model id wiring tests passed` |
| 4.4 | `python scripts/lint_blocking_calls.py` | 退出码 0（R4/R6/R7） |
| 4.5 | `python scripts/lint_tool_executor_signature.py` | 退出码 0（T1） |

覆盖内容：中/英文基准估算、空文本下限、空白忽略、段预算求和≈目标（±10%）、段预算下限与 0 倍率、归一化容差内不干预/等比压缩/单镜头下限/兜底合并保台词、单镜头组只压缩、零目标 no-op、engine 与 api 的倍率归一化（含 `"2"` 与 `2` 幂等不漂移）。

## 5. L2 · 组件级冒烟（不启服务，验证纯函数与前后端公式对拍）

```bash
python - <<'EOF'
import sys; sys.path.insert(0, '.')
from config import config_util
from config.config_util import get_config_path
stub = {"database": {"host": "h", "port": 1, "user": "t", "password": "t", "database": "t"},
        "llm": {}, "edition": {"mode": "community"}}
for f in (get_config_path(), "config_dev.yml", "config.yaml"):
    config_util._config_cache[f] = stub
from llm.script_parser import estimate_script_duration_seconds, enforce_total_duration_limit

# 断言1：270 个纯汉字 ≈ 60 秒（±0.5s）
cn = "他走进房间看了看四周" * 27
assert abs(estimate_script_duration_seconds(cn) - 60.0) < 0.5, estimate_script_duration_seconds(cn)

# 断言2：80s 拆分结果压到 40s 目标
data = {"shot_groups": [{"group_id": f"g{i}", "shots": [
    {"shot_id": f"s{i}{j}", "duration": 8.0, "description": "A", "dialogue": []}
    for j in range(2)]} for i in range(5)]}
rep = enforce_total_duration_limit(data, 40.0)
total = sum(s["duration"] for g in data["shot_groups"] for s in g["shots"])
assert rep["applied"] and total <= 40.0 * 1.15, (rep, total)
print("L2 smoke OK")
EOF
```

公式对拍（前端）：在浏览器控制台（storyboard 页或 video_workflow 页模块作用域）分别用同一段文本调用 `estimateScriptDurationSeconds`，与后端输出一致（前端空文本返回 0，非空时与后端一致）。

## 6. L3 · API 集成测试（需运行中的服务端 + auth_token + 已有 world）

推荐用 **video_workflow 来源**（`/api/parse-script`），前置条件最少：只需一个存在且带参考图场景的 `world_id`（拆分前置校验 `_validate_world_scene_precondition` 会拒绝无场景资产的 world）。

### 6.1 请求序列

```bash
TOKEN="<auth_token>"; BASE="http://127.0.0.1:<port>"
# 先算期望目标：把下方 SCRIPT 换成实际剧本，运行一次 §5 的估算函数得到 estimate
# ① 提交 2 倍任务
curl -s -X POST "$BASE/api/parse-script" -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" -d '{
    "script_content": "<测试剧本，建议 200~600 字>",
    "max_group_duration": 15,
    "total_duration_multiplier": 2,
    "world_id": <world_id>,
    "sequence_mode": "speed",
    "model": "deepseek-v4-flash"
  }'
# 期望：202 {"code":0,"data":{"task_id":N,"status_url":"/api/script-split/tasks/N"}}

# ② 幂等验证：把上面的 "total_duration_multiplier": 2 改成 "2"（字符串）重发
# 期望：202 且 task_id 与 ① 相同（message 为"已有进行中的拆分任务"或同任务返回）

# ③ 对照任务：total_duration_multiplier=0（或不传）
# 期望：新 task_id（倍率参与幂等键，不同倍率=不同任务）

# ④ 轮询直至 completed（LLM 拆分耗时数分钟，间隔 ≥3s）
curl -s "$BASE/api/script-split/tasks/<task_id>" -H "Authorization: Bearer $TOKEN"
# ⑤ 取结果
curl -s "$BASE/api/script-split/tasks/<task_id>/result" -H "Authorization: Bearer $TOKEN"
```

### 6.2 结果断言（对 2 倍任务）

1. `data.final_result.metadata.total_duration_control` 存在，且：
   - `multiplier == 2.0`；`estimated_script_seconds` ≈ 手工估算值（±0.2s）
   - `target_seconds == round(estimated_script_seconds * 2, 1)`
   - `total_after <= target_seconds * 1.15`（容差上限）
   - `applied`：LLM 未超时为 false（正常），超了为 true 且 `total_before > total_after`
2. 实测总时长复核：`sum(shot.duration for group in shot_groups for shot in group.shots)` == `total_after` == `final_result.total_duration`（±1，后者是 int 取整）
3. 每组分镜总时长仍 ≤ `max_group_duration + 0.05`（归一化不得破坏组上限）
4. 兜底合并发生时（`merged_shots > 0`）：无空组；被合并镜头的 `description`/`dialogue` 以「；」追加保留，台词不丢失
5. 对照任务（倍率 0）：`metadata.total_duration_control` **不存在**，总时长无任何压缩（允许超过任何倍数）

### 6.3 storyboard 来源（可选，前置条件多）

需要：storyboard 已设 `workflow_ratio`、无既有分镜、关联剧本非空、world 有带参考图场景。
`POST /api/storyboard/{id}/generate-from-script` 带 `total_duration_multiplier`，完成后查 storyboard 分镜列表求和 `duration`，断言 ≤ 估算×倍率×1.15。

## 7. L4 · UI 测试清单

### 7.1 storyboard 页（storyboard.html）

| # | 步骤 | 期望 |
|---|------|------|
| 1 | 打开无分镜的 storyboard（关联了剧本） | 拆分弹窗出现，「镜头组时长」下方有「总分镜时长」下拉，默认**不限制** |
| 2 | 观察下拉 hint | 通用说明文案；剧本正文加载完成后（选倍率时）变为「剧本估算约 X × N倍 → 目标总分镜时长约 Y」 |
| 3 | 选择 1倍 / 2倍 / 3倍 | hint 数字随倍率变化；「不限制」时回到通用说明 |
| 4 | 刷新页面后重开弹窗 | 选中倍率保持（`config_json` 持久化） |
| 5 | 未关联剧本 / 剧本接口失败 | hint 退化为通用说明，弹窗不报错不阻塞 |
| 6 | 提交生成分镜（Network 面板） | `generate-from-script` 请求体含 `total_duration_multiplier`，值与所选一致 |

### 7.2 video_workflow 页（video_workflow.html 剧本节点）

| # | 步骤 | 期望 |
|---|------|------|
| 1 | 新建剧本节点 | 参数区「镜头组时长」下方有「总分镜时长」下拉，默认不限制，hint 为通用说明 |
| 2 | 在 textarea 输入/粘贴剧本后选择 2倍 | hint 实时显示「剧本估算约 … × 2倍 → 目标 …」；清空文本回退通用说明 |
| 3 | 保存工作流 → 刷新页面重载 | 下拉恢复所选倍率，hint 与剧本内容匹配（`node.data.totalDurationMultiplier` 序列化/恢复） |
| 4 | 打开旧版本工作流（无该字段） | 默认不限制，不报错 |
| 5 | 点「拆分幕」提交（Network 面板） | `/api/parse-script` 请求体含 `total_duration_multiplier` |
| 6 | 编辑期快捷验证（可选） | 节点内选择器与故事板弹窗对同一段文本显示相同估算数字 |

## 8. 验收标准

**P0（任一失败即打回）**
- §4 全部通过；§5 断言通过
- 倍率 0 时行为与 develop 完全一致（无 prompt 注入、无归一化、无 metadata 写入）
- 倍率 N>0 时最终总时长 ≤ 估算×N×1.15，且组分镜上限规则不被破坏
- 幂等：同一倍率的 `"2"`/`2` 视为同一任务；不同倍率产生不同任务
- 工作流重载后倍率与 hint 正确恢复（AGENTS.md 第 4 条要求）

**P1（缺陷可协商）**
- 倍率 N>0 且 LLM 结果低于目标时不向上拉伸（设计如此，非缺陷）
- 兜底合并导致镜头数减少、镜头描述以「；」拼接（信息保留即可）
- hint 估算与后端估算有 ±1 秒内舍入差

## 9. 存量失败基线（develop 上就失败，**不要**计入本功能缺陷）

以下在改动前的干净树上同样失败，已逐一比对确认与本次无关：

```
tests/services/test_script_split_engine.py
  ::test_segment_extended_hard_gate_on_space_unit_registry_new_root
  ::test_disabled_qc_pauses_on_new_root_location_without_forced_accept
  ::test_exhausted_qc_checkpoint_cannot_force_accept_hard_location_error
  ::test_enabled_qc_passes_registry_characters_to_agent
  ::test_step_merge_reopens_completed_segment_when_location_graph_is_illegal
tests/llm/test_script_parser_spatial_layout_prompt.py  （3 个 repair_spatial 用例）
tests/storyboard/test_script_split_api.py::TestNormalizeRequestConfig::test_sequence_mode_default_speed
tests/js/test_storyboard_empty_split_dialog.js
```

前端 `tests/js/` 下另有若干存量失败文件（candidate_asset_urls、editor_navigation_static、generate_alert_summary、list_static、llm_model_selection、prop_reference_chip、timeline_card_static 等）。判定方法：`git stash` 后在干净树跑同一文件对比，失败集合一致即存量。若发现**基线之外**的新失败才需上报。

## 10. 边界与风险提示

- LLM prompt 层是**软约束**：模型可能超预算，属预期内——最终硬保障是合并阶段归一化，验收只看最终总时长
- 估算按"非空白字符数"，中文标点计入拉丁速率档（与前端一致），非缺陷
- 长剧本多段任务：各段预算之和 ≈ 目标（±10% 内），单段允许下限 3s
- 归一化在 `renumber_global` 之前执行，镜头编号重排在后，不应出现跳号/重号
- 并发/取消/断点续传路径未改动，无需回归（如时间充裕可抽查任务取消后元数据不残留）

## 11. 缺陷上报格式

```
标题: [total_duration] 一句话现象
复现: 分支/入口(7.x 编号)/参数(倍率、max_group_duration、sequence_mode、剧本字数)
期望 vs 实际: 目标 Xs±15% vs 实际 Ys；total_duration_control 报告 JSON 原文
证据: 测试输出/接口响应/curl 命令
```
