# 数据库连接池设计文档

> 背景：[2026-08-01 数据库连接端口耗尽事故](../incidents/2026-08-01-db-port-exhaustion.md)
> 改造目标：根治客户端 TCP 临时端口耗尽（Errno 99），从机制上消除高并发下的 DB 连接风暴。

## 1. 方案选型

| 方案 | 评估 | 是否采用 |
|------|------|---------|
| **DBUtils.PooledDB（同步池）** | 改动最小，复用现有 pymysql 与全部调用点；立即解决端口耗尽 | ✅ **本次采用** |
| aiomysql / asyncmy（异步池） | 契合 FastAPI 异步特性，彻底消除事件循环阻塞隐患 | ❌ 后续迭代（需改 114 文件 async/await，工作量大、回归风险高） |
| 系统参数调优（tcp_tw_reuse 等） | 仅缓解，不根治；治标 | ❌ 作为短期运维手段，非本次代码改动 |

**选 DBUtils 的核心理由**：零破坏性。所有调用点（`execute_query/update/insert`、`transaction()`、`get_db_connection()`）的签名与语义完全不变，仅底层 `pymysql.connect` 被替换为池借用。现有 `asyncio.to_thread(...)` 包装同步 model 方法的调用方式也无需改动，池化后自动受益。

## 2. 核心实现（model/database.py）

### 懒加载池工厂 + pid 校验（fork 安全的机制保证）

```python
_pool = None          # 模块级池单例，惰性创建
_pool_pid = None      # 记录建池时的 pid
_pool_lock = threading.Lock()

def _get_pool():
    global _pool, _pool_pid
    if _pool is not None and _pool_pid == os.getpid():
        return _pool
    with _pool_lock:                      # double-checked locking
        if _pool is None or _pool_pid != os.getpid():
            pool_cfg = DB_CONFIG.get('pool') or {}
            _pool = PooledDB(creator=pymysql, ...)
            _pool_pid = os.getpid()
    return _pool
```

### get_db_connection() 改为从池借连接

```python
@contextmanager
def get_db_connection():
    connection = None
    try:
        connection = _get_pool().connection()   # 借（复用空闲或新建）
        yield connection
    finally:
        if connection:
            connection.close()   # 语义变化：归还池而非真关闭
```

其余 `execute_query/update/insert`、`transaction()`、`*_in_transaction` 全部不动，走 `get_db_connection()` 自动受益。

## 3. fork 安全（多进程模型）

### 项目进程拓扑（run_prod.py）

```
run_prod.py（父进程 manager）
├── run_scheduler.py              独立 Python 进程，APScheduler，独立建池
├── run_script_split_worker × N   独立进程（N=script_split.worker_total），独立建池
└── gunicorn master
    └── UvicornWorker × 4         fork 出的子进程，各自 fork 后独立建池
```

稳态约 5 个查库进程（scheduler + 4 gunicorn worker），worker_total>0 时再加 N 个 script_split worker。

### 为什么 fork 安全（机制保证，非靠注释论证）

`_get_pool()` 每次取池时比对 `os.getpid()`：

| 场景 | 行为 |
|------|------|
| 正常（gunicorn 无 `--preload`） | 每个 worker fork 后首次调用才建池，pid 各异、天然隔离 |
| 防御（误加 `--preload` + 模块级触发 DB 调用） | master 建了池，fork 出的子进程 pid 与建池 pid 不同 → 检测漂移 → 丢弃旧池重建 → 绝不跨进程共享 MySQL 的 TCP socket（共享会导致协议错乱） |

**每个进程独立建池、互不共享连接**，这是 DBUtils 在多进程下安全的根本机制。

## 4. 配置项

### YAML（config_prod.base.yaml / config_dev.base.yml 兜底）

```yaml
database:
  pool:
    mincached: 2            # 启动时预热连接数
    maxcached: 20           # 空闲池上限（每进程）。复用优先，超出归还时真关闭
    maxconnections: 0       # 0=无硬上限。如需彻底封顶防端口耗尽，可设具体值（如 30）
```

与用户文件 `config_prod.yml`（含 host/password）的 `database:` 段深度合并，pool 子段由 base 兜底。

### 超时常量（config/constant.py，AGENTS.md 第 9 条）

```python
DB_POOL_CONNECT_TIMEOUT = 10   # 新建底层 MySQL 连接的 connect_timeout（秒）
```

**故意不设 read_timeout**：保持现状的无限等待，彻底零破坏。详见第 6 节。

## 5. 容量规划

### MySQL 侧总连接预算

```
总连接数 ≈ (1 scheduler + 4 gunicorn worker + N script_split worker) × maxcached
        = 5 × 20 = 100（默认 worker_total=0）
```

需确认 MySQL `max_connections ≥ 100 + 其他客户端余量`。8·1 事故证明服务端余量充足（高峰每秒数百次建连未触发 `Too many connections`）。

**注意空闲常驻与瞬时连接的区别**：改造前是瞬时短连接（峰值数百条但快速释放），改造后是空闲常驻（≤100 条永不关闭）。性质不同，需确认 MySQL 侧能承受这部分常驻。

### 池满策略（当前：无硬上限）

| 配置 | 行为 |
|------|------|
| `maxconnections=0`（当前） | 无硬上限。空闲池内复用优先；瞬时并发超 maxcached 时临时新建，归还时多出的真关闭。绝不池满抛错/死锁，换取简单性 |
| `maxconnections=30`（可选） | 触顶后 `blocking=True` 阻塞等待复用。可彻底封顶端口占用，但调用线程会等待 |

配置位已留好，默认 0；未来如需彻底封顶，改 YAML 为具体值即可，无需改代码。

### 无硬上限的边界（诚实标注）

极端瞬时并发 > maxcached 时仍会临时新建超过 20 条连接，产生少量 TIME_WAIT。但相比改造前（每查询 connect/close）已是数量级改善——稳态复用使连接创建速率从"每查询一次"降为"≈0"。8·1 那种高峰场景（~277 错误/秒）不再复现。

## 6. read_timeout 不设的理由（彻底零破坏）

### 现状
改造前 pymysql 未设 `read_timeout`（默认 None = 无限等待）。若新增 read_timeout，任何执行超过该值的 SQL 会抛 `OperationalError(2013)` 并回滚，是**真实的行为回归**。

### 排查结论（logs/app.2026-08-01.log）
当日 SQL 超时类错误 `(2013)/(2006)/(1205)/(1213)` 真实出现次数均为 **0**，说明现状下连最慢的 SQL 也没触发过超时。

### 但确有两条"定时炸弹"SQL
| SQL | 风险 | 已处理 |
|-----|------|--------|
| `model/tasks.py:430` `UPDATE tasks SET status=? WHERE status=?` | `tasks.status` 无独立索引，启动时全表扫描 UPDATE | ✅ 本次补 `idx_status` |
| `model/agent_tasks.py:365` `DELETE FROM agent_tasks WHERE status IN(...) AND created_at<...` | `agent_tasks.created_at` 无独立索引，每 6h 全表扫描 DELETE | ✅ 本次补 `idx_created_at` |

### 决策
本次采用**彻底零破坏**：不设 read_timeout，保持现状无限等待。同时补上述两个索引根治慢 SQL。这样：
- 任何现有 SQL 行为完全不变（无回归风险）。
- 慢 SQL 因补索引而加速（纯增益）。
- 未来若想加 read_timeout 兜底，补完索引 + 改 cleanup 为分批 DELETE 后即可安全下调（记入第 8 节 TODO）。

> 经核实，其余 3 张清理表索引齐全，无需处理：`agent_task_messages.idx_created_at`、`chat_sessions.idx_expires_at`、`agent_verifications.idx_created_at`。

## 7. 配套索引补充（alembic 迁移）

迁移脚本：`alembic/versions/20260801_add_slow_query_indexes.py`

```python
# upgrade：幂等预检 + 建索引
op.create_index('idx_status', 'tasks', ['status'])
op.create_index('idx_created_at', 'agent_tasks', ['created_at'])
# downgrade：对应 drop
```

- `down_revision = '20260722_agent_media_ctx'`（迁移链 head）
- 索引命名遵循项目规范（无表名前缀，参考 `idx_session_id` 等）
- MySQL online DDL（ALGORITHM=INPLACE）建索引对 InnoDB 不锁表
- 已同步更新 `model/tasks.py`、`model/agent_tasks.py` 末尾 CREATE_TABLE_SQL（AGENTS.md 第 7 条）
- 服务重启时 `run_prod.py` 的 `auto_migrate` 自动执行迁移

## 8. 风险边界与后续优化 TODO

### SteadyDB 透明重试与 transaction() 的 begin() 保护（已修复 2026-08-03）

DBUtils 池返回的是 SteadyDB 加固连接（`tough=True`）：连接在非显式事务中断开时
（如 MySQL 端 kill 连接、网络抖动），会**自动重连并静默重试失败命令一次，不向上抛错**。
透明重试的开关是 `_transaction` 标志，**只有 `begin()` 会置 True**
（steady_db.py：`begin()` 注释 "connections won't be transparently replaced, and all
errors will be raised to the application"）。

影响评估：

- **单语句助手（`execute_query/update/insert`，114 个调用点）：安全，无需改动。**
  `autocommit=False` 下，连接死亡时 MySQL 服务端自动回滚该连接上未提交的事务，
  重试不会重复写入；且"MySQL 重启后自动自愈"是净收益。
- **多语句事务（`transaction()`，全仓库 13 处）：曾被暴露，已修复。**
  若不处理，语句 1..k-1 随死连接被服务端回滚，语句 k 却在新连接上重试成功 →
  只提交后半段且无报错（原子性破坏）；`SELECT ... FOR UPDATE` 租约场景
  （`script_split_task.claim_next_task`、`download_queue.claim_pending` 等）
  还会丢锁盲写，导致同一任务被多个 worker 认领。

修复（`model/database.py` `transaction()`）：借出连接后立即 `conn.begin()`。
事务中途连接错误直接抛给调用方 → `rollback()` → 原子性恢复（与池化改造前语义一致）。
`begin()` 不改变提交时机（数据仍只在 `commit()` 时落库），不影响非事务连接
（它们永不调 `begin()`，透明重试/自愈行为不变），归还池时 `reset=True` 的
ROLLBACK 兜底清场，无状态跨借用泄漏。

测试：`tests/model/test_database_pool.py` 断言 begin→commit（成功）与
begin→rollback（异常透出）调用序列。

### 本次不做（缩小爆炸半径）
- [ ] **改 cleanup DELETE 为分批 `LIMIT 1000` 循环**：彻底消除单条 DELETE 持锁过久。索引已补缓解，分批是进一步优化。
- [ ] **评估 read_timeout 兜底**：补完索引 + 分批 DELETE 后，可考虑设 `DB_POOL_READ_TIMEOUT`（如 60-120s）兜底挂死 SQL，防止占用池连接不归还。
- [ ] **异步驱动迁移（aiomysql/asyncmy）**：彻底消除同步 DB 在异步服务中的阻塞隐患，契合 FastAPI 特性。工作量大，作为独立迭代。

### 监控建议（上线后观察）
- 服务启动日志应有 `[DBPool] 连接池已创建 pid=... mincached=2 maxcached=20`。
- `SHOW PROCESSLIST` 观察常驻连接数稳定在 ≤100，不飙升。
- 观察是否再出现 `(2003) Errno 99`（预期归零）。
- 观察是否出现新的 `(2013)` 报错（若 read_timeout 后续启用）。

## 9. 测试

`tests/model/test_database_pool.py` 覆盖：
- 懒加载 + 单例（同进程多次 `_get_pool` 返回同一对象）
- 默认配置兜底（DB_CONFIG 缺 pool 段时用内置默认值，兼容 conftest stub）
- pid 漂移检测（fork 后丢弃旧池重建）
- 连接复用（`SELECT CONNECTION_ID()` 断言借-还-再借是同一条底层连接，需真实 DB，无 DB 时 skip）

## 10. 依赖

- `requirements.txt`：新增 `DBUtils>=3.1.0`（3.x 纯 Python，pymysql 1.4.6 实测兼容）；修复了 pymysql 重复声明（删除 `pymysql>=1.1.0`，保留 `>=1.1.2`）。
- 跨平台（AGENTS.md 第 6 条）：DBUtils 纯 Python，无平台差异。
