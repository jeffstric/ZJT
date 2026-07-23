from pathlib import Path
import sys

from starlette.routing import Match

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from api.storyboard import router


def test_storyboard_models_route_is_not_captured_by_storyboard_id_route():
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/storyboard/models",
        "root_path": "",
        "path_params": {},
    }

    matches = [
        (route, child_scope)
        for route in router.routes
        for match, child_scope in [route.matches(scope)]
        if match == Match.FULL
    ]

    assert matches
    route, child_scope = matches[0]
    assert route.name == "get_storyboard_models"
    assert child_scope.get("path_params") == {}
