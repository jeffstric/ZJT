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
import re
import argparse
import subprocess
import time
import unittest

# 添加项目根目录到 Python 路径
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(current_dir))
sys.path.insert(0, project_root)

APP_DIR = project_root

from tests.base.db_test_config import get_test_db_config
from scripts.testing.test_discovery import discover_tests_by_category, get_all_categories, get_category_display_name
from config.constant import UNIT_TEST_MODULE_TIMEOUT_SECONDS


# ---------------- unittest -v 输出解析（进程隔离模式） ----------------
# 兼容 Python 3.10（单行 `test_x (class) ... ok`）与 3.11+（docstring 换行版式）。
_UNITTEST_STATUS_TAIL_RE = re.compile(
    r"\.\.\.\s+(ok|FAIL|ERROR|skipped\b[^\n]*|expected failure|unexpected success)\s*$"
)
# Python 3.11+ 无 docstring 用例输出为独立裸状态行（如单独一行 "ok"）
_UNITTEST_STATUS_BARE_RE = re.compile(
    r"^(ok|FAIL|ERROR|skipped\b.*|expected failure|unexpected success)\s*$"
)
_UNITTEST_TESTLINE_RE = re.compile(r"^(test\S*)\s+\(([^)]+)\)\s*$")
_UNITTEST_INLINE_TEST_RE = re.compile(r"^(test\S*)\s+\(([^)]+)\)")
_UNITTEST_TB_HEAD_RE = re.compile(r"^(FAIL|ERROR):\s+(\S+?)(?:\s+\(([^)]+)\))?\s*$")
_UNITTEST_SEPARATOR_RE = re.compile(r"^(?:=+|-+)$")

# 用例状态归一化：skipped/expected failure 计入通过（与同进程模式 testsRun 口径一致）
_STATUS_PASSED = {"ok", "skipped", "expected failure"}
_STATUS_FAILED = {"FAIL", "unexpected success"}


def _normalize_status(raw_status: str) -> str:
    status = raw_status.split()[0] if raw_status.startswith("skipped") else raw_status
    if status in _STATUS_PASSED:
        return "passed"
    if status in _STATUS_FAILED:
        return "failed"
    return "error"


def parse_unittest_verbose_output(output: str):
    """解析 `python -m unittest -v` 的合并输出。

    Returns:
        (cases, tracebacks) 二元组：
        - cases: dict，键为 `test_name (classname)`（与 unittest 的 str(test) 一致），
          值为 passed/failed/error；
        - tracebacks: dict，键与 cases 相同（模块导入失败等无类名场景键为测试名），
          值为对应的 FAIL/ERROR 报告块文本。
    """
    lines = output.splitlines()
    cases: dict = {}
    tracebacks: dict = {}
    last_test_key = None

    for line in lines:
        test_match = _UNITTEST_TESTLINE_RE.match(line)
        if test_match:
            last_test_key = f"{test_match.group(1)} ({test_match.group(2)})"
            continue
        status_match = _UNITTEST_STATUS_TAIL_RE.search(line)
        if not status_match:
            stripped = line.strip()
            if _UNITTEST_STATUS_BARE_RE.match(stripped):
                status_match = _UNITTEST_STATUS_BARE_RE.match(stripped)
        if status_match:
            inline_match = _UNITTEST_INLINE_TEST_RE.match(line)
            key = (
                f"{inline_match.group(1)} ({inline_match.group(2)})"
                if inline_match
                else last_test_key
            )
            if key:
                cases[key] = _normalize_status(status_match.group(1))

    # 按分隔线（===== / -----）切块，块首形如 `FAIL: test_x (class)` 的即报告块
    blocks: list = []
    current_block: list = []
    for line in lines:
        if _UNITTEST_SEPARATOR_RE.match(line.strip()):
            if current_block:
                blocks.append(current_block)
                current_block = []
        else:
            current_block.append(line)
    if current_block:
        blocks.append(current_block)

    for block in blocks:
        if not block:
            continue
        head_match = _UNITTEST_TB_HEAD_RE.match(block[0])
        if not head_match:
            continue
        if head_match.group(3):
            key = f"{head_match.group(2)} ({head_match.group(3)})"
        else:
            key = head_match.group(2)
        tracebacks[key] = "\n".join(block).rstrip()

    return cases, tracebacks


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
            'agents': {'passed': 0, 'failed': 0, 'errors': 0},
            'services': {'passed': 0, 'failed': 0, 'errors': 0},
            'script_writer_core': {'passed': 0, 'failed': 0, 'errors': 0},
            'enterprise': {'passed': 0, 'failed': 0, 'errors': 0},
            'model': {'passed': 0, 'failed': 0, 'errors': 0},
            'task': {'passed': 0, 'failed': 0, 'errors': 0},
            'total': {'passed': 0, 'failed': 0, 'errors': 0}
        }
        # 收集所有失败测试的详细信息
        self.failed_tests = []
        # 当前正在执行的分类（供进程隔离模式的失败归因使用）
        self._current_category = 'unknown'
    
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
        self._current_category = category

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
                if getattr(self.args, 'no_isolate', False):
                    module_passed, module_failed, module_errors = self._run_module_inprocess(test_module)
                else:
                    module_passed, module_failed, module_errors = self._run_module_isolated(test_module)
                passed += module_passed
                failed += module_failed
                errors += module_errors

                if (module_failed > 0 or module_errors > 0) and self.args.failfast:
                    break

            except Exception as e:
                print(f"[ERROR] 执行 {test_module} 失败: {e}")
                errors += 1

        return passed, failed, errors

    def _record_module_failures(self, category: str, test_module: str, entries: list) -> None:
        """收集失败测试的详细信息到 self.failed_tests"""
        for entry in entries:
            entry_with_meta = dict(entry)
            entry_with_meta['category'] = category
            entry_with_meta['module'] = test_module
            self.failed_tests.append(entry_with_meta)

    def _run_module_inprocess(self, test_module: str):
        """同进程执行单个测试模块（--no-isolate 快速模式，历史默认行为）。"""
        suite = unittest.TestLoader().loadTestsFromName(test_module)
        runner = unittest.TextTestRunner(verbosity=1)
        result = runner.run(suite)

        entries = []
        for test, traceback_str in result.failures:
            entries.append({'test': str(test), 'type': 'failure', 'traceback': traceback_str})
        for test, traceback_str in result.errors:
            entries.append({'test': str(test), 'type': 'error', 'traceback': traceback_str})
        self._record_module_failures(self._current_category, test_module, entries)

        return (
            result.testsRun - len(result.failures) - len(result.errors),
            len(result.failures),
            len(result.errors),
        )

    def _run_module_isolated(self, test_module: str):
        """独立子进程执行单个测试模块（默认隔离模式）。

        每个模块一个全新解释器：模块级 sys.modules 注入、注册表清空、
        importlib.reload 漂移等全局状态污染被物理限制在本模块内，
        不再向后连锁（曾导致 CI 全量跑 25 项连锁失败，见 d01ec49e）。
        子进程超时由 UNIT_TEST_MODULE_TIMEOUT_SECONDS 保护，防止挂死拖垮整轮 CI。
        """
        timeout = getattr(self.args, 'module_timeout', None) or UNIT_TEST_MODULE_TIMEOUT_SECONDS
        env = os.environ.copy()
        # Windows 默认 GBK 管道编码会打乱中文 docstring/traceback，强制 UTF-8
        env.setdefault('PYTHONIOENCODING', 'utf-8')
        env.setdefault('PYTHONUTF8', '1')
        cmd = [sys.executable, '-m', 'unittest', '-v', test_module]
        started = time.time()

        try:
            proc = subprocess.run(
                cmd,
                cwd=APP_DIR,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=timeout,
                text=True,
                encoding='utf-8',
                errors='replace',
            )
            output = proc.stdout or ''
            returncode = proc.returncode
        except subprocess.TimeoutExpired as exc:
            partial = exc.stdout or ''
            if isinstance(partial, bytes):
                partial = partial.decode('utf-8', errors='replace')
            print(f"[TIMEOUT] {test_module} 超过 {timeout}s 被强制终止")
            entry = {
                'test': f'{test_module} (module-run)',
                'type': 'error',
                'traceback': (
                    f'ModuleTimeoutError: 测试模块 {test_module} 执行超过 {timeout}s 被强制终止。\n'
                    f'已捕获的部分输出:\n{partial[-4000:]}'
                ),
            }
            self._record_module_failures(self._current_category, test_module, [entry])
            return 0, 0, 1

        elapsed = time.time() - started
        cases, tracebacks = parse_unittest_verbose_output(output)
        passed = sum(1 for status in cases.values() if status == 'passed')
        failed_count = sum(1 for status in cases.values() if status == 'failed')
        error_count = sum(1 for status in cases.values() if status == 'error')

        entries = []
        for key, status in cases.items():
            if status == 'passed':
                continue
            entries.append({
                'test': key,
                'type': 'failure' if status == 'failed' else 'error',
                'traceback': tracebacks.get(key, output[-4000:]),
            })

        # 解析不到任何用例（如模块导入失败时 unittest 输出 _FailedTest，
        # 或崩溃在打印结果之前）但退出码非 0：整模块记 1 条 error
        if not cases and returncode != 0:
            error_count = 1
            entries.append({
                'test': f'{test_module} (module-run)',
                'type': 'error',
                'traceback': output[-8000:] or f'exit code={returncode}, 无输出',
            })

        self._record_module_failures(self._current_category, test_module, entries)
        status_flag = 'OK' if (failed_count == 0 and error_count == 0) else 'FAILED'
        print(f"[{status_flag}] {test_module}: passed={passed} failed={failed_count} "
              f"errors={error_count} ({elapsed:.1f}s)", flush=True)

        return passed, failed_count, error_count
    
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

    def run_llm_tests(self):
        """执行 LLM 相关测试"""
        print("=" * 60)
        print("LLM 测试")
        print("=" * 60)

        passed, failed, errors = self._discover_and_run('llm')
        self.test_results['llm']['passed'] = passed
        self.test_results['llm']['failed'] = failed
        self.test_results['llm']['errors'] = errors

        print()
        return errors == 0 and failed == 0

    def run_agents_tests(self):
        """执行 Agents 相关测试"""
        print("=" * 60)
        print("Agents 测试")
        print("=" * 60)

        passed, failed, errors = self._discover_and_run('agents')
        self.test_results['agents']['passed'] = passed
        self.test_results['agents']['failed'] = failed
        self.test_results['agents']['errors'] = errors

        print()
        return errors == 0 and failed == 0

    def run_services_tests(self):
        """执行 Services 相关测试"""
        print("=" * 60)
        print("Services 测试")
        print("=" * 60)

        passed, failed, errors = self._discover_and_run('services')
        self.test_results['services']['passed'] = passed
        self.test_results['services']['failed'] = failed
        self.test_results['services']['errors'] = errors

        print()
        return errors == 0 and failed == 0

    def run_script_writer_core_tests(self):
        """执行 Script Writer Core 相关测试"""
        print("=" * 60)
        print("Script Writer Core 测试")
        print("=" * 60)

        passed, failed, errors = self._discover_and_run('script_writer_core')
        self.test_results['script_writer_core']['passed'] = passed
        self.test_results['script_writer_core']['failed'] = failed
        self.test_results['script_writer_core']['errors'] = errors

        print()
        return errors == 0 and failed == 0

    def run_enterprise_tests(self):
        """执行企业版相关测试"""
        print("=" * 60)
        print("Enterprise 测试")
        print("=" * 60)

        passed, failed, errors = self._discover_and_run('enterprise')
        self.test_results['enterprise']['passed'] = passed
        self.test_results['enterprise']['failed'] = failed
        self.test_results['enterprise']['errors'] = errors

        print()
        return errors == 0 and failed == 0

    def run_model_tests(self):
        """执行数据模型测试"""
        print("=" * 60)
        print("数据模型测试")
        print("=" * 60)

        passed, failed, errors = self._discover_and_run('model')
        self.test_results['model']['passed'] = passed
        self.test_results['model']['failed'] = failed
        self.test_results['model']['errors'] = errors

        print()
        return errors == 0 and failed == 0

    def run_task_tests(self):
        """执行任务相关测试"""
        print("=" * 60)
        print("任务测试")
        print("=" * 60)

        passed, failed, errors = self._discover_and_run('task')
        self.test_results['task']['passed'] = passed
        self.test_results['task']['failed'] = failed
        self.test_results['task']['errors'] = errors

        print()
        return errors == 0 and failed == 0

    def generate_junit_xml(self):
        """生成 JUnit XML 格式的测试报告供 GitLab CI 解析"""
        import xml.etree.ElementTree as ET

        testsuites = ET.Element('testsuites')

        for category in ['db_connection', 'crud', 'driver', 'utils', 'config',
                         'drivers', 'driver_integration', 'llm',
                         'agents', 'services', 'script_writer_core', 'enterprise',
                         'model', 'task']:
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
        for category in ['db_connection', 'cdn', 'crud', 'driver', 'utils', 'config',
                         'auth', 'reference_images', 'stats', 'drivers', 'driver_integration',
                         'llm', 'agents', 'services', 'script_writer_core', 'enterprise',
                         'model', 'task']:
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

        print(f"LLM 测试:        "
              f"通过 {self.test_results['llm']['passed']}, "
              f"失败 {self.test_results['llm']['failed']}, "
              f"错误 {self.test_results['llm']['errors']}")

        print(f"Agents 测试:     "
              f"通过 {self.test_results['agents']['passed']}, "
              f"失败 {self.test_results['agents']['failed']}, "
              f"错误 {self.test_results['agents']['errors']}")

        print(f"Services 测试:   "
              f"通过 {self.test_results['services']['passed']}, "
              f"失败 {self.test_results['services']['failed']}, "
              f"错误 {self.test_results['services']['errors']}")

        print(f"ScriptWriterCore:"
              f"通过 {self.test_results['script_writer_core']['passed']}, "
              f"失败 {self.test_results['script_writer_core']['failed']}, "
              f"错误 {self.test_results['script_writer_core']['errors']}")

        print(f"Enterprise 测试:  "
              f"通过 {self.test_results['enterprise']['passed']}, "
              f"失败 {self.test_results['enterprise']['failed']}, "
              f"错误 {self.test_results['enterprise']['errors']}")

        print(f"数据模型测试:    "
              f"通过 {self.test_results['model']['passed']}, "
              f"失败 {self.test_results['model']['failed']}, "
              f"错误 {self.test_results['model']['errors']}")

        print(f"任务测试:        "
              f"通过 {self.test_results['task']['passed']}, "
              f"失败 {self.test_results['task']['failed']}, "
              f"错误 {self.test_results['task']['errors']}")

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
            self.args.llm_only,
            self.args.agents_only,
            self.args.services_only,
            self.args.script_writer_core_only,
            self.args.enterprise_only,
            self.args.model_only,
            self.args.task_only,
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

        # 步骤 12: LLM 测试
        if self.args.llm_only or not has_only_flag:
            self.run_llm_tests()

        # 步骤 13: Agents 测试
        if self.args.agents_only or not has_only_flag:
            self.run_agents_tests()

        # 步骤 14: Services 测试
        if self.args.services_only or not has_only_flag:
            self.run_services_tests()

        # 步骤 15: Script Writer Core 测试
        if self.args.script_writer_core_only or not has_only_flag:
            self.run_script_writer_core_tests()

        # 步骤 16: Enterprise 测试
        if self.args.enterprise_only or not has_only_flag:
            self.run_enterprise_tests()

        # 步骤 17: 数据模型测试
        if self.args.model_only or not has_only_flag:
            self.run_model_tests()

        # 步骤 18: 任务测试
        if self.args.task_only or not has_only_flag:
            self.run_task_tests()

        # 步骤 17: 输出摘要
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
    parser.add_argument('--llm-only', action='store_true', help='只执行 LLM 测试')
    parser.add_argument('--agents-only', action='store_true', help='只执行 Agents 测试')
    parser.add_argument('--services-only', action='store_true', help='只执行 Services 测试')
    parser.add_argument('--script-writer-core-only', action='store_true', help='只执行 Script Writer Core 测试')
    parser.add_argument('--enterprise-only', action='store_true', help='只执行企业版测试')
    parser.add_argument('--model-only', action='store_true', help='只执行数据模型测试')
    parser.add_argument('--task-only', action='store_true', help='只执行任务测试')
    parser.add_argument('--verbose', '-v', action='store_true', help='显示详细输出')
    parser.add_argument('--failfast', '-x', action='store_true', help='遇到失败立即停止')
    parser.add_argument('--coverage', action='store_true', help='生成覆盖率报告')
    parser.add_argument('--no-isolate', action='store_true',
                        help='关闭进程隔离：所有测试模块在同一进程顺序执行（快速但存在全局状态串扰风险）')
    parser.add_argument('--module-timeout', type=int, default=None,
                        help=f'进程隔离模式下单个测试模块的子进程超时秒数'
                             f'（默认 {UNIT_TEST_MODULE_TIMEOUT_SECONDS}s，见 config/constant.py）')
    
    args = parser.parse_args()
    
    runner = TestRunner(args)
    exit_code = runner.run()
    sys.exit(exit_code)


if __name__ == '__main__':
    main()
