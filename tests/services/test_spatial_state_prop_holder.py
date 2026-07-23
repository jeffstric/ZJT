"""空间状态机：道具持有关系兼容与 enter-held 语义。

Community CI does not ship the `enterprise` package (gitignored). Skip cleanly
when the module is unavailable so services discovery still succeeds.
"""
import importlib.util
import unittest

_HAS_ENTERPRISE_SPATIAL_STATE = (
    importlib.util.find_spec("enterprise") is not None
    and importlib.util.find_spec(
        "enterprise.services.script_split_quality.spatial_state"
    )
    is not None
)

if _HAS_ENTERPRISE_SPATIAL_STATE:
    from enterprise.services.script_split_quality.spatial_state import (
        SpatialCatalog,
        apply_spatial_intent,
        normalize_initial_state,
    )


def _catalog():
    plan = {
        "compiled_registry": {
            "characters": [
                {"id": "char_001", "name": "林晓"},
                {"id": "char_003", "name": "赵先生"},
            ],
            "locations": [{"id": "loc_001", "name": "大堂"}],
            "props": [
                {"id": "prop_002", "name": "公文包"},
                {"id": "prop_003", "name": "桂花糕"},
            ],
            "spatial_world": {
                "space_units": [
                    {
                        "space_unit_id": "space_unit:lobby",
                        "containers": [
                            {
                                "container_id": "container:front_desk",
                                "slots": [
                                    {"slot_id": "guest_side"},
                                    {"slot_id": "staff_side"},
                                    {"slot_id": "counter_surface"},
                                    {"slot_id": "drawer"},
                                ],
                            }
                        ],
                        "anchors": [
                            {"anchor_id": "anchor:lobby_entrance"},
                        ],
                    }
                ]
            },
        }
    }
    return SpatialCatalog.from_plan(plan)


def _initial(catalog):
    raw = {
        "entities": {
            "char_001": {
                "entity_type": "character",
                "presence": "present",
                "space_unit_id": "space_unit:lobby",
                "container_id": "container:front_desk",
                "slot_id": "staff_side",
            },
            "prop_003": {
                "entity_type": "prop",
                "presence": "present",
                "space_unit_id": "space_unit:lobby",
                "container_id": "container:front_desk",
                "slot_id": "drawer",
            },
        }
    }
    state, diags = normalize_initial_state(raw, catalog)
    assert diags == []
    return state


def _error_codes(diags):
    return [d["code"] for d in diags if d.get("severity") == "error"]


@unittest.skipUnless(
    _HAS_ENTERPRISE_SPATIAL_STATE,
    "enterprise.services.script_split_quality.spatial_state not available",
)
class TestSpatialStatePropHolder(unittest.TestCase):
    def test_enter_prop_with_top_level_holder_is_held(self):
        """task 49 s003 形态：enter 公文包 + 顶层 holder。"""
        catalog = _catalog()
        state = {
            "schema_version": 1,
            "entities": {
                "char_003": {
                    "entity_type": "character",
                    "presence": "present",
                    "space_unit_id": "space_unit:lobby",
                    "anchor_id": "anchor:lobby_entrance",
                }
            },
        }
        intent = {
            "state_changes": [
                {
                    "entity_type": "prop",
                    "entity_id": "prop_002",
                    "operation": "enter",
                    "to": {
                        "space_unit_id": "space_unit:lobby",
                        "anchor_id": "anchor:lobby_entrance",
                    },
                    "holder_character_id": "char_003",
                }
            ]
        }
        state, diags = apply_spatial_intent(state, intent, catalog)
        self.assertEqual(_error_codes(diags), [])
        prop = state["entities"]["prop_002"]
        self.assertEqual(prop["holder_character_id"], "char_003")
        self.assertEqual(prop["presence"], "present")

    def test_put_down_after_enter_held_succeeds(self):
        catalog = _catalog()
        state = {
            "schema_version": 1,
            "entities": {
                "char_003": {
                    "entity_type": "character",
                    "presence": "present",
                    "space_unit_id": "space_unit:lobby",
                    "container_id": "container:front_desk",
                    "slot_id": "guest_side",
                },
                "prop_002": {
                    "entity_type": "prop",
                    "presence": "present",
                    "holder_character_id": "char_003",
                    "space_unit_id": "space_unit:lobby",
                },
            },
        }
        intent = {
            "state_changes": [
                {
                    "entity_type": "prop",
                    "entity_id": "prop_002",
                    "operation": "put_down",
                    "from": {
                        "holder_character_id": "char_003",
                        "slot_id": "guest_side",
                    },
                    "to": {
                        "space_unit_id": "space_unit:lobby",
                        "container_id": "container:front_desk",
                        "slot_id": "counter_surface",
                    },
                }
            ]
        }
        state, diags = apply_spatial_intent(state, intent, catalog)
        self.assertEqual(_error_codes(diags), [])
        prop = state["entities"]["prop_002"]
        self.assertIn(prop.get("holder_character_id"), (None, ""))
        self.assertEqual(prop["slot_id"], "counter_surface")

    def test_pickup_accepts_top_level_holder_character_id(self):
        """task 49 s010 形态：holder 写在顶层，to 只有物理 slot。"""
        catalog = _catalog()
        state = _initial(catalog)
        intent = {
            "state_changes": [
                {
                    "entity_type": "prop",
                    "entity_id": "prop_003",
                    "operation": "pickup",
                    "from": {
                        "space_unit_id": "space_unit:lobby",
                        "container_id": "container:front_desk",
                        "slot_id": "drawer",
                    },
                    "to": {
                        "space_unit_id": "space_unit:lobby",
                        "container_id": "container:front_desk",
                        "slot_id": "staff_side",
                    },
                    "holder_character_id": "char_001",
                }
            ]
        }
        state, diags = apply_spatial_intent(state, intent, catalog)
        self.assertEqual(_error_codes(diags), [])
        self.assertEqual(state["entities"]["prop_003"]["holder_character_id"], "char_001")

    def test_transfer_accepts_top_level_target_holder(self):
        """task 49 s012 形态：to 无 holder，顶层写接收方。"""
        catalog = _catalog()
        state = _initial(catalog)
        state["entities"]["char_003"] = {
            "entity_type": "character",
            "presence": "present",
            "space_unit_id": "space_unit:lobby",
            "container_id": "container:front_desk",
            "slot_id": "guest_side",
        }
        state["entities"]["prop_003"]["holder_character_id"] = "char_001"
        state["entities"]["prop_003"].pop("container_id", None)
        state["entities"]["prop_003"].pop("slot_id", None)

        intent = {
            "state_changes": [
                {
                    "entity_type": "prop",
                    "entity_id": "prop_003",
                    "operation": "transfer",
                    "from": {
                        "holder_character_id": "char_001",
                        "slot_id": "staff_side",
                    },
                    "to": {
                        "space_unit_id": "space_unit:lobby",
                        "container_id": "container:front_desk",
                        "slot_id": "guest_side",
                    },
                    "holder_character_id": "char_003",
                }
            ]
        }
        state, diags = apply_spatial_intent(state, intent, catalog)
        self.assertEqual(_error_codes(diags), [])
        self.assertEqual(state["entities"]["prop_003"]["holder_character_id"], "char_003")

    def test_task49_style_sequence_passes_end_to_end(self):
        """回放 task 49 段1 关键 intent 链：enter-held → put_down → pickup 顶层 → transfer 顶层。"""
        catalog = _catalog()
        state = _initial(catalog)

        steps = [
            {
                "state_changes": [
                    {
                        "entity_type": "character",
                        "entity_id": "char_003",
                        "operation": "enter",
                        "to": {
                            "space_unit_id": "space_unit:lobby",
                            "anchor_id": "anchor:lobby_entrance",
                        },
                    },
                    {
                        "entity_type": "prop",
                        "entity_id": "prop_002",
                        "operation": "enter",
                        "to": {
                            "space_unit_id": "space_unit:lobby",
                            "anchor_id": "anchor:lobby_entrance",
                        },
                        "holder_character_id": "char_003",
                    },
                ]
            },
            {
                "state_changes": [
                    {
                        "entity_type": "character",
                        "entity_id": "char_003",
                        "operation": "move",
                        "to": {
                            "space_unit_id": "space_unit:lobby",
                            "container_id": "container:front_desk",
                            "slot_id": "guest_side",
                        },
                    },
                    {
                        "entity_type": "prop",
                        "entity_id": "prop_002",
                        "operation": "move",
                        "from": {"holder_character_id": "char_003"},
                        "to": {
                            "space_unit_id": "space_unit:lobby",
                            "container_id": "container:front_desk",
                            "slot_id": "guest_side",
                        },
                        "holder_character_id": "char_003",
                    },
                ]
            },
            {
                "state_changes": [
                    {
                        "entity_type": "prop",
                        "entity_id": "prop_002",
                        "operation": "put_down",
                        "from": {"holder_character_id": "char_003"},
                        "to": {
                            "space_unit_id": "space_unit:lobby",
                            "container_id": "container:front_desk",
                            "slot_id": "counter_surface",
                        },
                    }
                ]
            },
            {
                "state_changes": [
                    {
                        "entity_type": "prop",
                        "entity_id": "prop_003",
                        "operation": "pickup",
                        "to": {
                            "space_unit_id": "space_unit:lobby",
                            "container_id": "container:front_desk",
                            "slot_id": "staff_side",
                        },
                        "holder_character_id": "char_001",
                    }
                ]
            },
            {
                "state_changes": [
                    {
                        "entity_type": "prop",
                        "entity_id": "prop_003",
                        "operation": "transfer",
                        "from": {"holder_character_id": "char_001"},
                        "to": {
                            "space_unit_id": "space_unit:lobby",
                            "container_id": "container:front_desk",
                            "slot_id": "guest_side",
                        },
                        "holder_character_id": "char_003",
                    }
                ]
            },
        ]

        all_errors = []
        for intent in steps:
            state, diags = apply_spatial_intent(state, intent, catalog)
            all_errors.extend(_error_codes(diags))

        self.assertEqual(all_errors, [])
        self.assertIn(
            state["entities"]["prop_002"].get("holder_character_id"), (None, "")
        )
        self.assertEqual(state["entities"]["prop_002"]["slot_id"], "counter_surface")
        self.assertEqual(state["entities"]["prop_003"]["holder_character_id"], "char_003")
