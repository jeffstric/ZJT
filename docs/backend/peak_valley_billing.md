# 大模型峰谷计费（Peak / Off-peak Billing）

## 背景

DeepSeek 官方自 **2026-08-17** 起采用峰谷定价：高峰时段价格为空闲时段的 2 倍。
- 高峰时段（北京时间，左闭右开）：`9:00-12:00`、`14:00-18:00`
- 其余为空闲时段

本方案在现有「供应商 × 模型 × token 区间」分段计费基础上，新增「计费时段」维度，完全向后兼容。

## 字段语义对照

现有 `vendor_model` 三档阈值与 DeepSeek 价格表一一对应，**无需新增价格列**：

| DeepSeek 价格项 | `vendor_model` 字段 |
|------|------|
| 输入（缓存未命中） | `input_token_threshold` |
| 输入（缓存命中）   | `cache_read_threshold` |
| 输出              | `out_token_threshold` |

## 数据结构

`vendor_model` 新增字段：

```sql
time_period ENUM('normal','peak','off_peak') NOT NULL DEFAULT 'normal'
```

- `normal`：不分峰谷（默认，现有模型零影响）
- `peak` / `off_peak`：高峰 / 空闲

唯一性维度（代码层 `exists_tier` 校验，因 MySQL 唯一索引对 NULL 失效）：
`(vendor_id, model_id, raw_token_threshold, time_period)`

## 核心组件

### 1. 时段常量 — `config/constant.py`

```python
class PeakValleyBillingConstants:
    PERIOD_NORMAL = 'normal'
    PERIOD_PEAK = 'peak'
    PERIOD_OFF_PEAK = 'off_peak'
    ALL_PERIODS = (PERIOD_NORMAL, PERIOD_PEAK, PERIOD_OFF_PEAK)
    PEAK_TIME_RANGES = ((9, 12), (14, 18))   # 北京时间 [start, end)
```

### 2. 时段判断 — `utils/billing_period.py`

```python
get_billing_period(dt) -> 'peak' | 'off_peak'
```

- 固定 UTC+8（`timezone(timedelta(hours=8))`），不依赖系统时区库 / tzdata，跨 Win/Linux/macOS 一致
- naive datetime 视为北京时间；aware datetime 自动转换
- None / 无法解析 → 当前北京时间兜底，**绝不抛异常**，保证扣费链路不中断

### 3. 选档算法 — `model/vendor_model.py`

`get_by_vendor_model_for_billing(vendor_id, model_id, raw_input_token, time_period)`：

```sql
WHERE vendor_id=? AND model_id=?
  AND (raw_token_threshold >= ? OR raw_token_threshold IS NULL)
ORDER BY
  CASE time_period WHEN ? THEN 0 WHEN 'normal' THEN 1 ELSE 2 END,  -- 三级兜底
  raw_token_threshold IS NULL,
  raw_token_threshold ASC
LIMIT 1
```

**三级兜底**（确保不漏扣）：
1. 与传入时段一致的档（精确匹配）
2. `normal` 档（向后兼容）
3. 其余时段档（最终兜底）

### 4. 扣费链路 — `task/token_task.py`

```
LLM 调用 → token_log(status=0, created_at=调用时间)
   ↓ 每 6s 后台任务
process_token_logs()
   → calculate_computing_power_from_tokens(..., created_at=token_log.created_at)
       period = get_billing_period(created_at)          # 用调用时间，非任务时间
       vm = get_by_vendor_model_for_billing(..., period) # 时段选档
       cost = (input/th + out/th + cache/th) × (1+抽成)
   → 扣减算力 + 写 computing_power_log
```

**关键**：时段判断用 `token_log.created_at`（调用发生时间），不能用后台任务执行时间，否则跨时段边界算错。

`computing_power_log.note` 记录 `时段(调用:peak, 命中档:peak)` 便于审计。

### 5. 估算链路

`llm/llm_client_factory.py`、`script_writer_core/mcp_tool.py` 列出模型当前价时，传 `get_billing_period(None)`（当前时段），使展示反映当前峰谷价。

## 后端接口

`api/admin.py` 计费档位接口全部支持 `time_period`：

| 接口 | 说明 |
|------|------|
| `POST /api/admin/vendor-models` | 创建档位，带 `time_period`（默认 normal） |
| `PUT /api/admin/vendor-models/{id}` | 更新档位（可改时段） |
| `POST /api/admin/models/{id}/billing/reset-defaults` | 还原默认（按 `default_vendor_model_billing` 重建，含时段） |

## 默认档位 — `config/default_vendor_model_billing.py`

官方 `deepseek` 的 `flash`/`pro` 已登记 `peak` + `off_peak` 两档：

| 模型 | 时段 | 输入(未命中) | 输出 | 缓存(命中) | 元/百万 |
|------|------|------|------|------|------|
| deepseek-v4-flash | peak | 3.0 | 9.0 | 0.10 |
| deepseek-v4-flash | off_peak | 1.5 | 4.5 | 0.05 |
| deepseek-v4-pro | peak | 9.0 | 27.0 | 0.30 |
| deepseek-v4-pro | off_peak | 4.5 | 13.5 | 0.15 |

中转商（zjt_api / 火山）维持 `normal`，是否峰谷按实际计费规则在界面单独配置。

## 迁移 — `alembic/versions/20260813_vendor_model_time_period.py`

1. `ALTER vendor_model ADD time_period ... DEFAULT 'normal'`（幂等，检查列存在）
2. 为官方 deepseek 初始化峰谷两档（`INSERT ... SELECT ... WHERE NOT EXISTS`，幂等）

`downgrade` 删除迁移插入的峰谷档 + 移除字段。

## 前端 — `web/admin.html` / `web/js/admin.js`

- 计费档位弹窗新增「计费时段」下拉（通用/高峰/空闲）
- 档位列表在区间旁显示高峰/空闲标签（仅非 normal 档）
- i18n：`models_billing_period_*`（zh-CN / en）

## 上线

1. 合入迁移（加字段，对线上零影响）→ 执行 `alembic upgrade head`
2. 8/17 后新调用自动按峰谷扣费（官方 deepseek 已由迁移初始化）
3. 其他模型如需峰谷，在 admin.html 计费档位弹窗选择「高峰/空闲」配置两档

## 测试

`tests/utils/test_billing_period.py`：14 个用例覆盖高峰/空闲窗口、边界值、时区转换、字符串解析、异常兜底。
