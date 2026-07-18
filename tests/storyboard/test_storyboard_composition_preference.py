from api import storyboard as storyboard_api
from model import storyboard as storyboard_model


class _WorldWithComposition:
    visual_style = "cinematic"
    composition_preference = "center composition, low angle"


def test_build_storyboard_defaults_inherits_composition_preference():
    defaults = storyboard_api.build_storyboard_defaults(_WorldWithComposition(), {})

    assert defaults["composition_preference"] == "center composition, low angle"


def test_storyboard_create_table_sql_contains_composition_preference():
    assert "`composition_preference` VARCHAR(500)" in storyboard_model.CREATE_TABLE_SQL
