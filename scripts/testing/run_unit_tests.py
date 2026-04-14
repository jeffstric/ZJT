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

from tests.db_test_config import get_test_db_config


class TestRunner:
    """测试执行器"""

    def __init__(self, args):
        self.args = args
        self.test_results = {
            'db_connection': {'passed': 0, 'failed': 0, 'errors': 0},
            'crud': {'passed': 0, 'failed': 0, 'errors': 0},
            'driver': {'passed': 0, 'failed': 0, 'errors': 0},
            'utils': {'passed': 0, 'failed': 0, 'errors': 0},
            'config': {'passed': 0, 'failed': 0, 'errors': 0},
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
        from tests.db_test_config import get_unit_test_config_path
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
    
    def run_crud_tests(self):
        """执行所有 CRUD 测试"""
        print("=" * 60)
        print("步骤 3: CRUD 测试")
        print("=" * 60)

        crud_test_files = [
            'tests.test_ai_tools_crud',
            'tests.test_ai_tools_cdn_integration',
            'tests.test_ai_audio_crud',
            'tests.test_chat_sessions_crud',
            'tests.test_character_reference_images',
            'tests.test_implementation_stats',
            'tests.test_location_crud',
            'tests.test_location_reference_images',
            'tests.test_payment_orders_crud',
            'tests.test_props_crud',
            'tests.test_runninghub_slots_crud',
            'tests.test_script_crud',
            'tests.test_tasks_crud',
            'tests.test_video_workflow_crud',
            'tests.test_world_crud',
        ]

        all_passed = True
        for test_module in crud_test_files:
            try:
                print(f"\n执行: {test_module}")
                suite = unittest.TestLoader().loadTestsFromName(test_module)
                runner = unittest.TextTestRunner(verbosity=1)
                result = runner.run(suite)

                self.test_results['crud']['passed'] += result.testsRun - len(result.failures) - len(result.errors)
                self.test_results['crud']['failed'] += len(result.failures)
                self.test_results['crud']['errors'] += len(result.errors)

                # 收集失败信息
                for test, traceback_str in result.failures:
                    self.failed_tests.append({
                        'category': 'crud',
                        'module': test_module,
                        'test': str(test),
                        'type': 'failure',
                        'traceback': traceback_str
                    })
                for test, traceback_str in result.errors:
                    self.failed_tests.append({
                        'category': 'crud',
                        'module': test_module,
                        'test': str(test),
                        'type': 'error',
                        'traceback': traceback_str
                    })

                if not result.wasSuccessful():
                    all_passed = False
                    if self.args.failfast:
                        break

            except Exception as e:
                print(f"[ERROR] 执行 {test_module} 失败: {e}")
                all_passed = False

        print()
        return all_passed

    def run_cdn_tests(self):
        """执行 CDN 相关测试"""
        print("=" * 60)
        print("步骤 3: CDN 专项测试")
        print("=" * 60)

        cdn_test_files = [
            'tests.test_ai_tools_cdn_integration',
            'tests.test_cdn_storage',
        ]

        all_passed = True
        for test_module in cdn_test_files:
            try:
                print(f"\n执行: {test_module}")
                suite = unittest.TestLoader().loadTestsFromName(test_module)
                runner = unittest.TextTestRunner(verbosity=1)
                result = runner.run(suite)

                self.test_results['crud']['passed'] += result.testsRun - len(result.failures) - len(result.errors)
                self.test_results['crud']['failed'] += len(result.failures)
                self.test_results['crud']['errors'] += len(result.errors)

                # 收集失败信息
                for test, traceback_str in result.failures:
                    self.failed_tests.append({
                        'category': 'crud',
                        'module': test_module,
                        'test': str(test),
                        'type': 'failure',
                        'traceback': traceback_str
                    })
                for test, traceback_str in result.errors:
                    self.failed_tests.append({
                        'category': 'crud',
                        'module': test_module,
                        'test': str(test),
                        'type': 'error',
                        'traceback': traceback_str
                    })

                if not result.wasSuccessful():
                    all_passed = False
                    if self.args.failfast:
                        break

            except Exception as e:
                print(f"[ERROR] 执行 {test_module} 失败: {e}")
                all_passed = False

        print()
        return all_passed

    def run_utils_tests(self):
        """执行工具函数测试"""
        print("=" * 60)
        print("步骤 4: 工具函数测试")
        print("=" * 60)

        utils_test_files = [
            'tests.test_image_upload_utils',
            'tests.test_media_cache_temp',
            'tests.test_auth_service',
            'tests.test_qwen_multi_angle_driver',
        ]

        all_passed = True
        for test_module in utils_test_files:
            try:
                print(f"\n执行: {test_module}")
                suite = unittest.TestLoader().loadTestsFromName(test_module)
                runner = unittest.TextTestRunner(verbosity=1)
                result = runner.run(suite)

                self.test_results['utils']['passed'] += result.testsRun - len(result.failures) - len(result.errors)
                self.test_results['utils']['failed'] += len(result.failures)
                self.test_results['utils']['errors'] += len(result.errors)

                # 收集失败信息
                for test, traceback_str in result.failures:
                    self.failed_tests.append({
                        'category': 'utils',
                        'module': test_module,
                        'test': str(test),
                        'type': 'failure',
                        'traceback': traceback_str
                    })
                for test, traceback_str in result.errors:
                    self.failed_tests.append({
                        'category': 'utils',
                        'module': test_module,
                        'test': str(test),
                        'type': 'error',
                        'traceback': traceback_str
                    })

                if not result.wasSuccessful():
                    all_passed = False
                    if self.args.failfast:
                        break

            except Exception as e:
                print(f"[ERROR] 执行 {test_module} 失败: {e}")
                all_passed = False

        print()
        return all_passed
    
    def run_driver_tests(self):
        """执行所有驱动集成测试"""
        print("=" * 60)
        print("步骤 4: 驱动集成测试")
        print("=" * 60)

        driver_test_files = [
            'tests.driver_integration.test_digital_human_driver_with_db',
            'tests.driver_integration.test_sora2_driver_with_db',
            'tests.driver_integration.test_ltx2_driver_with_db',
            'tests.driver_integration.test_ltx2_3_driver_with_db',
            'tests.driver_integration.test_vidu_driver_with_db',
            'tests.driver_integration.test_wan22_driver_with_db',
            'tests.driver_integration.test_kling_driver_with_db',
            'tests.driver_integration.test_veo3_driver_with_db',
            'tests.driver_integration.test_gemini_driver_with_db',
            'tests.driver_integration.test_seedream_driver_with_db',
            'tests.driver_integration.test_vidu_q2_driver_with_db',
        ]

        all_passed = True
        for test_module in driver_test_files:
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

                self.test_results['driver']['passed'] += result.testsRun - len(result.failures) - len(result.errors)
                self.test_results['driver']['failed'] += len(result.failures)
                self.test_results['driver']['errors'] += len(result.errors)

                # 收集失败信息
                for test, traceback_str in result.failures:
                    self.failed_tests.append({
                        'category': 'driver',
                        'module': test_module,
                        'test': str(test),
                        'type': 'failure',
                        'traceback': traceback_str
                    })
                for test, traceback_str in result.errors:
                    self.failed_tests.append({
                        'category': 'driver',
                        'module': test_module,
                        'test': str(test),
                        'type': 'error',
                        'traceback': traceback_str
                    })

                if not result.wasSuccessful():
                    all_passed = False
                    if self.args.failfast:
                        break

            except Exception as e:
                print(f"[ERROR] 执行 {test_module} 失败: {e}")
                all_passed = False

        print()
        return all_passed

    def run_config_tests(self):
        """执行配置相关测试"""
        print("=" * 60)
        print("步骤 5: 配置测试")
        print("=" * 60)

        config_test_files = [
            'tests.test_implementation_config',
            'tests.test_unified_config_frontend',
        ]

        all_passed = True
        for test_module in config_test_files:
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

                self.test_results['config']['passed'] += result.testsRun - len(result.failures) - len(result.errors)
                self.test_results['config']['failed'] += len(result.failures)
                self.test_results['config']['errors'] += len(result.errors)

                # 收集失败信息
                for test, traceback_str in result.failures:
                    self.failed_tests.append({
                        'category': 'config',
                        'module': test_module,
                        'test': str(test),
                        'type': 'failure',
                        'traceback': traceback_str
                    })
                for test, traceback_str in result.errors:
                    self.failed_tests.append({
                        'category': 'config',
                        'module': test_module,
                        'test': str(test),
                        'type': 'error',
                        'traceback': traceback_str
                    })

                if not result.wasSuccessful():
                    all_passed = False
                    if self.args.failfast:
                        break

            except Exception as e:
                print(f"[ERROR] 执行 {test_module} 失败: {e}")
                all_passed = False

        print()
        return all_passed

    def print_summary(self):
        """打印测试摘要"""
        print("=" * 60)
        print("测试执行摘要")
        print("=" * 60)

        # 计算总数
        for category in ['db_connection', 'crud', 'driver', 'utils', 'config']:
            for key in ['passed', 'failed', 'errors']:
                self.test_results['total'][key] += self.test_results[category][key]

        print(f"数据库连接测试: "
              f"通过 {self.test_results['db_connection']['passed']}, "
              f"失败 {self.test_results['db_connection']['failed']}, "
              f"错误 {self.test_results['db_connection']['errors']}")

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

        print(f"配置测试:       "
              f"通过 {self.test_results['config']['passed']}, "
              f"失败 {self.test_results['config']['failed']}, "
              f"错误 {self.test_results['config']['errors']}")

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

        # 步骤 2: CDN 专项测试（独立运行，不受 only 标志影响）
        if self.args.only_cdn:
            self.run_cdn_tests()
            return_code = self.print_summary()
            self.print_failed_tests()
            print("\n测试执行完成！")
            return return_code

        # 检查是否设置了任何 only 标志
        has_only_flag = any([
            self.args.crud_only,
            self.args.driver_only,
            self.args.utils_only,
            self.args.config_only
        ])

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

        # 步骤 6: 驱动测试
        if self.args.driver_only or not has_only_flag:
            self.run_driver_tests()

        # 步骤 7: 配置测试
        if self.args.config_only or not has_only_flag:
            self.run_config_tests()

        # 步骤 8: 输出摘要
        return_code = self.print_summary()

        # 步骤 9: 输出失败测试详情
        self.print_failed_tests()

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
    from tests.db_test_config import TEST_DB_CONFIG
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
    parser.add_argument('--driver-only', action='store_true', help='只执行驱动测试')
    parser.add_argument('--utils-only', action='store_true', help='只执行工具函数测试')
    parser.add_argument('--config-only', action='store_true', help='只执行配置测试')
    parser.add_argument('--only-cdn', action='store_true', help='只执行 CDN 相关测试')
    parser.add_argument('--verbose', '-v', action='store_true', help='显示详细输出')
    parser.add_argument('--failfast', '-x', action='store_true', help='遇到失败立即停止')
    parser.add_argument('--coverage', action='store_true', help='生成覆盖率报告')
    
    args = parser.parse_args()
    
    runner = TestRunner(args)
    exit_code = runner.run()
    sys.exit(exit_code)


if __name__ == '__main__':
    main()
