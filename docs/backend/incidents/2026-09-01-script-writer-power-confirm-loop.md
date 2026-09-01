# 2026-09-01 剧本创作页算力确认门超时循环扣费事故

## 现象

用户在剧本创作页（`script_writer.html`，world 16，user 2）回答完最后一个问题（09:30:40「帮我补全所有缺失资产」）后不再操作，系统仍持续扣减算力约 40 分钟（09:30–10:09），余额 938 → 643（共 297 算力 / 117 笔扣费，同时段另一世界会话叠加扣费）。期间前端每 5 分钟弹出一次「算力确认」验证卡片，并伴随「验证已超时」toast。

数据库佐证（`agent_verifications`）：

```text
09:35:58 ask_user（资产检查提问）            → cancelled（300s 超时）
09:41:38 ask_user（是否覆盖已有图）          → cancelled
09:47:38 computing_power_confirm「算力确认」 → cancelled
09:52:40 computing_power_confirm            → cancelled
09:57:51 computing_power_confirm            → cancelled
10:02:53 computing_power_confirm            → cancelled
```

「算力确认」卡片内容显示 `本轮已用未确认：34 / 自动确认上限：35`——弹窗间隔精确等于 `wait_for_verification` 的 300 秒超时。

## 根因

8/18 上线的「高算力生成前按用户阈值确认」（`0cf43b52`）把确认门实现在共用的 `ExpertAgent._execute_tool` 中，导致剧本创作链路也被拦截，与无人应答场景组合成死循环：

1. 本轮「已用未确认算力」累计到 34，任何新生图（2 算力）满足 `34+2 > 软阈值 35`，必须弹「算力确认」。
2. 用户离开页面，`wait_for_verification` 300 秒超时后**任务恢复 running 继续执行**，超时以 `{"error": "验证超时"}` 返回给 LLM，无「勿重试」引导。
3. 超时/拒绝路径**不清零** `unconfirmed_cost`，阈值判定永远不通过。
4. LLM 收到超时错误后重试生成 → 再次触发确认门 → 再次弹窗 → 再次超时……每轮循环伴随 1–3 次 LLM 调用（单次输入 40–52 万 token，扣 1–13 算力）。
5. 保护机制层层失效：
   - `ask_user_mixin.py` 中超时**不计入** `ASK_USER_MAX_CONSECUTIVE_FAILS` 连续失败计数（该保护只覆盖非超时失败）；
   - `ExpertAgent` 的进展检测/迭代上限只对子 agent 优雅收尾，PM 通过 `call_agent` 重新拉起子 agent 后所有计数归零；
   - 前端收到 `verification_timeout` 即置 `isProcessing=false` 并 drain 排队消息，可能与仍在后台运行的旧任务并发。

## 修复

按需求将剧本创作链路的算力确认门整体摘除（marketing 与 storyboard 链路保留）：

- `ExpertAgent.__init__` 新增 `power_confirm_enabled: bool = True`；`_gate_computing_power` 入口短路（关闭时直接放行，不估算、不弹验证、不累计未确认消耗）；系统提示第 6 条（阈值说明）仅在开启时注入。
- `PMAgent.__init__` 透传该开关给子 ExpertAgent；`MarketingPMAgent` 未传，保持默认开启。
- `chat_session.py` 分流：`session_type=2`（营销）不变；剧本智能体分支显式 `power_confirm_enabled=False`。
- `script_writer_core/skills/storyboard-image|video` 的 SKILL.md 门文案未改动：这两个技能由分镜链路（门保留）加载，且「不要自己询问算力」的引导在门关闭的剧本链路恰好产生期望行为（直接提交、无确认打断）。
- 测试：`tests/script_writer_core/test_expert_agent.py` 新增 `TestPowerConfirmSwitch`（关闭放行 / 关闭不注入提示 / 默认开启注入提示）。

## 遗留风险（后续建议）

门摘除后，剧本链路的算力保护仅剩主循环每轮迭代的余额检查（`check_computing_power_sync`）。以下通用问题对 marketing 链路仍然存在，建议后续修复：

- `ask_user` 超时不计入连续失败熔断：用户离开时 marketing 链路仍可能进入同类超时-重试循环（建议超时连续 2 次即终止任务链）。
- 超时返回给 LLM 的错误文案缺少「勿立即重试」引导。
- 前端 `verification_timeout` 分支无条件 `isProcessing=false` + `schedulePendingDrain()`，与后端任务仍在运行的事实不一致。
