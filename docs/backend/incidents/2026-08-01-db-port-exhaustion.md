# 2026-08-01 数据库连接端口耗尽事故记录

> 本报告所有数据均经日志直接核实（`logs/app.2026-08-01.log`，839 MB / 698 万行）。事故期间 80+ 用户在线。

## 概述

| 项目 | 内容 |
|------|------|
| 事故定性 | 客户端 TCP 临时端口耗尽（ephemeral port exhaustion）导致 DB 访问层全面雪崩 |
| 影响时段 | `2026-08-01 10:43:53` 首发 → `16:00:04` 自愈，高峰 `14:00–15:00` |
| 影响范围 | 全站 DB 依赖模块（15 个模块），含鉴权（`model.user_tokens`）；终端用户可见生成失败 |
| 根因 | `model/database.py` 无连接池 + 每次查询 connect/close 短连接，高并发下 TIME_WAIT 占满客户端 ~6.4 万临时端口 |
| 服务端状态 | MySQL `192.168.10.212:3306` **全程在线**（详见证据 1、3） |

**关键判定：不是 MySQL 宕机，也不是 MySQL 连接数超限，而是本机（应用服务器）出站端口被自身的短连接耗尽。**

## 现象

- 全天 ERROR **96 万次**，CRITICAL 330 条（其中 213 条为本事故的 DB 错误，其余为 LLM 剧本文本误命中）。
- 几乎所有 ERROR 都是同一个底层错误在不同业务层的连锁表现。
- 故障传导到终端用户：LLM Agent 把后端 DB 报错写进了对话回复（`图片生成过程中发生错误: ... [Errno 99] ...`，约 214 次），生成结果以 `success:false` 返回。
- 213 次真实系统 CRITICAL 全部来自 `task.sync_task_executor` 的 fallback 失败：
  ```
  2026-08-01 10:52:50 - task.sync_task_executor - CRITICAL - [SyncTaskExecutor] CRITICAL: fallback failure handling failed for task 20669: (2003, "Can't connect to MySQL server on '192.168.10.212' ([Errno 99] Cannot assign requested address)")
  ```

## 故障时间线

Errno 99 按小时分布（典型 TIME_WAIT 堆积 → 耗尽 → 自愈曲线）：

| 小时 | Errno 99 次数 | 备注 |
|------|--------------|------|
| 00:00–09:59 | 0 | 正常 |
| 10:00 | 17,431 | `10:43:53` 首次爆发 |
| 11:00 | 52,047 | 上升 |
| 12:00 | 49,651 | 高位 |
| 13:00 | 46,531 | 高位 |
| **14:00** | **413,120** | **峰值小时** |
| **15:00** | **375,485** | **峰值小时** |
| 16:00 | 212 | `16:00:04` 后基本恢复 |
| 17:00 之后 | 0 | 持续正常 |

峰值分钟（Top）：

| 分钟 | Errno 99 次数 | 折算 |
|------|--------------|------|
| 14:52 | 16,626 | ~277 次/秒 |
| 14:51 | 15,931 | ~265 次/秒 |
| 14:33 | 14,101 | |
| 14:47 | 12,667 | |

## 根因分析（五条证据链）

### 证据 1：错误类型是 Errno 99，不是 Errno 111 —— 客户端端口耗尽而非服务端宕机

| 错误 | 次数 | 含义 |
|------|------|------|
| `Errno 99 / Cannot assign requested address` | **984,782** | 客户端 `connect()` 时本地源端口已占满，无法发出 SYN |
| `Errno 111 / Connection refused` | **0** | 服务端拒绝（MySQL 宕机会报这个） |

- Errno 99 发生在 TCP 三次握手**之前**：内核要为本次出站连接选一个临时源端口，但全部被占（大量 TIME_WAIT），根本没发出 SYN 包。
- 若是 MySQL 宕机/重启，会报 Errno 111（SYN 发出后被 RST）。今天 **0 次** → MySQL 全程在线。
- 原始行（`app.2026-08-01.log:546062`）：
  ```
  2026-08-01 10:43:53 - model.database - ERROR - Database connection error: (2003, "Can't connect to MySQL server on '192.168.10.212' ([Errno 99] Cannot assign requested address)")
  ```
  pymysql 错误码 `2003` = "Can't connect to MySQL server"，`[Errno 99]` 明确指向客户端本地绑定失败。

### 证据 2：故障严格随负载高峰出现，闲时为零

| 时间窗口 | Errno 99 次数 |
|----------|--------------|
| 09:00–09:59（故障前） | 0 |
| 14:00–14:59（峰） | 413,120 |
| 16:00–16:59（恢复后） | 212 |
| 20:00–20:59（晚上） | 0 |

"高峰爆、闲时零、数小时后自行恢复"的形态，正是 TIME_WAIT 堆积 → 端口耗尽 → TIME_WAIT 过期（默认 60s）后释放 → 自愈的典型曲线。若为配置错误则会"一直连不上"，与观测不符。

### 证据 3：排除所有其他竞争假设

主动 grep 了所有其他可能的 DB / 系统级问题，**全部为 0**：

| 竞争假设 | 关键词 | 次数 | 结论 |
|----------|--------|------|------|
| MySQL 连接数超限 | `Too many connections`（1040） | 0 | 排除 |
| MySQL 配置限制 | `max_connections` | 0 | 排除 |
| 认证失败 | `Access denied` | 0 | 排除 |
| 连接被断开 | `server has gone away`（2006）/ `Lost connection`（2013） | 0 | 排除 |
| 内存 OOM | `Out of memory` / `Killed process` | 0 | 排除：非 OOM killer |
| 磁盘满 | `No space left on device` | 0 | 排除 |

> 注：grep `2006`/`2013` 时有少量命中，但均为行号、task_id 数字误匹配（非真实错误码），人工核对原始行后排除。

没有任何其他系统级故障能解释该现象，唯一与端口耗尽自洽。

### 证据 4：雪崩传导到几乎所有业务模块

发出 `Can't connect to MySQL` 的模块 Top 15（证明不是单点 bug，而是底层 DB 访问层失效）：

| 次数 | 模块 |
|------|------|
| 354,435 | `model.database` |
| 165,349 | `api.script_writer` |
| 105,643 | `model.agent_task_messages` |
| 104,990 | `model.agent_tasks` |
| 45,957 | `api.storyboard` |
| 39,750 | `model.storyboard_scene` |
| 36,073 | `model.implementation_power` |
| 14,849 | `script_writer_core.agents.task_manager` |
| 14,773 | `model.user_tokens`（**鉴权受影响**） |
| 13,262 | `model.agent_verifications` |
| 5,404 | `model.system_config` |
| 4,771 | `config.config_util` |
| 4,291 | `perseids_server.client` |
| 4,239 | `server` |

共 15 个模块、总量约 **969,849** 次。鉴权模块（`user_tokens`）失效意味着连"判断当前用户"都可能失败，影响面进一步放大。

### 证据 5：代码机制 —— 无连接池 + 短连接

这是把"高并发"翻译成"端口耗尽"的机制，`model/database.py:31-59`：

```python
@contextmanager
def get_db_connection():
    connection = None
    try:
        connection = pymysql.connect(...)   # 每次【新建】一条 TCP 连接
        yield connection
    except Exception as e:
        logger.error(f"Database connection error: {e}")
        raise
    finally:
        if connection:
            connection.close()              # 用完【立即关闭】→ 进入 TIME_WAIT
```

- `execute_query` / `execute_update` / `execute_insert`（第 62/86/104 行）每一个都走 `with get_db_connection()`，即**每次 DB 操作 = 一次 TCP 建连 + 一次关闭**。
- 全仓库**无连接池**：`DBUtils / PooledDB / aiomysql / asyncmy / SQLAlchemy / QueuePool` 在 requirements、pyproject 和代码中**均无匹配**。
- 共有 **114 个 .py 文件**调用这些函数。
- 叠加高峰期高频轮询（SSE `poll messages` ~8 万次、`[SSE-STREAM]` ~17 万行），短连接创建速率远超 60s TIME_WAIT 释放速率 → 端口必然耗尽。

> 日志规范瑕疵（修正记录）：`model.database` 的 `Database connection error:` 文案被复用——它有时打印业务异常（如"资产不存在、类型不匹配或不属于该分镜"），有时才是真正的 Errno 99。**判断本次事故必须以 `[Errno 99]` 为准，不能只看 `Database connection error` 文案。** 该模块的异常日志规范需单独治理。

## 次生影响

| 项 | 次数 | 说明 |
|----|------|------|
| `pipeline_processor` 流程告警 | 23,200 | `Step N is PROCESSING but has no async_task_id, step_type=storyboard_first_frame_grid_split`，疑为故障期流程中断的次生影响，需单独排查 |
| `grid_image_task` 真实任务超时 | 187 | `任务超时: ..., 尝试次数: 61/60`（非 DB 噪声，真实业务超时） |
| 上游 `ReadTimeoutError` | 34 | `yw.perseids.cn ... (read timeout=600)`，上游 LLM/视频供应商慢 |
| SSE 高频轮询放大风暴 | — | `[SSE-STREAM]` 169,934 行、`poll messages` 81,659 次；DB 故障期间每次轮询都制造新连接，加剧端口耗尽 |

## 可观测性缺陷（本次排查的障碍）

本次定位困难，根子在日志体系本身。这些缺陷独立于事故，建议优先补齐：

| 问题 | 现状 | 影响 |
|------|------|------|
| 单文件巨大 | `app` 日志 839 MB；`logs/` 共 9 GB；gunicorn `error.log` 706 MB / `access.log` 340 MB 且**永不轮转** | grep/读取极慢，磁盘隐患 |
| 时间精度仅到秒 | app/llm 日志 `%(asctime)s` 无毫秒；仅 `api_requests`/`qiniu_upload` 带毫秒 | 同秒内事件无法定序 |
| 无请求追踪 | 无 request id / trace id / user id 注入日志 | 跨模块串联一次请求极困难 |
| 无耗时埋点 | 代码中 0 处 `elapsed/duration/time_cost/latency`；无慢请求中间件 | 无法回答"哪个接口慢" |
| 噪声刷屏 | `权限检查（空实现）` 一行占大量日志 | 掩盖真正信号 |

- 日志配置核心：`utils/logger_config.py`（自定义 `DailyFileHandler`，按天切，**无大小轮转**）。
- gunicorn 参数：`multi_thread_start_prod.sh:21-28`（access/error 直接指向工作目录根，无 logrotate）。

## 修复与改进建议

### 短期缓解（运维侧，需运维评估）
1. 调高客户端临时端口范围：`net.ipv4.ip_local_port_range`（默认 `32768 60999`，可扩到 `1024 65535`，需评估安全性）。
2. 降低 TIME_WAIT 保持时间：`net.ipv4.tcp_fin_timeout`（默认 60s 可下调）。
3. 开启 `net.ipv4.tcp_tw_reuse=1`（允许复用 TIME_WAIT 端口，对出站短连接场景有效）。

### 中期改造（根治，最高优先级）
4. ✅ **已实施（2026-08-01）**：引入 `DBUtils.PooledDB` 同步连接池包裹 `pymysql.connect`，复用连接。
   - 方案：选 PooledDB（同步池）而非 aiomysql（异步池），零破坏性改造，114 个调用点签名不变。
   - 详细设计见 [database_connection_pool.md](../database_connection_pool.md)。
   - 同时补 `tasks.status`、`agent_tasks.created_at` 两个缺失索引（迁移 `20260801_add_slow_query_indexes`），消除慢 SQL。
   - fork 安全：懒加载 + pid 校验，多进程下各自独立建池。
5. **轮询治理**：评估 SSE（`api/script_writer`）与后台 worker tick（`task/visual_task` 的 `No pending` 空转 15,332 次）的轮询频率，引入动态退避，故障期自动降级，避免连接风暴放大。

### 长期（可观测性，后续所有排查的前提）
6. 加 **request id 中间件** + **毫秒级时间戳**，注入全链路日志。
7. 加**请求耗时埋点** / 慢请求日志中间件。
8. 日志**大小轮转**（含 gunicorn access/error），避免单文件无限增长。
9. 治理噪声日志（如 `权限检查（空实现）` 改为 DEBUG 或下线）。

## 待办（后续深入调查）

- [x] DB 连接池改造（`model/database.py`，采用 DBUtils.PooledDB）+ 补慢 SQL 索引。详见 [database_connection_pool.md](../database_connection_pool.md)。
- [ ] 轮询治理：SSE / 后台 tick 频率与故障期退避策略。
- [ ] 可观测性补齐：request id 中间件 + 毫秒时间戳 + 耗时埋点 + 日志轮转。
- [ ] 排查 `pipeline_processor` 23,200 次告警根因（`Step is PROCESSING but has no async_task_id`）。
- [ ] 排查 `grid_image_task` 187 次真实任务超时是否与本次故障相关。
- [ ] 治理 `model.database` 异常日志规范（统一文案，区分连接错误与业务异常）。
- [ ] cleanup DELETE 改为分批 `LIMIT 1000` 循环，进一步消除单条 DELETE 持锁过久。
- [ ] 补完索引 + 分批后，评估是否启用 `DB_POOL_READ_TIMEOUT` 兜底挂死 SQL。
