# 新场景层级被「父级链无法到达已有数据库场景」误杀 — 调查与修复方案

> **状态：已实施（2026-08-18）**
>
> 2026-08-04 调查完成；2026-08-18 客户现场再次复现
> （「第1集_保姆上岗第一天撞见壁咚现场」，文案「场景 loc_003 的父级链无法到达已有数据库场景」，
> 进度 84%、逐段拆分已停止）。按 §4 落地：父链允许终止于待落库新顶层，
> bootstrap 改为按 `parent_id` 拓扑排序。

## 1. 问题现象

剧本拆分任务进入 `paused`，`last_error_code = location_parent_invalid`，
`last_error_message` 形如「场景 lod002 的父级链无法到达已有数据库场景」。
resume 后同样的错误反复出现（死循环），拆分无法完成。

## 2. 根因

提交 `6684a5dd`（2026-07-18）为解"新顶层场景死锁"放开了新顶层门禁：

- `services/location_structure_guard.py:validate_segment_new_roots` 改为直接返回 `[]`（新顶层放行）；
- `services/storyboard_location_bootstrap_service.py` 允许新顶层（`parent_id=None`）落库。

**但父链回溯逻辑没有同步改**，形成自相矛盾：

- 新场景 `parent_id=null`（直接做顶层）→ 放行；
- 新场景挂在**新**顶层下（二级新层级，如 `lod002 教室` 的 parent 指向 `lod001 学校`）→
  父链回溯发现链端既无 DB 匹配又无 parent → 报 `location_parent_invalid`
  （`reason=unreachable_root`，硬门禁）。

报错产出点（全仓仅两处，同文案）：

- `services/location_structure_guard.py:360`（`validate_full_location_structure`，
  L0 规划编译 `script_split_engine.py:172`、L2 合并 `:1378`、L3 发布 `:1519` 均调用）；
- `services/storyboard_location_bootstrap_service.py:245`
  （`_validate_structure_before_write`，发布 bootstrap 前）。

放大因素：

- 提示词 `script_writer_core/skills/script-parser/SKILL.md` 第 5 条明确教 LLM 用
  `parent_id`/`level` 建嵌套层级。剧本出现 DB 没有的新地点时，LLM 必然产出
  「新根 + 新子场景」结构 → 100% 触发，与 LLM 发挥无关。
- 合并门禁失败后 `ScriptSplitSegmentModel.reopen_completed_for_hard_errors`
  （`model/script_split_segment.py:260`）把相关分段打回 failed，resume 后 LLM 用同样的
  剧本+提示词重跑，大概率产出同样结构 → 再次 paused，构成死循环。
- 后缀模糊解绑（如"阳台"撞上"酒店A阳台"且父级不同 → 拒绝绑定按新场景处理）
  会进一步增加"新场景"，加剧触发面。

## 3. enterprise 代码不同步怀疑的核查结论

**该报错与 enterprise 版本无关**：

- `enterprise/services/script_split_quality/contract.py:7` 为
  `from services.location_structure_guard import bind_and_validate_planned_locations`
  ——enterprise **没有**自己的场景门禁副本，L0 规划门禁委托主仓代码执行。
- `unreachable_root` 文案全仓仅主仓上述两处产出，enterprise 新旧版本不可能单独产生。

但部署核查仍有价值：若客户环境主仓版本旧于 `6684a5dd`（2026-07-18），同类剧本会先以
`new_root_location_forbidden` 暂停（文案不同）。可据客户实际报错文案反推其部署版本。
当前工作区主仓代码（≥ `c0381332`）中本问题客观存在，**仅重新部署现有代码不会消除**。

## 4. 修复方案（已实施）

原则：父链链端是「待落库的新顶层」即合法（政策已允许新顶层落库）；
`cycle` / `missing_parent` 是真正的结构错误，保留硬门禁。

### 4.1 `services/location_structure_guard.py`

`validate_full_location_structure` 父链回溯循环（约 315-366 行）：

```python
next_parent = str(current.get("parent_id") or "")
if not next_parent:
    # 改前：append unreachable_root 硬门禁错误
    # 改后：链端是新顶层场景（政策允许落库），合法终止
    break
```

同步更新三处 docstring 去掉 unreachable 表述：模块头（「可达性与环」）、
`validate_segment_new_roots`、`validate_full_location_structure`。

### 4.2 `services/storyboard_location_bootstrap_service.py`

- `_validate_structure_before_write`（约 241-246 行）：走到无 parent 的新场景时
  `break`（不再 raise）；保留 cycle / missing 两个 raise。
- `_topological_order` 改为真拓扑排序（**必须同做**）：现实现只按 LLM 给的 `level`
  排序，level 缺失/错误且子场景排在父前时会先建子 → `parent_db_id=None` →
  raise「父场景未能映射到数据库」，等于换了个硬错误。改为按 `parent_id` 链接的 DFS
  拓扑排序（三态 visited 环防护 + 原列表顺序 tie-break + orphan 保留 warning 按根处理
  + 无 id 项按原序输出），不再使用 `level`。

### 4.3 测试

- `tests/services/test_location_structure_guard.py` 新增：
  - 两级新层级（新根+新子，均无 DB 匹配）→ `validate_full_location_structure` 返回 `[]`；
  - 三级新层级 → 返回 `[]`；
  - L0 `bind_and_validate_planned_locations` 全未匹配新层级（带 `parent_location_key`）
    → errors 为空且 bound 保留 parent 链接。
  - 现有 missing_parent / cycle 断言（189-210 行）不动。
- `tests/services/test_storyboard_location_bootstrap_service.py` 新增：
  - 新根+新子 bootstrap 成功，`create` 两次，子的 `parent_id` == 根的 DB id；
  - 子场景排在父前且全部缺失 `level` → 仍父先子后落库（覆盖 284 行现有用例盲区）。
- 回归：`tests/llm/test_script_parser_location_sanitizer.py`。

### 4.4 文档回写

- 本文件状态改为「已实施」；
- `docs/script/script_split_early_new_root_location_gate.md` 第 40 行
  「父链最终可达已有 DB 场景」改为「父链允许终止于待落库的新顶层」；
- `docs/script/script_parser_incremental_split_design.md` 校验规则段补
  `unreachable_root` 取消的说明。

### 4.5 明确不做

- 不动 `RESUME_BLOCKED_ERROR_CODES`：cycle/missing 仍需拦截。**注意存量因
  unreachable_root 暂停的任务 error code 同为 `location_parent_invalid`（code 不区分
  reason），修复上线后需 force resume 一次才能通过 resume 拦截**。
- 不动 `_new_root_error` 死代码与 merge 处 `new_root_location_forbidden` 死日志分支。
- 不动 planner / skill 提示词（「优先挂已有顶层」软引导仍然成立）。

## 5. 部署验证步骤

1. 部署本修复后，对存量因 `location_parent_invalid` / unreachable_root 暂停的任务
   **force resume 一次**（resume 拦截不区分 reason）。
2. 观察 merge / publish：新根 + 新子层级应通过，bootstrap 按父先子后落库。
3. 若仍报 `new_root_location_forbidden`，说明环境主仓版本旧于 `6684a5dd`，需先升级。
