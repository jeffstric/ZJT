# -*- coding: utf-8 -*-
"""回归清单解析、改坏补丁能否对上当前代码、导航跳过已有永久测试。"""
import importlib.util
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.testing.regression_catalog import (
    ReplayError,
    apply_patch,
    feature_ids,
    load_entries,
    load_patch,
    replace_once,
)
from scripts.testing.run_bug_replay import _classify_patched


def _load_navigator():
    path = ROOT / "auto_test" / "test_navigator.py"
    spec = importlib.util.spec_from_file_location("test_navigator", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_replace_once_keeps_crlf():
    text = "alpha\r\nbeta\r\n"
    updated = replace_once(text, "beta", "BETA")
    assert updated == "alpha\r\nBETA\r\n"


def _workdir():
    base = Path(ROOT.anchor) / "tmp" / "comfyui-bug-replay-tests"
    base.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix="case-", dir=str(base)))


def test_replace_once_rejects_zero_and_two():
    try:
        replace_once("abc", "z", "Z")
    except ReplayError as exc:
        assert "0" in str(exc)
    else:
        raise AssertionError("没有匹配时应该失败")
    try:
        replace_once("aa", "a", "b")
    except ReplayError as exc:
        assert "2" in str(exc)
    else:
        raise AssertionError("匹配两次时应该失败")


def test_apply_patch_replaces_and_creates():
    tmp_path = _workdir()
    try:
        _apply_patch_case(tmp_path)
    finally:
        shutil.rmtree(tmp_path, ignore_errors=True)


def _apply_patch_case(tmp_path):
    target = tmp_path / "api" / "user.py"
    target.parent.mkdir()
    target.write_text("keep\n@router.get(\"/x\")\nkeep\n", encoding="utf-8")
    apply_patch(tmp_path, {
        "replaces": [{
            "path": "api/user.py",
            "old": "@router.get(\"/x\")\n",
            "new": "",
        }],
        "creates": [{
            "path": "task/new_bug.py",
            "content": "def bad():\n    return 1\n",
        }],
    })
    assert "@router.get" not in target.read_text(encoding="utf-8")
    assert (tmp_path / "task" / "new_bug.py").is_file()


def test_catalog_feature_ids_and_pilot_patches_match_source():
    catalog = ROOT / "tests" / "regressions"
    entries = load_entries(catalog)
    ids = {entry["id"] for entry in entries}
    assert "2026-10-21-sse-silent-stall" in ids
    assert "ai-tools-status-cas" in ids
    assert "power-budget-route-missing" in ids
    assert feature_ids(catalog) == set()

    matched = 0
    for entry in entries:
        raw = entry.get("patch") or ""
        if not isinstance(raw, str) or not raw.strip():
            continue
        patch = load_patch(catalog / raw)
        for item in patch.get("replaces") or []:
            text = (ROOT / item["path"]).read_text(encoding="utf-8").replace("\r\n", "\n")
            assert text.count(item["old"].replace("\r\n", "\n")) == 1
            matched += 1
        for item in patch.get("creates") or []:
            assert not (ROOT / item["path"]).exists()
            matched += 1
    assert matched == 5


def test_classify_patched_result():
    assert _classify_patched(0, False) == "blind"
    assert _classify_patched(1, False) == "caught"
    assert _classify_patched(0, True) == "caught"
    assert _classify_patched(5, False) == "infra"


def test_navigator_skips_feature_with_permanent_test():
    tmp_path = _workdir()
    try:
        _navigator_case(tmp_path)
    finally:
        shutil.rmtree(tmp_path, ignore_errors=True)


def _navigator_case(tmp_path):
    sessions = tmp_path / "test_sessions"
    sessions.mkdir()
    session = {
        "modules": [{
            "id": "auth",
            "name": "认证",
            "features": [
                {
                    "id": "auth_done",
                    "name": "已有永久测试",
                    "pass": False,
                    "test_steps": [{"step": 1, "pass": False, "is_processed": False, "action": "点"}],
                },
                {
                    "id": "auth_next",
                    "name": "还要测",
                    "pass": False,
                    "test_steps": [{"step": 1, "pass": False, "is_processed": False, "action": "再点"}],
                },
            ],
        }]
    }
    (sessions / "session_1.json").write_text(
        json.dumps(session, ensure_ascii=False), encoding="utf-8")
    regressions = tmp_path / "regressions"
    regressions.mkdir()
    (regressions / "auth-done.md").write_text(
        "---\nid: auth-done\npatch:\ntests:\nreplay_tests:\nfeature_ids:\n  - auth_done\n---\n\n## 当时坏成什么样\n\nx\n",
        encoding="utf-8",
    )
    navigator = _load_navigator().TestNavigator(
        base_dir=str(tmp_path), regressions_dir=str(regressions))
    nxt = navigator.get_next_test()
    assert nxt["feature_id"] == "auth_next"
