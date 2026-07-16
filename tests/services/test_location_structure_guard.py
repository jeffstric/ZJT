from services.location_structure_guard import (
    validate_full_location_structure,
    validate_segment_new_roots,
)


def _codes(errors):
    return [error["code"] for error in errors]


def test_segment_rejects_unmatched_new_root_as_hard_gate():
    parsed = {
        "locations": [
            {
                "id": "loc_001",
                "name": "新酒店",
                "location_db_id": None,
                "parent_id": None,
            }
        ]
    }

    errors = validate_segment_new_roots(parsed, [])

    assert _codes(errors) == ["new_root_location_forbidden"]
    assert errors[0]["_hard_gate"] is True
    assert errors[0]["location_id"] == "loc_001"


def test_guard_accepts_location_id_and_location_name_aliases():
    parsed = {
        "locations": [{
            "location_id": "loc_alias",
            "location_name": "别名场景",
            "location_db_id": None,
            "parent_id": None,
        }]
    }

    errors = validate_segment_new_roots(parsed, [])

    assert errors[0]["location_id"] == "loc_alias"
    assert errors[0]["location_name"] == "别名场景"


def test_segment_allows_new_child_whose_parent_may_arrive_from_another_segment():
    parsed = {
        "locations": [
            {
                "id": "loc_child",
                "name": "套房阳台",
                "location_db_id": None,
                "parent_id": "loc_future_parent",
            }
        ]
    }

    assert validate_segment_new_roots(parsed, []) == []


def test_existing_child_with_omitted_parent_reuses_database_hierarchy():
    parsed = {
        "locations": [
            {
                "id": "loc_001",
                "name": "套房阳台",
                "location_db_id": 20,
                "parent_id": None,
            }
        ]
    }
    db_locations = [
        {
            "id": 10,
            "name": "城南酒店",
            "parent_id": None,
            "children": [
                {"id": 20, "name": "套房阳台", "parent_id": 10, "children": []}
            ],
        }
    ]

    assert validate_full_location_structure(parsed, db_locations) == []


def test_existing_location_with_explicit_wrong_parent_reports_conflict():
    parsed = {
        "locations": [
            {"id": "loc_hotel_b", "name": "酒店B", "location_db_id": 11, "parent_id": None},
            {
                "id": "loc_balcony",
                "name": "套房阳台",
                "location_db_id": 20,
                "parent_id": "loc_hotel_b",
            },
        ]
    }
    db_locations = [
        {"id": 10, "name": "酒店A", "parent_id": None, "children": []},
        {"id": 11, "name": "酒店B", "parent_id": None, "children": []},
        {"id": 20, "name": "套房阳台", "parent_id": 10, "children": []},
    ]

    errors = validate_full_location_structure(parsed, db_locations)

    assert _codes(errors) == ["location_parent_conflict"]
    assert errors[0]["expected_parent_db_id"] == 10
    assert errors[0]["actual_parent_db_id"] == 11


def test_full_validation_detects_missing_parent_and_cycle():
    missing_parent = {
        "locations": [
            {
                "id": "loc_child",
                "name": "套房阳台",
                "location_db_id": None,
                "parent_id": "loc_missing",
            }
        ]
    }
    cycle = {
        "locations": [
            {"id": "loc_a", "name": "A", "location_db_id": None, "parent_id": "loc_b"},
            {"id": "loc_b", "name": "B", "location_db_id": None, "parent_id": "loc_a"},
        ]
    }

    assert _codes(validate_full_location_structure(missing_parent, [])) == ["location_parent_invalid"]
    cycle_errors = validate_full_location_structure(cycle, [])
    assert _codes(cycle_errors) == ["location_parent_invalid"]
    assert cycle_errors[0]["reason"] == "cycle"
