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
import subprocess
from pathlib import Path

APP_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, APP_DIR)

from tests.db_test_config import get_test_db_config, get_unit_test_setting


class TestRunner:
    """测试执行器"""
    
    def __init__(self, args):
        self.args = args
        self.test_results = {
            'db_connection': {'passed': 0, 'failed': 0, 'errors': 0},
            'crud': {'passed': 0, 'failed': 0, 'errors': 0},
            'driver': {'passed': 0, 'failed': 0, 'errors': 0},
            'total': {'passed': 0, 'failed': 0, 'errors': 0}
        }
    
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
            'tests.test_ai_audio_crud',
            'tests.test_location_crud',
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
            'tests.driver_integration.test_vidu_driver_with_db',
            'tests.driver_integration.test_wan22_driver_with_db',
            'tests.driver_integration.test_kling_driver_with_db',
            'tests.driver_integration.test_veo3_driver_with_db',
            'tests.driver_integration.test_gemini_driver_with_db',
            'tests.driver_integration.test_gemini_pro_driver_with_db',
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
        for category in ['db_connection', 'crud', 'driver']:
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
    
    def run(self):
        """执行完整测试流程"""
        print("\n" + "=" * 60)
        print("单元测试一键执行")
        print("=" * 60 + "\n")
        
        # 步骤 1: 检查环境
        if not self.check_environment():
            return 1
        
        # 步骤 2: 数据库连接测试
        if not self.args.crud_only and not self.args.driver_only:
            if not self.run_db_connection_test():
                if self.args.failfast:
                    return 1
        
        # 步骤 3: CRUD 测试
        if not self.args.driver_only:
            self.run_crud_tests()
        
        # 步骤 4: 驱动测试
        if not self.args.crud_only:
            self.run_driver_tests()
        
        # 步骤 5: 输出摘要
        return_code = self.print_summary()
        
        print("\n测试执行完成！")
        return return_code


def main():
    parser = argparse.ArgumentParser(description='单元测试一键执行脚本')
    parser.add_argument('--crud-only', action='store_true', help='只执行 CRUD 测试')
    parser.add_argument('--driver-only', action='store_true', help='只执行驱动测试')
    parser.add_argument('--verbose', '-v', action='store_true', help='显示详细输出')
    parser.add_argument('--failfast', '-x', action='store_true', help='遇到失败立即停止')
    parser.add_argument('--coverage', action='store_true', help='生成覆盖率报告')
    
    args = parser.parse_args()
    
    runner = TestRunner(args)
    exit_code = runner.run()
    sys.exit(exit_code)


if __name__ == '__main__':
    main()
