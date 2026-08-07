# -*- coding: utf-8 -*-
"""
一体包 MySQL binlog 保留配置工具。

仅写 my.ini / my.cnf 配置文件，不执行任何 SQL（无 SET GLOBAL / PURGE）。
供 Windows/macOS 启动器与 package.py 共用。

TODO(deprecate): 启动器侧调用为存量迁移；新装依赖打包固化后，可删除 start_* 中的调用，
本模块仍可供 package.py 使用。
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, List, Optional, Tuple, Union

# 与 config.constant.MysqlBinlogConstants.EXPIRE_LOGS_SECONDS 保持一致
DEFAULT_EXPIRE_LOGS_SECONDS = 7 * 24 * 3600  # 604800，约 7 天

BINLOG_EXPIRE_KEY = "binlog_expire_logs_seconds"
# Comment written above the key when inserting/updating (English only; my.ini path encoding safety)
BINLOG_EXPIRE_COMMENT = (
    "# Keep binary logs for ~7 days to limit disk usage (MySQL auto_purge)"
)

MYSQL_CONFIG_FILENAMES = (
    "my.ini",
    "my.ini.template",
    "my.cnf",
    "my.cnf.template",
)


def _resolve_expire_seconds(expire_seconds: Optional[int] = None) -> int:
    if expire_seconds is not None:
        return int(expire_seconds)
    try:
        from config.constant import MysqlBinlogConstants

        return int(MysqlBinlogConstants.EXPIRE_LOGS_SECONDS)
    except Exception:
        return DEFAULT_EXPIRE_LOGS_SECONDS


def _is_section_header(stripped: str) -> bool:
    return stripped.startswith("[") and stripped.endswith("]") and len(stripped) >= 2


def _is_expire_key_line(stripped: str) -> bool:
    lower = stripped.lower()
    return lower.startswith(BINLOG_EXPIRE_KEY + "=") or lower.startswith(
        BINLOG_EXPIRE_KEY + " ="
    )


def ensure_mysql_binlog_retention(
    config_path: Union[str, Path],
    expire_seconds: Optional[int] = None,
) -> Tuple[bool, str]:
    """
    确保 MySQL 配置文件中存在 binlog_expire_logs_seconds=<expire>。

    - 已存在则规范为指定秒数
    - 不存在则写入 [mysqld] 段
    - 幂等；仅文件 IO

    Returns:
        (成功?, 说明信息)
    """
    path = Path(config_path)
    if not path.is_file():
        return False, f"配置文件不存在: {path}"

    seconds = _resolve_expire_seconds(expire_seconds)
    value_line = f"{BINLOG_EXPIRE_KEY}={seconds}"

    def _append_expire_block(target: List[str]) -> None:
        """Append English comment + expire key (avoid duplicate adjacent comment)."""
        if not target or target[-1].strip() != BINLOG_EXPIRE_COMMENT:
            target.append(BINLOG_EXPIRE_COMMENT)
        target.append(value_line)

    try:
        original = path.read_text(encoding="utf-8")
    except OSError as e:
        return False, f"读取失败 {path}: {e}"

    lines = original.splitlines()
    new_lines: List[str] = []
    found = False
    in_mysqld = False
    saw_mysqld = False

    for line in lines:
        stripped = line.strip()

        if _is_section_header(stripped):
            # 离开 [mysqld] 进入其它段时，若尚未写入则插在段前
            if in_mysqld and not found:
                _append_expire_block(new_lines)
                found = True
            in_mysqld = stripped.lower() == "[mysqld]"
            if in_mysqld:
                saw_mysqld = True
            new_lines.append(line)
            continue

        # Drop legacy Chinese / alternate comments immediately before our key
        if in_mysqld and stripped.startswith("#") and (
            "binlog" in stripped.lower()
            or "一体包" in stripped
            or "binary log" in stripped.lower()
        ):
            # Skip; English comment is re-added with the key
            continue

        if in_mysqld and _is_expire_key_line(stripped):
            if not found:
                _append_expire_block(new_lines)
                found = True
            # 丢弃重复的同名配置行
            continue

        new_lines.append(line)

    if not found:
        if saw_mysqld:
            _append_expire_block(new_lines)
        else:
            if new_lines and new_lines[-1].strip() != "":
                new_lines.append("")
            new_lines.append("[mysqld]")
            _append_expire_block(new_lines)

    new_content = "\n".join(new_lines)
    if original.endswith("\n") or original.endswith("\r\n"):
        new_content += "\n"

    if new_content.replace("\r\n", "\n") == original.replace("\r\n", "\n"):
        return True, f"已是最新 ({value_line}): {path}"

    try:
        path.write_text(new_content, encoding="utf-8")
    except OSError as e:
        return False, f"写入失败 {path}: {e}"

    return True, f"已写入 {value_line}: {path}"


def ensure_mysql_dir_binlog_retention(
    mysql_dir: Union[str, Path],
    expire_seconds: Optional[int] = None,
    filenames: Optional[Iterable[str]] = None,
) -> List[Tuple[Path, bool, str]]:
    """
    对 MySQL 安装目录下已知配置文件批量 ensure。

    Returns:
        [(path, ok, message), ...] 仅包含实际存在的文件
    """
    root = Path(mysql_dir)
    names = tuple(filenames) if filenames is not None else MYSQL_CONFIG_FILENAMES
    results: List[Tuple[Path, bool, str]] = []
    for name in names:
        cfg = root / name
        if cfg.is_file():
            ok, msg = ensure_mysql_binlog_retention(cfg, expire_seconds=expire_seconds)
            results.append((cfg, ok, msg))
    return results
