# 代码自动升级方案设计

> 文档版本：v2.0
> 创建日期：2026-05-04
> 最近更新：2026-05-04（采纳方案 C：git 传输层 + 自定义升级层）
> 适用范围：客户端部署的 Windows / macOS / Linux 三平台 ZIP 分发包
> **状态：设计方案文档（部分功能尚未实现）。已实现的简易升级方案见 `docs/upgrade/simple_git_upgrade.md`。**

---

## 一、背景与目标

### 1.1 现状

本系统当前以 ZIP 包形式分发到终端用户机器：
- Windows：`start.bat`（依赖 `bin/uv`、`bin/mysql`）
- macOS：`start.command`（同上，区分 Intel / ARM）
- Linux：`scripts/running/linux_start_prod.sh`

内置 MySQL 与 uv 包管理器。目前只有数据库 Alembic 迁移机制，**没有任何代码层面的自动升级能力**。

### 1.2 目标

在不破坏用户数据（`data/mysql/`、`upload/`、`config_*.yml`、`files/`、`logs/`）的前提下，实现：
1. **可远程触发** —— 后台 API 检查、用户点击升级
2. **断点续传** —— 网络不稳定也能完成下载
3. **可回滚** —— 升级失败自动回到旧版
4. **可灰度发布** —— 先小范围发布、再全量
5. **可紧急撤回** —— 错误版本能秒级阻止新升级

### 1.3 核心约束（已与用户确认）

1. 用户是**普通终端用户**（点 `start.bat` 即用），**不能要求装 git**
2. 必须支持**灰度发布与紧急撤回**（生产关键）
3. **二进制锁定**（MySQL / ffmpeg / uv 不跟随升级），**仅升级 Python 代码 / 前端 / SQL / 模板**
4. 项目开源，希望**复用 GitHub / Gitee 平台**作为分发渠道
5. 三平台行为一致

---

## 二、核心挑战与方案选型

### 2.1 三大根本难题

| 难题 | 原因 | 方案 |
|------|------|------|
| **进程不能替换自己** | Python 进程持有 `.py` 文件锁（Windows 尤其严重），无法删除/覆盖正在运行的代码 | 独立 Updater 进程（仿 Chrome / VSCode 模式） |
| **MySQL 数据不能丢** | 用户业务数据在 `data/mysql/`，体积大不便备份 | 不备份业务数据，仅备份 schema 元信息，依赖 Alembic 安全迁移 + 用户自备份 |
| **跨平台一致性** | 信号、文件锁、权限模型差异大 | Updater 用纯 Python + uv，复用 `pid_manager.py` 的跨平台逻辑 |

### 2.2 方案选型对比（已选 C）

| 维度 | A. 纯自建 manifest | B. 纯 git pull | **C. git 传输层 + 自定义升级层（已选）** |
|------|--------------------|----------------|-----------------------------------------|
| 包来源 | 自建 CDN | 客户端 git pull | **GitHub/Gitee Release archive zip** |
| 客户端依赖 git | 否 | **必须** | 否（HTTP 下载 archive） |
| 服务器基础设施 | 自建 + 维护 | 无 | **零基础设施（复用 GitHub/Gitee）** |
| 灰度/撤回 | manifest 控制 | 困难 | **manifest（仓库内）控制** |
| 二进制更新 | 包内 | git LFS 复杂 | 不更新（锁定） |
| 签名验证 | 包 + manifest 双签 | GPG（外部 PKI） | **仅 manifest 签名 + 包 SHA256** |
| 用户本地修改 | 整体替换 | 冲突 | 整体替换（PRESERVE_PATHS 保护数据） |
| 完整性校验 | SHA256 | SHA-1（弱） | **SHA256（manifest 中提供）** |
| 国内访问 | 自建 CDN | 必须 Gitee mirror | **多源 fallback（Gitee → GitHub）** |
| 进程自替换 | 需 Updater | **同样需 Updater** | 需 Updater |
| 维护成本 | 高 | 低 | **中** |

**为何选 C：**
- 用户是普通终端用户，**A 维护成本太高**（需自建 CDN）
- 终端用户机器没装 git，**B 不可行**
- C 利用 GitHub/Gitee archive 接口（HTTP 下载，无需 git 客户端）
- 仓库内 `releases/manifest.json` 作为版本清单，**用 git push 控制灰度**
- 维持完整 Updater 流程（解决进程自替换、健康检查、回滚等核心问题）

### 2.3 外部 Updater 模式

```
主程序(server.py) ──触发升级──> 拉起 Updater 子进程(detached) ──> 主程序退出
                                       │
                                       ▼
                          Updater 完成所有升级动作
                                       │
                                       ▼
                              Updater 拉起新主程序
```

**为何不选其他 Updater 实现：**
- 进程内升级：Win 文件锁解不开，不可行
- 双目录切换（`current/` 与 `next/` 软链）：跨平台软链不一致
- **外部 Updater：** 复用 `start.bat`/`start.command` 当前结构，最小侵入

---

## 三、整体架构

```
┌──────────────────────────────────────────────────────────────┐
│ 开发侧（项目维护者）                                            │
│  git tag v1.5.2 && git push                                  │
│         ↓                                                    │
│  python releases/sign_manifest.py     (用维护者私钥签名)       │
│         ↓                                                    │
│  编辑 releases/manifest.json：                                │
│    beta.latest = v1.5.2  ← 灰度阶段先放 beta                  │
│    stable.latest 暂不变                                      │
│         ↓                                                    │
│  git commit && push   （manifest 即生效）                     │
└──────────────────────────────────────────────────────────────┘
                           ↓ HTTPS（强制）
┌──────────────────────────────────────────────────────────────┐
│ GitHub / Gitee（零运维）                                       │
│  raw URL: releases/manifest.json + manifest.json.sig         │
│  archive URL: archive/refs/tags/v1.5.2.zip                   │
└─────────────┬────────────────────────────────────────────────┘
              │ HTTPS
              ▼
┌──────────────────────────────────────────────────────────────┐
│ 客户端 主程序（运行中）                                        │
│  ┌──────────────────────┐    ┌────────────────────────────┐ │
│  │ api/upgrade.py       │←──→│ services/upgrade/          │ │
│  │  /check /status      │    │  - release_index           │ │
│  │  /download /apply    │    │  - download_manager        │ │
│  │  /rollback           │    │  - upgrade_state (持久化)   │ │
│  └──────────────────────┘    │  - signature_verifier      │ │
│                              │  - updater_launcher        │ │
│                              └────────────────────────────┘ │
└─────────────┬────────────────────────────────────────────────┘
              │ subprocess.Popen(detached)
              ▼
┌──────────────────────────────────────────────────────────────┐
│ Updater (独立进程，拷贝到 %TEMP% 运行)                         │
│  scripts/updater/updater.py                                  │
│   1. 等主程序退出 → 2. 停 MySQL → 3. 备份 → 4. 解压           │
│   5. 替换文件 → 6. 拉起主程序 → 7. 健康检查 → 8. 收尾或回滚   │
└──────────────────────────────────────────────────────────────┘
```

---

## 四、升级包与版本清单格式

### 4.1 仓库内 `releases/manifest.json`（git 跟踪）

```json
{
  "schema_version": 1,
  "channels": {
    "stable": {
      "latest": "v1.5.1",
      "min_upgrade_from": "v1.4.0"
    },
    "beta": {
      "latest": "v1.5.2",
      "min_upgrade_from": "v1.4.0"
    },
    "dev": {
      "latest": "v1.5.3-rc1",
      "min_upgrade_from": "v1.5.0"
    }
  },
  "releases": {
    "v1.5.2": {
      "release_date": "2026-05-10",
      "force_upgrade": false,
      "requires_db_migration": true,
      "requires_dependency_install": false,
      "min_disk_space_bytes": 524288000,
      "changelog_url": "https://github.com/owner/repo/releases/tag/v1.5.2",
      "archives": {
        "github": "https://github.com/owner/repo/archive/refs/tags/v1.5.2.zip",
        "gitee":  "https://gitee.com/owner/repo/repository/archive/v1.5.2.zip"
      },
      "sha256": "abc123...",
      "blacklisted": false
    },
    "v1.5.1": { "...": "..." }
  }
}
```

**关键字段说明：**

| 字段 | 作用 |
|------|------|
| `channels.{channel}.latest` | 该通道当前推荐版本（控制灰度） |
| `channels.{channel}.min_upgrade_from` | 必须 ≥ 此版本才能升级到 latest |
| `releases.{version}.archives` | 多源下载地址（Gitee 优先，GitHub 备用） |
| `releases.{version}.sha256` | 包完整性校验 |
| `releases.{version}.blacklisted` | 已发布但被撤回 → 客户端不再升级到此版本 |
| `releases.{version}.force_upgrade` | 强制升级（用户无法跳过） |
| `releases.{version}.requires_dependency_install` | requirements.txt 是否变化 |

**附带文件：**
- `releases/manifest.json.sig`：维护者私钥对 manifest.json 的 RSA 签名（Base64）
- `releases/public_key.pem`：公钥（仓库内供查阅，与代码内置一致）
- `releases/sign_manifest.py`：发布工具（开发侧用）

### 4.2 升级包来源：GitHub/Gitee archive zip

**优势：**
- 完全免维护（GitHub/Gitee 自动生成）
- 无需用户装 git
- HTTP 下载，简单

**关键技术细节：**
- GitHub archive：`https://github.com/{owner}/{repo}/archive/refs/tags/{tag}.zip`
- Gitee archive：`https://gitee.com/{owner}/{repo}/repository/archive/{tag}.zip`
- **解压后顶层有目录前缀** `{repo_name}-{tag}/`（GitHub 会去掉 v 前缀，Gitee 保留）
- Updater 必须**自动识别并跳过这层目录**

### 4.3 解压后期望的目录结构

```
{解压目录}/{repo}-{tag}/         ← Updater 跳过这层
├── api/
├── model/
├── scripts/
├── pyproject.toml
├── requirements.txt
└── ...                          ← 正常的项目根目录内容
```

**注意：** archive zip **不含 `.git` 目录**（天然的优势），也**不含 `bin/`**（已被 `.gitignore` 排除）。

### 4.4 PRESERVE_PATHS（升级时绝不动的路径）

升级时**完全不动**的路径（白名单）：

```python
UPGRADE_DEFAULT_PRESERVE_PATHS = [
    # 用户配置
    "config_prod.yml", "config_dev.yml", "config_unit.yml",
    # 用户数据
    "data/", "upload/", "files/", "logs/",
    # 二进制（仓库本就没有，但显式保护）
    "bin/",
    # 本地特殊文件
    "*.local.json", ".env",
    # 升级状态文件
    "data/upgrade_state.json", "data/upgrade_backups/", "data/update_packages/",
    # 用户二开覆盖
    "custom_overrides/",
]
```

### 4.5 删除策略

archive zip 是**完整的代码快照**。升级时：
1. 计算"新版本所有文件 - PRESERVE_PATHS"作为目标文件集
2. 旧版项目目录中"不在目标集且不在 PRESERVE_PATHS"的文件 → **删除**（处理重构后已废弃的文件）
3. 复制新文件到项目目录

> 旧版独有但不在 PRESERVE_PATHS 的文件会被删除（如 `deprecated/old_module.py`）。

---

## 五、升级状态机

### 5.1 状态转换图

```
            ┌──────────────────────────────────────────┐
            │                                          │
   IDLE → CHECKING → UPDATE_AVAILABLE → DOWNLOADING ───┘ (用户取消)
                                            │
                                            ▼
                                       VERIFYING ──失败──> FAILED
                                            │
                          (用户点击应用)     ▼
                                      READY_TO_APPLY
                                            │
                                            ▼
                                    STOPPING_SERVICES ──失败──> ROLLING_BACK
                                            │
                                            ▼
                                       BACKING_UP ──失败──> ROLLING_BACK
                                            │
                                            ▼
                                     INSTALLING ──失败──> ROLLING_BACK
                                            │
                                            ▼
                                  STARTING_NEW_VERSION ──失败──> ROLLING_BACK
                                            │
                                            ▼
                                      MIGRATING (DB) ──失败──> ROLLING_BACK
                                            │
                                            ▼
                                     HEALTH_CHECK ──失败──> ROLLING_BACK
                                            │
                                            ▼
                                       COMPLETED ──> IDLE

   ROLLING_BACK ──> ROLLED_BACK / ROLLBACK_FAILED(需人工介入)
```

### 5.2 状态文件结构（`data/upgrade_state.json`）

```json
{
  "state": "INSTALLING",
  "from_version": "v1.5.1",
  "to_version": "v1.5.2",
  "channel": "stable",
  "started_at": "2026-05-10T15:30:00+08:00",
  "current_step": "replacing_files",
  "progress": 65.0,
  "backup_id": "2026-05-10_15-30-00",
  "package_path": "data/update_packages/v1.5.2.zip",
  "archive_source": "gitee",
  "updater_pid": 12345,
  "main_pid_before": 6789,
  "error": null,
  "last_heartbeat": "2026-05-10T15:32:15+08:00"
}
```

> **关键：每次状态变更都 `fsync` 落盘**。Updater 崩溃时，新启动的主程序读取此文件即可知道升级处于何种状态，决定继续 / 回滚 / 告警。

---

## 六、详细升级流程

### Phase 0：启动时前置检查（主程序入口）

```python
# 在 run_prod.py / start_*.py 启动初期就执行
def check_pending_upgrade():
    state = load_upgrade_state()
    if state.state == 'IDLE':
        return  # 正常启动

    if state.state in ('UPGRADING', 'INSTALLING', 'STARTING_NEW_VERSION'):
        if (now() - state.last_heartbeat) > timedelta(minutes=5):
            log_critical("检测到上次升级未完成，启动恢复流程")
            attempt_recovery(state)  # 自动回滚或提示人工

    if state.state == 'HEALTH_CHECK':
        # 启动到这里说明上次健康检查通过了，标记完成
        state.state = 'COMPLETED'
        save_state()
```

### Phase 1：检查更新（异步）

```
Frontend ──> GET /api/upgrade/check
         ↓
release_index.fetch_async():
  1. 读取 config.upgrade.release_index_urls（多源数组）
     - 默认顺序：Gitee raw → GitHub raw
  2. 异步 GET {url} 拉取 manifest.json（aiohttp）
     - 任一源成功即用
  3. 异步 GET {url}.sig 拉取签名
  4. 校验 manifest 签名（用内置 RSA 公钥）
  5. 解析 channels[当前 channel].latest
  6. 检查 releases[latest].blacklisted（黑名单则跳过）
  7. semver 比较：latest vs 当前版本
  8. 检查 min_upgrade_from
  9. 持久化最新版本信息到状态
```

> **非阻塞要求（项目硬规定）**：HTTP 请求绝对不能用 `requests`，必须用 `aiohttp`。

**示例配置：**
```yaml
upgrade:
  release_index_urls:
    - "https://gitee.com/{owner}/{repo}/raw/main/releases/manifest.json"
    - "https://raw.githubusercontent.com/{owner}/{repo}/main/releases/manifest.json"
```

### Phase 2：下载（异步任务）

```python
class DownloadManager:
    async def download_async(self, version_info):
        # 1. 检查磁盘空间（5x 留给解压+备份）
        free = shutil.disk_usage(target_dir).free
        if free < version_info.min_disk_space_bytes:
            raise InsufficientDiskSpace

        # 2. 创建临时文件
        tmp_path = f"data/update_packages/{version}.zip.tmp"

        # 3. 选源（Gitee 优先，失败 fallback 到 GitHub）
        for source_name, url in version_info.archives.items():
            try:
                # 4. 分块下载（aiohttp + Range 请求支持断点续传）
                async with aiohttp.ClientSession() as session:
                    already = os.path.getsize(tmp_path) if os.path.exists(tmp_path) else 0
                    headers = {'Range': f'bytes={already}-'} if already else {}
                    async with session.get(url, headers=headers) as resp:
                        async with aiofiles.open(tmp_path, 'ab') as f:
                            async for chunk in resp.content.iter_chunked(1024*1024):
                                if cancel_event.is_set():
                                    raise DownloadCancelled
                                await f.write(chunk)
                                await update_state_progress(...)
                state.archive_source = source_name
                break
            except (NetworkError, TimeoutError) as e:
                log_warn(f"{source_name} 下载失败，尝试下一个源: {e}")

        # 5. 校验 SHA256（来自 manifest）
        if compute_sha256(tmp_path) != version_info.sha256:
            os.remove(tmp_path)
            raise ChecksumMismatch

        # 6. 重命名为正式包
        os.rename(tmp_path, tmp_path.replace('.tmp', ''))
```

**重试策略：** 单源 3 次重试（指数退避 1s/2s/4s），失败后切换源。

> **包不单独签名**：因为 SHA256 在已签名的 manifest 中，等价于通过 manifest 签名锁定包内容。

### Phase 3：应用升级（最关键）

```python
# api/upgrade.py
@router.post("/api/upgrade/apply")
async def apply_upgrade():
    state = load_upgrade_state()
    if state.state != 'READY_TO_APPLY':
        raise HTTPException(400, "包未就绪")

    # 1. 锁定状态，防并发
    if not state.try_acquire_lock():
        raise HTTPException(409, "已有升级在进行")

    # 2. 准备 Updater
    updater_launcher.prepare_updater()

    # 3. 启动 Updater（detached 子进程）
    updater_pid = updater_launcher.start_updater_detached(
        package_path=state.package_path,
        main_pid=os.getpid(),
        from_version=current_version,
        to_version=state.to_version
    )

    # 4. 写入状态：UPGRADING
    state.state = 'STOPPING_SERVICES'
    state.updater_pid = updater_pid
    state.main_pid_before = os.getpid()
    state.save()

    # 5. 异步延迟 3 秒后退出主程序
    asyncio.create_task(delayed_exit(3))

    return {"started": True, "updater_pid": updater_pid}
```

### Phase 4：Updater 执行（核心）

```python
# scripts/updater/updater.py（独立进程）

def main():
    # 1. 准备：拷贝自己到 %TEMP%/zjt_updater_<pid>/ 防被覆盖
    if not running_from_temp():
        relaunch_from_temp(); sys.exit(0)

    # 2. 等主程序退出
    wait_for_pid_exit(main_pid, timeout=60)
    if process_still_alive(main_pid):
        force_kill(main_pid)

    # 3. 停止所有项目相关进程（复用 pid_manager 逻辑）
    stop_all_project_processes()

    # 4. 停止 MySQL
    stop_mysql_gracefully(timeout=30)
    if mysql_still_running(): force_kill_mysql()

    # 5. 验证：项目目录下无活跃进程占用文件
    verify_no_locks_on_project_dir()

    # 6. 备份（注意：必须在停 MySQL 前预先记录 alembic_version）
    backup_id = create_backup()
        # - 备份将被替换的代码
        # - 备份配置文件（虽不替换，但兜底）
        # - 备份 alembic_version 信息（在停 MySQL 前用 mysqldump --no-data 抓取）

    # 7. 解压新包到临时目录并校验
    extracted = extract_archive(package_path)
    inner_root = find_inner_root(extracted)  # 跳过 GitHub/Gitee 的顶层目录前缀

    # 8. 替换文件（核心动作）
    replace_files(inner_root, project_dir, PRESERVE_PATHS)
        # 8.1 删除旧版独有文件（不在新版且不在 PRESERVE_PATHS）
        # 8.2 跳过 PRESERVE_PATHS
        # 8.3 复制新文件，遇到 PermissionError 重试 10 次

    # 9. 启动主程序（关键：通过原启动脚本启动）
    state.state = 'STARTING_NEW_VERSION'
    state.save()

    if platform == 'windows':
        subprocess.Popen(['start.bat', '--from-updater'], cwd=project_dir, ...)
    elif platform == 'darwin':
        subprocess.Popen(['./start.command', '--from-updater'], ...)
    else:
        subprocess.Popen(['bash', 'scripts/running/linux_start_prod.sh'], ...)

    # 10. 健康检查
    state.state = 'HEALTH_CHECK'
    state.save()

    if not health_check(timeout=120, url=f'http://127.0.0.1:{port}/api/health'):
        rollback(backup_id)
        sys.exit(1)

    # 11. 完成
    state.state = 'COMPLETED'
    state.save()
    cleanup_temp_files()
    sys.exit(0)
```

### Phase 5：依赖与数据库迁移（自动）

**依赖更新：** 由 `start.bat` 中的 `uv run --with-requirements requirements.txt` 自动检测并安装新依赖（uv 内置能力，无需 Updater 干预）。

**数据库迁移：** 由 `run_prod.py` 在主程序启动时自动执行 `alembic upgrade head`。Updater 不直接干预。

**迁移失败处理：**
- `run_prod.py` 抛错 → 主程序无法启动 → 健康检查超时 → Updater 触发回滚

---

## 七、回滚机制

### 7.1 回滚触发条件

1. 用户在 UI 手动触发
2. Updater 任一步骤失败
3. 健康检查超时
4. 启动主程序连续 5 次失败
5. 启动后检测到 DB 迁移失败

### 7.2 回滚流程

```python
def rollback(backup_id):
    state.state = 'ROLLING_BACK'
    state.save()

    # 1. 停止所有进程（如果还在跑）
    stop_all_project_processes()
    stop_mysql_gracefully()

    # 2. 数据库回滚（如果做过迁移）
    if state.db_migrated:
        old_revision = backup.alembic_version
        start_mysql()
        result = run_alembic_downgrade(target=old_revision)
        if result.failed:
            state.state = 'ROLLBACK_FAILED'
            log_critical("DB 回滚失败，需人工介入")
            return

    # 3. 恢复代码文件
    restore_files_from_backup(backup_id)

    # 4. 启动旧版本
    start_main_program()

    # 5. 健康检查
    if health_check():
        state.state = 'ROLLED_BACK'
    else:
        state.state = 'ROLLBACK_FAILED'
        log_critical("回滚后启动失败")
```

### 7.3 数据库回滚的风险

如果新版本的 Alembic 迁移是破坏性的（删字段、删表），即使 downgrade 函数写得对，**数据也回不来**。所以：
- 升级前用 `mysqldump --no-data` 备份 schema 信息（不备份业务数据）
- 大版本升级前**强制要求用户手动备份**（升级页面显示警告勾选框）
- 配置项 `upgrade.require_user_backup_confirm: true`

### 7.4 紧急撤回（服务端）

当发现已发布版本有严重 bug：
1. 编辑仓库 `releases/manifest.json`
2. 把出问题版本标 `blacklisted: true`
3. 把 `channels.stable.latest` 改回上一个稳定版本
4. 重新签名 + commit + push
5. 客户端检查更新时：
   - 未升级用户：看到 latest 仍是旧版，不会升级
   - 已升级用户：看到当前版本被 blacklist + latest 比当前低 → UI 提示"该版本存在问题，建议手动回滚"

---

## 八、关键边界情况清单（不放过任何问题）

| # | 场景 | 处理方案 |
|---|------|----------|
| 1 | 下载中网络断开 | aiohttp 单源 3 次重试 + 跨源 fallback；保留 `.tmp` 文件支持断点续传 |
| 2 | 磁盘空间不足 | 下载前检查 `min_disk_space_bytes × 2`；不足直接拒绝 |
| 3 | SHA256 校验失败 | 删除文件、重置状态、提示用户 |
| 4 | manifest 签名验证失败 | 拒绝升级，记录安全告警日志 |
| 5 | 用户中途取消下载 | `cancel_event` 信号，保留 .tmp 供下次续传或清理 |
| 6 | 主程序未在 60s 内退出 | Updater 强杀（`taskkill /F` 或 `kill -9`） |
| 7 | MySQL 无法停止 | 先 `mysqladmin shutdown`（30s），失败则 PID 强杀 |
| 8 | Win 文件被锁（DLL/exe） | 重试 10 次×1s；二进制锁定后此风险大幅降低（仅 .py 文件） |
| 9 | 文件系统权限不足 | 升级前检测：`os.access(project_dir, os.W_OK)`；失败提示 UAC |
| 10 | 中文路径编码问题 | 全程使用 `pathlib.Path` 和 utf-8 编码（项目跨平台规则） |
| 11 | Updater 自身被杀 | 主程序启动时检查状态文件，发现非终态则进入恢复流程 |
| 12 | 升级中断电 | 同上，状态文件 fsync 落盘后即使断电也能恢复 |
| 13 | 并发升级请求 | 状态机锁 + `data/upgrade.lock` 文件（含 PID + start time） |
| 14 | 版本降级 | 默认拒绝；配置 `allow_downgrade: false`；强制降级需带数据库兼容性警告 |
| 15 | 跨大版本升级（1.0 → 2.0） | manifest.min_upgrade_from 拒绝；提示先升到中间版本 |
| 16 | 强制升级 | manifest.force_upgrade=true 时主程序启动后强制弹窗，无法跳过 |
| 17 | GitHub/Gitee 限流或不可用 | 多源 fallback + 指数退避；最终失败提示用户稍后再试 |
| 18 | 升级期间用户访问 API | 服务停止后访问失败；前端轮询升级状态接口 |
| 19 | DB 迁移失败 | 自动回滚 + downgrade；downgrade 也失败则人工介入 |
| 20 | 健康检查超时 | 120s 内 `/api/health` 不返回 200 视为失败 |
| 21 | 端口被占用 | 启动失败 → 重试 5 次 → 触发回滚 |
| 22 | requirements.txt 变化 | uv 自动检测并安装（依赖现有 `uv run --with-requirements`） |
| 23 | 用户改过的代码被覆盖 | PRESERVE_PATHS 之外默认覆盖；提供 `custom_overrides/` 目录给用户放自定义文件，升级后自动复制覆盖 |
| 24 | 升级包下载到一半服务重启 | `.tmp` 文件保留，新启动主程序检查到状态恢复继续 |
| 25 | 备份目录磁盘占满 | 保留最近 N 个备份（默认 3），自动清理最旧的 |
| 26 | 数据库 schema 损坏 | 升级前 `mysqldump --no-data` 备份 schema，失败时尝试恢复 |
| 27 | 时钟同步问题 | 状态时间戳用 ISO 8601 + 时区，避免本地时间漂移 |
| 28 | 中国大陆下载慢 | manifest 中 Gitee URL 优先；客户端按 ping 选最快源 |
| 29 | manifest.json 被篡改（GitHub 账号被盗） | manifest 单独 RSA 签名，攻击者无私钥无法伪造 |
| 30 | Updater 程序自己被替换 | Updater 拷贝到 `%TEMP%` 运行（独立于项目目录） |
| 31 | GitHub archive 算法变更 | 监控 + 发布时多机器校验；manifest 中 sha256 标记发布时间 |
| 32 | 仓库迁移（GitLab → GitHub） | manifest 中保留多个 archive URL；可灰度迁移 |
| 33 | archive 顶层目录前缀 | `find_inner_root()` 自动识别（`{repo}-{tag}/`） |
| 34 | 已发布版本紧急撤回 | manifest.releases.{ver}.blacklisted=true + channels.latest 回退 |
| 35 | 用户处于无网络环境 | 升级 API 返回明确错误，不阻塞日常使用 |

---

## 九、文件结构（落地清单）

```
comfyui_server_dev2/
├── api/
│   └── upgrade.py                       【新增】升级 API 路由
├── services/
│   └── upgrade/                         【新增】升级业务层
│       ├── __init__.py
│       ├── release_index.py             (拉取 manifest，多源 fallback)
│       ├── version.py                   (semver 比较 + channel 判断)
│       ├── download_manager.py          (aiohttp + 断点续传)
│       ├── upgrade_state.py             (状态机 + 持久化)
│       ├── signature_verifier.py        (RSA 签名验证)
│       ├── package_manager.py           (archive zip 解析)
│       ├── updater_launcher.py          (拉起 Updater)
│       └── recovery.py                  (启动时检测异常状态)
├── scripts/
│   └── updater/                         【新增】独立 Updater
│       ├── updater.py                   (主入口)
│       ├── relauncher.py                (拷贝自己到 temp)
│       ├── backup.py
│       ├── installer.py                 (文件替换核心)
│       ├── rollback.py
│       ├── service_controller.py        (启停服务)
│       ├── health_checker.py
│       └── check_upgrade_state_on_boot.py (启动脚本调用)
├── config/
│   ├── constant.py                      【修改】新增升级常量
│   ├── unified_config.py                【修改】新增升级配置
│   ├── config.example.yml               【修改】新增 upgrade 段
│   ├── config_prod.base.yaml            【修改】新增 upgrade 默认值
│   └── upgrade_public_key.pem           【新增】RSA 公钥（内置）
├── alembic/versions/
│   └── 20260510_xxx_add_upgrade_log.py  【新增】升级日志表迁移
├── model/
│   ├── upgrade_log.py                   【新增】升级日志 model
│   └── sql/baseline_with_db.sql         【修改】加入 upgrade_log 表
├── releases/                            【新增】版本清单（仓库内，git 跟踪）
│   ├── manifest.json                    (每次发布更新)
│   ├── manifest.json.sig                (维护者签名)
│   ├── public_key.pem                   (公钥，仅供查阅)
│   └── sign_manifest.py                 (发布工具)
├── data/                                【运行时】
│   ├── upgrade_state.json               (状态文件)
│   ├── upgrade.lock                     (锁文件)
│   ├── update_packages/                 (下载缓存)
│   └── upgrade_backups/                 (备份目录)
├── custom_overrides/                    【可选】用户二开覆盖目录
├── web/
│   └── admin/
│       ├── upgrade.html                 【新增】升级管理页
│       └── js/upgrade.js                【新增】升级前端逻辑（SSE）
├── docs/
│   └── upgrade/                         (本目录)
│       ├── auto_upgrade_design.md       (本设计文档)
│       ├── api_reference.md             (待写)
│       ├── release_workflow.md          (待写)
│       └── troubleshooting.md           (待写)
├── start.bat                            【修改】新增 --from-updater + 升级状态预检
├── start.command                        【修改】同上
└── scripts/running/linux_start_prod.sh  【修改】同上
```

---

## 十、配置项（按项目规则集中管理）

### 10.1 `config/constant.py` 新增

```python
# === 自动升级 ===
UPGRADE_STATE_FILE = "data/upgrade_state.json"
UPGRADE_LOCK_FILE = "data/upgrade.lock"
UPGRADE_PACKAGE_DIR = "data/update_packages"
UPGRADE_BACKUP_DIR = "data/upgrade_backups"
UPGRADE_BACKUP_KEEP_COUNT = 3
UPGRADE_HEALTH_CHECK_TIMEOUT = 120
UPGRADE_HEALTH_CHECK_URL = "/api/health"
UPGRADE_DOWNLOAD_TIMEOUT = 1800
UPGRADE_DOWNLOAD_CHUNK_SIZE = 1024 * 1024
UPGRADE_DOWNLOAD_RETRY_COUNT = 3
UPGRADE_FILE_REPLACE_RETRY = 10
UPGRADE_DEFAULT_PRESERVE_PATHS = [
    "config_prod.yml", "config_dev.yml", "config_unit.yml",
    "data/", "upload/", "files/", "logs/",
    "bin/",
    "*.local.json", ".env",
    "custom_overrides/",
]
```

### 10.2 `config.example.yml` 新增

```yaml
upgrade:
  enabled: true
  # 版本清单地址（多源 fallback，按顺序尝试）
  release_index_urls:
    - "https://gitee.com/{owner}/{repo}/raw/main/releases/manifest.json"
    - "https://raw.githubusercontent.com/{owner}/{repo}/main/releases/manifest.json"
  # 通道：stable / beta / dev
  channel: "stable"
  # 自动检查间隔（小时），0 = 关闭
  check_interval_hours: 24
  # 自动下载（仅下载，不安装）
  auto_download: false
  # 公钥路径（用于 manifest 签名验证）
  public_key_path: "config/upgrade_public_key.pem"
  # 强制签名验证
  require_signature: true
  # 是否允许降级
  allow_downgrade: false
  # 大版本升级要求用户确认已备份
  require_user_backup_confirm: true
  # 备份保留数量
  backup_keep_count: 3
  # 失败时自动回滚
  auto_rollback_on_failure: true
  # 代理（aiohttp）
  proxy: ""
```

---

## 十一、API 端点设计（仅管理员可访问）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/upgrade/version` | 当前版本 + 平台信息 |
| GET | `/api/upgrade/check` | 检查更新（异步） |
| GET | `/api/upgrade/status` | 实时状态（SSE 推送，轮询兜底） |
| POST | `/api/upgrade/download` | 启动下载 |
| POST | `/api/upgrade/cancel` | 取消下载 |
| POST | `/api/upgrade/apply` | 应用升级（5s 后服务退出） |
| POST | `/api/upgrade/rollback` | 回滚到指定备份 |
| GET | `/api/upgrade/backups` | 备份列表 |
| GET | `/api/upgrade/changelog` | 更新说明 |
| GET | `/api/upgrade/history` | 升级历史（从 upgrade_log 表） |

> 全部 `async def` + `aiohttp` / `aiofiles`，遵循非阻塞规则。

---

## 十二、数据库表（按项目规则）

```python
# model/upgrade_log.py
class UpgradeLog(Base):
    __tablename__ = "upgrade_log"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    from_version = Column(String(32), nullable=False)
    to_version = Column(String(32), nullable=False)
    channel = Column(String(16))                # stable / beta / dev
    archive_source = Column(String(16))         # gitee / github
    status = Column(String(32), nullable=False)
        # pending / downloading / installing / success / failed / rolled_back
    started_at = Column(DateTime, nullable=False)
    completed_at = Column(DateTime)
    error_message = Column(Text)
    backup_id = Column(String(64))
    triggered_by = Column(String(32))           # manual / auto / forced
    operator_id = Column(BigInteger)
    create_at = Column(DateTime, default=datetime.now)
    update_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
```

需同步：
- `alembic/versions/20260510_xxx_add_upgrade_log.py`（新增表）
- `model/sql/baseline_with_db.sql`（加入 upgrade_log）

---

## 十三、启动脚本修改要点

### 13.1 `start.bat` 关键修改

```batch
:: 启动前检查升级状态
"%PYTHON%" scripts\updater\check_upgrade_state_on_boot.py
if errorlevel 2 (
    :: errorlevel 2 = 检测到中断的升级，需要恢复
    "%PYTHON%" scripts\updater\recover.py
    if errorlevel 1 (
        echo [ERROR] 升级恢复失败，请联系支持。
        pause
        exit /b 1
    )
)

:: 接受 --from-updater 参数（来自 Updater 启动）
if "%1"=="--from-updater" (
    set FROM_UPDATER=1
    echo [INFO] 由升级器启动，跳过部分初始化
)

:: 现有逻辑继续...
uv run --python ... start_windows.py %FROM_UPDATER%
```

`start.command` 与 `linux_start_prod.sh` 做同样修改（注意三平台一致）。

---

## 十四、安全设计

| 安全点 | 措施 |
|--------|------|
| **manifest 来源可信** | RSA 2048 签名（manifest.json.sig），公钥内置代码 |
| **包来源可信** | 包 SHA256 写入 manifest，由 manifest 签名间接锁定 |
| 传输安全 | 强制 HTTPS，验证证书 |
| 完整性 | manifest 中提供包 SHA256，下载后校验 |
| 权限 | 升级 API 仅管理员；操作记录 operator_id |
| 频率限制 | 每分钟最多 1 次 check |
| 公钥更新 | 不允许在线更新公钥（防供应链攻击） |
| 降级防御 | 严防签名包被替换为旧漏洞包，对比 version 拒绝降级 |
| GitHub 账号被盗 | 攻击者改 manifest 但无私钥 → 客户端签名验证失败 → 拒绝升级 |

> **关键：私钥由维护者保管，不在仓库内**。仓库内 `releases/public_key.pem` 仅供查阅，必须与代码内置的 `config/upgrade_public_key.pem` 一致（CI 校验）。

---

## 十五、前端 UI 流程

```
[管理后台首页]
  └─ 顶部状态条：检测到新版本 v1.5.2 [查看详情]
                 ↓
[升级管理页]
  ├─ 当前版本：v1.5.1（2026-04-30）  当前通道：stable
  ├─ 最新版本：v1.5.2（2026-05-10）
  ├─ 更新内容：（changelog）
  ├─ 包大小：50MB  预估时间：1-3 分钟
  ├─ ⚠️ 重要数据请提前备份  [✓我已备份]
  ├─ [立即升级] [稍后提醒]

[升级中]（升级开始后页面切换为升级监控页）
  ├─ 阶段：[●下载●][●备份●][●安装○][○迁移○][○重启○]
  ├─ 进度条：65% 正在替换文件...
  ├─ 日志窗口：实时显示 Updater 输出
  └─ ⚠️ 请勿关闭电源 / 网络

[升级完成]
  ├─ ✓ 升级成功，当前版本 v1.5.2
  └─ [刷新页面]

[升级失败]
  ├─ ✗ 升级失败：DB 迁移异常
  ├─ 已自动回滚到 v1.5.1
  └─ [查看日志] [重试] [联系支持]

[版本被撤回提示]
  └─ ⚠️ 您当前的版本 v1.5.2 已被撤回，建议回滚到 v1.5.1
     [立即回滚] [忽略]
```

> 前端用 **SSE（Server-Sent Events）** 推送状态，比轮询更优雅；保留轮询作为兜底。

---

## 十六、实施分阶段（建议落地顺序）

| 阶段 | 内容 | 备注 |
|------|------|------|
| **P0 基础骨架** | 状态机、配置、常量、API 框架、Frontend 占位页、数据库表 | 不实际升级，先打通管控面 |
| **P1 检查+下载** | manifest 拉取（多源 fallback）、版本比较、签名验证、下载、SHA256 校验 | 用户能"看到有新版本" |
| **P2 Updater 核心** | 备份、解压（处理 archive 顶层目录）、文件替换、健康检查 | 在测试环境跑通完整链路 |
| **P3 回滚 + 异常恢复** | 备份恢复、DB downgrade、启动时状态检测、断电恢复、并发锁 | 失败场景测试 |
| **P4 灰度发布 + 撤回** | channel 配置、blacklisted 处理、强制升级、撤回提示 | 上线策略 |
| **P5 UX 打磨** | SSE 进度、changelog 渲染、备份管理 UI、升级历史 | 用户体验 |
| **P6 文档完整** | api_reference / release_workflow / troubleshooting | 长期维护 |

---

## 十七、设计红线（必须强调）

1. **不在异步函数中用 `requests`** —— 项目硬规定，全部 aiohttp。
2. **不备份 MySQL 业务数据** —— 不现实，依赖 Alembic + 用户自备份。
3. **Updater 不放在项目目录运行** —— Win 文件锁问题。
4. **公钥不在线更新** —— 防供应链攻击。
5. **不允许跳过 manifest 签名** —— `require_signature: true` 是默认且推荐。
6. **状态文件每次变更必 fsync** —— 断电恢复依赖。
7. **备份只备份"将被替换的文件"** —— 不是全量备份。
8. **三平台启动脚本都要改** —— Windows / macOS / Linux 一致行为。
9. **文档同步更新到 `docs/upgrade/`** —— 项目规则。
10. **升级日志表加入 `alembic` 和 `baseline_with_db.sql`** —— 项目规则。
11. **二进制锁定，绝不更新 `bin/`** —— 简化升级范围、降低风险。
12. **archive zip 顶层目录前缀必须自动识别** —— GitHub/Gitee 都有 `{repo}-{tag}/` 前缀。

---

## 十八、测试计划

### 18.1 单元测试

- 版本比较逻辑（semver，含 1.10.0 vs 1.9.0）
- manifest 签名验证（正确 / 篡改 / 错误公钥）
- SHA256 计算
- 状态机转换（含异常路径）
- archive 顶层目录识别（GitHub / Gitee 不同格式）

### 18.2 集成测试

搭建本地静态文件服务器模拟 GitHub raw + archive：
```bash
# 准备
mkdir -p /tmp/test-upgrade-server/releases
# 写假 manifest
# 创建假 archive zip
python -m http.server 8888 --directory /tmp/test-upgrade-server

# 配置项目指向本地
config.upgrade.release_index_urls: ["http://localhost:8888/releases/manifest.json"]

# 触发升级 API 测试完整流程
```

测试项：
- 完整升级流程（dev → 模拟新版本）
- 下载中断重试 + 跨源 fallback
- 升级中断恢复（手动 kill updater）
- 回滚流程（含 DB downgrade）
- 并发升级请求拒绝
- 灰度（beta only）+ 撤回（blacklisted）

### 18.3 手动测试

- 跨平台测试（Windows 11 / macOS Sonoma / Ubuntu 22.04）
- 中文用户名路径（`C:\Users\张三\zjt`）
- 大文件下载（> 500MB）
- 慢速网络（限速 100KB/s）
- 磁盘空间不足
- 升级期间断电（虚拟机模拟）
- GitHub 不可达，仅 Gitee 可用
- 用户改过 `web/` 文件的覆盖告警

---

## 十九、发布流程（给开发团队）

### 19.1 准备发布

```bash
# 1. 开发完成 → 测试通过
# 2. 更新版本号
vim pyproject.toml  # version = "1.5.2"

# 3. 生成 archive zip 并计算 SHA256
git tag v1.5.2 && git push origin v1.5.2
# 等 GitHub/Gitee 自动生成 archive

curl -L https://github.com/owner/repo/archive/refs/tags/v1.5.2.zip -o /tmp/v1.5.2.zip
sha256sum /tmp/v1.5.2.zip
# 同样验证 Gitee 包 SHA256（应该相同）
curl -L https://gitee.com/owner/repo/repository/archive/v1.5.2.zip -o /tmp/v1.5.2-gitee.zip
sha256sum /tmp/v1.5.2-gitee.zip
# ⚠️ 如果两边 SHA256 不一致，需在 manifest 中分别填写
```

### 19.2 更新 manifest

```bash
# 4. 编辑 releases/manifest.json，加入 v1.5.2 release 元数据
vim releases/manifest.json

# 5. 灰度阶段：只把 beta 通道指向新版本，stable 不动
{
  "channels": {
    "stable": { "latest": "v1.5.1" },
    "beta":   { "latest": "v1.5.2" }
  },
  "releases": {
    "v1.5.2": { "...": "..." }
  }
}

# 6. 用维护者私钥签名 manifest
python releases/sign_manifest.py \
  --private-key ~/.zjt/release_private_key.pem \
  --manifest releases/manifest.json \
  --output releases/manifest.json.sig

# 7. commit & push
git add releases/manifest.json releases/manifest.json.sig
git commit -m "release: v1.5.2 to beta channel"
git push
```

### 19.3 灰度提升

```bash
# 8. 观察 1 周 beta 用户反馈，无重大问题
# 9. 把 stable 指向 v1.5.2
vim releases/manifest.json
# stable.latest = v1.5.2

# 10. 重新签名 + push
python releases/sign_manifest.py ...
git commit -am "release: promote v1.5.2 to stable"
git push
```

### 19.4 紧急撤回

```bash
# 11. 发现 v1.5.2 严重 bug
vim releases/manifest.json
# releases.v1.5.2.blacklisted = true
# channels.stable.latest = "v1.5.1"

# 12. 重新签名 + push
python releases/sign_manifest.py ...
git commit -am "release: blacklist v1.5.2 due to critical bug"
git push

# 客户端下次检查更新即生效
```

---

## 二十、未尽事项 / 后续可扩展

1. **增量更新（Delta Update）** ：只下载变化部分，bsdiff/xdelta3 算法。当前为整包替换。
2. **二进制更新通道** ：MySQL/ffmpeg 大版本升级时的独立通道。当前锁定。
3. **P2P 分发** ：内网用户互相同步升级包。
4. **A/B 测试** ：同一版本下两套行为，灰度对比。
5. **升级公告系统** ：从 manifest 拉取重要公告并推送。
6. **多语言 changelog** ：根据用户语言展示不同的更新说明。
7. **升级失败自动上报** ：错误日志脱敏后回传，便于发布方排查。
8. **自定义二开支持** ：`custom_overrides/` 机制成熟化（升级合并策略）。
9. **私有仓库支持** ：通过 deploy token 拉私有仓库 archive（当前仅公开仓库）。

---

## 附录 A：方案对比详解

### A.1 为什么不选纯自建 manifest（方案 A）

**优势：**
- 完全自主控制
- 可做高级灰度（按地理位置、按用户特征）
- 可统计升级数据

**劣势（致命）：**
- 需自建 CDN（成本）
- 需维护服务（人力）
- 国内访问需自建多区域节点

**结论：** 对开源项目过重，且项目规模未到必要程度。

### A.2 为什么不选纯 git pull（方案 B）

**优势：**
- 零基础设施
- 增量更新天然
- 回滚 `git reset` 一键

**劣势（致命）：**
- 终端用户不装 git（项目目标用户是普通人）
- `.git` 目录体积大（首次 clone 慢）
- 用户本地修改造成冲突
- 灰度发布困难（`git push` 即对所有人生效）
- 紧急撤回困难
- SHA-1 完整性弱（已被破解）

**结论：** 仅适合开发者用户，不适合普通终端用户。

### A.3 为什么选 git 传输层 + 自定义升级层（方案 C）

**核心思想：**
- 利用 GitHub/Gitee 自动生成的 archive zip 作为分发包（HTTP 下载，无需 git 客户端）
- 仓库内维护 `releases/manifest.json` 作为版本清单
- 维护者通过 `git push` 控制灰度与撤回（仓库即"管理后台"）
- 客户端保留完整 Updater 流程（解决进程自替换、健康检查、回滚）

**优势：**
- 零基础设施（GitHub/Gitee 公开服务）
- 用户体验好（HTTP 下载，无需装 git）
- 灰度撤回灵活（git push 控制）
- 跨平台一致

**劣势：**
- 依赖 GitHub/Gitee 可用性（已有多源 fallback 缓解）
- 当前 archive 算法不一定永久稳定（需监控）
- 仅适合公开仓库（私有仓库需 deploy token，复杂度上升）

**适用场景判断：**
- 开源项目 ✓
- 用户量中等 ✓
- 团队没有运维能力 ✓
- 需要灰度撤回 ✓

→ **完全契合本项目场景，故选 C**。

---

## 附录 B：关键技术约束

### B.1 archive 包的天然结构

GitHub `archive/refs/tags/v1.5.2.zip` 解压后：
```
{repo_name}-1.5.2/    ← 顶层去掉 v 前缀
├── api/
├── model/
└── ...
```

Gitee `repository/archive/v1.5.2.zip` 解压后：
```
{repo_name}-v1.5.2/   ← 保留 v 前缀
├── api/
├── model/
└── ...
```

`installer.py` 的 `find_inner_root()` 必须**自动识别两种格式**，定位真实项目根。

### B.2 archive 不含的内容

archive zip **不含**：
- `.git/`（节省体积）
- `.gitignore` 排除的所有路径（如 `bin/`、`upload/`、`config_*.yml` 等）
- 提交者邮箱等元数据（不像 git clone 会暴露历史）

archive zip **包含**：
- 仓库内所有 git 跟踪文件
- 包括 `releases/manifest.json` 本身（升级后会被覆盖到客户端，但客户端读的是远程 raw URL，无影响）

### B.3 二进制锁定的实现

`bin/` 加入 `PRESERVE_PATHS` → 升级时不动。
新版 `requirements.txt` 会被复制到客户端，下次启动时 `uv run --with-requirements` 自动安装新 Python 包，但不动 `bin/uv`、`bin/mysql`、`bin/ffmpeg`。

### B.4 用户二开支持

`custom_overrides/` 目录：
- 用户把自己改过的文件放这里（保留原项目相对路径，如 `custom_overrides/web/index.html`）
- 升级后 Updater 自动从此目录复制覆盖到对应位置
- 此目录加入 `PRESERVE_PATHS`，升级不会覆盖
- 升级前 UI 显示 `custom_overrides/` 文件清单 + 是否还能在新版本中应用的检测结果
