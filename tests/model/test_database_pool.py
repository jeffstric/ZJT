"""连接池（DBUtils PooledDB）行为测试。

覆盖 model/database.py 引入连接池后的关键不变量：
- 懒加载 + 单例（同进程多次 _get_pool 返回同一对象）
- 默认配置兜底（DB_CONFIG 缺 pool 段时不报错，兼容 conftest stub）
- pid 漂移检测（fork 后丢弃旧池重建，机制保证 fork 安全）
- 连接复用（借-还-再借是同一条底层连接，验证 close 是「归还池」而非「真关闭」）

设计说明：
- 纯逻辑测试（前 3 项）用 monkeypatch mock 掉 PooledDB 构造，不依赖真实 MySQL，
  在无 DB 的 CI/单测环境也能跑。
- 连接复用测试（第 4 项）需真实 DB 才能验证，连不上则 skip（不阻断单测流水线）。
- 现有测试用 sys.modules['model.database']=MagicMock() 整体替换模块的方式 mock，
  对池实现透明，本测试文件是补充而非替代。
"""
import os
import sys
import importlib

import pytest


# ---------------------------------------------------------------------------
# 夹具：确保 model.database 以真实模块加载（而非被其他测试替换成 MagicMock）
# ---------------------------------------------------------------------------
@pytest.fixture
def db_module(monkeypatch):
    """返回真实 model.database 模块，并保证用例结束后还原全局池状态。

    多个测试共享同一进程，模块级 _pool 状态会串扰，故每个用例前置重置。
    """
    # 清掉可能被其他测试塞入的 MagicMock
    sys.modules.pop('model.database', None)
    import model.database as db
    # 重置池全局状态
    monkeypatch.setattr(db, '_pool', None)
    monkeypatch.setattr(db, '_pool_pid', None)
    return db


# ===========================================================================
# 测试 1：懒加载 + 单例
# ===========================================================================
def test_pool_is_lazy_and_singleton(db_module, monkeypatch):
    """_get_pool() 首次调用才建池，同进程多次调用返回同一对象。"""
    created = []

    class FakePooledDB:
        def __init__(self, **kwargs):
            created.append(kwargs)
            self.kwargs = kwargs

        def connection(self):
            return ("fake-conn",)

    monkeypatch.setattr(db_module, 'PooledDB', FakePooledDB)

    pool1 = db_module._get_pool()
    assert len(created) == 1, "首次调用应触发建池"

    pool2 = db_module._get_pool()
    assert pool1 is pool2, "同进程多次调用应返回同一池单例"
    assert len(created) == 1, "单例不应重复建池"


# ===========================================================================
# 测试 2：默认配置兜底（兼容 conftest stub 无 pool 段）
# ===========================================================================
def test_pool_defaults_when_no_pool_config(db_module, monkeypatch):
    """DB_CONFIG 缺 'pool' 子段时使用内置默认值，不报错。

    conftest.py 注入的 database stub 只有 host/port/user/password/database，
    无 pool 子段也无 charset。本测试验证懒加载在此情况下仍可建池。
    """
    captured = {}

    class FakePooledDB:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def connection(self):
            return ("fake-conn",)

    monkeypatch.setattr(db_module, 'PooledDB', FakePooledDB)
    monkeypatch.setitem(db_module.DB_CONFIG, 'charset', 'utf8mb4')

    db_module._get_pool()

    # 验证内置默认值生效（与 database.py 代码兜底值一致；各环境实际值由 base yaml 覆盖：
    # prod=10, dev=20）
    assert captured['mincached'] == 2
    assert captured['maxcached'] == 20
    assert captured['maxconnections'] == 0
    # 关键 pymysql 参数透传
    assert captured['cursorclass'].__name__ == 'DictCursor'
    assert captured['autocommit'] is False
    # 故意不设 read_timeout（彻底零破坏）
    assert 'read_timeout' not in captured
    # 设了 connect_timeout（来自 constant.py）
    assert captured['connect_timeout'] == db_module.DB_POOL_CONNECT_TIMEOUT


# ===========================================================================
# 测试 3：pid 漂移检测（fork 安全的机制保证）
# ===========================================================================
def test_pool_rebuilt_on_pid_drift(db_module, monkeypatch):
    """pid 变化时（fork 后子进程）应丢弃旧池重建，绝不跨进程共享。"""
    created = []

    class FakePooledDB:
        def __init__(self, **kwargs):
            created.append(kwargs)

        def connection(self):
            return ("fake-conn",)

    monkeypatch.setattr(db_module, 'PooledDB', FakePooledDB)

    # 首次建池，记录当前 pid
    db_module._get_pool()
    assert len(created) == 1
    original_pool = db_module._pool

    # 模拟 fork：_pool_pid 被设成了一个不同的 pid（子进程视角）
    monkeypatch.setattr(db_module, '_pool_pid', db_module._pool_pid + 999)

    # 再次取池应重建（pid 漂移检测命中）
    db_module._get_pool()
    assert len(created) == 2, "pid 漂移后应重建池"
    assert db_module._pool is not original_pool, "重建后应是新池对象"
    # 新池的 pid 应是当前进程
    assert db_module._pool_pid == os.getpid()


# ===========================================================================
# 测试 4：连接复用（需真实 DB，连不上则 skip）
# ===========================================================================
def test_connection_reuse_via_pool(db_module):
    """借-还-再借是同一条底层 MySQL 连接（验证 close 是归还而非真关闭）。

    用 SELECT CONNECTION_ID() 断言底层连接身份，不依赖池内部归还顺序
    （审查修正建议：不要依赖归还顺序，直接比较连接身份）。
    """
    import pymysql

    # 尝试真实建池；连不上则 skip（无 DB 环境/CI）
    try:
        pool = db_module._get_pool()
    except pymysql.err.OperationalError:
        pytest.skip("真实 MySQL 不可用，跳过连接复用测试")

    def _connection_id():
        with db_module.get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT CONNECTION_ID() AS cid")
            row = cur.fetchone()
            return row['cid']

    try:
        cid1 = _connection_id()
        cid2 = _connection_id()
        cid3 = _connection_id()
    except pymysql.err.OperationalError:
        pytest.skip("真实 MySQL 不可用，跳过连接复用测试")

    # 单线程串行借-还-再借，底层应复用同一条连接（CONNECTION_ID 相同）
    assert cid1 == cid2 == cid3, (
        f"连接复用失败：CONNECTION_ID 不一致 {cid1}/{cid2}/{cid3}，"
        "可能 close 未正确归还池"
    )


# ===========================================================================
# 测试 5/6：transaction() 必须调用 conn.begin()（禁用 SteadyDB 透明重试）
# ===========================================================================
class _FakeConn:
    """记录调用序列的假连接，模拟 PooledDedicatedDBConnection 代理行为。"""

    def __init__(self):
        self.calls = []

    def begin(self):
        self.calls.append('begin')

    def commit(self):
        self.calls.append('commit')

    def rollback(self):
        self.calls.append('rollback')

    def close(self):
        # 池化语义：归还池而非真关闭
        self.calls.append('close')


class _FakePool:
    def __init__(self, conn):
        self._conn = conn

    def connection(self):
        return self._conn


def test_transaction_calls_begin_then_commit(db_module, monkeypatch):
    """正常路径：begin → commit → close（归还池）。

    begin() 是关键：它告知 SteadyDB 进入事务，禁用透明重连重试，
    保证多语句事务出错时直接抛错而非静默重试后半段（原子性保障）。
    """
    conn = _FakeConn()
    monkeypatch.setattr(db_module, '_get_pool', lambda: _FakePool(conn))

    with db_module.transaction() as c:
        assert c is conn

    assert conn.calls == ['begin', 'commit', 'close']


def test_transaction_calls_begin_then_rollback_on_error(db_module, monkeypatch):
    """异常路径：begin → rollback → close，且异常原样透出。"""
    conn = _FakeConn()
    monkeypatch.setattr(db_module, '_get_pool', lambda: _FakePool(conn))

    with pytest.raises(ValueError, match='boom'):
        with db_module.transaction():
            raise ValueError('boom')

    assert conn.calls == ['begin', 'rollback', 'close']
