# -*- coding: utf-8 -*-
"""资产库服务层单元测试（services/asset_library_service.py）。

不连接数据库：权限判定、成员归一化、扩展名推断、SQL 过滤片段组装、
quota 错误语义。DB 交互经 monkeypatch 替换。
"""
import pytest

from config.constant import AssetLibraryConstants as ALC
from services.asset_library_service import (
    AssetLibraryError,
    _apply_filters,
    _guess_extension,
    _normalize_members,
    _validate_permission,
    can_edit,
    can_view,
)
from model.asset_library import AssetItem


def make_asset(**kw):
    base = dict(
        id=1, user_id=10, group_id=None, asset_type='image', name='a',
        source_url='https://x/1.png', file_path='asset_library/10/a.png',
        file_size=100, view_permission='private', edit_permission='private',
    )
    base.update(kw)
    return AssetItem(**base)


# ============ 权限判定 ============

def test_can_view_owner_always(monkeypatch):
    asset = make_asset(view_permission='private')
    assert can_view(asset, 10) is True
    assert can_view(asset, 11) is False


def test_can_view_public(monkeypatch):
    asset = make_asset(view_permission='public')
    assert can_view(asset, 11) is True


def test_can_view_edit_public_implies_view(monkeypatch):
    # 编辑权限隐含查看权限
    asset = make_asset(view_permission='private', edit_permission='public')
    assert can_view(asset, 11) is True


def test_can_view_specified_member(monkeypatch):
    asset = make_asset(view_permission='specified')
    monkeypatch.setattr(
        'services.asset_library_service._perm_members',
        lambda asset_id: {'view': [11], 'edit': []},
    )
    assert can_view(asset, 11) is True
    assert can_view(asset, 12) is False


def test_can_view_specified_edit_member_implies_view(monkeypatch):
    asset = make_asset(view_permission='private', edit_permission='specified')
    monkeypatch.setattr(
        'services.asset_library_service._perm_members',
        lambda asset_id: {'view': [], 'edit': [12]},
    )
    assert can_view(asset, 12) is True
    assert can_view(asset, 11) is False


def test_can_edit_matrix(monkeypatch):
    monkeypatch.setattr(
        'services.asset_library_service._perm_members',
        lambda asset_id: {'view': [11], 'edit': [12]},
    )
    owner = make_asset(edit_permission='private')
    assert can_edit(owner, 10) is True           # 属主
    assert can_edit(owner, 10, is_admin=True) is True
    assert can_edit(owner, 11) is False          # 仅 view 成员
    assert can_edit(owner, 12) is False          # edit=private 时指定成员无效

    specified = make_asset(edit_permission='specified')
    assert can_edit(specified, 12) is True       # edit 指定成员
    assert can_edit(specified, 11) is False      # view 成员不可编辑

    public = make_asset(edit_permission='public')
    assert can_edit(public, 99) is True


# ============ 参数校验 ============

def test_validate_permission_rejects_invalid():
    with pytest.raises(AssetLibraryError):
        _validate_permission('everyone', '查看权限')
    assert _validate_permission('public', '查看权限') == 'public'


def test_normalize_members_dedup_and_limit():
    assert _normalize_members([3, '3', 5, 0, None]) == [3, 5]
    assert _normalize_members([]) == []
    with pytest.raises(AssetLibraryError):
        _normalize_members('abc')
    with pytest.raises(AssetLibraryError):
        _normalize_members(list(range(1, 52)))  # 51 个正整数 → 超过 50 人上限


def test_guess_extension_from_url_and_content_type():
    assert _guess_extension('https://x.com/a/b.png?token=1') == '.png'
    assert _guess_extension('/upload/x/y.JPG') == '.jpg'  # 白名单小写匹配
    assert _guess_extension('https://x.com/get', 'image/webp') == '.webp'
    assert _guess_extension('https://x.com/get') == '.png'  # 兜底


# ============ SQL 过滤片段 ============

def test_visible_where_params():
    from services.asset_library_service import _visible_where
    where, params = _visible_where(7)
    assert params == [7, 7]
    assert 'a.user_id = %s' in where
    assert "a.view_permission = 'public'" in where
    assert 'asset_permission_member' in where


def test_apply_filters_ungrouped_sentinel():
    params = []
    filters = _apply_filters(params, group_id='ungrouped')
    assert 'a.group_id IS NULL' in filters
    assert params == []  # 哨兵不产生绑定参数


def test_apply_filters_group_keyword_scope():
    params = []
    filters = _apply_filters(params, group_id=5, keyword=' 主图 ', scope='mine', owner_user_id=9)
    assert 'a.group_id = %s' in filters
    assert 'a.name LIKE %s' in filters
    assert 'a.user_id = %s' in filters
    assert params == [5, '%主图%', 9]


def test_apply_filters_shared_scope_excludes_owner():
    params = []
    filters = _apply_filters(params, scope='shared', owner_user_id=9)
    assert 'a.user_id != %s' in filters
    assert params == [9]


def test_apply_filters_empty_returns_empty_string():
    assert _apply_filters([]) == ''


# ============ 入库主链路（本地复制 + 配额预留 + 失败回滚） ============

import asyncio
import os
from pathlib import Path
from types import SimpleNamespace

from services import asset_library_service as svc
from utils.project_path import get_upload_subdir
from config.constant import UploadPathConstants


def _prepare_local_source(monkeypatch, content: bytes):
    """在 upload/temp 下造一个真实源文件，返回其 /upload 访问路径。"""
    src_dir = Path(get_upload_subdir('temp', 'al_test'))
    src = src_dir / 'src_e2e.png'
    src.write_bytes(content)
    rel = str(src.relative_to(Path(get_upload_subdir()))).replace(os.sep, '/')
    return f'/upload/{rel}'


def _mock_models(monkeypatch, reserve_ok=True):
    calls = {'create': None, 'reserve': [], 'release': [], 'members': []}
    monkeypatch.setattr(svc.AssetGroupModel, 'get_by_id',
                        staticmethod(lambda gid: SimpleNamespace(id=gid)))
    monkeypatch.setattr(svc.AssetLibraryQuotaModel, 'ensure_for_user',
                        staticmethod(lambda uid, **kw: None))
    monkeypatch.setattr(svc.AssetLibraryQuotaModel, 'try_reserve',
                        staticmethod(lambda uid, size: (calls['reserve'].append((uid, size)), reserve_ok)[1]))
    monkeypatch.setattr(svc.AssetLibraryQuotaModel, 'release',
                        staticmethod(lambda uid, size: calls['release'].append((uid, size))))
    monkeypatch.setattr(svc.AssetLibraryModel, 'create',
                        staticmethod(lambda **kw: (calls.__setitem__('create', kw), 1)[1]))
    monkeypatch.setattr(svc.AssetLibraryModel, 'get_by_id',
                        staticmethod(lambda aid: AssetItem(id=aid, user_id=1, name='t',
                                                           file_path=calls['create']['file_path'],
                                                           file_size=calls['create']['file_size'])))
    monkeypatch.setattr(svc.AssetPermissionMemberModel, 'replace_for_asset',
                        staticmethod(lambda *a, **k: calls['members'].append(a)))
    return calls


def _cleanup_asset_dir(user_id=1):
    user_dir = Path(get_upload_subdir(UploadPathConstants.ASSET_LIBRARY_DIR, str(user_id), ensure=False))
    if user_dir.exists():
        for f in user_dir.glob('asset_1_*'):
            f.unlink()
        for f in user_dir.glob('.tmp_*'):
            f.unlink()


def test_add_asset_local_copy_success(monkeypatch):
    payload = b'PNGDATA' * 10
    url = _prepare_local_source(monkeypatch, payload)
    calls = _mock_models(monkeypatch)
    try:
        asset = asyncio.run(svc.add_asset(user_id=1, source_url=url, name='主图'))
        assert asset.file_size == len(payload)
        assert calls['create']['file_size'] == len(payload)
        assert calls['create']['file_path'].startswith('asset_library/1/asset_1_')
        assert calls['create']['file_path'].endswith('.png')
        assert calls['reserve'] == [(1, len(payload))]
        assert calls['release'] == []  # 成功路径不回滚
        # 文件真实落盘且内容一致
        local = Path(get_upload_subdir()).joinpath(*calls['create']['file_path'].split('/'))
        assert local.exists() and local.read_bytes() == payload
        # 指定成员写入两次（view/edit），属主被剔除语义在模型层单测覆盖
        assert len(calls['members']) == 2
    finally:
        _cleanup_asset_dir()


def test_add_asset_quota_exceeded_rolls_back_file(monkeypatch):
    payload = b'X' * 33
    url = _prepare_local_source(monkeypatch, payload)
    calls = _mock_models(monkeypatch, reserve_ok=False)
    try:
        with pytest.raises(AssetLibraryError) as ei:
            asyncio.run(svc.add_asset(user_id=1, source_url=url, name='x'))
        assert ei.value.code == 'quota_exceeded'
        assert calls['create'] is None      # 未落库
        user_dir = Path(get_upload_subdir(UploadPathConstants.ASSET_LIBRARY_DIR, '1', ensure=False))
        leftovers = list(user_dir.glob('asset_1_*')) + list(user_dir.glob('.tmp_*')) if user_dir.exists() else []
        assert leftovers == []              # 临时文件已清理
    finally:
        _cleanup_asset_dir()


def test_add_asset_rejects_relative_upload_path_when_missing(monkeypatch):
    # /upload/ 路径但本地文件不存在 → 明确 source_missing，而非走 aiohttp 下载相对路径
    with pytest.raises(AssetLibraryError) as ei:
        asyncio.run(svc.add_asset(user_id=1, source_url='/upload/temp/al_test/not_exist.png', name='x'))
    assert ei.value.code == 'source_missing'


# ============ 第三轮修复回归 ============

def test_get_asset_detail_admin_can_view_private(monkeypatch):
    # admin 查看他人 private 资产：is_admin 放行（此前 update_asset 后返回详情会 404）
    other_private = make_asset(user_id=10, view_permission='private', edit_permission='private')
    monkeypatch.setattr(svc.AssetLibraryModel, 'get_by_id', staticmethod(lambda aid: other_private))
    monkeypatch.setattr(svc, '_perm_members', lambda aid: {'view': [], 'edit': []})
    monkeypatch.setattr(svc.UsersModel, 'get_display_names', staticmethod(lambda ids: {10: '他人'}))
    detail = svc.get_asset_detail(user_id=99, asset_id=1, is_admin=True)
    assert detail['owner_name'] == '他人'
    assert detail['can_edit'] is True
    # 普通用户仍不可见
    with pytest.raises(AssetLibraryError) as ei:
        svc.get_asset_detail(user_id=99, asset_id=1)
    assert ei.value.code == 'not_found'


def test_purge_asset_tolerates_dirty_file_path(monkeypatch):
    # file_path 脏数据（resolve 抛 ValueError）时清除仍成功：记录/配额已清理，不 500
    dirty = make_asset(user_id=10, file_path='../../etc/passwd')
    monkeypatch.setattr(svc.AssetLibraryModel, 'get_by_id', staticmethod(lambda aid: dirty))
    monkeypatch.setattr(svc.AssetLibraryModel, 'delete', staticmethod(lambda aid: 1))
    releases = []
    monkeypatch.setattr(svc.AssetLibraryQuotaModel, 'release',
                        staticmethod(lambda uid, size: releases.append((uid, size))))
    monkeypatch.setattr(svc.AssetPermissionMemberModel, 'delete_for_asset',
                        staticmethod(lambda aid: None))
    result = svc.purge_asset(1)
    assert result['freed_bytes'] == 100
    assert releases == [(10, 100)]


def test_search_users_uses_nickname_channel_only(monkeypatch):
    # 成员搜索仅走昵称通道（手机号/邮箱精确匹配可枚举注册用户，禁用）
    calls = {'nickname': [], 'account': []}
    monkeypatch.setattr(svc.UsersModel, 'find_ids_by_nickname',
                        staticmethod(lambda q, limit=20: (calls['nickname'].append(q), [3])[1]))
    monkeypatch.setattr(svc.UsersModel, 'find_ids_by_nickname_or_account',
                        staticmethod(lambda q, limit=20: (calls['account'].append(q), [])[1]))
    monkeypatch.setattr(svc.UsersModel, 'get_display_names', staticmethod(lambda ids: {3: '张三'}))
    result = svc.search_users('张')
    assert result == [{'user_id': 3, 'display_name': '张三'}]
    assert calls['nickname'] == ['张']
    assert calls['account'] == []  # 账号通道未被触碰


def test_count_by_group_sql_has_group_by(monkeypatch):
    # 回归：无 GROUP BY 时 MySQL 聚合对空组返回单行 (NULL,0)，int(None) 崩溃（真实环境抓到）
    from model import asset_library as asset_model
    captured = {}

    def fake_query(sql, params, fetch_all=True, **kw):
        captured['sql'] = sql
        # 模拟带 GROUP BY 的正确行为：空组返回 0 行
        return []

    monkeypatch.setattr(asset_model, 'execute_query', staticmethod(fake_query))
    assert asset_model.AssetLibraryModel.count_by_group([7]) == {}
    assert 'GROUP BY group_id' in captured['sql']
