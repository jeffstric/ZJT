"""安全审计 BUG-R2-S1-A7-H2 / A7-H1：FileManager 路径穿越防护测试。

- resolve_character_file_path：name 含路径分隔符/盘符/绝对路径/'..' 时必须拒绝
  （该函数是 delete_staging_asset 与 staging_file_exists 的唯一文件出口，
  修复前候选 1/3 用原始 name 拼接可穿越删除/探测任意 .json）。
- save_script：episode_number 参与输出文件名构造（f"{episode_number}.json"），
  必须与 create_script_json 保持正整数不变量，拒绝字符串穿越。
- mcp_tool.update_script_json：target_episode（含从既有文件读出的
  current_episode）同样必须为正整数。
"""
import json

import pytest

from script_writer_core.file_manager import (
    EntityNameValidationError,
    FileManager,
)


@pytest.mark.parametrize(
    'name',
    [
        '../../evil',                      # 相对穿越（候选 3 主链）
        '../../../web/i18n/locales/zh-CN/common',
        'a/../../b',                       # 混合正常段与穿越段
        '..\\..\\evil',                    # Windows 分隔符
        '/etc/passwd',                     # 绝对路径
        'C:/evil',                         # 盘符
        'C:\\evil',
        '..',                              # 纯 ..
        '../',
    ],
)
def test_resolve_character_file_path_rejects_traversal(tmp_path, name):
    fm = FileManager(base_dir=str(tmp_path))
    assert fm.resolve_character_file_path(name, '1', '1') is None


def test_resolve_character_file_path_accepts_normal_name(tmp_path):
    fm = FileManager(base_dir=str(tmp_path))
    assert fm.save_character('角色A', json.dumps({'name': '角色A'}), '1', '1')
    resolved = fm.resolve_character_file_path('角色A', '1', '1')
    assert resolved is not None
    # 解析结果必须落在 characters/ 目录内
    assert resolved.parent == (
        tmp_path / 'files' / 'script_writer' / '1' / '1' / 'characters'
    )


@pytest.mark.parametrize(
    'episode',
    [
        '../../../../../web/i18n/locales/zh-CN/index',  # 主攻击链
        '2',
        0,
        -1,
        True,     # bool 是 int 子类，必须显式拒绝
        False,
        1.5,
    ],
)
def test_save_script_rejects_non_positive_int_episode(tmp_path, episode):
    fm = FileManager(base_dir=str(tmp_path))
    content = json.dumps({'title': '剧本A', 'episode_number': episode, 'content': ''})
    with pytest.raises(EntityNameValidationError, match='正整数'):
        fm.save_script('剧本A', content, '1', '1')

    scripts_dir = tmp_path / 'files' / 'script_writer' / '1' / '1' / 'scripts'
    assert not list(scripts_dir.glob('*.json'))


def test_save_script_accepts_positive_int_episode(tmp_path):
    fm = FileManager(base_dir=str(tmp_path))
    content = json.dumps({'title': '剧本A', 'episode_number': 3, 'content': ''})
    assert fm.save_script('剧本A', content, '1', '1')
    assert (tmp_path / 'files' / 'script_writer' / '1' / '1' / 'scripts' / '3.json').exists()


def test_update_script_json_rejects_poisoned_episode(tmp_path, monkeypatch):
    """agent 更新路径：episode_number（或既有文件中被投毒的值）非正整数 → success=False"""
    from script_writer_core import mcp_tool

    fm = FileManager(base_dir=str(tmp_path))
    assert fm.save_script(
        '剧本A', json.dumps({'title': '剧本A', 'episode_number': 1, 'content': ''}), '1', '1'
    )
    monkeypatch.setattr(mcp_tool, 'get_file_manager', lambda: fm)

    result = mcp_tool.update_script_json(
        user_id='1', world_id='1', auth_token='tok', title='剧本A',
        episode_number='../../evil',
    )
    assert result['success'] is False
    assert '正整数' in result['error']

    result_bool = mcp_tool.update_script_json(
        user_id='1', world_id='1', auth_token='tok', title='剧本A',
        episode_number=True,
    )
    assert result_bool['success'] is False

    # 既有文件内被投毒的 episode_number 同样不能作为目标文件名
    # （save_script 已拒绝该值，须直接落盘构造被投毒的既有文件）
    scripts_dir = tmp_path / 'files' / 'script_writer' / '1' / '1' / 'scripts'
    poisoned = scripts_dir / '2.json'
    poisoned.write_text(
        json.dumps({'title': '剧本B', 'episode_number': '../stolen', 'content': ''}),
        encoding='utf-8',
    )
    result2 = mcp_tool.update_script_json(
        user_id='1', world_id='1', auth_token='tok', title='剧本B', content='x'
    )
    assert result2['success'] is False
    assert '正整数' in result2['error']
