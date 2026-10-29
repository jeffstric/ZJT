"""three.js 场景转换与空间一致性审计单测。

Community CI does not ship the `enterprise` package (gitignored). Skip cleanly
when the module is unavailable so services discovery still succeeds.
"""
import copy
import importlib.util
import unittest

def _detect_enterprise_spatial() -> bool:
    """探测 three_scene 模块是否可导入。

    find_spec 带点路径会先导入父包：enterprise 整体缺失时抛
    ModuleNotFoundError 而非返回 None（Community CI 无 enterprise 目录
    即此场景）；父包 __init__ 或其依赖在部分精简镜像下也可能抛异常。
    模块级异常会让 unittest 收集直接报 _FailedTest，必须降级为 False，
    让用例干净跳过。
    """
    try:
        if (
            importlib.util.find_spec("enterprise.services.storyboard_spatial.three_scene")
            is None
        ):
            return False
        from enterprise.services.storyboard_spatial.three_scene import (
            audit_spatial_layout,
            build_three_scene,
        )
        globals()["audit_spatial_layout"] = audit_spatial_layout
        globals()["build_three_scene"] = build_three_scene
        return True
    except Exception:
        return False


_HAS_ENTERPRISE_SPATIAL = _detect_enterprise_spatial()


def _cabin_layout():
    """双座位车舱 + 车外左前方机位（与 prompt schema 示例同构）。"""
    return {
        "schema_version": 2,
        "space_unit_refs": ["space_prop_001_cabin"],
        "camera_pose": {
            "space_unit_id": "space_prop_001_cabin",
            "eye": {"x": 0.0, "y": -0.8, "z": 0.6},
            "target": {"x": 0.3, "y": 0.45, "z": 0.35},
            "up": {"x": 0, "y": 0, "z": 1},
            "fov": "medium",
        },
        "containers": [
            {
                "container_type": "prop",
                "prop_id": "prop_001",
                "name": "泡泡蒸汽车",
                "slots": [
                    {
                        "space_unit_id": "space_prop_001_cabin",
                        "slot_id": "front_left_seat",
                        "position_3d": {"x": -0.55, "y": 0.45, "z": 0.25},
                        "screen_position": "画面左侧",
                        "occupant_type": "character",
                        "character_id": "char_001",
                        "name": "奶酪_Cheese",
                        "visibility": "visible",
                        "framing_role": "primary_subject",
                    },
                    {
                        "space_unit_id": "space_prop_001_cabin",
                        "slot_id": "front_right_seat",
                        "position_3d": {"x": 0.55, "y": 0.45, "z": 0.25},
                        "screen_position": "画面右侧",
                        "occupant_type": "character",
                        "character_id": "char_002",
                        "name": "奶昔_Milkshake",
                        "visibility": "visible",
                    },
                ],
            }
        ],
        "loose_positions": [],
    }


def _cabin_world():
    return {
        "space_units": [
            {
                "space_unit_id": "space_prop_001_cabin",
                "name": "泡泡蒸汽车驾驶室",
                "anchors": [
                    {
                        "anchor_id": "front_driver_seat",
                        "label": "驾驶座",
                        "position_3d": {"x": 0.55, "y": 0.45, "z": 0.25},
                    },
                    {
                        "anchor_id": "front_passenger_seat",
                        "label": "副驾驶座",
                        "position_3d": {"x": -0.55, "y": 0.45, "z": 0.25},
                    },
                ],
            }
        ]
    }


@unittest.skipUnless(
    _HAS_ENTERPRISE_SPATIAL,
    "enterprise.services.storyboard_spatial not available",
)
class TestBuildThreeScene(unittest.TestCase):
    def test_entities_projected_to_expected_screen_sides(self):
        scene = build_three_scene(_cabin_layout(), _cabin_world())
        by_id = {e["id"]: e for e in scene["entities"]}
        self.assertEqual(by_id["char_001"]["derived_screen_position"], "画面左侧")
        self.assertEqual(by_id["char_002"]["derived_screen_position"], "画面右侧")
        # 与 LLM 写的 screen_position 一致时不应有左右冲突诊断
        codes = [d["code"] for d in scene["diagnostics"]]
        self.assertNotIn("screen_position_conflict", codes)

    def test_camera_metadata_and_fov_mapping(self):
        scene = build_three_scene(_cabin_layout(), _cabin_world())
        camera = scene["camera"]
        self.assertTrue(camera["present"])
        self.assertEqual(camera["eye"], {"x": 0.0, "y": -0.8, "z": 0.6})
        self.assertEqual(camera["fov_deg"], 50.0)

    def test_anchors_from_referenced_space_units_only(self):
        scene = build_three_scene(_cabin_layout(), _cabin_world())
        anchor_ids = {a["id"] for a in scene["anchors"]}
        self.assertEqual(anchor_ids, {"front_driver_seat", "front_passenger_seat"})

    def test_missing_camera_pose_falls_back_with_warning(self):
        layout = _cabin_layout()
        del layout["camera_pose"]
        scene = build_three_scene(layout, _cabin_world())
        codes = [d["code"] for d in scene["diagnostics"]]
        self.assertIn("camera_pose_missing", codes)
        # 相机缺失时投影为空，实体仍保留位置供渲染
        self.assertEqual(len(scene["entities"]), 2)
        self.assertTrue(all(e["position"] for e in scene["entities"]))

    def test_position_resolved_from_world_anchor_when_slot_omits_3d(self):
        layout = _cabin_layout()
        # 槽位缺 position_3d，但可通过 anchor 解析（驾驶座锚点 x=0.55）
        layout["containers"][0]["slots"][0].pop("position_3d")
        layout["containers"][0]["slots"][0]["anchor_id"] = "front_driver_seat"
        scene = build_three_scene(layout, _cabin_world())
        by_id = {e["id"]: e for e in scene["entities"]}
        self.assertEqual(by_id["char_001"]["position"], {"x": 0.55, "y": 0.45, "z": 0.25})

    def test_screen_position_left_right_reversal_reports_error(self):
        layout = _cabin_layout()
        # 奶昔在 3D 右侧（x=0.55），但 screen_position 写成左侧 → 左右反转
        layout["containers"][0]["slots"][1]["screen_position"] = "画面左侧"
        scene = build_three_scene(layout, _cabin_world())
        conflicts = [d for d in scene["diagnostics"] if d["code"] == "screen_position_conflict"]
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(conflicts[0]["severity"], "error")
        self.assertEqual(conflicts[0]["entity_id"], "char_002")
        self.assertEqual(conflicts[0]["written_side"], "left")
        self.assertEqual(conflicts[0]["derived_side"], "right")

    def test_center_boundary_mismatch_is_warning_not_error(self):
        layout = _cabin_layout()
        # 奶昔 3D 推导右侧，screen_position 写中央 → 模糊边界降级 warning
        layout["containers"][0]["slots"][1]["screen_position"] = "画面中央"
        scene = build_three_scene(layout, _cabin_world())
        mismatches = [
            d for d in scene["diagnostics"] if d["code"] == "screen_position_center_mismatch"
        ]
        self.assertEqual(len(mismatches), 1)
        self.assertEqual(mismatches[0]["severity"], "warning")
        codes = [d["code"] for d in scene["diagnostics"]]
        self.assertNotIn("screen_position_conflict", codes)

    def test_unresolvable_position_emits_warning(self):
        layout = _cabin_layout()
        layout["containers"][0]["slots"][0].pop("position_3d")
        scene = build_three_scene(layout, None)
        codes = [d["code"] for d in scene["diagnostics"]]
        self.assertIn("entity_position_missing", codes)

    def test_malformed_input_degrades_without_raising(self):
        scene = build_three_scene({"containers": "not-a-list", "camera_pose": 42}, None)
        self.assertEqual(scene["entities"], [])
        self.assertTrue(any(d["code"] == "camera_pose_missing" for d in scene["diagnostics"]))

    def test_scene_is_json_serializable(self):
        import json

        scene = build_three_scene(_cabin_layout(), _cabin_world())
        json.dumps(scene, ensure_ascii=False)  # 不抛错即可


@unittest.skipUnless(
    _HAS_ENTERPRISE_SPATIAL,
    "enterprise.services.storyboard_spatial not available",
)
class TestAuditSpatialLayout(unittest.TestCase):
    def test_visible_entity_behind_camera_reported(self):
        layout = _cabin_layout()
        # 奶昔挪到相机身后（eye y=-0.8 后方更远），仍标记 visible
        layout["containers"][0]["slots"][1]["position_3d"] = {"x": 0.55, "y": -2.5, "z": 0.25}
        diagnostics = audit_spatial_layout(layout, _cabin_world())
        behind = [d for d in diagnostics if d["code"] == "behind_camera_visible"]
        self.assertEqual(len(behind), 1)
        self.assertEqual(behind[0]["entity_id"], "char_002")

    def test_clean_layout_has_no_behind_camera(self):
        diagnostics = audit_spatial_layout(_cabin_layout(), _cabin_world())
        self.assertEqual(
            [d for d in diagnostics if d["code"] == "behind_camera_visible"],
            [],
        )

    def test_audit_does_not_mutate_input(self):
        layout = _cabin_layout()
        snapshot = copy.deepcopy(layout)
        audit_spatial_layout(layout, _cabin_world())
        self.assertEqual(layout, snapshot)


if __name__ == "__main__":
    unittest.main()
