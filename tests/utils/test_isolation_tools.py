"""tests/base/test_isolation.py 隔离工具的行为测试。

这些工具是 CI 静态红线（lint R8）指定的唯一合法 stub 方式，
必须有自身的行为回归覆盖。
"""
import sys
import unittest

from tests.base.test_isolation import (
    dropped_modules,
    install_module_stubs,
    module_stub,
    restore_module_stubs,
    stub_modules,
    unified_registry_guard,
)


class TestStubModules(unittest.TestCase):
    """stub_modules 上下文管理器"""

    def test_stub_visible_inside_and_restored_after(self):
        import config.constant as real_const

        with stub_modules({
            'config.constant': module_stub('config.constant', SMOKE_FLAG='stub'),
        }):
            import config
            self.assertEqual(config.constant.SMOKE_FLAG, 'stub')
            self.assertEqual(sys.modules['config.constant'].SMOKE_FLAG, 'stub')

        self.assertIs(sys.modules['config.constant'], real_const)
        import config
        self.assertIs(config.constant, real_const)

    def test_restore_even_when_body_raises(self):
        """with 块内 import 失败/抛异常也必须恢复（d01ec49e 事故的根治点）"""
        import config.constant as real_const

        with self.assertRaises(ImportError):
            with stub_modules({
                'config.constant': module_stub('config.constant'),  # 缺常量的瘦身 stub
            }):
                from config.constant import USER_MODULE_IMPL_NAME_PREFIX  # noqa: F401

        self.assertIs(sys.modules['config.constant'], real_const)

    def test_fresh_name_installed_and_removed(self):
        name = 'tests_isolation_smoke_pkg.fresh_mod'
        with stub_modules({name: module_stub(name, value=42)}):
            self.assertEqual(sys.modules[name].value, 42)
        self.assertNotIn(name, sys.modules)

    def test_toplevel_name_without_parent(self):
        name = 'tests_isolation_smoke_top'
        with stub_modules({name: module_stub(name)}):
            self.assertIn(name, sys.modules)
        self.assertNotIn(name, sys.modules)


class TestInstallRestoreTokens(unittest.TestCase):
    """手工 install/restore API（setUpClass/tearDownClass 场景）"""

    def test_roundtrip_with_manual_api(self):
        import config.constant as real_const

        tokens = install_module_stubs({
            'config.constant': module_stub('config.constant', X=1),
        })
        try:
            self.assertEqual(sys.modules['config.constant'].X, 1)
        finally:
            restore_module_stubs(tokens)
        self.assertIs(sys.modules['config.constant'], real_const)

    def test_restore_skips_overwritten_entry(self):
        """stub 被后续代码覆盖时，restore 不得误删新状态"""
        tokens = install_module_stubs({
            'config.constant': module_stub('config.constant'),
        })
        replacement = module_stub('config.constant', newer=True)
        sys.modules['config.constant'] = replacement
        restore_module_stubs(tokens)
        self.assertIs(sys.modules['config.constant'], replacement)
        # 清理，避免污染同进程后续测试
        del sys.modules['config.constant']
        import config.constant  # noqa: F401


class TestDroppedModules(unittest.TestCase):
    def test_dropped_inside_restored_after(self):
        import json  # noqa: F401  确保预先加载

        with dropped_modules('json'):
            self.assertNotIn('json', sys.modules)
        self.assertIn('json', sys.modules)


class TestUnifiedRegistryGuard(unittest.TestCase):
    def test_registry_state_restored(self):
        from config.unified_config import UnifiedConfigRegistry

        before = dict(UnifiedConfigRegistry._configs)
        with unified_registry_guard():
            UnifiedConfigRegistry._configs.clear()
            self.assertEqual(len(UnifiedConfigRegistry._configs), 0)
        self.assertEqual(UnifiedConfigRegistry._configs, before)


if __name__ == '__main__':
    unittest.main()
