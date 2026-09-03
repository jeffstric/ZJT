"""Asset library helper unit tests (owner check, staging delete, usage)."""
from unittest.mock import MagicMock

from services.asset_library import (
    ASSET_TYPE_CHARACTERS,
    ASSET_TYPE_LOCATIONS,
    ASSET_TYPE_SCRIPTS,
    attach_usage,
    delete_staging_asset,
    owner_user_id_matches,
)


def test_owner_user_id_matches_int_and_str():
    assert owner_user_id_matches(1383, 1383) is True
    assert owner_user_id_matches('1383', 1383) is True
    assert owner_user_id_matches(1383, '1383') is True
    assert owner_user_id_matches(1, 2) is False
    assert owner_user_id_matches(None, 1) is False


def test_delete_staging_character_uses_resolve(monkeypatch):
    path = MagicMock()
    fm = MagicMock()
    fm.resolve_character_file_path.return_value = path
    monkeypatch.setattr('services.asset_library.get_file_manager', lambda: fm)

    assert delete_staging_asset(ASSET_TYPE_CHARACTERS, '女主', '9', '3') is True
    fm.resolve_character_file_path.assert_called_once_with('女主', '9', '3')
    path.unlink.assert_called_once()


def test_delete_staging_missing_character_returns_false(monkeypatch):
    fm = MagicMock()
    fm.resolve_character_file_path.return_value = None
    monkeypatch.setattr('services.asset_library.get_file_manager', lambda: fm)
    assert delete_staging_asset(ASSET_TYPE_CHARACTERS, '女主', '9', '3') is False


def test_delete_staging_script_uses_episode_key(monkeypatch):
    fm = MagicMock()
    fm.delete_script.return_value = True
    monkeypatch.setattr('services.asset_library.get_file_manager', lambda: fm)
    assert delete_staging_asset(ASSET_TYPE_SCRIPTS, '2', '9', '3') is True
    fm.delete_script.assert_called_once_with('2', '9', '3')


def test_delete_staging_failure_is_swallowed(monkeypatch):
    fm = MagicMock()
    fm.delete_location.side_effect = OSError('disk')
    monkeypatch.setattr('services.asset_library.get_file_manager', lambda: fm)
    assert delete_staging_asset(ASSET_TYPE_LOCATIONS, '客厅', '9', '3') is False


def test_attach_usage_script_counts_storyboards(monkeypatch):
    monkeypatch.setattr(
        'services.asset_library.StoryboardModel.count_by_script_id',
        staticmethod(lambda script_id: 4),
    )
    monkeypatch.setattr(
        'services.asset_library.staging_file_exists',
        lambda *a, **k: True,
    )
    out = attach_usage(
        ASSET_TYPE_SCRIPTS,
        {'id': 12, 'world_id': 3, 'episode_number': 1, 'title': '开端'},
        '9',
    )
    assert out['usage']['storyboard_count'] == 4
    assert out['usage']['staging_file_exists'] is True


def test_attach_usage_location_children_and_parent_name(monkeypatch):
    parent = MagicMock()
    parent.name = '庄园'
    monkeypatch.setattr(
        'services.asset_library.LocationModel.get_children',
        staticmethod(lambda location_id: [1, 2]),
    )
    monkeypatch.setattr(
        'services.asset_library.LocationModel.get_by_id',
        staticmethod(lambda location_id: parent),
    )
    monkeypatch.setattr(
        'services.asset_library.staging_file_exists',
        lambda *a, **k: False,
    )
    out = attach_usage(
        ASSET_TYPE_LOCATIONS,
        {'id': 8, 'world_id': 3, 'name': '客厅', 'parent_id': 1},
        '9',
    )
    assert out['usage']['child_location_count'] == 2
    assert out['parent_name'] == '庄园'
