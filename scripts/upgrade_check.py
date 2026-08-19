#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
启动前检查更新脚本
由 start.bat / start.command / linux_start_prod.sh 在主程序启动前调用

通过监控远程 git tag 变化判断是否需要升级。
升级时执行 git stash -> git pull --ff-only -> git stash pop。

返回值：
  0 - 正常（已更新 / 无需更新 / 跳过），继续启动
  1 - 更新失败但可继续，使用本地版本
  2 - 严重错误，应暂停并提示用户
"""

import os
import subprocess
import sys
from pathlib import Path


# 确保项目根目录在 sys.path 中，以便 import config.config_util
_project_dir = Path(__file__).parent.parent.resolve()
if str(_project_dir) not in sys.path:
    sys.path.insert(0, str(_project_dir))

def get_project_dir() -> Path:
    """获取项目根目录"""
    return Path(__file__).parent.parent.resolve()


def find_git_binary():
    """查找 git 二进制

    Windows: 仅使用项目内置的 bin/git，不回退到系统 PATH
    macOS/Linux: 优先使用内置 git，找不到则回退到系统 PATH
    """
    project_dir = get_project_dir()

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

    # macOS/Linux: 回退到系统 PATH 中的 git
    if sys.platform != "win32":
        import shutil
        system_git = shutil.which("git")
        if system_git:
            return system_git

    return None


def get_upgrade_config():
    """读取升级相关配置

    优先使用 config_util 读取配置（如果可用）。
    如果 import 失败（如 Python 环境未就绪），回退到直接解析 YAML。
    """
    defaults = {
        "enabled": True,
        "repo_urls": [],       # 多源配置，按顺序尝试
        "branch": "main",
        "timeout_seconds": 30,
    }

    try:
        from config.config_util import get_config_value
        result = {}
        for key in defaults:
            result[key] = get_config_value("upgrade", key, default=defaults[key])
        return result
    except Exception:
        return _read_config_from_yaml(defaults)


def _read_config_from_yaml(defaults):
    """直接解析配置文件读取 upgrade 配置（回退方案）"""
    project_dir = get_project_dir()
    env = os.environ.get("comfyui_env", "dev")
    config_file = project_dir / f"config_{env}.yml"

    if not config_file.exists():
        base_file = project_dir / f"config_{env}.base.yaml"
        if base_file.exists():
            config_file = base_file
        else:
            return defaults

    try:
        import yaml
        with open(config_file, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}
        upgrade = config.get("upgrade", {})
        result = {}
        for key in defaults:
            result[key] = upgrade.get(key, defaults[key])
        return result
    except Exception:
        return defaults


def read_remote_binaries_config(git_cmd, project_dir, branch, timeout):
    """从远程仓库读取二进制依赖配置

    使用 git show 读取远程分支中的 config/required_binaries.yml 文件。
    返回: 配置字典，读取失败时返回空字典
    """
    rc, out, err = run_git(
        git_cmd,
        ["show", f"origin/{branch}:config/required_binaries.yml"],
        project_dir,
        timeout=timeout
    )

    if rc != 0:
        # 文件不存在或读取失败，返回空配置
        return {}

    try:
        import yaml
        return yaml.safe_load(out) or {}
    except ImportError:
        # PyYAML 不可用，跳过检查
        print("[upgrade] PyYAML 未安装，跳过二进制依赖检查")
        return {}
    except Exception as e:
        print(f"[upgrade] 解析二进制配置失败（忽略）: {e}")
        return {}


def check_binaries_for_version(project_dir, binaries_config, target_version):
    """检查目标版本需要的二进制依赖是否存在

    Args:
        project_dir: 项目目录
        binaries_config: 二进制配置（从 YAML 读取）
        target_version: 目标版本号

    Returns:
        缺失的二进制列表
    """
    if not binaries_config or not binaries_config.get("binaries"):
        return []

    # 平台映射
    platform_map = {
        "win32": "windows",
        "linux": "linux",
        "darwin": "macos",
    }
    current_platform = platform_map.get(sys.platform, "linux")

    missing = []
    for name, config in binaries_config["binaries"].items():
        # 检查版本要求
        required_since = config.get("required_since", "0.0.0")
        if compare_version(target_version, required_since) < 0:
            # 目标版本早于此依赖的最低要求版本，跳过
            continue

        # 检查文件是否存在
        check_paths = config.get("check_paths", {})
        check_path = check_paths.get(current_platform)

        if not check_path:
            continue

        full_path = project_dir / check_path
        if not full_path.exists():
            missing.append({
                "name": name,
                "description": config.get("description", ""),
                "download_url": config.get("download_url", ""),
            })

    return missing


def parse_version(v):
    """解析版本号为可比较的数字列表

    支持格式: "1.5.1", "v1.5.1", "1.5.1-beta"
    返回: [1, 5, 1]
    """
    v = v.lstrip("vV")
    num_part = v.split("-")[0]
    result = []
    for p in num_part.split("."):
        try:
            result.append(int(p))
        except ValueError:
            result.append(0)
    return result


def compare_version(v1, v2):
    """比较两个版本号

    返回:
        1  if v1 > v2
        -1 if v1 < v2
        0  if v1 == v2
    """
    p1, p2 = parse_version(v1), parse_version(v2)
    max_len = max(len(p1), len(p2))
    for i in range(max_len):
        a = p1[i] if i < len(p1) else 0
        b = p2[i] if i < len(p2) else 0
        if a != b:
            return 1 if a > b else -1
    return 0


def read_pyproject_version(project_dir):
    """从 pyproject.toml 读取 version 字段，失败返回 None。"""
    pyproject = project_dir / "pyproject.toml"
    if not pyproject.exists():
        return None
    try:
        content = pyproject.read_text(encoding="utf-8")
        for line in content.split("\n"):
            line = line.strip()
            if line.startswith("version"):
                parts = line.split("=", 1)
                if len(parts) == 2:
                    return parts[1].strip().strip('"').strip("'")
    except Exception:
        pass
    return None


def get_local_version(project_dir, git_cmd=None):
    """读取本地版本号

    同时收集以下候选，取版本号最高者（避免 describe 仍指向旧 tag、
    而 pyproject/HEAD 已是新版本时误判，导致 start.bat 无限重启）：
      1. git tag --points-at HEAD
      2. git describe --tags --abbrev=0
      3. pyproject.toml 的 version
    """
    candidates = []

    if git_cmd:
        # 1) 当前 commit 上的 tag
        rc, out, _ = run_git(
            git_cmd,
            ["tag", "--points-at", "HEAD"],
            project_dir, timeout=10
        )
        if rc == 0 and out.strip():
            for t in out.strip().split("\n"):
                t = t.strip()
                if t:
                    candidates.append(t)

        # 2) 最近祖先 tag（可能落后于当前代码里的 pyproject 版本）
        rc, out, _ = run_git(
            git_cmd,
            ["describe", "--tags", "--abbrev=0"],
            project_dir, timeout=10
        )
        if rc == 0 and out.strip():
            candidates.append(out.strip())

    # 3) 代码内声明的版本（reset 到含新 pyproject 的 commit 后应与远程一致）
    py_ver = read_pyproject_version(project_dir)
    if py_ver:
        candidates.append(py_ver)

    if not candidates:
        return "unknown"

    candidates.sort(key=parse_version, reverse=True)
    return candidates[0]


def get_git_env(git_cmd):
    """获取运行 git 命令时的环境变量

    如果使用内置 git，设置 GIT_SSL_CAINFO 指向内置的证书文件，
    避免使用系统证书导致的 SSL 错误。

    升级检查是无人值守流程：必须禁止 Git Credential Manager / askpass
    弹出 GUI 凭据框（部分用户访问 Gitee 时会卡住 start.bat）。
    需要登录时直接失败，由上层返回码 1 跳过更新、继续本地启动。

    注意：禁用 credential.helper 必须用 ``git -c credential.helper=``（见 run_git），
    不要用 ``GIT_CONFIG_VALUE_*=`` 空字符串——Windows/MinGit 会报
    ``missing config value GIT_CONFIG_VALUE_N`` / ``unable to parse command-line config``。
    """
    env = os.environ.copy()
    git_path = Path(git_cmd)
    project_dir = get_project_dir()

    # 检查是否是内置 git（路径在项目 bin 目录下）
    try:
        git_path.resolve().relative_to(project_dir / "bin")
        is_builtin = True
    except ValueError:
        is_builtin = False

    if is_builtin and sys.platform == "win32":
        # MinGit 的证书路径
        ca_bundle = project_dir / "bin" / "git" / "mingw64" / "etc" / "ssl" / "certs" / "ca-bundle.crt"
        if ca_bundle.exists():
            env["GIT_SSL_CAINFO"] = str(ca_bundle)

    # --- 非交互凭据：禁止 GCM/终端弹窗 ---
    # GIT_TERMINAL_PROMPT=0：git 自身不向终端要用户名密码
    # GCM_INTERACTIVE / GCM_GUI_PROMPT：关闭 Git Credential Manager 的 GUI
    # GIT_ASKPASS 置空：避免调用 askpass 弹窗程序
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GCM_INTERACTIVE"] = "false"
    env["GCM_GUI_PROMPT"] = "false"
    env["GIT_ASKPASS"] = ""
    env["SSH_ASKPASS"] = ""
    # 覆盖用户/系统环境中可能存在的 askpass 指向
    env.pop("GCM_ASKPASS", None)

    # 清除可能由父进程注入的 GIT_CONFIG_*，避免空 VALUE 导致 git 直接失败
    try:
        legacy_count = int(env.get("GIT_CONFIG_COUNT", "0") or "0")
    except ValueError:
        legacy_count = 0
    for i in range(max(legacy_count, 0) + 8):
        env.pop(f"GIT_CONFIG_KEY_{i}", None)
        env.pop(f"GIT_CONFIG_VALUE_{i}", None)
    env.pop("GIT_CONFIG_COUNT", None)

    return env


def run_git(git_cmd, args, cwd, timeout=30, capture=True):
    """运行 git 命令

    返回 (returncode, stdout, stderr)

    每条命令前注入 ``-c credential.helper=``，仅本进程禁用凭据助手
    （不改用户 .gitconfig），避免脏凭据/GCM 弹窗；空 helper 用 -c 而不是
    环境变量空串，兼容 Windows MinGit。
    """
    # -c 必须紧跟 git 可执行文件之后
    cmd = [git_cmd, "-c", "credential.helper="] + list(args)
    env = get_git_env(git_cmd)
    # Windows：隐藏可能的子进程控制台窗口（GCM 等）；不影响已有控制台输出
    popen_kwargs = {}
    if sys.platform == "win32":
        # CREATE_NO_WINDOW = 0x08000000，避免 credential helper 再开控制台
        popen_kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    try:
        if capture:
            result = subprocess.run(
                cmd,
                cwd=str(cwd),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                env=env,
                **popen_kwargs,
            )
            return result.returncode, result.stdout, result.stderr
        else:
            result = subprocess.run(
                cmd, cwd=str(cwd), timeout=timeout, env=env, **popen_kwargs
            )
            return result.returncode, "", ""
    except subprocess.TimeoutExpired:
        return -1, "", "timeout"
    except Exception as e:
        return -1, "", str(e)


def normalize_repo_url(url):
    """标准化仓库 URL，便于比较（去末尾 / 与 .git）"""
    if not url:
        return ""
    url = url.strip().rstrip("/")
    if url.endswith(".git"):
        url = url[:-4]
    return url


def is_auth_or_prompt_error(message):
    """判断是否为鉴权/交互凭据类错误（网络正常但无法匿名访问）"""
    if not message:
        return False
    lower = message.lower()
    needles = (
        "could not read username",
        "terminal prompts disabled",
        "authentication failed",
        "authentication required",
        "support for password authentication was removed",
        "invalid username or password",
        "403",
        "401",
        "access denied",
        "permission denied",
        "repository not found",  # 私有仓常见伪装
    )
    return any(n in lower for n in needles)


def fetch_remote_with_fallback(git_cmd, project_dir, repo_urls, branch, timeout):
    """fetch 远程分支与 tags；失败时按 repo_urls 顺序切换源重试。

    客户环境访问 Gitee 常因限流/鉴权挑战返回 401，若只 fetch 一次会误报失败。
    按配置多源依次尝试，任一成功即停止。

    返回 (success: bool, error_message: str)
    """
    urls_to_try = []
    current = get_current_remote_url(git_cmd, project_dir, timeout)
    if current:
        urls_to_try.append(current)
    for url in repo_urls or []:
        if not url:
            continue
        if not any(normalize_repo_url(url) == normalize_repo_url(u) for u in urls_to_try):
            urls_to_try.append(url)

    if not urls_to_try:
        return False, "未配置可用远程源"

    last_err = ""
    for idx, url in enumerate(urls_to_try):
        current_now = get_current_remote_url(git_cmd, project_dir, timeout)
        if normalize_repo_url(current_now or "") != normalize_repo_url(url):
            rc, _, err = run_git(
                git_cmd, ["remote", "set-url", "origin", url],
                project_dir, timeout=timeout
            )
            if rc != 0:
                # 无 origin 时 set-url 失败，尝试 add
                rc2, _, err2 = run_git(
                    git_cmd, ["remote", "add", "origin", url],
                    project_dir, timeout=timeout
                )
                if rc2 != 0:
                    last_err = err2 or err or "无法设置 origin"
                    print(f"[upgrade] 切换源失败 ({url}): {last_err}")
                    continue

        label = url
        if idx == 0 and len(urls_to_try) > 1:
            print(f"[upgrade] fetch 远程: {label}")
        elif len(urls_to_try) > 1:
            print(f"[upgrade] 尝试备用源: {label}")
        else:
            print(f"[upgrade] fetch 远程: {label}")

        rc, out, err = run_git(
            git_cmd, ["fetch", "origin", branch, "--tags", "--force"],
            project_dir, timeout=timeout
        )
        if rc == 0:
            if idx > 0:
                print(f"[upgrade] 已改用源: {url}")
            return True, ""

        last_err = (err or out or "未知错误").strip()
        if is_auth_or_prompt_error(last_err):
            print(f"[upgrade] 源需要登录或暂不可匿名访问，跳过: {url}")
        else:
            print(f"[upgrade] fetch 失败 ({url}): {last_err}")

    return False, last_err


def get_remote_latest_tag(git_cmd, project_dir, timeout):
    """获取远程最新的 tag 版本号

    使用 git ls-remote 获取远程所有 tag，本地排序找出最新的。
    过滤掉 peeled refs (^{}) 和非版本格式的 tag。
    """
    rc, out, _ = run_git(
        git_cmd, ["ls-remote", "--tags", "origin"],
        project_dir, timeout=timeout
    )
    if rc != 0 or not out.strip():
        return None

    tags = []
    for line in out.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        ref = parts[1]
        if not ref.startswith("refs/tags/"):
            continue
        tag = ref.replace("refs/tags/", "")
        # 过滤 peeled refs
        if tag.endswith("^{}"):
            continue
        # 只保留类似 v1.5.1 或 1.5.1 的 tag（至少有一个点号）
        clean = tag.lstrip("vV").split("-")[0]
        if "." in clean:
            tags.append(tag)

    if not tags:
        return None

    tags.sort(key=parse_version, reverse=True)
    return tags[0]


def init_git_repo(project_dir, git_cmd, repo_urls, branch, timeout):
    """首次启动：.git 不存在，自动初始化

    支持多源 fallback，按顺序尝试每个源。
    """
    print("[upgrade] 首次运行，初始化 git 仓库...")

    # git init 只需执行一次
    rc, _, err = run_git(git_cmd, ["init"], project_dir, timeout=timeout)
    if rc != 0:
        print(f"[upgrade] git init 失败: {err}")
        return False

    # 尝试每个源
    for url in repo_urls:
        print(f"[upgrade] 尝试源: {url}")

        # 清除已有的 remote（如果有）
        run_git(git_cmd, ["remote", "remove", "origin"], project_dir, timeout=10)

        # 添加 remote
        rc, _, err = run_git(
            git_cmd, ["remote", "add", "origin", url],
            project_dir, timeout=timeout
        )
        if rc != 0:
            print(f"[upgrade] 添加远程仓库失败: {err}")
            continue

        # fetch
        rc, _, err = run_git(
            git_cmd, ["fetch", "origin", branch, "--depth", "1", "--tags", "--force"],
            project_dir, timeout=timeout
        )
        if rc != 0:
            print(f"[upgrade] fetch 失败: {err}")
            continue

        # reset（Windows 下需处理 enterprise/*.pyd 占用）
        quarantine_locked_native_binaries(project_dir)
        rc, _, err = _hard_reset_with_unlink_retry(
            git_cmd, project_dir, f"origin/{branch}", timeout
        )
        if rc != 0:
            print(f"[upgrade] reset 失败: {err}")
            continue

        print(f"[upgrade] 初始化完成，使用源: {url}")
        return True

    print("[upgrade] 所有源都失败，无法初始化")
    return False



def is_windows_unlink_error(message: str) -> bool:
    """识别 Windows 下 git 无法删除被占用文件的典型错误。"""
    if not message:
        return False
    lower = message.lower()
    return (
        "unable to unlink old" in lower
        or "invalid argument" in lower
        or "permission denied" in lower
    )


def quarantine_locked_native_binaries(project_dir: Path) -> list:
    """在 git reset 前移走可能被占用的原生扩展（.pyd/.dll）。

    Windows 会锁定已加载的 DLL/.pyd：即便主程序看似未启动，残留的
    scheduler / python 进程或杀毒扫描也会导致::

        error: unable to unlink old 'enterprise/.../pyarmor_runtime.pyd': Invalid argument

    对占用中的文件，**重命名通常仍可成功**（删除会失败）。把旧文件挪开后，
    git 即可在原路径写入新版本。quarantine 文件可在下次启动或手动清理。
    """
    import time

    moved = []
    if sys.platform != "win32":
        return moved

    project_dir = Path(project_dir).resolve()
    skip_dir_names = {
        ".git", ".venv", "venv", "bin", "node_modules", "__pycache__",
        ".pytest_cache", "dist",
    }
    stamp = f"{os.getpid()}_{int(time.time())}"

    candidates = []
    # 优先 enterprise（PyArmor runtime），再扫其余目录中的 .pyd
    search_roots = [project_dir / "enterprise", project_dir]
    seen = set()
    for root in search_roots:
        if not root.is_dir():
            continue
        for pattern in ("*.pyd",):
            for path in root.rglob(pattern):
                try:
                    rel_parts = path.relative_to(project_dir).parts
                except ValueError:
                    continue
                if any(part in skip_dir_names for part in rel_parts):
                    continue
                if ".pending_unlink_" in path.name:
                    continue
                key = str(path.resolve()).lower()
                if key in seen:
                    continue
                seen.add(key)
                candidates.append(path)

    for path in candidates:
        dest = path.with_name(f"{path.name}.pending_unlink_{stamp}")
        try:
            os.replace(str(path), str(dest))
            rel = str(path.relative_to(project_dir))
            moved.append(rel)
        except OSError as e:
            print(f"[upgrade] 无法移走可能被占用的文件 {path.name}: {e}")

    if moved:
        print(
            f"[upgrade] 已临时移走 {len(moved)} 个原生库文件以便覆盖更新"
            f"（常见于 Windows 下 pyarmor_runtime.pyd 仍被进程占用）"
        )
    return moved


def _hard_reset_with_unlink_retry(git_cmd, project_dir, rev, timeout):
    """执行 git reset --hard，Windows 占用失败时移走 .pyd 后重试一次。"""
    rc, out, err = run_git(
        git_cmd, ["reset", "--hard", rev],
        project_dir, timeout=timeout
    )
    if rc == 0:
        return rc, out, err

    combined = f"{err or ''}\n{out or ''}"
    if sys.platform == "win32" and is_windows_unlink_error(combined):
        print(
            "[upgrade] 检测到文件占用（多为 enterprise/.../pyarmor_runtime.pyd），"
            "尝试移走后重试..."
        )
        print(
            "[upgrade] 提示: 请确认已关闭所有本程序窗口/托盘进程后再升级；"
            "若仍失败，可在任务管理器结束残留 python/pythonw 后重试"
        )
        quarantine_locked_native_binaries(project_dir)
        rc, out, err = run_git(
            git_cmd, ["reset", "--hard", rev],
            project_dir, timeout=timeout
        )
    return rc, out, err


def perform_update(git_cmd, project_dir, branch, timeout, target_tag=None):
    """执行更新（强制覆盖本地代码）

    使用 fetch + reset --hard 强制同步。
    优先 reset 到目标版本 tag（与远程「最新 tag」比较逻辑一致），
    tag 不可用时再回退到 origin/{branch}。
    不保留本地修改，确保升级过程无冲突，对小白用户透明。
    返回 (success, message)
    """
    # fetch 分支 + tags（必须带 tags，否则本地 describe/checkout tag 会落后）
    rc, out, err = run_git(
        git_cmd, ["fetch", "origin", branch, "--tags", "--force"],
        project_dir, timeout=timeout
    )
    if rc != 0:
        msg = err or out or "未知错误"
        return False, f"fetch 失败: {msg}"

    # Windows：先主动移走可能被占用的 .pyd，降低 reset 失败概率
    quarantine_locked_native_binaries(project_dir)

    # 优先对齐到版本 tag，使 tag --points-at HEAD 与远程最新 tag 一致
    if target_tag:
        rc, out, err = _hard_reset_with_unlink_retry(
            git_cmd, project_dir, target_tag, timeout
        )
        if rc == 0:
            print(f"[upgrade] 代码更新成功（已对齐 tag {target_tag}）")
            return True, ""
        print(f"[upgrade] 无法 checkout tag {target_tag}，回退到 origin/{branch}: {err or out}")

    # reset 到远程分支（强制覆盖）
    rc, out, err = _hard_reset_with_unlink_retry(
        git_cmd, project_dir, f"origin/{branch}", timeout
    )
    if rc != 0:
        msg = err or out or "未知错误"
        if is_windows_unlink_error(msg):
            msg = (
                f"{msg}\n"
                "  原因: Windows 无法覆盖正在使用的 .pyd（如 pyarmor_runtime.pyd）。\n"
                "  处理: 关闭所有本程序实例后重新运行 start.bat；"
                "或在任务管理器结束 python.exe / pythonw.exe 后重试。"
            )
        return False, f"reset 失败: {msg}"

    print("[upgrade] 代码更新成功")
    return True, ""



def check_requirements_changed(git_cmd, project_dir, timeout):
    """检查 requirements.txt 是否有变化"""
    rc, out, _ = run_git(
        git_cmd, ["diff", "--name-only", "HEAD@{1}", "HEAD"],
        project_dir, timeout=timeout
    )
    if rc == 0 and out:
        if "requirements.txt" in out:
            print("[upgrade] 注意：依赖有更新，启动时将自动安装")



def get_current_remote_url(git_cmd, project_dir, timeout):
    """获取当前 origin 的 URL"""
    rc, out, _ = run_git(
        git_cmd, ["remote", "get-url", "origin"],
        project_dir, timeout=timeout
    )
    if rc == 0 and out.strip():
        return out.strip()
    return None


def update_remote_url_if_needed(git_cmd, project_dir, repo_urls, timeout):
    """检查并更新 origin URL

    优先使用 repo_urls 中第一个源（最高优先级）。
    如果当前 origin 不是第一个源，尝试切换过去。
    如果最高优先级源不可用，降级接受当前已在列表中的源。
    返回 True 表示 origin URL 有效（无需更新或更新成功）。
    """
    current_url = get_current_remote_url(git_cmd, project_dir, timeout)

    if not current_url:
        # 没有 origin，添加第一个源
        if repo_urls:
            rc, _, err = run_git(
                git_cmd, ["remote", "add", "origin", repo_urls[0]],
                project_dir, timeout=timeout
            )
            if rc == 0:
                print(f"[upgrade] 添加 origin: {repo_urls[0]}")
                return True
            print(f"[upgrade] 添加 origin 失败: {err}")
        return False

    current_normalized = normalize_repo_url(current_url)
    first_url_normalized = normalize_repo_url(repo_urls[0]) if repo_urls else None

    # 当前已经是最高优先级源：不在这里做连通性探测。
    # 真正的 fetch 由 fetch_remote_with_fallback 负责多源回退，
    # 避免「origin 已是 Gitee 但匿名 401」时在此直接判定成功、随后单点失败。
    if first_url_normalized and current_normalized == first_url_normalized:
        return True

    # 尝试切换到最高优先级源
    if repo_urls:
        first_url = repo_urls[0]
        rc, _, err = run_git(
            git_cmd, ["remote", "set-url", "origin", first_url],
            project_dir, timeout=timeout
        )
        if rc == 0:
            rc, _, _ = run_git(
                git_cmd, ["ls-remote", "--heads", "origin"],
                project_dir, timeout=timeout
            )
            if rc == 0:
                print(f"[upgrade] 已切换到优先源: {first_url}")
                return True
            else:
                # 最高优先级源不可用，恢复原 URL
                print(f"[upgrade] 优先源 {first_url} 不可用，保持当前源")
                run_git(
                    git_cmd, ["remote", "set-url", "origin", current_url],
                    project_dir, timeout=timeout
                )

    # 检查当前 origin 是否在配置列表中（降级接受）
    for url in repo_urls:
        if normalize_repo_url(url) == current_normalized:
            return True

    # 当前 origin 不在配置中，按顺序找第一个可用的
    print(f"[upgrade] 当前 origin ({current_url}) 不在配置的源中")
    for url in repo_urls[1:]:  # 跳过第一个（已尝试过）
        rc, _, err = run_git(
            git_cmd, ["remote", "set-url", "origin", url],
            project_dir, timeout=timeout
        )
        if rc == 0:
            rc, _, _ = run_git(
                git_cmd, ["ls-remote", "--heads", "origin"],
                project_dir, timeout=timeout
            )
            if rc == 0:
                print(f"[upgrade] 已更新 origin: {url}")
                return True
            else:
                print(f"[upgrade] 源 {url} 不可用，尝试下一个")

    print("[upgrade] 所有配置的源都不可用")
    return False


def main():
    """主入口"""
    project_dir = get_project_dir()

    cfg = get_upgrade_config()

    if not cfg.get("enabled", True):
        print("[upgrade] 已禁用")
        return 0

    branch = cfg.get("branch", "main")
    timeout = cfg.get("timeout_seconds", 30)
    repo_urls = cfg.get("repo_urls", [])

    git_cmd = find_git_binary()
    if not git_cmd:
        print("[upgrade] 未找到 git，跳过更新检查")
        return 0

    git_dir = project_dir / ".git"

    if not git_dir.exists():
        if not repo_urls:
            print("[upgrade] 未配置仓库地址，跳过更新检查")
            print("[upgrade] 提示：如需自动更新，请在配置中设置 upgrade.repo_urls")
            return 0

        if not init_git_repo(project_dir, git_cmd, repo_urls, branch, timeout):
            print("[upgrade] 初始化失败，使用本地版本")
            return 1

        return 0


    # 1. 检查并更新 origin URL
    if not repo_urls:
        print("[upgrade] 未配置仓库地址，跳过更新检查")
        return 0

    if not update_remote_url_if_needed(git_cmd, project_dir, repo_urls, timeout):
        print("[upgrade] 无法设置有效的远程源，跳过更新检查")
        return 0

    # 2. 读取本地版本（优先 git tag，回退 pyproject.toml）
    local_version = get_local_version(project_dir, git_cmd)
    print(f"[upgrade] 当前版本: {local_version}")

    # 3. fetch 远程（包含 tag）；Gitee 限流/鉴权失败时自动尝试备用源（如 GitHub）
    ok, err = fetch_remote_with_fallback(
        git_cmd, project_dir, repo_urls, branch, timeout
    )
    if not ok:
        if is_auth_or_prompt_error(err):
            print(
                "[upgrade] 远程仓库暂时无法匿名访问（可能限流或需登录），"
                "跳过更新检查，继续使用本地版本"
            )
        else:
            print(f"[upgrade] 所有远程源均不可用，跳过更新检查: {err}")
        return 1

    # 4. 获取远程最新 tag
    latest_tag = get_remote_latest_tag(git_cmd, project_dir, timeout)
    if not latest_tag:
        print("[upgrade] 远程无可用版本 tag，跳过更新检查")
        return 0

    print(f"[upgrade] 远程最新版本: {latest_tag}")

    # 5. 比较版本
    cmp = compare_version(latest_tag, local_version)
    if cmp <= 0:
        if cmp == 0:
            print("[upgrade] 已是最新版本")
        else:
            print(f"[upgrade] 本地版本 ({local_version}) 高于远程 ({latest_tag})，无需更新")
        return 0

    # 6. 发现新版本，开始更新
    print(f"[upgrade] 发现新版本: {local_version} -> {latest_tag}")
    print("[upgrade] 开始更新...")

    # 7. 检查二进制依赖（从仓库配置文件读取）
    binaries_config = read_remote_binaries_config(git_cmd, project_dir, branch, timeout)
    missing = check_binaries_for_version(project_dir, binaries_config, latest_tag)
    if missing:
        print(f"\n[upgrade] ⚠ 新版本 {latest_tag} 需要以下二进制依赖，但本地缺失:")
        for b in missing:
            url = b.get('download_url', '无')
            print(f"  - {b['name']}: {b.get('description', '')}")
            print(f"    下载地址: {url}")
        print(f"\n[upgrade] 跳过自动更新，请先下载上述文件后再升级")
        print("[upgrade] 使用当前版本继续启动...")
        return 0

    # 8. 执行更新（优先对齐到远程最新 tag，避免只 reset 分支导致版本标记永远落后）
    success, message = perform_update(
        git_cmd, project_dir, branch, timeout, target_tag=latest_tag
    )
    if not success:
        print(f"[upgrade] 更新失败: {message}")
        return 1

    if message:
        print(f"[upgrade] 警告: {message}")

    # 9. 检查依赖变化
    check_requirements_changed(git_cmd, project_dir, timeout)

    # 10. 防无限重启：更新后若版本比较仍认为落后，说明 tag/pyproject/分支不一致，
    #     再返回 10 会让 start.bat 死循环（用户可见「不断重新启动」）
    new_local = get_local_version(project_dir, git_cmd)
    if compare_version(latest_tag, new_local) > 0:
        print(
            f"[upgrade] 警告: 更新后本地版本仍为 {new_local}（远程 {latest_tag}），"
            f"为避免启动循环将继续启动当前代码"
        )
        return 0

    print("[upgrade] 更新完成，需要重新启动...")
    return 10  # 特殊码：代码已更新，需要重启 start.bat


if __name__ == "__main__":
    sys.exit(main())
