# -*- coding: utf-8 -*-
"""历史缺陷清单的读取，以及把「改坏补丁」打进一份代码副本。"""
from __future__ import annotations

import json
from pathlib import Path


class ReplayError(Exception):
    """补丁对不上当前代码，或清单写坏了。"""


def parse_front_matter(text: str) -> dict:
    """读取条目顶部的简单字段。只支持 `key: value` 和 `key:` 下面的 `- item`。"""
    normalized = text.replace("\r\n", "\n")
    if not normalized.startswith("---\n"):
        raise ReplayError("清单条目缺少开头的 ---")
    end = normalized.find("\n---", 4)
    if end < 0:
        raise ReplayError("清单条目缺少结束的 ---")
    header = normalized[4:end]
    data = {
        "id": "",
        "patch": "",
        "tests": [],
        "replay_tests": [],
        "feature_ids": [],
    }
    current_list = None
    for raw_line in header.split("\n"):
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("- "):
            if current_list is None:
                raise ReplayError(f"列表项没有字段名: {line}")
            data[current_list].append(line[2:].strip())
            continue
        if ":" not in line:
            raise ReplayError(f"无法识别的清单行: {line}")
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        if value == "":
            data[key] = []
            current_list = key
            continue
        data[key] = value
        current_list = None
    return data


def load_entries(directory: Path) -> list[dict]:
    entries = []
    if not directory.is_dir():
        return entries
    for path in sorted(directory.glob("*.md")):
        if path.name.lower() == "readme.md":
            continue
        text = path.read_text(encoding="utf-8-sig")
        fields = parse_front_matter(text)
        fields["path"] = path
        if not fields.get("id"):
            fields["id"] = path.stem
        entries.append(fields)
    return entries


def feature_ids(directory: Path) -> set[str]:
    found = set()
    for entry in load_entries(directory):
        for feature_id in entry.get("feature_ids") or []:
            if feature_id:
                found.add(feature_id)
    return found


def load_patch(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise ReplayError(f"补丁不是合法 JSON: {path}") from exc
    if not isinstance(data, dict):
        raise ReplayError(f"补丁必须是对象: {path}")
    data.setdefault("replaces", [])
    data.setdefault("creates", [])
    return data


def replace_once(text: str, old: str, new: str) -> str:
    """把 old 换成 new，必须恰好出现一次。换行符按文件自身的风格写回。"""
    old_n = old.replace("\r\n", "\n")
    new_n = new.replace("\r\n", "\n")
    use_crlf = "\r\n" in text
    haystack = text.replace("\r\n", "\n") if use_crlf else text
    count = haystack.count(old_n)
    if count != 1:
        raise ReplayError(f"期望恰好匹配 1 处，实际 {count} 处")
    updated = haystack.replace(old_n, new_n, 1)
    if use_crlf:
        updated = updated.replace("\n", "\r\n")
    return updated


def _inside(root: Path, path: Path) -> None:
    resolved_root = root.resolve()
    resolved = path.resolve()
    if resolved != resolved_root and resolved_root not in resolved.parents:
        raise ReplayError(f"补丁路径越出目录: {path}")


def apply_patch(root: Path, patch: dict) -> None:
    for item in patch.get("replaces") or []:
        rel = item.get("path") or ""
        target = root / rel
        _inside(root, target)
        if not target.is_file():
            raise ReplayError(f"要修改的文件不存在: {rel}")
        original = target.read_text(encoding="utf-8")
        try:
            updated = replace_once(original, item.get("old") or "", item.get("new") or "")
        except ReplayError as exc:
            raise ReplayError(f"{rel}: {exc}") from exc
        target.write_text(updated, encoding="utf-8", newline="")
    for item in patch.get("creates") or []:
        rel = item.get("path") or ""
        target = root / rel
        _inside(root, target)
        if target.exists():
            raise ReplayError(f"补丁要新建的文件已经存在: {rel}")
        target.parent.mkdir(parents=True, exist_ok=True)
        content = item.get("content") or ""
        if not content.endswith("\n"):
            content += "\n"
        target.write_text(content, encoding="utf-8", newline="\n")
