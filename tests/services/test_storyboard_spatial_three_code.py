"""分镜 three.js 场景代码契约测试（LLM 直出 three.js 空间方案）。

覆盖：代码规范化、序列首镜判定、逐镜/整段校验诊断、API 预览载荷组装、
落库透传（build_storyboard_scenes_from_parsed_script → prompt_json）、
spatial handoff 携带上一镜代码。
"""
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.storyboard_spatial import (
    audit_three_scene_code,
    audit_three_scene_codes_for_shots,
    build_three_code_preview,
    is_sequence_start_code,
    normalize_three_scene_code,
)


FIRST_SHOT_CODE = (
    "startScene('面包车驾驶室');\n"
    "makeStage('车壳', 2.4, 1.5, 0, 0, {h: 1.6});\n"
    "makeActor('奶酪', -0.55, 0.3, {facing: 90});\n"
    "makeActor('奶昔', 0.55, 0.2, {facing: -90});\n"
    "setCamera(-1.8, 1.2, 0.5, 0, 0.9, 0, 55);"
)

INCREMENTAL_CODE = (
    "moveActor('奶酪', -1.2, 1.6, {facing: 180});\n"
    "setCamera(0, 1.6, 3.2, -0.8, 1.0, 1.2, 45);"
)


def test_normalize_strips_markdown_fences():
    wrapped = "```javascript\n" + FIRST_SHOT_CODE + "\n```"
    assert normalize_three_scene_code(wrapped) == FIRST_SHOT_CODE
    assert normalize_three_scene_code(None) == ""
    assert normalize_three_scene_code("   \n  ") == ""


def test_normalize_strips_single_line_fence():
    """单行围栏（无换行，如 LLM 输出 ```js code ```）不得残留开头围栏/语言标注。"""
    code = "setCamera(0, 1.2, 4.2, 0, 1.05, 0, 35);"
    assert normalize_three_scene_code(f"```js {code} ```") == code
    assert normalize_three_scene_code(f"```javascript {code}```") == code
    # 无语言标注、围栏后紧跟空格
    assert normalize_three_scene_code(f"``` {code} ```") == code
    # 空围栏块
    assert normalize_three_scene_code("```") == ""
    assert normalize_three_scene_code("```js") == ""
    # 未闭合围栏
    assert normalize_three_scene_code("```js\n" + code) == code


def test_normalize_single_line_fence_end_to_end_audit():
    """回归：单行围栏剥壳后须能通过整段代码链校验（修复前 audit 会通过
    但落库/前端执行被围栏污染）。"""
    shots = [{
        "shot_id": "s001",
        "three_scene_code": "```js " + FIRST_SHOT_CODE.replace("\n", " ") + " ```",
    }]
    issues = audit_three_scene_codes_for_shots(shots, first_shot_starts_sequence=True)
    assert issues == []
    assert normalize_three_scene_code(shots[0]["three_scene_code"]).startswith("startScene(")


def test_sequence_start_detection():
    assert is_sequence_start_code(FIRST_SHOT_CODE) is True
    assert is_sequence_start_code(INCREMENTAL_CODE) is False
    assert is_sequence_start_code("") is False


def test_audit_valid_first_shot_passes():
    assert audit_three_scene_code(FIRST_SHOT_CODE, is_first_shot=True) == []


def test_audit_valid_incremental_shot_passes():
    issues = audit_three_scene_code(
        INCREMENTAL_CODE, is_first_shot=False, previous_code=FIRST_SHOT_CODE,
    )
    assert issues == []


def test_audit_missing_code_is_error():
    issues = audit_three_scene_code("", is_first_shot=True)
    assert [i["code"] for i in issues] == ["three_code_missing"]
    assert issues[0]["severity"] == "error"


def test_audit_missing_camera_is_error():
    code = "moveActor('奶酪', -1.2, 1.6);"
    issues = audit_three_scene_code(code, is_first_shot=False)
    assert any(i["code"] == "three_code_camera_missing" and i["severity"] == "error"
               for i in issues)


def test_audit_first_shot_without_start_scene_is_error():
    code = (
        "makeStage('车壳', 2.4, 1.5, 0, 0, {h: 1.6});\n"
        "setCamera(-1.8, 1.2, 0.5, 0, 0.9, 0, 55);"
    )
    issues = audit_three_scene_code(code, is_first_shot=True)
    assert any(i["code"] == "three_code_scene_build_missing" for i in issues)


def test_audit_start_scene_without_build_is_error():
    code = "startScene('空场景');\nsetCamera(0, 1.5, 3, 0, 1, 0, 50);"
    issues = audit_three_scene_code(code, is_first_shot=True)
    assert any(i["code"] == "three_code_sequence_start_empty" for i in issues)


def test_chain_audit_marks_sequence_start_rollover():
    shots = [
        {"shot_id": "s001", "three_scene_code": FIRST_SHOT_CODE},
        {"shot_id": "s002", "three_scene_code": INCREMENTAL_CODE},
        # 场景切换：新序列首镜
        {"shot_id": "s003", "three_scene_code": FIRST_SHOT_CODE.replace("面包车", "天台")},
        {"shot_id": "s004", "three_scene_code": "setCamera(2, 1.4, 2, 0, 1, 0, 35);"},
    ]
    issues = audit_three_scene_codes_for_shots(shots, first_shot_starts_sequence=True)
    assert issues == []


def test_chain_audit_flags_incremental_chain_without_start():
    shots = [
        {"shot_id": "s001", "three_scene_code": INCREMENTAL_CODE},
        {"shot_id": "s002", "three_scene_code": INCREMENTAL_CODE},
    ]
    issues = audit_three_scene_codes_for_shots(shots, first_shot_starts_sequence=True)
    assert any(i["code"] == "three_code_scene_build_missing" and i["shot_ref"] == "s001"
               for i in issues)


def test_chain_audit_inherit_mode_allows_incremental_first_shot():
    shots = [{"shot_id": "s001", "three_scene_code": INCREMENTAL_CODE}]
    issues = audit_three_scene_codes_for_shots(shots, first_shot_starts_sequence=False)
    assert issues == []


def test_build_three_code_preview_payload():
    payload = build_three_code_preview("```js\n" + INCREMENTAL_CODE + "\n```")
    assert payload == {
        "kind": "three_code",
        "code": INCREMENTAL_CODE,
        "is_sequence_start": False,
        "diagnostics": [],
    }
    assert build_three_code_preview("") is None
    assert build_three_code_preview(None) is None
    assert build_three_code_preview(123) is None


def test_build_storyboard_scenes_passes_three_code_into_prompt_json():
    from api.storyboard import build_storyboard_scenes_from_parsed_script

    parsed = {
        "shot_groups": [{
            "group_id": "grp_001",
            "group_name": "开场",
            "shots": [{
                "shot_id": "s001",
                "shot_number": 1,
                "duration": 5.0,
                "characters_present": [],
                "three_scene_code": "```js\n" + FIRST_SHOT_CODE + "\n```",
            }],
        }],
    }
    scenes = build_storyboard_scenes_from_parsed_script(parsed)
    assert len(scenes) == 1
    assert scenes[0]["prompt"]["three_scene_code"] == FIRST_SHOT_CODE


def test_spatial_handoff_carries_upstream_three_code():
    from enterprise.services.script_split_quality.spatial_handoff import build_spatial_handoff

    upstream = {
        "shot_groups": [{
            "shots": [
                {"shot_id": "s001"},
                {"shot_id": "s002", "three_scene_code": INCREMENTAL_CODE,
                 "spatial_layout": {"camera_pose": {}}},
            ],
        }],
        "_spatial_final_state": {"entities": {}},
    }
    handoff = build_spatial_handoff(upstream, "seg_001")
    assert handoff["three_scene_code"] == INCREMENTAL_CODE
    assert handoff["source_shot_id"] == "s002"


def test_spatial_preview_endpoint_payload_prefers_three_code():
    from api.storyboard import _build_spatial_scene_preview

    scene = {
        "id": 7,
        "title": "分镜7",
        "sort_order": 7,
        "prompt_json": {
            "perspective": "平视 / 中景",
            "three_scene_code": FIRST_SHOT_CODE,
        },
    }
    payload = _build_spatial_scene_preview(scene)
    assert payload is not None
    assert payload["three_scene"]["kind"] == "three_code"
    assert payload["three_scene"]["is_sequence_start"] is True
    assert payload["three_scene"]["code"] == FIRST_SHOT_CODE
    assert payload["diagnostic_summary"] == {"errors": 0, "warnings": 0}
