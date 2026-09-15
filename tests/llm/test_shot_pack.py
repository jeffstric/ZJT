from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from llm.shot_pack import pack_parsed_for_reference_video, pack_shots_for_reference_video


def _shot(duration, description="d", dialogue=None, **extra):
    data = {
        "duration": duration,
        "description": description,
        "dialogue": dialogue or [],
        "characters_present": extra.pop("characters_present", ["a"]),
        "props_present": extra.pop("props_present", []),
    }
    data.update(extra)
    return data


def test_pack_merges_until_next_would_exceed():
    shots = [
        _shot(5, "A", dialogue=[{"text": "1"}]),
        _shot(5, "B", dialogue=[{"text": "2"}]),
        _shot(6, "C", dialogue=[{"text": "3"}]),
    ]
    packed = pack_shots_for_reference_video(shots, 15)
    assert len(packed) == 2
    assert packed[0]["duration"] == 10
    assert packed[1]["duration"] == 6
    assert [d["text"] for d in packed[0]["dialogue"]] == ["1", "2"]
    assert "镜头1：0~5S" in packed[0]["description"]
    assert "镜头2：5~10S" in packed[0]["description"]
    assert packed[0]["description"].count("A") == 1


def test_pack_does_not_merge_when_sum_exceeds():
    packed = pack_shots_for_reference_video([_shot(5, "A"), _shot(12, "B")], 15)
    assert len(packed) == 2
    assert packed[0]["duration"] == 5
    assert packed[1]["duration"] == 12


def test_pack_keeps_oversized_single_shot():
    packed = pack_shots_for_reference_video([_shot(20, "long")], 15)
    assert len(packed) == 1
    assert packed[0]["duration"] == 20


def test_pack_parsed_does_not_cross_groups():
    parsed = {
        "shot_groups": [
            {"group_id": "g1", "shots": [_shot(5, "A"), _shot(5, "B")]},
            {"group_id": "g2", "shots": [_shot(5, "C")]},
        ]
    }
    out = pack_parsed_for_reference_video(parsed, 15)
    assert len(out["shot_groups"][0]["shots"]) == 1
    assert out["shot_groups"][0]["shots"][0]["duration"] == 10
    assert len(out["shot_groups"][1]["shots"]) == 1
    assert out["shot_groups"][1]["shots"][0]["description"] == "C"
