"""测试全局状态隔离工具（官方推荐方式）。

背景：run_unit_tests.py 的 CI 全量跑在同一进程内顺序执行所有测试模块，
历史上多次出现模块级 ``sys.modules['xxx'] = MagicMock()`` 注入未恢复（或
"尾部恢复"因 import 中断未执行）导致的连锁失败（d01ec49e 等）。本模块
提供统一的 stub 安装/恢复原语，配套 CI 静态红线（lint R8）禁止裸赋值。

用法::

    from tests.base.test_isolation import module_stub, stub_modules

    # 模块级（import 被测模块前）
    with stub_modules({
        'config.config_util': module_stub(
            'config.config_util',
            get_config_path=lambda: 'config_prod.yml',
        ),
        'config.constant': module_stub('config.constant', SOME_CONST=30),
    }):
        from task import visual_task  # 即使此处抛 ImportError 也会恢复

    # setUpClass/tearDownClass 场景可用手工 API（见 install/restore 说明）
"""
import sys
import types
from contextlib import contextmanager


def module_stub(name: str, **attrs):
    """构造指定名字的轻量 stub 模块对象（types.ModuleType + 属性）。"""
    stub = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(stub, key, value)
    return stub


def install_module_stubs(stubs: dict) -> list:
    """把 stub 模块装入 sys.modules（并绑定父包属性），返回恢复凭据。

    与裸 ``sys.modules['config.constant'] = stub`` 相比：
    1. 同时把 stub 绑定到父包属性（``config.constant``），保证
       ``from config import constant`` 与 ``config.constant.X`` 一致；
    2. 返回的凭据交给 :func:`restore_module_stubs` 可完整还原
       sys.modules 条目与父包属性。

    一般不直接使用，优先 :func:`stub_modules` 上下文管理器。
    """
    tokens = []
    for name, stub in stubs.items():
        parent_name, _, child_attr = name.rpartition('.')
        saved_entry = sys.modules.get(name)
        parent = sys.modules.get(parent_name) if parent_name else None
        had_attr = parent is not None and hasattr(parent, child_attr)
        old_attr = getattr(parent, child_attr, None) if had_attr else None
        sys.modules[name] = stub
        if parent is not None:
            setattr(parent, child_attr, stub)
        tokens.append({
            'name': name,
            'stub': stub,
            'saved_sys_modules': saved_entry,
            'parent_name': parent_name,
            'child_attr': child_attr,
            'had_attr': had_attr,
            'old_attr': old_attr,
        })
    return tokens


def restore_module_stubs(tokens: list) -> None:
    """还原 :func:`install_module_stubs` 安装的全部 stub。

    只还原仍指向本 stub 的条目/属性（若已被后续代码覆盖则不动，避免
    误删其他测试中途安装的新状态）；父包在 stub 存活期间才被导入的
    场景同样处理：恢复时重新解析父包。
    """
    for token in reversed(tokens):
        name = token['name']
        saved_entry = token['saved_sys_modules']
        if sys.modules.get(name) is token['stub']:
            if saved_entry is not None:
                sys.modules[name] = saved_entry
            else:
                sys.modules.pop(name, None)
        parent = sys.modules.get(token['parent_name']) if token['parent_name'] else None
        if parent is None:
            continue
        if getattr(parent, token['child_attr'], None) is token['stub']:
            if token['had_attr']:
                setattr(parent, token['child_attr'], token['old_attr'])
            else:
                try:
                    delattr(parent, token['child_attr'])
                except AttributeError:
                    pass


@contextmanager
def stub_modules(stubs: dict):
    """with 块内替换 sys.modules 中的模块，离开时必然恢复。

    即使块内 import 触发 ImportError/任意异常，finally 也保证恢复——
    这正是手工"模块级注入 + 尾部恢复"模式在 import 中断时残留 stub、
    污染同进程后续全部测试的根治点。

    Args:
        stubs: {完整模块名: 模块对象}，模块对象可用 :func:`module_stub` 构造。
    """
    tokens = install_module_stubs(stubs)
    try:
        yield
    finally:
        restore_module_stubs(tokens)


@contextmanager
def unified_registry_guard():
    """with 块内保护 UnifiedConfigRegistry：进入快照、离开恢复。

    需要"清空/改写注册表"的测试用它包裹，避免注册表状态泄漏到同进程
    后续测试（UnifiedConfigRegistry.snapshot/restore 的上下文管理器封装）。
    """
    from config.unified_config import UnifiedConfigRegistry

    snapshot = UnifiedConfigRegistry.snapshot()
    try:
        yield UnifiedConfigRegistry
    finally:
        UnifiedConfigRegistry.restore(snapshot)


@contextmanager
def dropped_modules(*names):
    """with 块内从 sys.modules 移除指定模块（强制后续 import 重新加载）。

    典型场景：reload 型测试结束后需要把 stub 绑定版模块弹出，
    避免其永久驻留（见 test_visual_task_failure_reason 的历史问题）。
    """
    saved = {name: sys.modules.get(name) for name in names}
    for name in names:
        parent_name, _, child_attr = name.rpartition('.')
        sys.modules.pop(name, None)
        parent = sys.modules.get(parent_name) if parent_name else None
        if parent is not None and hasattr(parent, child_attr):
            try:
                delattr(parent, child_attr)
            except AttributeError:
                pass
    try:
        yield
    finally:
        for name, module in saved.items():
            if module is not None:
                sys.modules[name] = module
            else:
                sys.modules.pop(name, None)


@contextmanager
def purged_modules(*names):
    """移除指定模块且离开 with 后保持移除状态（后续 import 重新加载真实版）。

    与 :func:`dropped_modules` 的区别：不恢复进入时的旧条目——旧条目可能
    是其他测试在 mock 状态下加载出来的污染版本，恢复它等于没清理。
    同时清理父包属性，避免父包还指向污染版本。
    """
    for name in names:
        sys.modules.pop(name, None)
        parent_name, _, child_attr = name.rpartition('.')
        parent = sys.modules.get(parent_name) if parent_name else None
        if parent is not None and hasattr(parent, child_attr):
            try:
                delattr(parent, child_attr)
            except AttributeError:
                pass
    yield
