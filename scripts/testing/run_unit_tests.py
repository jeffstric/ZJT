#!/usr/bin/env python3
"""
单元测试一键执行脚本

功能：
1. 自动加载 config_unit.yml 配置
2. 执行数据库连接测试
3. 执行所有 CRUD 测试
4. 执行所有驱动集成测试
5. 生成测试报告
6. 输出执行摘要

用法：
    python run_unit_tests.py [选项]

选项：
    --crud-only     只执行 CRUD 测试
    --driver-only   只执行驱动测试
    --verbose       显示详细输出
    --failfast      遇到失败立即停止
    --coverage      生成覆盖率报告
"""
import sys
import os
import argparse
import unittest

# 添加项目根目录到 Python 路径
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(current_dir))
sys.path.insert(0, project_root)

APP_DIR = project_root

from tests.base.db_test_config import get_test_db_config
from scripts.testing.test_discovery import discover_tests_by_category, get_all_categories, get_category_display_name


class TestRunner:
    """测试执行器"""

    def __init__(self, args):
        self.args = args
        self.test_results = {
            'db_connection': {'passed': 0, 'failed': 0, 'errors': 0},
            'cdn': {'passed': 0, 'failed': 0, 'errors': 0},
            'crud': {'passed': 0, 'failed': 0, 'errors': 0},
            'driver': {'passed': 0, 'failed': 0, 'errors': 0},
            'utils': {'passed': 0, 'failed': 0, 'errors': 0},
            'config': {'passed': 0, 'failed': 0, 'errors': 0},
            'auth': {'passed': 0, 'failed': 0, 'errors': 0},
            'reference_images': {'passed': 0, 'failed': 0, 'errors': 0},
            'stats': {'passed': 0, 'failed': 0, 'errors': 0},
            'drivers': {'passed': 0, 'failed': 0, 'errors': 0},
            'driver_integration': {'passed': 0, 'failed': 0, 'errors': 0},
            'llm': {'passed': 0, 'failed': 0, 'errors': 0},
            'total': {'passed': 0, 'failed': 0, 'errors': 0}
        }
        # 收集所有失败测试的详细信息
        self.failed_tests = []
    
    def check_environment(self):
        """检查测试环境"""
        print("=" * 60)
        print("步骤 1: 检查测试环境")
        print("=" * 60)
        
        # 检查配置文件
        from tests.base.db_test_config import get_unit_test_config_path
        config_unit_path = os.path.join(APP_DIR, get_unit_test_config_path())
        if not os.path.exists(config_unit_path):
            print(f"[WARNING] {get_unit_test_config_path()} 不存在，将使用环境变量或默认值")
        else:
            print(f"[OK] 配置文件: {config_unit_path}")
        
        # 检查数据库配置
        try:
            db_config = get_test_db_config()
            print(f"[OK] 测试数据库: {db_config['database']}@{db_config['host']}")
            
            # 验证数据库名安全
            if not (db_config['database'].endswith('_test') or 
                    db_config['database'].endswith('_unittest')):
                print(f"[ERROR] 数据库名 '{db_config['database']}' 不符合安全规范")
                return False
        except Exception as e:
            print(f"[ERROR] 数据库配置错误: {e}")
            return False
        
        print()
        return True
    
    def run_db_connection_test(self):
        """执行数据库连接测试"""
        print("=" * 60)
        print("步骤 2: 数据库连接测试")
        print("=" * 60)

        try:
            import unittest
            from tests.test_db_connection import TestDatabaseConnection

            loader = unittest.TestLoader()
            suite = loader.loadTestsFromTestCase(TestDatabaseConnection)

            runner = unittest.TextTestRunner(verbosity=2 if self.args.verbose else 1)
            result = runner.run(suite)

            self.test_results['db_connection']['passed'] = result.testsRun - len(result.failures) - len(result.errors)
            self.test_results['db_connection']['failed'] = len(result.failures)
            self.test_results['db_connection']['errors'] = len(result.errors)

            # 收集失败信息
            for test, traceback_str in result.failures:
                self.failed_tests.append({
                    'category': 'db_connection',
                    'test': str(test),
                    'type': 'failure',
                    'traceback': traceback_str
                })
            for test, traceback_str in result.errors:
                self.failed_tests.append({
                    'category': 'db_connection',
                    'test': str(test),
                    'type': 'error',
                    'traceback': traceback_str
                })

            if result.wasSuccessful():
                print("[OK] 数据库连接测试通过")
                return True
            else:
                print("[FAILED] 数据库连接测试失败")
                return False

        except Exception as e:
            print(f"[ERROR] 执行连接测试时出错: {e}")
            self.test_results['db_connection']['errors'] = 1
            return False
        finally:
            print()

    def _discover_and_run(self, category: str):
        """
        发现并运行指定分类的测试。

        Args:
            category: 测试分类 (cdn, crud, utils, config, drivers, driver_integration, auth, reference_images, stats)

        Returns:
            (passed, failed, errors) 元组
        """
        test_modules = discover_tests_by_category(category)

        passed = failed = errors = 0
        for test_module in test_modules:
            try:
                # 检查文件是否存在
                file_path = test_module.replace('.', '/') + '.py'
                full_path = os.path.join(APP_DIR, file_path)
                if not os.path.exists(full_path):
                    print(f"[SKIP] {test_module} (文件不存在)")
                    continue

                print(f"\n执行: {test_module}")
                suite = unittest.TestLoader().loadTestsFromName(test_module)
                runner = unittest.TextTestRunner(verbosity=1)
                result = runner.run(suite)

                passed += result.testsRun - len(result.failures) - len(result.errors)
                failed += len(result.failures)
                errors += len(result.errors)

                # 收集失败信息
                for test, traceback_str in result.failures:
                    self.failed_tests.append({
                        'category': category,
                        'module': test_module,
                        'test': str(test),
                        'type': 'failure',
                        'traceback': traceback_str
                    })
                for test, traceback_str in result.errors:
                    self.failed_tests.append({
                        'category': category,
                        'module': test_module,
                        'test': str(test),
                        'type': 'error',
                        'traceback': traceback_str
                    })

                if not result.wasSuccessful() and self.args.failfast:
                    break

            except Exception as e:
                print(f"[ERROR] 执行 {test_module} 失败: {e}")
                errors += 1

        return passed, failed, errors
    
    def run_crud_tests(self):
        """执行 CRUD 测试"""
        print("=" * 60)
        print("CRUD 测试")
        print("=" * 60)

        passed, failed, errors = self._discover_and_run('crud')
        self.test_results['crud']['passed'] = passed
        self.test_results['crud']['failed'] = failed
        self.test_results['crud']['errors'] = errors

        print()
        return errors == 0 and failed == 0

    def run_cdn_tests(self):
        """执行 CDN 相关测试"""
        print("=" * 60)
        print("CDN 专项测试")
        print("=" * 60)

        passed, failed, errors = self._discover_and_run('cdn')
        self.test_results['cdn']['passed'] = passed
        self.test_results['cdn']['failed'] = failed
        self.test_results['cdn']['errors'] = errors

        print()
        return errors == 0 and failed == 0

    def run_utils_tests(self):
        """执行工具函数测试"""
        print("=" * 60)
        print("工具函数测试")
        print("=" * 60)

        passed, failed, errors = self._discover_and_run('utils')
        self.test_results['utils']['passed'] = passed
        self.test_results['utils']['failed'] = failed
        self.test_results['utils']['errors'] = errors

        print()
        return errors == 0 and failed == 0
    
    def run_driver_tests(self):
        """执行驱动集成测试"""
        print("=" * 60)
        print("驱动集成测试")
        print("=" * 60)

        passed, failed, errors = self._discover_and_run('driver_integration')
        self.test_results['driver']['passed'] = passed
        self.test_results['driver']['failed'] = failed
        self.test_results['driver']['errors'] = errors

        print()
        return errors == 0 and failed == 0

    def run_config_tests(self):
        """执行配置相关测试"""
        print("=" * 60)
        print("配置测试")
        print("=" * 60)

        passed, failed, errors = self._discover_and_run('config')
        self.test_results['config']['passed'] = passed
        self.test_results['config']['failed'] = failed
        self.test_results['config']['errors'] = errors

        print()
        return errors == 0 and failed == 0

    def run_auth_tests(self):
        """执行认证测试"""
        print("=" * 60)
        print("认证测试")
        print("=" * 60)

        passed, failed, errors = self._discover_and_run('auth')
        self.test_results['auth']['passed'] = passed
        self.test_results['auth']['failed'] = failed
        self.test_results['auth']['errors'] = errors

        print()
        return errors == 0 and failed == 0

    def run_reference_images_tests(self):
        """执行引用图片测试"""
        print("=" * 60)
        print("引用图片测试")
        print("=" * 60)

        passed, failed, errors = self._discover_and_run('reference_images')
        self.test_results['reference_images']['passed'] = passed
        self.test_results['reference_images']['failed'] = failed
        self.test_results['reference_images']['errors'] = errors

        print()
        return errors == 0 and failed == 0

    def run_stats_tests(self):
        """执行统计测试"""
        print("=" * 60)
        print("统计测试")
        print("=" * 60)

        passed, failed, errors = self._discover_and_run('stats')
        self.test_results['stats']['passed'] = passed
        self.test_results['stats']['failed'] = failed
        self.test_results['stats']['errors'] = errors

        print()
        return errors == 0 and failed == 0

    def run_drivers_tests(self):
        """执行驱动单元测试"""
        print("=" * 60)
        print("驱动单元测试")
        print("=" * 60)

        passed, failed, errors = self._discover_and_run('drivers')
        self.test_results['drivers']['passed'] = passed
        self.test_results['drivers']['failed'] = failed
        self.test_results['drivers']['errors'] = errors

        print()
        return errors == 0 and failed == 0

    def generate_junit_xml(self):
        """生成 JUnit XML 格式的测试报告供 GitLab CI 解析"""
        import xml.etree.ElementTree as ET

        testsuites = ET.Element('testsuites')

        for category in ['db_connection', 'crud', 'driver', 'utils', 'config']:
            results = self.test_results[category]
            total = results['passed'] + results['failed'] + results['errors']

            suite = ET.SubElement(testsuites, 'testsuite', {
                'name': category,
                'tests': str(total),
                'failures': str(results['failed']),
                'errors': str(results['errors']),
            })

            # 添加失败/错误的测试用例
            for failed in self.failed_tests:
                if failed['category'] != category:
                    continue
                testcase = ET.SubElement(suite, 'testcase', {
                    'name': failed['test'],
                    'classname': failed.get('module', category),
                })
                tag_name = 'failure' if failed['type'] == 'failure' else 'error'
                detail = ET.SubElement(testcase, tag_name, {
                    'message': failed['test'],
                })
                detail.text = failed['traceback']

            # 添加通过的测试用例（占位名称）
            passed_in_category = results['passed']
            for i in range(passed_in_category):
                ET.SubElement(suite, 'testcase', {
                    'name': f'{category}.passed_{i + 1}',
                    'classname': category,
                })

        tree = ET.ElementTree(testsuites)
        output_path = os.path.join(APP_DIR, 'test-results.xml')
        tree.write(output_path, encoding='unicode', xml_declaration=True)
        print(f"[INFO] JUnit 测试报告已生成: {output_path}")

    def print_summary(self):
        """打印测试摘要"""
        print("=" * 60)
        print("测试执行摘要")
        print("=" * 60)

        # 计算总数
        for category in ['db_connection', 'cdn', 'crud', 'driver', 'utils', 'config', 'auth', 'reference_images', 'stats', 'drivers', 'driver_integration']:
            for key in ['passed', 'failed', 'errors']:
                self.test_results['total'][key] += self.test_results[category][key]

        print(f"数据库连接测试:   "
              f"通过 {self.test_results['db_connection']['passed']}, "
              f"失败 {self.test_results['db_connection']['failed']}, "
              f"错误 {self.test_results['db_connection']['errors']}")

        print(f"CDN 测试:        "
              f"通过 {self.test_results['cdn']['passed']}, "
              f"失败 {self.test_results['cdn']['failed']}, "
              f"错误 {self.test_results['cdn']['errors']}")

        print(f"CRUD 测试:       "
              f"通过 {self.test_results['crud']['passed']}, "
              f"失败 {self.test_results['crud']['failed']}, "
              f"错误 {self.test_results['crud']['errors']}")

        print(f"驱动集成测试:    "
              f"通过 {self.test_results['driver']['passed']}, "
              f"失败 {self.test_results['driver']['failed']}, "
              f"错误 {self.test_results['driver']['errors']}")

        print(f"工具函数测试:    "
              f"通过 {self.test_results['utils']['passed']}, "
              f"失败 {self.test_results['utils']['failed']}, "
              f"错误 {self.test_results['utils']['errors']}")

        print(f"配置测试:        "
              f"通过 {self.test_results['config']['passed']}, "
              f"失败 {self.test_results['config']['failed']}, "
              f"错误 {self.test_results['config']['errors']}")

        print(f"认证测试:        "
              f"通过 {self.test_results['auth']['passed']}, "
              f"失败 {self.test_results['auth']['failed']}, "
              f"错误 {self.test_results['auth']['errors']}")

        print(f"引用图片测试:    "
              f"通过 {self.test_results['reference_images']['passed']}, "
              f"失败 {self.test_results['reference_images']['failed']}, "
              f"错误 {self.test_results['reference_images']['errors']}")

        print(f"统计测试:        "
              f"通过 {self.test_results['stats']['passed']}, "
              f"失败 {self.test_results['stats']['failed']}, "
              f"错误 {self.test_results['stats']['errors']}")

        print(f"驱动单元测试:    "
              f"通过 {self.test_results['drivers']['passed']}, "
              f"失败 {self.test_results['drivers']['failed']}, "
              f"错误 {self.test_results['drivers']['errors']}")

        print("-" * 60)
        print(f"总计:            "
              f"通过 {self.test_results['total']['passed']}, "
              f"失败 {self.test_results['total']['failed']}, "
              f"错误 {self.test_results['total']['errors']}")
        print("=" * 60)

        # 返回码
        if self.test_results['total']['failed'] > 0 or self.test_results['total']['errors'] > 0:
            return 1
        return 0

    def print_failed_tests(self):
        """打印所有失败的测试详情"""
        if not self.failed_tests:
            print("\n" + "=" * 60)
            print("没有失败的测试")
            print("=" * 60)
            return

        print("\n" + "=" * 60)
        print(f"失败测试详情 (共 {len(self.failed_tests)} 项)")
        print("=" * 60)

        for i, failed in enumerate(self.failed_tests, 1):
            print(f"\n{'─' * 60}")
            print(f"#{i} [{failed['category'].upper()}] {failed.get('module', 'N/A')}")
            print(f"测试: {failed['test']}")
            print(f"类型: {failed['type'].upper()}")
            print(f"{'─' * 60}")
            print(failed['traceback'])

        print("\n" + "=" * 60)
    
    def run(self):
        """执行完整测试流程"""
        print("\n" + "=" * 60)
        print("单元测试一键执行")
        print("=" * 60 + "\n")

        # 步骤 1: 检查环境
        if not self.check_environment():
            return 1

        # 检查是否设置了任何 only 标志
        has_only_flag = any([
            self.args.crud_only,
            self.args.driver_only,
            self.args.utils_only,
            self.args.config_only,
            self.args.only_cdn,
            self.args.auth_only,
            self.args.reference_images_only,
            self.args.stats_only,
            self.args.drivers_only,
            self.args.driver_integration_only,
        ])

        # 步骤 2: CDN 专项测试
        if self.args.only_cdn or not has_only_flag:
            self.run_cdn_tests()

        # 步骤 3: 数据库连接测试（只有没有任何 only 标志时才运行）
        if not has_only_flag:
            if not self.run_db_connection_test():
                if self.args.failfast:
                    self.print_failed_tests()
                    return 1

        # 步骤 4: CRUD 测试
        if self.args.crud_only or not has_only_flag:
            self.run_crud_tests()

        # 步骤 5: 工具函数测试
        if self.args.utils_only or not has_only_flag:
            self.run_utils_tests()

        # 步骤 6: 驱动集成测试
        # 注意: --driver-only 是 --driver-integration-only 的别名（向后兼容）
        if self.args.driver_integration_only or self.args.driver_only or not has_only_flag:
            self.run_driver_tests()

        # 步骤 7: 配置测试
        if self.args.config_only or not has_only_flag:
            self.run_config_tests()

        # 步骤 8: 认证测试
        if self.args.auth_only or not has_only_flag:
            self.run_auth_tests()

        # 步骤 9: 引用图片测试
        if self.args.reference_images_only or not has_only_flag:
            self.run_reference_images_tests()

        # 步骤 10: 统计测试
        if self.args.stats_only or not has_only_flag:
            self.run_stats_tests()

        # 步骤 11: 驱动单元测试
        if self.args.drivers_only or not has_only_flag:
            self.run_drivers_tests()

        # 步骤 12: 输出摘要
        return_code = self.print_summary()

        # 步骤 13: 输出失败测试详情
        self.print_failed_tests()

        
        # 步骤 14: 生成 JUnit XML 报告
        self.generate_junit_xml()


        print("\n测试执行完成！")
        return return_code


def main():
    import logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        datefmt='%H:%M:%S'
    )

    # 设置 comfyui_env=unit，使 config_util.get_config_path() 返回 config_unit.yml
    # 必须在 model.database 等模块被导入之前设置，因为 DB_CONFIG 在模块加载时读取配置
    os.environ['comfyui_env'] = 'unit'

    # 设置 DB_* 环境变量，使 model.database.DB_CONFIG 指向测试库（双重保障）
    from tests.base.db_test_config import TEST_DB_CONFIG
    os.environ['DB_HOST'] = TEST_DB_CONFIG['host']
    os.environ['DB_PORT'] = str(TEST_DB_CONFIG['port'])
    os.environ['DB_USER'] = TEST_DB_CONFIG['user']
    os.environ['DB_PASSWORD'] = TEST_DB_CONFIG['password']
    os.environ['DB_NAME'] = TEST_DB_CONFIG['database']
    logging.getLogger(__name__).info(
        f"测试环境已设置: comfyui_env=unit, DB={TEST_DB_CONFIG['database']}@{TEST_DB_CONFIG['host']}"
    )

    parser = argparse.ArgumentParser(description='单元测试一键执行脚本')
    parser.add_argument('--crud-only', action='store_true', help='只执行 CRUD 测试')
    parser.add_argument('--driver-only', action='store_true', help='只执行驱动测试（已废弃，使用 --driver-integration-only）')
    parser.add_argument('--driver-integration-only', action='store_true', help='只执行驱动集成测试')
    parser.add_argument('--drivers-only', action='store_true', help='只执行驱动单元测试（无 DB）')
    parser.add_argument('--utils-only', action='store_true', help='只执行工具函数测试')
    parser.add_argument('--config-only', action='store_true', help='只执行配置测试')
    parser.add_argument('--only-cdn', action='store_true', help='只执行 CDN 相关测试')
    parser.add_argument('--auth-only', action='store_true', help='只执行认证测试')
    parser.add_argument('--reference-images-only', action='store_true', help='只执行引用图片测试')
    parser.add_argument('--stats-only', action='store_true', help='只执行统计测试')
    parser.add_argument('--verbose', '-v', action='store_true', help='显示详细输出')
    parser.add_argument('--failfast', '-x', action='store_true', help='遇到失败立即停止')
    parser.add_argument('--coverage', action='store_true', help='生成覆盖率报告')
    
    args = parser.parse_args()
    
    runner = TestRunner(args)
    exit_code = runner.run()
    sys.exit(exit_code)


if __name__ == '__main__':
    main()
