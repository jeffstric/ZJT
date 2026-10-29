# -*- coding: utf-8 -*-
"""资产库服务层单元测试（services/asset_library_service.py）。

不连接数据库：权限判定、成员归一化、扩展名推断、SQL 过滤片段组装、
quota 错误语义。DB 交互经 monkeypatch 替换。
"""
import os
import shutil
import tempfile

import pytest

from config.constant import AssetLibraryConstants as ALC
from services.asset_library_service import (
    AssetLibraryError,
    _apply_filters,
    _guess_extension,
    _normalize_members,
    _validate_permission,
    can_delete,
    can_edit,
    can_view,
)
from model.asset_library import AssetItem, AssetLibraryModel


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


def test_can_delete_matrix():
    # 删除：仅属主 / 管理员；不受 public/specified 编辑权限影响
    asset = make_asset(edit_permission='public')
    assert can_delete(asset, 10) is True            # 属主
    assert can_delete(asset, 10, is_admin=True) is True
    assert can_delete(asset, 99) is False           # 他人（即便 edit=public）
    assert can_delete(asset, 99, is_admin=True) is True
    specified = make_asset(edit_permission='specified')
    assert can_delete(specified, 12) is False       # edit 指定成员也不可删除


# ============ 文件完整性 ============

def test_asset_file_exists(monkeypatch):
    from services.asset_library_service import asset_file_exists

    existing = {'asset_library/1/ok.png'}
    monkeypatch.setattr(os.path, 'isfile', lambda p: p in existing)
    # 脏路径：真实 resolve 抛 ValueError → 按缺失处理，不向上抛
    assert asset_file_exists('../../etc/passwd') is False
    assert asset_file_exists('') is False
    assert asset_file_exists(None) is False
    # 正常路径：resolve 映射到 upload 根下后按 isfile 判定
    monkeypatch.setattr(svc, 'resolve_upload_url_to_local_path', lambda p: p)
    assert asset_file_exists('asset_library/1/ok.png') is True
    assert asset_file_exists('asset_library/1/gone.png') is False


def test_verify_asset_files_lists_missing(monkeypatch):
    from services.asset_library_service import verify_asset_files

    rows = [
        {'id': 1, 'file_path': 'asset_library/1/a.png'},
        {'id': 2, 'file_path': 'asset_library/1/b.png'},
        {'id': 3, 'file_path': 'asset_library/1/c.png'},
    ]
    monkeypatch.setattr(svc, 'execute_query', staticmethod(lambda *a, **kw: rows))
    monkeypatch.setattr(
        svc, 'asset_file_exists',
        staticmethod(lambda p: any(f"asset_library/1/{n}.png" == p for n in ('a', 'c'))),
    )
    result = verify_asset_files()
    assert result['total'] == 3
    assert result['missing'] == [2]


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


# ============ lite 列表（@ 提及轻量模式） ============

def test_list_assets_lite_shape_and_pagination(monkeypatch):
    """lite 模式：不做 COUNT、不查属主/成员/文件存在性；条目精简 + has_more 探测。"""
    rows_page2 = [
        {"id": 1, "name": "A", "file_path": "asset_library/1/a.png", "group_id": 3},
    ]
    captured = []

    def fake_query(sql, params=(), fetch_one=False, fetch_all=False):
        captured.append((" ".join(sql.split()), tuple(params)))
        # page_size=1 + 探测 1 条 → 返回 2 行表示还有第二页
        return [
            {"id": 2, "name": "B", "file_path": "asset_library/1/b.png", "group_id": None},
            rows_page2[0],
        ]

    monkeypatch.setattr(svc, 'execute_query', staticmethod(fake_query))

    def _forbidden(*a, **kw):
        raise AssertionError("lite 模式不应触发属主/成员映射/文件存在性检查")

    monkeypatch.setattr(svc.UsersModel, 'get_display_names', staticmethod(_forbidden))
    monkeypatch.setattr(svc.AssetPermissionMemberModel, 'map_by_assets', staticmethod(_forbidden))
    monkeypatch.setattr(svc, 'asset_file_exists', _forbidden)

    result = svc.list_assets(user_id=7, page=1, page_size=1, lite=True)

    # 只有一条列表查询：无 COUNT(*)；LIMIT=page_size+1（has_more 探测）
    assert len(captured) == 1
    sql, params = captured[0]
    assert "COUNT(*)" not in sql
    assert params[-2:] == (2, 0)

    assert result["has_more"] is True
    assert result["items"] == [
        {"id": 2, "name": "B", "file_url": "/upload/asset_library/1/b.png", "group_id": None},
    ]
    assert "can_edit" not in result["items"][0]
    assert "owner_name" not in result["items"][0]


def test_list_assets_lite_last_page_has_more_false(monkeypatch):
    monkeypatch.setattr(svc, 'execute_query', staticmethod(
        lambda sql, params=(), fetch_one=False, fetch_all=False: [
            {"id": 1, "name": "A", "file_path": "asset_library/1/a.png", "group_id": None},
        ]
    ))
    result = svc.list_assets(user_id=7, page=1, page_size=2, lite=True)
    assert result["has_more"] is False
    assert len(result["items"]) == 1


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


def _mock_models(monkeypatch, reserve_ok=True, feature=None):
    calls = {'create': None, 'reserve': [], 'release': [], 'members': [], 'deleted': []}
    monkeypatch.setattr(svc, 'get_feature_config', lambda: feature or {
        'enabled': True, 'allow_all_users': True, 'total_quota_bytes': 0})
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
    monkeypatch.setattr(svc.AssetLibraryModel, 'delete',
                        staticmethod(lambda aid: calls['deleted'].append(aid)))
    monkeypatch.setattr(svc.AssetPermissionMemberModel, 'replace_for_asset',
                        staticmethod(lambda *a, **k: calls['members'].append(a)))
    return calls


@pytest.fixture
def asset_tmp_dir(monkeypatch):
    """把资产库存放根重定向到独立临时目录（yield 其路径，结束后整目录删除）。

    回归防护：早期版本在 finally 里 glob 清理生产 upload/asset_library/1/
    （asset_1_*），曾把真实用户资产一并删除；fixture 让测试全程不碰生产目录。
    """
    root = Path(tempfile.mkdtemp(prefix='al_asset_test_'))
    real_get_subdir = svc.get_upload_subdir

    def fake_get_subdir(*parts, ensure=True):
        if parts and parts[0] == UploadPathConstants.ASSET_LIBRARY_DIR:
            target = root.joinpath(*[str(p) for p in parts[1:]])
            if ensure:
                target.mkdir(parents=True, exist_ok=True)
            return str(target)
        return real_get_subdir(*parts, ensure=ensure)

    monkeypatch.setattr(svc, 'get_upload_subdir', fake_get_subdir)
    yield root
    shutil.rmtree(root, ignore_errors=True)


def test_add_asset_local_copy_success(monkeypatch, asset_tmp_dir):
    payload = b'PNGDATA' * 10
    url = _prepare_local_source(monkeypatch, payload)
    calls = _mock_models(monkeypatch)
    asset = asyncio.run(svc.add_asset(user_id=1, source_url=url, name='主图'))
    assert asset.file_size == len(payload)
    assert calls['create']['file_size'] == len(payload)
    assert calls['create']['file_path'].startswith('asset_library/1/asset_1_')
    assert calls['create']['file_path'].endswith('.png')
    assert calls['reserve'] == [(1, len(payload))]
    assert calls['release'] == []  # 成功路径不回滚
    # 文件真实落盘且内容一致（落点已被 fixture 重定向到临时目录）
    local = asset_tmp_dir.joinpath(*calls['create']['file_path'].split('/')[1:])
    assert local.exists() and local.read_bytes() == payload
    # 指定成员写入两次（view/edit），属主被剔除语义在模型层单测覆盖
    assert len(calls['members']) == 2


def test_add_asset_quota_exceeded_rolls_back_file(monkeypatch, asset_tmp_dir):
    payload = b'X' * 33
    url = _prepare_local_source(monkeypatch, payload)
    calls = _mock_models(monkeypatch, reserve_ok=False)
    with pytest.raises(AssetLibraryError) as ei:
        asyncio.run(svc.add_asset(user_id=1, source_url=url, name='x'))
    assert ei.value.code == 'quota_exceeded'
    assert calls['create'] is None      # 未落库
    user_dir = asset_tmp_dir / '1'
    leftovers = list(user_dir.glob('asset_1_*')) + list(user_dir.glob('.tmp_*')) if user_dir.exists() else []
    assert leftovers == []              # 临时文件已清理


def test_add_asset_members_failure_rolls_back_quota_and_row(monkeypatch, asset_tmp_dir):
    """落库后写成员失败：删除已插入行并释放配额，避免重试重复扣配额。"""
    payload = b'ROLLBACK' * 4
    url = _prepare_local_source(monkeypatch, payload)
    calls = _mock_models(monkeypatch)

    def boom(*_args, **_kwargs):
        raise RuntimeError('members fail')

    monkeypatch.setattr(svc.AssetPermissionMemberModel, 'replace_for_asset', boom)
    with pytest.raises(AssetLibraryError) as ei:
        asyncio.run(svc.add_asset(user_id=1, source_url=url, name='x'))
    assert ei.value.code == 'add_failed'
    assert calls['reserve'] == [(1, len(payload))]
    assert calls['release'] == [(1, len(payload))]
    assert calls['deleted'] == [1]
    user_dir = asset_tmp_dir / '1'
    leftovers = list(user_dir.glob('asset_1_*')) + list(user_dir.glob('.tmp_*')) if user_dir.exists() else []
    assert leftovers == []


def test_add_asset_rejects_relative_upload_path_when_missing(monkeypatch):
    # /upload/ 路径但本地文件不存在 → 明确 source_missing，而非走 aiohttp 下载相对路径
    _mock_models(monkeypatch)  # 放行功能开关（该用例只关注 source_missing 语义）
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
    assert detail['can_delete'] is True
    # 普通用户仍不可见
    with pytest.raises(AssetLibraryError) as ei:
        svc.get_asset_detail(user_id=99, asset_id=1)
    assert ei.value.code == 'not_found'


def test_purge_asset_owner_and_admin_allowed(monkeypatch):
    # 属主可删自己的资产；管理员可删他人资产（删除后释放属主配额）
    asset = make_asset(user_id=10, file_path='')  # file_path 置空：跳过文件删除分支
    monkeypatch.setattr(svc.AssetLibraryModel, 'get_by_id', staticmethod(lambda aid: asset))
    monkeypatch.setattr(svc.AssetLibraryModel, 'delete', staticmethod(lambda aid: 1))
    releases = []
    monkeypatch.setattr(svc.AssetLibraryQuotaModel, 'release',
                        staticmethod(lambda uid, size: releases.append((uid, size))))
    monkeypatch.setattr(svc.AssetPermissionMemberModel, 'delete_for_asset',
                        staticmethod(lambda aid: None))

    result = svc.purge_asset(1, user_id=10)
    assert result['owner_user_id'] == 10
    assert releases == [(10, 100)]

    result = svc.purge_asset(1, user_id=99, is_admin=True)
    assert result['owner_user_id'] == 10
    assert releases == [(10, 100), (10, 100)]


def test_purge_asset_forbidden_for_non_owner(monkeypatch):
    # 非属主非管理员不可删除（即便 edit=public 也不行）
    asset = make_asset(user_id=10, edit_permission='public')
    monkeypatch.setattr(svc.AssetLibraryModel, 'get_by_id', staticmethod(lambda aid: asset))
    with pytest.raises(AssetLibraryError) as ei:
        svc.purge_asset(1, user_id=99)
    assert ei.value.code == 'forbidden'


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
    result = svc.purge_asset(1, user_id=10)
    assert result['freed_bytes'] == 100
    assert releases == [(10, 100)]


def test_search_user_exact_hit_and_miss(monkeypatch):
    # 指定成员：完整账号精确查找，命中返回用户、未命中返回 None（前端据此提示）
    calls = {'exact': []}
    monkeypatch.setattr(svc.UsersModel, 'find_id_by_exact_account',
                        staticmethod(lambda a: (calls['exact'].append(a), 3 if a == '13800000000' else None)[1]))
    monkeypatch.setattr(svc.UsersModel, 'get_display_names', staticmethod(lambda ids: {3: '张三'}))

    hit = svc.search_user_exact('13800000000')
    assert hit == {'user_id': 3, 'display_name': '张三'}
    assert calls['exact'] == ['13800000000']

    assert svc.search_user_exact('不存在账号') is None
    assert svc.search_user_exact('   ') is None  # 空白不触发查找（模型层短路）


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


def test_update_group_id_null_reaches_sql(monkeypatch):
    # 回归（5轮测试抓到）：group_id 显式 None = 移回未分组，必须进 SET 子句；
    # 旧实现 is not None 过滤把它静默丢弃。其余字段 None 仍跳过。
    from model import asset_library as asset_model
    captured = {}

    def fake_update(sql, params):
        captured['sql'] = sql
        captured['params'] = params
        return 1

    monkeypatch.setattr(asset_model, 'execute_update', staticmethod(fake_update))
    AssetLibraryModel.update(5, group_id=None, name=None)
    assert 'group_id = %s' in captured['sql']
    assert 'name = %s' not in captured['sql']
    assert captured['params'][0] is None

    AssetLibraryModel.update(5, name='新名')
    assert 'name = %s' in captured['sql']
    assert 'group_id' not in captured['sql']


def test_http_error_group_not_found_maps_404():
    # 回归：分组不存在应 404（与资产 not_found 一致），旧实现落 400
    from api.asset_library import _http_error
    e = AssetLibraryError("分组不存在", "group_not_found")
    assert _http_error(e).status_code == 404
    e2 = AssetLibraryError("资产不存在或无权访问", "not_found")
    assert _http_error(e2).status_code == 404
    e3 = AssetLibraryError("没有该资产的编辑权限", "forbidden")
    assert _http_error(e3).status_code == 403


# ============ 功能开关 / 全局容量（R：admin 资产管理需求） ============

def test_add_asset_blocked_when_feature_disabled(monkeypatch):
    # 总开关关闭：入库直接拒绝（管理员也一样）
    url = _prepare_local_source(monkeypatch, b'disabled')
    calls = _mock_models(monkeypatch, feature={'enabled': False, 'allow_all_users': True, 'total_quota_bytes': 0})
    with pytest.raises(AssetLibraryError) as ei:
        asyncio.run(svc.add_asset(user_id=1, source_url=url, name='x', is_admin=True))
    assert ei.value.code == 'feature_disabled'
    assert calls['create'] is None


def test_add_asset_blocked_without_user_permission(monkeypatch, asset_tmp_dir):
    # 全员模式关闭 + 用户未开启 → 拒绝；开启 → 放行
    url = _prepare_local_source(monkeypatch, b'perm')
    calls = _mock_models(monkeypatch, feature={'enabled': True, 'allow_all_users': False, 'total_quota_bytes': 0})
    monkeypatch.setattr(svc.AssetLibraryQuotaModel, 'is_enabled', staticmethod(lambda uid: False))
    with pytest.raises(AssetLibraryError) as ei:
        asyncio.run(svc.add_asset(user_id=1, source_url=url, name='x'))
    assert ei.value.code == 'user_not_allowed'

    monkeypatch.setattr(svc.AssetLibraryQuotaModel, 'is_enabled', staticmethod(lambda uid: True))
    asset = asyncio.run(svc.add_asset(user_id=1, source_url=url, name='x'))
    assert asset.file_size == len(b'perm')


def test_add_asset_blocked_by_global_capacity(monkeypatch, asset_tmp_dir):
    # 全站总容量：已用+新增超限 → global_quota_exceeded，文件不落库
    url = _prepare_local_source(monkeypatch, b'G' * 50)
    calls = _mock_models(monkeypatch, feature={'enabled': True, 'allow_all_users': True, 'total_quota_bytes': 100})
    monkeypatch.setattr(svc, 'total_used_bytes', lambda: 80)  # 80+50 > 100
    with pytest.raises(AssetLibraryError) as ei:
        asyncio.run(svc.add_asset(user_id=1, source_url=url, name='x'))
    assert ei.value.code == 'global_quota_exceeded'
    assert calls['create'] is None

    monkeypatch.setattr(svc, 'total_used_bytes', lambda: 40)  # 40+50 <= 100
    asset = asyncio.run(svc.add_asset(user_id=1, source_url=url, name='ok'))
    assert asset.file_size == 50


def test_ensure_user_allowed_matrix(monkeypatch):
    cfg_off = {'enabled': False, 'allow_all_users': True, 'total_quota_bytes': 0}
    monkeypatch.setattr(svc, 'get_feature_config', lambda: cfg_off)
    with pytest.raises(AssetLibraryError) as ei:
        svc.ensure_user_allowed(1, is_admin=True)
    assert ei.value.code == 'feature_disabled'  # 开关关闭连管理员也拦

    cfg_on_all = {'enabled': True, 'allow_all_users': True, 'total_quota_bytes': 0}
    monkeypatch.setattr(svc, 'get_feature_config', lambda: cfg_on_all)
    svc.ensure_user_allowed(1)  # 全员模式：普通用户放行

    cfg_on_sel = {'enabled': True, 'allow_all_users': False, 'total_quota_bytes': 0}
    monkeypatch.setattr(svc, 'get_feature_config', lambda: cfg_on_sel)
    monkeypatch.setattr(svc.AssetLibraryQuotaModel, 'is_enabled', staticmethod(lambda uid: uid == 7))
    svc.ensure_user_allowed(7)      # 白名单内
    svc.ensure_user_allowed(1, is_admin=True)  # 管理员放行
    with pytest.raises(AssetLibraryError) as ei:
        svc.ensure_user_allowed(1)
    assert ei.value.code == 'user_not_allowed'
