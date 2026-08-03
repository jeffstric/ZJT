# 代码自动升级方案（简化版 —— 内置 git + 启动时检查）

> 文档版本：v1.0
> 创建日期：2026-05-04
> 适用范围：Windows / macOS / Linux 三平台 ZIP 分发包

---

## 一、背景

项目以 ZIP 形式分发给普通终端用户，用户点 `start.bat` / `start.command` 即用。当前没有代码自动升级能力，仅支持 Alembic 数据库迁移。

用户已明确：
- **用户是小白**，但**可以自带 git 二进制**
- **暂不需要灰度发布与紧急撤回**
- **二进制锁定**（MySQL / ffmpeg / uv 不更新），仅升级 Python 代码
- 希望**尽量简单**，不要复杂的 Updater 进程和状态机

---

## 二、核心思路

**一句话：在启动脚本里（主程序启动之前），用 git 检查远程差异 → 询问用户 → git pull 更新 → 正常启动。**

```
start.bat / start.command / linux_start_prod.sh
  │
  ▼
[阶段 1] 检查更新（Python 脚本，无独立进程）
  1. 找 git 二进制
  2. 检查 .git 目录 → 没有则自动初始化
  3. git fetch origin {branch}
  4. 检查 HEAD 与 origin 是否有差异
  5. 有差异 → 显示简要信息，问用户是否更新
  6. 用户确认 → git stash → git pull --ff-only → git stash pop（冲突则丢弃）
  7. 无差异/跳过/失败 → 继续
  │
  ▼
[阶段 2] 原有启动流程（不变）
  检查 uv → 检查 config → 检查 MySQL → uv run start_windows.py
```

**为什么不需要 Updater 独立进程？**
- git 操作在 Python 主程序启动**之前**执行
- 此时没有进程持有 `.py` 文件锁，git pull 可以正常覆盖
- 不需要"进程替换自己"的复杂处理

---

## 三、启动流程修改

### 3.1 start.bat（Windows）

```batch
@echo off
chcp 65001 > nul

:: === 新增：启动前检查更新 ===
echo [INFO] 检查更新...
"%PYTHON%" scripts\upgrade_check.py
if errorlevel 2 (
    echo [ERROR] 更新检查遇到严重错误
    pause
    exit /b 1
)
:: ============================

:: 原有逻辑继续...
echo [INFO] 检查 uv 环境...
:: ... 其余不变
```

### 3.2 start.command（macOS）

```bash
#!/bin/bash

# === 新增：启动前检查更新 ===
echo "[INFO] 检查更新..."
"$PYTHON" scripts/upgrade_check.py
if [ $? -eq 2 ]; then
    echo "[ERROR] 更新检查遇到严重错误"
    read -p "按回车键继续..."
    exit 1
fi
# ============================

# 原有逻辑继续...
echo "[INFO] 检查 uv 环境..."
```

### 3.3 linux_start_prod.sh（Linux）

```bash
#!/bin/bash

# === 新增：启动前检查更新 ===
echo "[INFO] 检查更新..."
python3 scripts/upgrade_check.py
if [ $? -eq 2 ]; then
    echo "[ERROR] 更新检查遇到严重错误"
    exit 1
fi
# ============================

# 原有逻辑继续...
export comfyui_env=prod
python3 scripts/running/run_prod.py
```

---

## 四、新增脚本：`scripts/upgrade_check.py`

### 4.0 二进制依赖检查

在执行 git 更新前，脚本会从仓库读取二进制依赖配置：

1. 使用 `git show` 读取远程分支中的 `config/required_binaries.yml` 文件
2. 解析配置文件中的 `binaries` 字段
3. 根据当前平台（windows/linux/macos）和目标版本检查二进制文件是否存在
4. 如果存在缺失的二进制文件：
   - 打印缺失文件清单及下载地址
   - **跳过自动更新**（不执行 git pull）
   - 允许程序以当前版本继续启动

**配置文件格式**：`config/required_binaries.yml`

```yaml
binaries:
  ffmpeg:
    description: "音视频处理工具"
    download_url: "https://cdn.zjt.com/bin/ffmpeg-6.0-win64.zip"
    check_paths:
      windows: "bin/ffmpeg/ffmpeg.exe"
      linux: "bin/ffmpeg/ffmpeg"
      macos: "bin/ffmpeg/ffmpeg"
    required_since: "2.0.0"  # 从 v2.0.0 开始需要此依赖
```

**设计意图**：
- 每个版本的二进制依赖都记录在仓库中，随版本发布
- 依赖源就是本项目，不依赖外部 API
- 支持多版本场景（v2.0 需要 A，v2.1 需要 A+B）

### 4.1 完整逻辑

```python
#!/usr/bin/env python3
"""
启动前检查更新脚本
由 start.bat / start.command / linux_start_prod.sh 在主程序启动前调用

返回值：
  0 - 正常（已更新 / 无需更新 / 跳过），继续启动
  1 - 更新失败但可继续，使用本地版本
  2 - 严重错误，应暂停并提示用户
"""

import os
import subprocess
import sys
from pathlib import Path


def find_git_binary():
    """查找 git 二进制

    仅使用项目内置的 bin/git，不回退到系统 PATH。
    Windows: bin/git/cmd/git.exe 或 bin/git/git.exe
    macOS/Linux: bin/git/bin/git
    """
    project_dir = Path(__file__).parent.parent.resolve()

    # 平台相关的候选路径
    if sys.platform == "win32":
        candidates = [
            project_dir / "bin" / "git" / "cmd" / "git.exe",   # MinGit 标准路径
            project_dir / "bin" / "git" / "git.exe",            # 旧路径兼容
        ]
    else:
        candidates = [
            project_dir / "bin" / "git" / "bin" / "git",       # Linux/macOS
            project_dir / "bin" / "git" / "git",                # 备用路径
        ]

    for p in candidates:
        if p.exists():
            return str(p)

    return None


def get_config(key, default=None):
    """读取配置（复用 config_util.py，或简单解析 YAML）"""
    # 实际实现时调用 config/config_util.py 的 get_config
    # 这里简化示意
    configs = {
        "upgrade.branch": "main",
        "upgrade.repo_urls": [
            "https://gitee.com/owner/repo.git",
            "https://github.com/owner/repo.git",
        ],
    }
    return configs.get(key, default)


def init_git_repo(project_dir, git_cmd, repo_urls, branch):
    """首次启动：.git 不存在，自动初始化

    支持多源 fallback，按顺序尝试每个源。
    """
    print("[upgrade] 首次运行，初始化 git 仓库...")

    # git init 只需执行一次
    subprocess.run([git_cmd, "init"], cwd=project_dir, check=True, capture_output=True)

    # 尝试每个源
    for url in repo_urls:
        print(f"[upgrade] 尝试源: {url}")
        try:
            # 清除已有的 remote（如果有）
            subprocess.run([git_cmd, "remote", "remove", "origin"],
                          cwd=project_dir, capture_output=True)
            # 添加 remote
            subprocess.run([git_cmd, "remote", "add", "origin", url],
                          cwd=project_dir, check=True, capture_output=True)
            # fetch
            subprocess.run([git_cmd, "fetch", "origin", branch, "--depth", "1", "--tags"],
                          cwd=project_dir, check=True, capture_output=True, timeout=60)
            # reset
            subprocess.run([git_cmd, "reset", "--hard", f"origin/{branch}"],
                          cwd=project_dir, check=True, capture_output=True)
            print(f"[upgrade] 初始化完成，使用源: {url}")
            return True
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
            print(f"[upgrade] 源 {url} 失败: {e}")
            continue

    print("[upgrade] 所有源都失败")
    return False


def check_and_update():
    project_dir = Path(__file__).parent.parent.resolve()

    # 1. 找 git 二进制
    git_cmd = find_git_binary()
    if not git_cmd:
        print("[upgrade] 未找到 git，跳过更新检查")
        return 0

    # 2. 读配置
    branch = get_config("upgrade.branch", "main")
    repo_urls = get_config("upgrade.repo_urls", [])

    # 3. 检查 .git 目录
    git_dir = project_dir / ".git"
    if not git_dir.exists():
        if not repo_urls:
            print("[upgrade] 未配置仓库地址，跳过更新")
            return 0
        if not init_git_repo(project_dir, git_cmd, repo_urls, branch):
            print("[upgrade] 初始化失败，跳过更新，使用本地版本")
            return 1
        # 初始化后当前版本已与 remote 一致，无需再 pull
        return 0

    # 4. fetch remote
    try:
        subprocess.run([git_cmd, "fetch", "origin", branch],
                      cwd=project_dir, timeout=30, check=True, capture_output=True)
    except subprocess.TimeoutExpired:
        print("[upgrade] 网络超时，跳过更新，使用本地版本")
        return 1
    except subprocess.CalledProcessError:
        print("[upgrade] 获取远程信息失败，跳过更新，使用本地版本")
        return 1

    # 5. 检查差异
    try:
        result = subprocess.run([git_cmd, "log", f"HEAD..origin/{branch}", "--oneline"],
                              cwd=project_dir, capture_output=True, text=True, check=False)
        if not result.stdout.strip():
            print("[upgrade] 已是最新版本")
            return 0
    except Exception:
        return 1

    commits = result.stdout.strip().split("\n")
    commit_count = len(commits)

    # 6. 显示更新信息
    print(f"[upgrade] 检测到 {commit_count} 个更新：")
    for c in commits[:5]:
        print(f"  {c}")
    if commit_count > 5:
        print(f"  ... 还有 {commit_count - 5} 个更新")

    # 7. 发现新版本，开始更新
    print(f"[upgrade] 发现新版本，开始更新...")

    # 8. 执行更新
    # 8.1 暂存用户本地修改（防止冲突）
    stashed = False
    try:
        subprocess.run([git_cmd, "stash", "push", "--include-untracked", "-m", "auto-upgrade-stash"],
                      cwd=project_dir, check=True, capture_output=True)
        stashed = True
        print("[upgrade] 本地修改已暂存")
    except subprocess.CalledProcessError:
        pass  # 可能没有本地修改，stash 失败没关系

    # 8.2 pull
    try:
        subprocess.run([git_cmd, "pull", "origin", branch, "--ff-only"],
                      cwd=project_dir, check=True, capture_output=True)
        print("[upgrade] 更新成功")
    except subprocess.CalledProcessError as e:
        print(f"[upgrade] 更新失败: {e}")
        if stashed:
            subprocess.run([git_cmd, "stash", "pop"], cwd=project_dir, check=False)
        return 1

    # 8.3 恢复 stash
    if stashed:
        try:
            subprocess.run([git_cmd, "stash", "pop"], cwd=project_dir, check=True, capture_output=True)
            print("[upgrade] 本地修改已恢复")
        except subprocess.CalledProcessError:
            # pop 冲突，丢弃 stash
            subprocess.run([git_cmd, "stash", "drop"], cwd=project_dir, check=False)
            print("[upgrade] 警告: 本地修改与新版本冲突，已自动丢弃。如需保留请提前备份。")

    # 9. 检查 requirements.txt 变化
    try:
        diff_result = subprocess.run([git_cmd, "diff", "--name-only", "HEAD@{1}", "HEAD"],
                                    cwd=project_dir, capture_output=True, text=True)
        if "requirements.txt" in diff_result.stdout:
            print("[upgrade] 依赖有更新，启动时将自动安装")
    except Exception:
        pass

    return 0


if __name__ == "__main__":
    sys.exit(check_and_update())
```

### 4.2 关键设计点

| 设计点 | 处理 |
|--------|------|
| 本地版本检测 | 收集 `tag --points-at HEAD` / `describe` / `pyproject.toml`，取版本最高者（避免 describe 落后导致启动死循环） |
| 更新对齐目标 | 优先 `reset --hard <远程最新 tag>`，失败再回退 `origin/{branch}` |
| 防无限重启 | 更新后若本地版本仍落后远程 tag，返回 0 继续启动，不再返回 10 |
| git 二进制 | 仅使用项目内置 bin/git，不回退系统 PATH |
| .git 不存在 | 自动 `git init` + `remote add` + `fetch --depth 1` + `reset --hard origin/{branch}` |
| 网络不通 | timeout 30s，失败返回 1（跳过更新，继续启动） |
| 无差异 | 静默通过，返回 0 |
| 有差异 | 显示前 5 条 commit，问用户（input） |
| 用户拒绝 | 返回 0，正常启动本地版本 |
| 二进制依赖缺失 | 跳过更新，返回 0，允许以当前版本启动 |
| 本地修改冲突 | `git stash` → `git pull` → `git stash pop` → pop 冲突则 `stash drop` |
| requirements.txt 变化 | 检测并提示，uv 启动时自动安装 |
| 数据库迁移 | git pull 后 Alembic 脚本更新，启动时 `run_prod.py` 自动执行 `alembic upgrade head` |

---

## 五、用户数据保护

git 不会触碰以下路径（已 `.gitignore`）：

```gitignore
# 当前 .gitignore 中已保护
data/
upload/
logs/
config_*.yml
*.local.json
enterprise/
scheduler.lock
```

升级后这些文件保持不变。

**如果用户改了 git 跟踪的文件（如 `web/`）：**
- 升级前自动 `git stash` 暂存
- 升级后尝试 `git stash pop` 恢复
- 如果冲突，丢弃 stash 并提示用户

---

## 六、各平台 Git 获取方式

### 6.1 Windows：内置 MinGit

Windows 分发包内置 **Git for Windows MinGit**（最小化版本），用户无需安装 Git。

- **来源**: https://github.com/git-for-windows/git/releases
- **文件**: `MinGit-{version}-64-bit.zip`（约 38MB）
- **放置位置**: 解压到 `bin/git/` 目录
- **入口**: `bin/git/cmd/git.exe`

```
bin/git/
├── cmd/git.exe           # 启动器（48KB）
├── mingw32/bin/git.exe   # 真正的 git（4.5MB）
├── mingw32/bin/*.dll     # 依赖库
├── mingw32/libexec/git-core/  # git 子命令
├── usr/                  # MSYS2 工具
├── etc/                  # 配置
└── LICENSE.txt
```

### 6.2 macOS / Linux：内置 git

macOS/Linux 分发包同样内置 git 二进制，放置于 `bin/git/` 目录下。

- 查找路径: `bin/git/bin/git` 或 `bin/git/git`
- **不回退**到系统 PATH，确保版本一致性

如果内置 git 不存在，升级检查会跳过（返回 0），不影响正常启动。

### 6.3 查找优先级

```
find_git_binary() 逻辑（仅使用内置 bin/git）：

Windows:
  1. bin/git/cmd/git.exe  (MinGit 标准路径)
  2. bin/git/git.exe       (旧路径兼容)

macOS/Linux:
  1. bin/git/bin/git
  2. bin/git/git           (备用路径)
```

---

## 七、配置项

`config/config.example.yml` 新增：

```yaml
upgrade:
  enabled: true              # 总开关，启动时检查并自动更新
  repo_urls:                 # Git 仓库地址（多源，按顺序尝试）
    - "https://gitee.com/owner/repo.git"       # 优先 Gitee（国内快）
    - "https://github.com/owner/repo.git"      # 备用 GitHub
  branch: "main"             # 跟踪分支
  timeout_seconds: 30        # fetch 超时
```

**配置说明**：
- `repo_urls`：多源列表，按顺序尝试，第一个成功即停止
- 推荐将国内源（Gitee）放在前面，GitHub 放在后面

`config/config_prod.base.yaml` 同样新增默认值。

---

## 八、文件改动清单

### 新增

| 文件 | 作用 |
|------|------|
| `scripts/upgrade_check.py` | 启动前检查更新 + 二进制依赖检查（核心脚本） |

### 修改

| 文件 | 修改点 |
|------|--------|
| `start.bat` | uv 检查之前插入 `python scripts\upgrade_check.py` |
| `start.command` | 同上 |
| `scripts/running/linux_start_prod.sh` | 同上 |
| `config/config.example.yml` | 新增 `upgrade:` 段 |
| `config/config_prod.base.yaml` | 新增 `upgrade:` 默认值 |
| `config/constant.py` | 新增升级常量（可选，如 UPGRADE_TIMEOUT） |
| `scripts/package.py` | 可选：改为保留 `.git` 目录（见 7.1 节） |

### 复用的现有功能

| 现有模块 | 复用点 |
|---------|--------|
| `config/config_util.py` | 读取配置 |
| `run_prod.py` 中的 Alembic 迁移 | 数据库升级自动执行 |
| `start.bat` 中的 uv run | requirements.txt 变化后自动装依赖 |

---

## 九、关于 `.git` 目录的两种策略

### 策略 A：分发包不带 .git（推荐，保持现状）

- package.py 继续排除 `.git`
- 首次启动时 `upgrade_check.py` 自动 `git init` + `fetch`
- **优点**：ZIP 体积小
- **缺点**：首次启动需要网络（fetch），无网环境无法初始化

### 策略 B：分发包带 .git（shallow clone）

- package.py 改为保留 `.git`
- 打包前执行 `git gc --aggressive` 压缩
- 分支已跟踪 origin，用户拿到即用
- **优点**：首次启动就能检查更新，无需网络初始化
- **缺点**：ZIP 体积增加（.git 目录通常 5-20MB）

**建议：** 先用策略 A（不改动 package.py），后续根据用户反馈决定是否需要策略 B。

---

## 十、边界情况

| # | 场景 | 处理 |
|---|------|------|
| 1 | 找不到 git | 跳过检查，正常启动 |
| 2 | 没有 .git + 无网络 | 跳过检查，正常启动（策略 A） |
| 3 | fetch 超时 | 提示网络超时，跳过更新 |
| 4 | fetch 失败（仓库不存在/权限不足） | 提示失败，跳过更新 |
| 4b | Gitee/GitHub 要求登录或本机脏凭据 | **不弹 GCM 凭据框**；git 直接失败 → 返回码 1，跳过更新继续启动（见「已知问题 #2」） |
| 5 | 用户拒绝更新 | 正常启动本地版本 |
| 6 | 二进制依赖缺失 | 跳过更新，打印缺失清单及下载地址，正常启动本地版本 |
| 7 | git pull 失败（非 fast-forward） | 提示失败，stash pop 恢复，启动本地版 |
| 8 | stash pop 冲突 | 丢弃 stash，提示用户，继续启动 |
| 9 | 中文路径 | pathlib + utf-8，git 原生支持 |
| 10 | 升级后 requirements.txt 变了 | 提示"依赖更新"，uv 启动时自动安装 |
| 11 | 升级后 Alembic 迁移失败 | run_prod.py 抛错 → 启动失败 → 用户需手动回滚（`git reset --hard HEAD@{1}`） |
| 12 | 并发启动 | 无问题（顺序执行，无并发状态） |
| 13 | 用户改了被 git 跟踪的文件 | stash → pull → pop，冲突则丢弃 |
| 14 | 启动脚本升级 | start.bat 本身被 git 跟踪，升级后下次启动用新版脚本 |
| 15 | Windows 下 git 锁定 | 无问题（主程序未启动） |
| 16 | macOS ARM/Intel | git 命令一致，跨平台 |

---

## 十一、与完整方案（auto_upgrade_design.md）的对比

| 维度 | 简化版（本文） | 完整版（auto_upgrade_design.md） |
|------|-------------|--------------------------------|
| **核心机制** | git pull | 独立 Updater + HTTP 下载 archive |
| **灰度发布** | ❌ 不支持 | ✅ manifest 控制 channel |
| **紧急撤回** | ❌ 不支持 | ✅ blacklisted 字段 |
| **断点续传** | ✅ git 自带 | ✅ 自实现 Range 下载 |
| **签名验证** | ❌ 不需要 | ✅ RSA 签名 manifest |
| **独立进程** | ❌ 不需要 | ✅ Updater 子进程 |
| **状态机** | ❌ 不需要 | ✅ 13 状态持久化 |
| **回滚** | 手动 git reset | ✅ 自动回滚 + DB downgrade |
| **代码量** | ~200 行 | ~3000+ 行 |
| **适用场景** | 快速上线、简单维护 | 大规模分发、需要精细控制 |

---

## 十二、发布流程（给维护者）

```bash
# 1. 开发完成 → 测试通过
# 2. 更新 pyproject.toml 版本号
# 3. commit + push
# 4. 打 tag（如 v1.5.0）并推送 tag
#    git tag v1.5.0
#    git push origin v1.5.0
# 5. 完毕

# 不需要：
# - manifest.json
# - 签名
# - 上传 CDN
# - 计算 SHA256

# 用户下次启动时自动检测并提示更新
```

---

## 十三、测试计划

1. **无网络环境**：断网启动 → 应提示"网络不可用"→ 正常启动
2. **无 git**：删除 git 二进制 → 应提示"未找到 git"→ 正常启动
3. **无差异**：HEAD 与 origin 一致 → 静默通过
4. **有差异**：push 新 commit → 启动时应显示更新信息 → 确认后 pull
5. **用户拒绝**：显示差异 → 输入 n → 正常启动本地版
6. **本地修改冲突**：改一个被跟踪的文件 → stash → pull → pop 冲突 → 丢弃并提示
7. **requirements.txt 变化**：pull 后检测并提示依赖更新
8. **跨平台**：Win / macOS / Linux 分别测试
9. **中文路径**：用户目录含中文 → 正常执行
10. **首次启动无 .git**：策略 A，自动 init + fetch

---

## 十四、已知问题

| # | 问题 | 影响 | 解决方案 |
|---|------|------|----------|
| 1 | Linux 启动脚本直接用 `python3` 执行 `upgrade_check.py`，未使用 `uv run` | 如果系统未安装 `pyyaml` 模块，配置文件解析会失败，回退到默认值 | Linux 推荐使用 Docker 部署，Docker 内已包含依赖；或手动 `pip install pyyaml` |
| 2 | 内置 MinGit 默认 `credential.helper = manager`，访问 Gitee 需鉴权/限流/本机脏凭据时会弹出 **Git Credential Manager** GUI | 部分用户启动卡在 `[1.5/4] Checking for updates`，小白不知如何处理 | **已修复**：`get_git_env()` 设置 `GIT_TERMINAL_PROMPT=0`、`GCM_INTERACTIVE=false`、`GCM_GUI_PROMPT=false`，并本进程禁用 `credential.helper`；需要登录时直接失败并跳过更新，继续本地启动 |

---

## 十五、风险提示

1. **无灰度**：所有用户同时看到更新，push 前必须充分测试
2. **无撤回**：bug 版本 push 后无法阻止已 pull 的用户，只能通过再 push 修复
3. **Alembic 迁移失败**：git pull 后如果迁移脚本有 bug，启动会失败。用户需手动 `git reset --hard HEAD@{1}` 回退。建议大版本升级前在 changelog 中强提示备份
4. **用户本地修改丢失风险**：stash pop 冲突时会丢弃用户修改。应在 UI 中明确提示
