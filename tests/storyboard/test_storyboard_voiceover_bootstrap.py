"""StoryboardVoiceoverBootstrapService 测试。

覆盖方案 docs/storyboard/storyboard_auto_voiceover_after_split_design.md §15：
- 根因回归：ensure_for_split_task 后产生 ai_audio + tasks + dialogue_audio + selected
- 原子性：四步任一步异常 → 回滚 → 无孤儿
- 幂等：同一 dialogue 连续调两次 → 一条任务链
- 业务分类：empty_text / missing_reference_audio / narration_without_voice
- 不覆盖：已有选中配音 → reused
"""
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.constant import (
    AI_AUDIO_STATUS_PENDING,
    AI_AUDIO_STATUS_FAILED,
    TASK_TYPE_GENERATE_AUDIO,
    TASK_STATUS_QUEUED,
    StoryboardAudioGenerateConstants,
)
from services.storyboard_voiceover_bootstrap_service import (
    StoryboardVoiceoverBootstrapService,
)


# ---------------------------------------------------------------------------
# 辅助：构造一个能记录所有事务内操作的 fake conn + transaction
# ---------------------------------------------------------------------------

class _FakeCursor:
    """模拟 DictCursor：记录 execute 的 SQL/params，返回预设行。"""

    def __init__(self, store):
        self._store = store

    def execute(self, sql, params=None):
        self._store["executed"].append((sql, params or ()))

    def fetchone(self):
        return self._store.get("fetchone_result")

    def fetchall(self):
        return self._store.get("fetchall_result") or []

    @property
    def lastrowid(self):
        return self._store.get("lastrowid", 1)


class _FakeConn:
    def __init__(self, store):
        self._store = store

    def cursor(self):
        return _FakeCursor(self._store)

    def commit(self):
        self._store["committed"] = True

    def rollback(self):
        self._store["rolled_back"] = True


@pytest.fixture
def voiceover_service(monkeypatch):
    """构造带 mock 的 service，并捕获事务内的 model 调用。"""
    svc = StoryboardVoiceoverBootstrapService()
    calls = {
        "audio_create": [],
        "task_create": [],
        "da_create": [],
        "set_selected": [],
        "executed": [],        # 事务内 cursor.execute 的原始 SQL/params
        "fetchone_result": None,
        "fetchall_result": None,
        "lastrowid": 500,      # ai_audio / tasks / dialogue_audio 的自增 id 基线
        "committed": False,
        "rolled_back": False,
    }
    # 让每次 create_in_transaction 返回递增 id
    _counter = {"v": 500}

    def _next_id():
        _counter["v"] += 1
        return _counter["v"]

    monkeypatch.setattr(
        "services.storyboard_voiceover_bootstrap_service.transaction",
        lambda: _ctx_mgr(calls),
        raising=True,
    )
    monkeypatch.setattr(
        "services.storyboard_voiceover_bootstrap_service.execute_query_in_transaction",
        lambda conn, sql, params=None, fetch_one=False: (
            calls["fetchone_result"] if fetch_one else (calls["fetchall_result"] or [])
        ),
        raising=True,
    )
    # mock 三个 model 的事务变体
    from model import ai_audio as ai_audio_mod
    from model import tasks as tasks_mod
    from model import storyboard_dialogue_audio as da_mod

    def _audio_create_txn(conn, **kwargs):
        calls["audio_create"].append(kwargs)
        return 501

    def _task_create_txn(conn, **kwargs):
        calls["task_create"].append(kwargs)
        return 601

    def _da_create_txn(conn, **kwargs):
        calls["da_create"].append(kwargs)
        return 301

    def _set_selected_txn(conn, dialogue_id, dialogue_audio_id):
        calls["set_selected"].append((dialogue_id, dialogue_audio_id))
        return 1

    monkeypatch.setattr(ai_audio_mod.AIAudioModel, "create_in_transaction", _audio_create_txn)
    monkeypatch.setattr(tasks_mod.TasksModel, "create_in_transaction", _task_create_txn)
    monkeypatch.setattr(da_mod.StoryboardDialogueAudioModel, "create_in_transaction", _da_create_txn)
    monkeypatch.setattr(da_mod.StoryboardDialogueAudioModel, "set_selected_in_transaction", _set_selected_txn)

    return svc, calls


import contextlib


@contextlib.contextmanager
def _ctx_mgr(store):
    """模拟 transaction()：yield fake conn，正常退出 commit，异常 rollback。"""
    conn = _FakeConn(store)
    try:
        yield conn
        store["committed"] = True
    except Exception:
        store["rolled_back"] = True
        raise


# ---------------------------------------------------------------------------
# 测试：_submit_dialogue_voiceover_atomically
# ---------------------------------------------------------------------------

def _setup_dialogue(monkeypatch, svc, *, selected_audio_id=None, text="你好", character_id=17):
    """mock StoryboardDialogueModel.get_by_id + CharacterModel.get_by_id。"""
    dialogue = SimpleNamespace(
        id=101, scene_id=201, character_id=character_id, text=text,
        selected_audio_id=selected_audio_id,
    )
    character = SimpleNamespace(id=17, default_voice="/upload/voice/a.wav")
    monkeypatch.setattr(
        "services.storyboard_voiceover_bootstrap_service.StoryboardDialogueModel",
        SimpleNamespace(get_by_id=lambda _id: dialogue),
    )
    monkeypatch.setattr(
        "services.storyboard_voiceover_bootstrap_service.CharacterModel",
        SimpleNamespace(get_by_id=lambda _id: character),
    )
    return dialogue


def test_submit_atomically_creates_full_task_chain(voiceover_service, monkeypatch):
    """根因回归：单条提交产生 ai_audio + tasks + dialogue_audio + set_selected 四步。"""
    svc, calls = voiceover_service
    _setup_dialogue(monkeypatch, svc)

    # FOR UPDATE 返回 selected_audio_id 为空（需要创建）
    calls["fetchone_result"] = {"id": 101, "selected_audio_id": None}

    result = svc.ensure_dialogue_voiceover(101, 7)

    assert result["decision"] == "submitted"
    assert result["audio_id"] == 501
    assert result["dialogue_audio_id"] == 301
    # 四步都执行
    assert len(calls["audio_create"]) == 1
    assert calls["audio_create"][0]["text"] == "你好"
    assert calls["audio_create"][0]["ref_path"] == "/upload/voice/a.wav"
    assert len(calls["task_create"]) == 1
    assert calls["task_create"][0]["task_type"] == TASK_TYPE_GENERATE_AUDIO
    assert calls["task_create"][0]["task_id"] == 501
    assert calls["task_create"][0]["status"] == TASK_STATUS_QUEUED
    assert len(calls["da_create"]) == 1
    assert calls["da_create"][0]["dialogue_id"] == 101
    assert calls["da_create"][0]["ai_audio_id"] == 501
    assert calls["set_selected"] == [(101, 301)]
    # 事务提交，未回滚
    assert calls["committed"] is True
    assert calls["rolled_back"] is False


def test_submit_atomically_idempotent_when_already_selected(voiceover_service, monkeypatch):
    """幂等：已有选中配音 → reused，不创建新任务链。"""
    svc, calls = voiceover_service
    _setup_dialogue(monkeypatch, svc, selected_audio_id=999)

    # FOR UPDATE 返回已选中 + 该 dialogue_audio 有效（有 audio_url）
    calls["fetchone_result"] = {"id": 101, "selected_audio_id": 999}
    # _check_selected_audio 内部查询 dialogue_audio
    da_query_result = {"ai_audio_id": 501, "audio_url": "http://x/y.wav"}
    ai_query_result = {"status": AI_AUDIO_STATUS_PENDING}

    # mock execute_query_in_transaction 的多次调用（先 FOR UPDATE，再 check）
    call_count = {"n": 0}
    results = [calls["fetchone_result"], da_query_result, ai_query_result]

    def _fake_query(conn, sql, params=None, fetch_one=False):
        idx = call_count["n"]
        call_count["n"] += 1
        return results[idx] if fetch_one else []

    import services.storyboard_voiceover_bootstrap_service as svc_mod
    monkeypatch.setattr(svc_mod, "execute_query_in_transaction", _fake_query)

    result = svc.ensure_dialogue_voiceover(101, 7)

    assert result["decision"] == "reused"
    # 没有创建任何新记录
    assert len(calls["audio_create"]) == 0
    assert len(calls["task_create"]) == 0
    assert len(calls["da_create"]) == 0
    assert calls["set_selected"] == []


def test_submit_atomically_skips_empty_text(voiceover_service, monkeypatch):
    """业务分类：台词为空 → skipped(empty_text)，不进事务。"""
    svc, calls = voiceover_service
    _setup_dialogue(monkeypatch, svc, text="   ")

    result = svc.ensure_dialogue_voiceover(101, 7)

    assert result["decision"] == "skipped"
    assert result["reason"] == StoryboardAudioGenerateConstants.SKIP_REASON_EMPTY_TEXT
    # 没进事务（fetchone 没被调，四步都没执行）
    assert len(calls["audio_create"]) == 0


def test_submit_atomically_skips_missing_reference_audio(voiceover_service, monkeypatch):
    """业务分类：角色无 default_voice → skipped(missing_reference_audio)。"""
    svc, calls = voiceover_service
    _setup_dialogue(monkeypatch, svc)
    # 角色无声音
    monkeypatch.setattr(
        "services.storyboard_voiceover_bootstrap_service.CharacterModel",
        SimpleNamespace(get_by_id=lambda _id: SimpleNamespace(id=17, default_voice=None)),
    )

    result = svc.ensure_dialogue_voiceover(101, 7)

    assert result["decision"] == "skipped"
    assert result["reason"] == StoryboardAudioGenerateConstants.SKIP_REASON_MISSING_REFERENCE_AUDIO
    assert len(calls["audio_create"]) == 0


def test_submit_atomically_skips_narration_without_voice(voiceover_service, monkeypatch):
    """业务分类：旁白无 character_id 且无 ref_path → skipped(narration_without_voice)。"""
    svc, calls = voiceover_service
    # character_id=None 的旁白
    _setup_dialogue(monkeypatch, svc, character_id=None)

    result = svc.ensure_dialogue_voiceover(101, 7)

    assert result["decision"] == "skipped"
    assert result["reason"] == StoryboardAudioGenerateConstants.SKIP_REASON_NARRATION_WITHOUT_VOICE
    assert len(calls["audio_create"]) == 0


def test_submit_atomically_rolls_back_on_failure(voiceover_service, monkeypatch):
    """原子性：四步任一步异常 → 事务回滚，无孤儿记录。"""
    svc, calls = voiceover_service
    _setup_dialogue(monkeypatch, svc)
    calls["fetchone_result"] = {"id": 101, "selected_audio_id": None}

    # 让 dialogue_audio create 抛异常（模拟第三步失败）
    from model import storyboard_dialogue_audio as da_mod
    monkeypatch.setattr(
        da_mod.StoryboardDialogueAudioModel, "create_in_transaction",
        lambda conn, **kwargs: (_ for _ in ()).throw(RuntimeError("db down")),
    )

    with pytest.raises(RuntimeError, match="db down"):
        svc.ensure_dialogue_voiceover(101, 7)

    # 前两步（ai_audio/tasks）执行了，但事务回滚，不会真正落库
    assert len(calls["audio_create"]) == 1
    assert len(calls["task_create"]) == 1
    assert len(calls["da_create"]) == 0  # 第三步抛异常
    assert calls["set_selected"] == []
    assert calls["rolled_back"] is True
    assert calls["committed"] is False


# ---------------------------------------------------------------------------
# 测试：ensure_for_split_task
# ---------------------------------------------------------------------------

def test_ensure_for_split_task_reconciles_all_dialogues(voiceover_service, monkeypatch):
    """对账：本任务全部合格对白都被提交。"""
    svc, calls = voiceover_service

    # mock _list_dialogues_by_split_task：2 条合格（有 text + character），1 条不合格
    dialogues = [
        {"id": 101, "scene_id": 201, "character_id": 17, "text": "你好", "selected_audio_id": None},
        {"id": 102, "scene_id": 201, "character_id": 17, "text": "再见", "selected_audio_id": None},
        {"id": 103, "scene_id": 201, "character_id": None, "text": "旁白", "selected_audio_id": None},
    ]
    # 第一次查询返回未选中状态，第二次（对账后重统计 remaining）返回已选中
    query_calls = {"n": 0}

    def _list_dialogues(_split_task_id):
        query_calls["n"] += 1
        if query_calls["n"] == 1:
            return dialogues
        # 对账后：101/102 已选中，103 旁白仍为空但不符合资格
        return [
            {"id": 101, "scene_id": 201, "character_id": 17, "text": "你好", "selected_audio_id": 301},
            {"id": 102, "scene_id": 201, "character_id": 17, "text": "再见", "selected_audio_id": 302},
            {"id": 103, "scene_id": 201, "character_id": None, "text": "旁白", "selected_audio_id": None},
        ]

    monkeypatch.setattr(svc, "_list_dialogues_by_split_task", _list_dialogues)
    # mock ensure_dialogue_voiceover 避免走完整事务（单测聚焦对账逻辑）
    submitted = []

    def _ensure(dialogue_id, user_id, config=None):
        submitted.append(dialogue_id)
        return {"success": True, "decision": "submitted", "dialogue_id": dialogue_id,
                "audio_id": 500 + dialogue_id, "dialogue_audio_id": 300 + dialogue_id}

    monkeypatch.setattr(svc, "ensure_dialogue_voiceover", _ensure)

    summary = svc.ensure_for_split_task(36, 7)

    # 2 条合格对白都提交了（103 旁白不合格被排除）
    assert submitted == [101, 102]
    assert summary["eligible_count"] == 2
    assert summary["submitted_count"] == 2
    # 旁白无 character_id：不可自动处理，不计入 remaining，避免 publishing 卡死
    assert summary["remaining_count"] == 0


def test_ensure_for_split_task_remaining_excludes_skipped_and_non_eligible(
    voiceover_service, monkeypatch,
):
    """remaining 只统计仍可处理且未完成：skip / 无角色 不阻挡 completed。"""
    svc, _calls = voiceover_service
    dialogues = [
        {"id": 101, "scene_id": 201, "character_id": 17, "text": "有参考音", "selected_audio_id": None},
        {"id": 102, "scene_id": 201, "character_id": 18, "text": "缺参考音", "selected_audio_id": None},
        {"id": 103, "scene_id": 201, "character_id": None, "text": "旁白", "selected_audio_id": None},
    ]

    def _list_dialogues(_split_task_id):
        return list(dialogues)

    def _ensure(dialogue_id, user_id, config=None):
        if dialogue_id == 101:
            dialogues[0]["selected_audio_id"] = 901
            return {
                "success": True,
                "decision": "submitted",
                "dialogue_id": 101,
                "reason": None,
            }
        return {
            "success": True,
            "decision": "skipped",
            "dialogue_id": dialogue_id,
            "reason": "missing_reference_audio",
            "message": "角色缺少参考音频",
        }

    monkeypatch.setattr(svc, "_list_dialogues_by_split_task", _list_dialogues)
    monkeypatch.setattr(svc, "ensure_dialogue_voiceover", _ensure)

    summary = svc.ensure_for_split_task(50, 7)

    assert summary["submitted_count"] == 1
    assert summary["skipped_count"] == 1
    assert summary["eligible_count"] == 2
    assert summary["remaining_count"] == 0


def test_ensure_for_split_task_remaining_counts_unprocessed_batch(
    voiceover_service, monkeypatch,
):
    """batch 截断后，未处理的 eligible 未选中对白仍计入 remaining。"""
    svc, _calls = voiceover_service
    dialogues = [
        {"id": 101, "scene_id": 1, "character_id": 1, "text": "a", "selected_audio_id": None},
        {"id": 102, "scene_id": 1, "character_id": 1, "text": "b", "selected_audio_id": None},
        {"id": 103, "scene_id": 1, "character_id": 1, "text": "c", "selected_audio_id": None},
    ]

    def _list_dialogues(_split_task_id):
        return list(dialogues)

    def _ensure(dialogue_id, user_id, config=None):
        for d in dialogues:
            if d["id"] == dialogue_id:
                d["selected_audio_id"] = 1000 + dialogue_id
        return {
            "success": True,
            "decision": "submitted",
            "dialogue_id": dialogue_id,
        }

    monkeypatch.setattr(svc, "_list_dialogues_by_split_task", _list_dialogues)
    monkeypatch.setattr(svc, "ensure_dialogue_voiceover", _ensure)

    summary = svc.ensure_for_split_task(50, 7, limit=1)

    assert summary["submitted_count"] == 1
    assert summary["remaining_count"] == 2
