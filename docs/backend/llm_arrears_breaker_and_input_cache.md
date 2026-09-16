# LLM 欠费熔断 与 剧本拆分输入缓存优化

> 关联分支：`develop_f869`
> 关联代码：`llm/base_llm_client.py`、`llm/openai_base_client.py`、`llm/gemini_client.py`、
> `config/unified_config.py`、`llm/script_parser.py`、`tests/llm/test_arrears_breaker.py`

## 背景事故（2026-09-16）

用户 1970（15025122822）当天 09:49–11:00 通过分段剧本拆分（deepseek-v4-pro）发起 21 次调用，
消耗 91.8 万输入 / 54.7 万输出 token，算力从 87 点一路扣至 **-511 点**，期间所有调用照常放行。

根因：token 计费是**后付费**——`task/token_task.py` 的 `process_token_logs()` 直接
`新余额 = 当前余额 - 扣减`，无任何下限保护（这是记账事实，供应商成本已发生，本身不该改）；
而调用前的余额拦截只存在于图片/视频生成接口和 Agent 循环（`check_computing_power_sync`，
阈值 `COMPUTING_POWER_CHECK_THRESHOLD=1`），**LLM 调用统一入口没有任何拦截**，
长任务（分段拆分/Agent 工具循环）一旦启动就可以无限把余额扣穿。

库里另有 10 个历史负余额用户（最低 -597），说明该穿透长期存在。

## 修复一：LLM 欠费熔断

### 拦截位置

选择在 **LLM 客户端统一入口**（调用发起前）拦截，而不是扣费任务里：

- `OpenAIBaseClient.call_api` —— 覆盖 deepseek / claude / qwen / volcengine / zjt /
  agnes / mimo / aliyun 等全部 OpenAI 兼容付费供应商
- `GeminiClient.call_api` —— 覆盖 gemini 原生链路
- `ollama` / `vllm` 本地推理不计费，不拦截

扣费侧 `process_token_logs()` 保持后付费语义不变：在途调用产生的费用仍会如实记账
（可以扣成负数），只是**不会再有下一次调用**。

### 行为语义

新增 `BaseLLMClient._enforce_arrears_breaker(auth_token, vendor_id, model_id, agent_id)`：

- 仅当 `auth_token`、`vendor_id`、`model_id` 三者齐备时才检查（无 token / 不产生
  token_log 的调用不拦截）
- 余额取自内部接口 `user/check_computing_power`（与 Agent 循环同源）
- `余额 < LLM_ARREARS_BREAKER_THRESHOLD`（默认 1，即余额 <=0）时抛出
  `InsufficientPowerForLLMCallError`，调用方任务按普通失败终止并展示报错文案
- **fail-open**：余额服务不可用/异常时放行并记录 warning，与
  `check_computing_power_sync` 的兜底策略一致，避免余额服务故障阻塞所有任务

### 损失上界

熔断把欠费损失限制为「熔断前最后一次在途调用」的成本（分段拆分单次约 20~50 点），
不再随任务长度线性扩大。

### 配置常量（config/unified_config.py）

```python
LLM_ARREARS_BREAKER_ENABLED = True    # 欠费熔断总开关
LLM_ARREARS_BREAKER_THRESHOLD = 1     # 余额低于该值拒绝发起新调用
```

### 成本

每次付费 LLM 调用前增加 2 次内部 DB 读（token 校验 + 余额查询），相对秒级 LLM 调用可忽略。

## 修复二：剧本拆分输入缓存命中率优化

### 问题

生产实测（同上事故）：分段拆分 21 次调用，单次输入约 4.7 万 token，
`cache_read` 仅 5376（命中率 <12%）。DeepSeek 等供应商的上下文缓存按**前缀精确匹配**，
原版 user prompt 把**每段都不同的剧本内容放在最前**，导致缓存只能命中 system prompt，
后面每次调用都重复、完全不变的部分（核心规则约上万 token + 数据库资产列表 + JSON 格式示例）
全部按未命中价计费。

### 方案：user prompt 按「稳定 → 易变」重排

`llm/script_parser.py` `parse_script_to_shots()` 的 user prompt 顺序调整为：

1. （稳定）核心规则 1~9 + JSON 格式示例 + special/emotion 要求（任务级参数）
2. （稳定）数据库场景/道具/角色列表 + 角色形象变化说明 + 参考生视频模式说明
3. （易变）`qc_retry_block`、`segment_context_block`（分段上下文）、剧本内容、
   本段时长预算，最后仍是「下面请开始解析：」

所有文本内容**一字未改**，仅调整顺序；唯一措辞修正是时长预算块中的方位词
（「该预算与~~下方~~上方『镜头组时长限制』同时生效」）。

同一段剧本任务的第 2 个分段起，前缀（1+2，通常 1.5 万~3 万 token）可全部命中缓存；
QC 重试调用同样受益。规则先于内容、内容紧邻「开始解析」指令，符合长上下文 prompt 惯例。

### 预期收益

以事故当天为例：每次调用约 4.7 万输入，其中约 3 万为可稳定前缀。按 DeepSeek 缓存命中价
约为未命中价 1/10 计，分段任务输入侧供应商成本约可下降 50%~60%（任务越长段数越多收益越大）。
对用户的算力计费不变（`vendor_model` 阈值机制会自动把 cache_read 部分按缓存价折算，
用户侧同样受益）。

## 测试

- `tests/llm/test_arrears_breaker.py`：熔断触发/放行/无 token 跳过/缺计费要素跳过/
  服务异常 fail-open，共 6 例
- `tests/llm/` 全量 202 passed（`test_script_parser_spatial_layout_prompt` 中 3 个用例
  在 origin/develop 上即为存量失败，已用 git stash 验证与本次改动无关）
- `scripts/lint_blocking_calls.py` 对改动文件无 error 级违例

## 欠费后用户的恢复入口（前端）

拆分任务被熔断后进入 `paused`（段级调用失败重试 3 次耗尽 → `segment_max_retries`），
前端在 2026-09-16 补齐了显式入口（见 `docs/script/script_parser_incremental_split_design.md` §14.1）：

- **继续拆分**：paused 时「拆分幕」「拆分幕 + 宫格生图」按钮文案自动切换为
  「继续拆分…」。点击后同配置重提，后端幂等命中原任务并从检查点自动恢复，
  已完成分段不重跑、不重复计费。用户充值后点一次即可续跑。
- **放弃并重新拆分**：状态行追加的小按钮。取消旧任务并轮询至终态
  （active_key 唯一索引终态释放）后，重新触发完整拆分（全新任务、重新计费）。
- 页面刷新恢复路径（`workflow.js` createScriptNodeWithData）同享以上入口；
  故事板侧进度弹窗原已有「重试」按钮（走同一 create 幂等恢复路径）。
