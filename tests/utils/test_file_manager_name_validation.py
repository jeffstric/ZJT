"""角色、场景、剧本名称的跨平台文件名校验测试。"""
import json

import pytest

from script_writer_core.file_manager import (
    EntityNameValidationError,
    FileManager,
    validate_entity_name,
)


@pytest.mark.parametrize('char', ['<', '>', ':', '"', '/', '\\', '|', '?', '*', '\x00', '\x1f'])
def test_validate_entity_name_rejects_invalid_filename_chars(char):
    with pytest.raises(EntityNameValidationError, match='不能包含'):
        validate_entity_name(f'A{char}B', '角色名称')


@pytest.mark.parametrize('name', ['', '   ', '.', '..', 'name.', 'name '])
def test_validate_entity_name_rejects_empty_and_invalid_endings(name):
    with pytest.raises(EntityNameValidationError):
        validate_entity_name(name, '场景名称')


def test_validate_entity_name_accepts_and_trims_normal_name():
    assert validate_entity_name('  角色 A', '角色名称') == '角色 A'
    assert len(validate_entity_name('名' * 200, '角色名称')) == 200
    with pytest.raises(EntityNameValidationError, match='200'):
        validate_entity_name('名' * 201, '角色名称')


def test_character_and_location_reject_invalid_content_name(tmp_path):
    fm = FileManager(base_dir=str(tmp_path))
    for save, name in ((fm.save_character, 'A/B'), (fm.save_location, 'A\\B')):
        with pytest.raises(EntityNameValidationError):
            save(name, json.dumps({'name': name}), '1', '1')

    base = tmp_path / 'files' / 'script_writer' / '1' / '1'
    assert not list((base / 'characters').glob('*.json'))
    assert not list((base / 'locations').glob('*.json'))


def test_script_rejects_invalid_title_even_with_episode_filename(tmp_path):
    fm = FileManager(base_dir=str(tmp_path))
    content = json.dumps({'title': '第1/2集', 'episode_number': 1, 'content': ''})

    with pytest.raises(EntityNameValidationError, match='剧本标题'):
        fm.save_script('1', content, '1', '1')

    scripts_dir = tmp_path / 'files' / 'script_writer' / '1' / '1' / 'scripts'
    assert not list(scripts_dir.glob('*.json'))


def test_character_location_and_script_accept_valid_names(tmp_path):
    fm = FileManager(base_dir=str(tmp_path))
    assert fm.save_character('角色A', json.dumps({'name': '角色A'}), '1', '1')
    assert fm.save_location('场景A', json.dumps({'name': '场景A'}), '1', '1')
    assert fm.save_script(
        '1', json.dumps({'title': '剧本 A', 'episode_number': 1, 'content': ''}), '1', '1'
    )

    base = tmp_path / 'files' / 'script_writer' / '1' / '1'
    assert (base / 'characters' / 'character_角色A.json').is_file()
    assert (base / 'locations' / 'location_场景A.json').is_file()
    assert (base / 'scripts' / '1.json').is_file()
