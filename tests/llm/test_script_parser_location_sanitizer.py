from llm.script_parser import sanitize_parsed_location_references


def test_name_fallback_with_explicit_wrong_parent_does_not_bind_database_id():
    parsed = {
        "locations": [
            {"id": "loc_hotel_b", "name": "酒店B", "location_db_id": 11, "parent_id": None},
            {
                "id": "loc_balcony",
                "name": "套房阳台",
                "location_db_id": None,
                "parent_id": "loc_hotel_b",
            },
        ],
        "shot_groups": [{"shots": [{"location_id": "loc_balcony"}]}],
    }
    db_locations = [
        {"id": 10, "name": "酒店A", "parent_id": None, "children": []},
        {"id": 11, "name": "酒店B", "parent_id": None, "children": []},
        {"id": 20, "name": "套房阳台", "parent_id": 10, "children": []},
    ]

    result = sanitize_parsed_location_references(parsed, db_locations)

    balcony = next(item for item in result["locations"] if item["id"] == "loc_balcony")
    assert balcony["location_db_id"] is None
    assert balcony["parent_id"] == "loc_hotel_b"
    assert result["shot_groups"][0]["shots"][0]["location_id"] == "loc_balcony"


def test_name_fallback_without_explicit_parent_reuses_existing_child():
    parsed = {
        "locations": [
            {
                "id": "loc_balcony",
                "name": "套房阳台",
                "location_db_id": None,
                "parent_id": None,
            }
        ],
        "shot_groups": [],
    }
    db_locations = [
        {
            "id": 10,
            "name": "酒店A",
            "parent_id": None,
            "children": [
                {"id": 20, "name": "套房阳台", "parent_id": 10, "children": []}
            ],
        }
    ]

    result = sanitize_parsed_location_references(parsed, db_locations)

    assert result["locations"][0]["location_db_id"] == 20
    assert result["locations"][0]["parent_id"] is None
