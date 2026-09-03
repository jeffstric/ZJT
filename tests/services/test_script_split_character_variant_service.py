"""角色形象变化变体服务测试（纯函数 + ensure 推进逻辑 mock）。"""
from types import SimpleNamespace

from services.script_split_character_variant_service import (
    EFFECTIVE_CHANGES_FIELD,
    PLAN_METADATA_KEY,
    build_character_variant_summary,
    build_variant_prompt,
    collect_appearance_change_specs,
    collect_ready_variant_map,
    ensure_character_variants,
    sanitize_and_propagate_appearance_changes,
)


def _merged():
    """两个 DB 角色 + 一个新角色的合并结果骨架。

    镜头序列：
      s1: 小林(char_001) 换上晚礼服（变化点）
      s2: 小林 在场（应延续晚礼服）
      s3: 小林 不在场（不应传播）
      s4: 小林 在场 + revert（恢复默认，后续不再延续）
      s5: 小林 在场（无 effective）
      s6: 阿珍(char_002) 变身战斗形态（变化点，DB 角色）
      s7: 新角色 char_003 标记变化（应被剔除，character_db_id=None）
    """
    return {
        "characters": [
            {"id": "char_001", "name": "小林_Xiaolin", "character_db_id": 11},
            {"id": "char_002", "name": "阿珍_Azhen", "character_db_id": 22},
            {"id": "char_003", "name": "新角色", "character_db_id": None},
        ],
        "shot_groups": [
            {
                "group_id": "grp_001",
                "shots": [
                    {
                        "shot_id": "s1",
                        "characters_present": ["char_001"],
                        "character_appearance_changes": [
                            {"character_id": "char_001", "label": "晚礼服",
                             "description": "深蓝色露肩晚礼服，盘发"},
                        ],
                    },
                    {"shot_id": "s2", "characters_present": ["char_001"]},
                    {"shot_id": "s3", "characters_present": ["char_002"]},
                    {
                        "shot_id": "s4",
                        "characters_present": ["char_001"],
                        "character_appearance_changes": [
                            {"character_id": "char_001", "label": "默认", "revert": True},
                        ],
                    },
                    {"shot_id": "s5", "characters_present": ["char_001"]},
                    {
                        "shot_id": "s6",
                        "characters_present": ["char_002"],
                        "character_appearance_changes": [
                            {"character_id": "char_002", "label": "战斗形态",
                             "description": "银色铠甲"},
                        ],
                    },
                    {
                        "shot_id": "s7",
                        "characters_present": ["char_003"],
                        "character_appearance_changes": [
                            {"character_id": "char_003", "label": "雨衣"},
                        ],
                    },
                ],
            }
        ],
    }


def _shots(merged):
    return merged["shot_groups"][0]["shots"]


def test_propagate_marks_change_point_and_continues_while_present():
    merged = sanitize_and_propagate_appearance_changes(_merged())
    shots = _shots(merged)

    s1 = shots[0][EFFECTIVE_CHANGES_FIELD]
    assert s1 == [{"character_id": "char_001", "label": "晚礼服",
                   "description": "深蓝色露肩晚礼服，盘发"}]
    # s2 延续（description 为空，仅供发布期选择）
    assert shots[1][EFFECTIVE_CHANGES_FIELD] == [
        {"character_id": "char_001", "label": "晚礼服", "description": ""}
    ]
    # s3 小林不在场：无传播
    assert EFFECTIVE_CHANGES_FIELD not in shots[2]


def test_revert_stops_propagation_and_keeps_marker():
    merged = sanitize_and_propagate_appearance_changes(_merged())
    shots = _shots(merged)

    # s4 revert：标记保留（幂等依赖），但 effective 无条目且 current 清空
    assert shots[3]["character_appearance_changes"] == [
        {"character_id": "char_001", "label": "默认", "description": "", "revert": True}
    ]
    assert EFFECTIVE_CHANGES_FIELD not in shots[3]
    assert EFFECTIVE_CHANGES_FIELD not in shots[4]


def test_non_db_character_changes_are_dropped():
    merged = sanitize_and_propagate_appearance_changes(_merged())
    shots = _shots(merged)

    assert "character_appearance_changes" not in shots[6]
    assert EFFECTIVE_CHANGES_FIELD not in shots[6]
    # s6 DB 角色变身保留
    assert shots[5][EFFECTIVE_CHANGES_FIELD][0]["label"] == "战斗形态"


def test_label_is_cleaned_and_truncated():
    merged = _merged()
    merged["shot_groups"][0]["shots"][0]["character_appearance_changes"] = [
        {"character_id": "char_001", "label": "  " + "超" * 40, "description": ""},
        {"character_id": "char_001", "label": "   ", "description": "空标签剔除"},
    ]
    sanitize_and_propagate_appearance_changes(merged)
    changes = merged["shot_groups"][0]["shots"][0]["character_appearance_changes"]
    assert len(changes) == 1
    assert changes[0]["label"] == "超" * 24


def test_legacy_result_without_field_is_noop_and_idempotent():
    merged = _merged()
    for shot in _shots(merged):
        shot.pop("character_appearance_changes", None)
    sanitize_and_propagate_appearance_changes(merged)
    assert all(EFFECTIVE_CHANGES_FIELD not in shot for shot in _shots(merged))

    # 幂等：带标记的结果重复传播结果一致
    twice = sanitize_and_propagate_appearance_changes(_merged())
    sanitize_and_propagate_appearance_changes(twice)
    once = sanitize_and_propagate_appearance_changes(_merged())
    assert _shots(twice) == _shots(once)


def test_collect_specs_dedupes_and_keeps_change_point_description():
    merged = sanitize_and_propagate_appearance_changes(_merged())
    specs = collect_appearance_change_specs(merged)

    by_key = {(spec["character_db_id"], spec["label"]): spec for spec in specs}
    assert set(by_key) == {(11, "晚礼服"), (22, "战斗形态")}
    assert by_key[(11, "晚礼服")]["description"] == "深蓝色露肩晚礼服，盘发"
    assert by_key[(11, "晚礼服")]["character_name"] == "小林_Xiaolin"
    assert by_key[(22, "战斗形态")]["character_name"] == "阿珍_Azhen"


def test_collect_specs_dedupes_empty_description_entries():
    """回归：变化点与延续条目 description 均为空时也不得重复收集。

    判重必须靠独立的 seen 集合——若用 descriptions 兼任，空 description 的 key
    永远不会被记录，同一 (db_id, label) 会被重复 append，导致重复提交变体生图。
    """
    merged = {
        "characters": [
            {"id": "char_001", "name": "小林_Xiaolin", "character_db_id": 11},
        ],
        "shot_groups": [{
            "group_id": "grp_001",
            "shots": [
                {"shot_id": "s1", "characters_present": ["char_001"],
                 "character_appearance_changes": [
                     {"character_id": "char_001", "label": "晚礼服"}]},
                {"shot_id": "s2", "characters_present": ["char_001"]},
                {"shot_id": "s3", "characters_present": ["char_001"]},
            ],
        }],
    }
    sanitize_and_propagate_appearance_changes(merged)
    specs = collect_appearance_change_specs(merged)
    assert [(spec["character_db_id"], spec["label"]) for spec in specs] == [(11, "晚礼服")]


def test_collect_specs_respects_max_count():
    merged = sanitize_and_propagate_appearance_changes(_merged())
    merged["characters"].append({"id": "char_009", "name": "批量", "character_db_id": 99})
    shots = merged["shot_groups"][0]["shots"]
    for index in range(30):
        shots.append({
            "shot_id": f"sx{index}",
            "characters_present": ["char_009"],
            "character_appearance_changes": [
                {"character_id": "char_009", "label": f"造型{index}", "description": ""}
            ],
        })
    sanitize_and_propagate_appearance_changes(merged)
    specs = collect_appearance_change_specs(merged)
    assert len(specs) == 20  # CHARACTER_VARIANT_MAX_COUNT


def test_variant_prompt_keeps_identity_and_mentions_label():
    prompt = build_variant_prompt("晚礼服", "深蓝色露肩晚礼服")
    assert "晚礼服" in prompt
    assert "identical" in prompt
    assert "front view" in prompt


def test_ready_map_and_summary_only_include_ready_entries():
    final_result = {
        "metadata": {
            PLAN_METADATA_KEY: [
                {"character_db_id": 11, "character_name": "小林_Xiaolin", "label": "晚礼服",
                 "status": "ready", "url": "http://img/a.png", "error": ""},
                {"character_db_id": 22, "character_name": "阿珍_Azhen", "label": "战斗形态",
                 "status": "failed", "url": "", "error": "grid_task_-1"},
                {"character_db_id": 33, "character_name": "无主图", "label": "雨衣",
                 "status": "skipped", "url": "", "error": "no_main_image"},
            ]
        }
    }
    ready = collect_ready_variant_map(final_result)
    assert ready == {"11": {"晚礼服": "http://img/a.png"}}

    summary = build_character_variant_summary(final_result)
    assert summary["total"] == 3
    assert summary["ready"] == 1
    assert summary["failed"] == 1
    assert summary["skipped"] == 1
    assert all("url" not in item for item in summary["items"])


class _FakeCharacter:
    def __init__(self, name, reference_image, reference_images):
        self.name = name
        self.reference_image = reference_image
        self.reference_images = reference_images


def test_ensure_variants_reuses_existing_and_submits_and_settles(monkeypatch):
    merged = sanitize_and_propagate_appearance_changes(_merged())
    final_result = dict(merged)

    characters = {
        11: _FakeCharacter("小林_Xiaolin", "http://img/main1.png",
                           '[{"id": "v1", "label": "晚礼服", "url": "http://img/v1.png"}]'),
        22: _FakeCharacter("阿珍_Azhen", "http://img/main2.png", None),
    }
    monkeypatch.setattr(
        "model.character.CharacterModel.get_by_id",
        staticmethod(lambda db_id: characters.get(db_id)),
    )

    submitted = []

    def _fake_generate(user_id, world_id, auth_token, character_name,
                       variant_label, variant_prompt, aspect_ratio="16:9",
                       force_update=False):
        submitted.append((character_name, variant_label))
        return {"success": True, "task_id": f"{user_id}_7_{character_name}|{variant_label}"}

    monkeypatch.setattr(
        "script_writer_core.mcp_tool.generate_character_variant_image", _fake_generate)

    grid_tasks = {}

    class _GridTask:
        def __init__(self, status):
            self.status = status

    monkeypatch.setattr(
        "model.grid_image_tasks.GridImageTasksModel.get_by_task_key",
        staticmethod(lambda key: grid_tasks.get(key)),
    )

    task = SimpleNamespace(
        user_id=7,
        auth_token="tok",
        get_request_config=lambda: {"world_id": 3},
    )

    # 第一轮：晚礼服复用已有变体 → ready；战斗形态提交 → submitted
    summary = ensure_character_variants(task, final_result)
    assert summary["all_settled"] is False
    assert summary["ready"] == 1
    assert summary["submitted"] == 1
    assert submitted == [("阿珍_Azhen", "战斗形态")]

    # 第二轮：后台任务完成并写回 DB → ready，全部终态
    characters[22].reference_images = '[{"id": "v2", "label": "战斗形态", "url": "http://img/v2.png"}]'
    grid_tasks["7_7_阿珍_Azhen|战斗形态"] = _GridTask(2)  # COMPLETED
    summary = ensure_character_variants(task, final_result)
    assert summary["all_settled"] is True
    assert summary["ready"] == 2

    ready = collect_ready_variant_map(final_result)
    assert ready == {
        "11": {"晚礼服": "http://img/v1.png"},
        "22": {"战斗形态": "http://img/v2.png"},
    }


def test_ensure_variants_skips_without_main_image_and_degrades_on_failure(monkeypatch):
    merged = sanitize_and_propagate_appearance_changes(_merged())
    final_result = dict(merged)

    monkeypatch.setattr(
        "model.character.CharacterModel.get_by_id",
        staticmethod(lambda db_id: _FakeCharacter(f"角色{db_id}", "", None)),
    )
    monkeypatch.setattr(
        "script_writer_core.mcp_tool.generate_character_variant_image",
        lambda **kwargs: {"success": False, "error": "模型不可用"},
    )

    task = SimpleNamespace(
        user_id=7,
        auth_token="tok",
        get_request_config=lambda: {"world_id": 3},
    )
    summary = ensure_character_variants(task, final_result)
    # 无主图/提交失败均降级为终态，不阻塞拆分
    assert summary["all_settled"] is True
    assert summary["ready"] == 0
    assert summary["failed"] + summary["skipped"] == summary["total"] == 2


def test_ensure_variants_builds_plan_only_from_effective_changes(monkeypatch):
    """无形象变化的旧任务：plan 为空且立即 settle（行为与关闭开关一致）。"""
    final_result = {"metadata": {}, "characters": [], "shot_groups": [{"shots": [{}]}]}
    task = SimpleNamespace(
        user_id=7,
        auth_token="tok",
        get_request_config=lambda: {"world_id": 3},
    )
    summary = ensure_character_variants(task, final_result)
    assert summary["all_settled"] is True
    assert summary["total"] == 0
    assert collect_ready_variant_map(final_result) == {}


def test_propagation_supports_dict_characters_present():
    """characters_present 为对象形态（{"id": ...}）时同样按内部 id 传播。"""
    merged = _merged()
    shots = merged["shot_groups"][0]["shots"]
    shots[1]["characters_present"] = [{"id": "char_001"}, {"character_id": "char_002"}]

    sanitize_and_propagate_appearance_changes(merged)
    assert shots[1][EFFECTIVE_CHANGES_FIELD] == [
        {"character_id": "char_001", "label": "晚礼服", "description": ""}
    ]


def test_outfit_switch_and_new_change_after_revert():
    """同角色换第二种造型时覆盖持续状态；revert 后再次换装从头传播。"""
    merged = _merged()
    shots = merged["shot_groups"][0]["shots"]
    # s2 显式切换战斗服；s5（revert 之后）重新换上运动服
    shots[1]["character_appearance_changes"] = [
        {"character_id": "char_001", "label": "战斗服", "description": "黑色作战服"}
    ]
    shots[4]["character_appearance_changes"] = [
        {"character_id": "char_001", "label": "运动服", "description": "红色运动服"}
    ]

    sanitize_and_propagate_appearance_changes(merged)
    # s1 晚礼服（变化点）→ s2 战斗服（显式切换，覆盖）→ s3 不在场 → s4 revert
    assert shots[0][EFFECTIVE_CHANGES_FIELD][0]["label"] == "晚礼服"
    assert shots[1][EFFECTIVE_CHANGES_FIELD] == [
        {"character_id": "char_001", "label": "战斗服", "description": "黑色作战服"}
    ]
    assert EFFECTIVE_CHANGES_FIELD not in shots[3]
    # s5 重新换上运动服并延续到后续在场镜头
    assert shots[4][EFFECTIVE_CHANGES_FIELD][0]["label"] == "运动服"

    specs = collect_appearance_change_specs(merged)
    labels = {(spec["character_db_id"], spec["label"]) for spec in specs}
    assert (11, "晚礼服") in labels
    assert (11, "战斗服") in labels
    assert (11, "运动服") in labels


def test_propagation_spans_multiple_shot_groups():
    """持续状态跨 shot_groups 传播（传播基于最终镜头顺序，不限于组内）。"""
    # 注意：不能复用 _merged()（其 s4 有 revert，持续状态已在组内清除），
    # 这里用无 revert 的骨架验证跨组延续。
    merged = {
        "characters": [
            {"id": "char_001", "name": "小林_Xiaolin", "character_db_id": 11},
            {"id": "char_002", "name": "阿珍_Azhen", "character_db_id": 22},
        ],
        "shot_groups": [
            {
                "group_id": "grp_001",
                "shots": [
                    {
                        "shot_id": "s1",
                        "characters_present": ["char_001"],
                        "character_appearance_changes": [
                            {"character_id": "char_001", "label": "晚礼服",
                             "description": "深蓝色露肩晚礼服，盘发"},
                        ],
                    },
                ],
            },
            {
                "group_id": "grp_002",
                "shots": [
                    {"shot_id": "t1", "characters_present": ["char_001"]},
                    {"shot_id": "t2", "characters_present": ["char_002"]},
                ],
            },
        ],
    }
    group2 = merged["shot_groups"][1]

    sanitize_and_propagate_appearance_changes(merged)
    t1, t2 = group2["shots"]
    assert t1[EFFECTIVE_CHANGES_FIELD] == [
        {"character_id": "char_001", "label": "晚礼服", "description": ""}
    ]
    assert EFFECTIVE_CHANGES_FIELD not in t2


def test_ensure_variants_resumes_from_persisted_plan(monkeypatch):
    """metadata 已有 plan 时按原计划推进，不根据 shot 重建（跨 tick 幂等恢复）。"""
    merged = sanitize_and_propagate_appearance_changes(_merged())
    final_result = dict(merged)
    final_result["metadata"] = {
        PLAN_METADATA_KEY: [
            {"character_db_id": 11, "character_name": "小林_Xiaolin", "label": "晚礼服",
             "description": "", "status": "ready", "task_key": "", "url": "http://img/v1.png",
             "error": "", "submitted_at": ""},
        ]
    }
    # 若错误重建 plan 会调用 collect（这里通过让 DB 提交抛错验证未被走到）
    def _boom(**kwargs):
        raise AssertionError("plan should not be rebuilt from shots")

    monkeypatch.setattr(
        "script_writer_core.mcp_tool.generate_character_variant_image", _boom)
    monkeypatch.setattr(
        "model.character.CharacterModel.get_by_id",
        staticmethod(lambda db_id: None),
    )
    task = SimpleNamespace(
        user_id=7, auth_token="tok", get_request_config=lambda: {"world_id": 3},
    )

    summary = ensure_character_variants(task, final_result)
    assert summary["all_settled"] is True
    assert summary["total"] == 1
    assert summary["ready"] == 1
    assert collect_ready_variant_map(final_result) == {"11": {"晚礼服": "http://img/v1.png"}}


def test_submitted_variant_times_out_and_degrades(monkeypatch):
    """submitted 条目超过 CHARACTER_VARIANT_TASK_TIMEOUT_SECONDS 未终态 → failed 降级。"""
    from datetime import datetime, timedelta

    from config.constant import ScriptSplitConstants

    merged = sanitize_and_propagate_appearance_changes(_merged())
    final_result = dict(merged)
    stale = (datetime.now() - timedelta(
        seconds=float(ScriptSplitConstants.CHARACTER_VARIANT_TASK_TIMEOUT_SECONDS) + 60,
    )).isoformat(timespec="seconds")
    final_result["metadata"] = {
        PLAN_METADATA_KEY: [
            {"character_db_id": 11, "character_name": "小林_Xiaolin", "label": "晚礼服",
             "description": "", "status": "submitted", "task_key": "k1",
             "url": "", "error": "", "submitted_at": stale},
        ]
    }

    class _Running:
        status = 1  # QUEUED/PROCESSING 之类的非终态

    monkeypatch.setattr(
        "model.grid_image_tasks.GridImageTasksModel.get_by_task_key",
        staticmethod(lambda key: _Running()),
    )
    task = SimpleNamespace(
        user_id=7, auth_token="tok", get_request_config=lambda: {"world_id": 3},
    )

    summary = ensure_character_variants(task, final_result)
    assert summary["all_settled"] is True
    assert summary["failed"] == 1
    entry = final_result["metadata"][PLAN_METADATA_KEY][0]
    assert entry["status"] == "failed"
    assert entry["error"] == "variant_task_timeout"


def test_submitted_variant_degrades_on_grid_failure_or_missing_record(monkeypatch):
    """后台任务失败或 task_key 查无记录 → failed；COMPLETED 但未写回变体 → failed。"""
    merged = sanitize_and_propagate_appearance_changes(_merged())
    final_result = dict(merged)
    final_result["metadata"] = {
        PLAN_METADATA_KEY: [
            {"character_db_id": 11, "character_name": "小林_Xiaolin", "label": "晚礼服",
             "description": "", "status": "submitted", "task_key": "k-fail",
             "url": "", "error": "", "submitted_at": "2026-01-01T00:00:00"},
            {"character_db_id": 22, "character_name": "阿珍_Azhen", "label": "战斗形态",
             "description": "", "status": "submitted", "task_key": "k-missing",
             "url": "", "error": "", "submitted_at": "2026-01-01T00:00:00"},
            {"character_db_id": 33, "character_name": "角色", "label": "雨衣",
             "description": "", "status": "submitted", "task_key": "k-no-writeback",
             "url": "", "error": "", "submitted_at": "2026-01-01T00:00:00"},
        ]
    }

    from model.grid_image_tasks import GridImageTaskStatus

    grid_tasks = {
        "k-fail": SimpleNamespace(status=GridImageTaskStatus.FAILED),
        "k-no-writeback": SimpleNamespace(status=GridImageTaskStatus.COMPLETED),
    }
    monkeypatch.setattr(
        "model.grid_image_tasks.GridImageTasksModel.get_by_task_key",
        staticmethod(lambda key: grid_tasks.get(key),
    ))
    monkeypatch.setattr(
        "model.character.CharacterModel.get_by_id",
        staticmethod(lambda db_id: _FakeCharacter("角色", "http://img/main.png", "[]")),
    )
    task = SimpleNamespace(
        user_id=7, auth_token="tok", get_request_config=lambda: {"world_id": 3},
    )

    summary = ensure_character_variants(task, final_result)
    assert summary["all_settled"] is True
    assert summary["failed"] == 3
    entries = final_result["metadata"][PLAN_METADATA_KEY]
    by_task = {entry["task_key"]: entry for entry in entries}
    assert "FAILED" in by_task["k-fail"]["error"] or "failed" in by_task["k-fail"]["error"]
    assert by_task["k-missing"]["error"] == "task_record_missing"
    assert by_task["k-no-writeback"]["error"] == "variant_not_written_back"


def test_ensure_variants_reuses_variant_generated_concurrently(monkeypatch):
    """提交返回 already_has_variant（拆分期间用户手动生成同 label）→ 重读 DB 复用。"""
    merged = sanitize_and_propagate_appearance_changes(_merged())
    final_result = dict(merged)

    monkeypatch.setattr(
        "model.character.CharacterModel.get_by_id",
        staticmethod(lambda db_id: _FakeCharacter(
            "小林_Xiaolin", "http://img/main1.png",
            '[{"id": "v1", "label": "晚礼服", "url": "http://img/v1.png"}]'),
    ))
    monkeypatch.setattr(
        "script_writer_core.mcp_tool.generate_character_variant_image",
        lambda **kwargs: {"success": False, "skip_reason": "already_has_variant"},
    )
    task = SimpleNamespace(
        user_id=7, auth_token="tok", get_request_config=lambda: {"world_id": 3},
    )

    summary = ensure_character_variants(task, final_result)
    assert summary["all_settled"] is True
    assert summary["ready"] >= 1
    assert collect_ready_variant_map(final_result).get("11", {}).get("晚礼服") == (
        "http://img/v1.png"
    )


def test_ensure_variants_limits_submit_batch_per_tick(monkeypatch):
    """单个 tick 最多提交 CHARACTER_VARIANT_SUBMIT_BATCH_SIZE 个 pending。"""
    from config.constant import ScriptSplitConstants

    batch = int(ScriptSplitConstants.CHARACTER_VARIANT_SUBMIT_BATCH_SIZE)
    assert batch >= 2

    merged = {
        "characters": [
            {"id": f"char_{i:03d}", "name": f"角色{i}", "character_db_id": i}
            for i in range(1, batch + 3)
        ],
        "shot_groups": [{
            "shots": [
                {"shot_id": f"s{i}", "characters_present": [f"char_{i:03d}"],
                 "character_appearance_changes": [
                     {"character_id": f"char_{i:03d}", "label": "制服", "description": ""}
                 ]}
                for i in range(1, batch + 3)
            ],
        }],
    }
    sanitize_and_propagate_appearance_changes(merged)
    final_result = merged

    submit_calls = []

    def _fake_generate(**kwargs):
        submit_calls.append(kwargs.get("character_name"))
        return {"success": True, "task_id": f"t-{len(submit_calls)}"}

    monkeypatch.setattr(
        "model.character.CharacterModel.get_by_id",
        staticmethod(lambda db_id: _FakeCharacter(f"角色{db_id}", "http://img/main.png", None)),
    )
    monkeypatch.setattr(
        "script_writer_core.mcp_tool.generate_character_variant_image", _fake_generate)
    task = SimpleNamespace(
        user_id=7, auth_token="tok", get_request_config=lambda: {"world_id": 3},
    )

    summary = ensure_character_variants(task, final_result)
    assert len(submit_calls) == batch
    assert summary["submitted"] == batch
    assert summary["pending"] == 2  # batch + 2 个规格，剩余 pending 留给下一 tick
    assert summary["all_settled"] is False
