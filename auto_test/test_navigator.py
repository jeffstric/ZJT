#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试导航器 - 自动分析测试 JSON 文件，提供下一个需要测试的端到端测试内容
避免 LLM 大模型上下文快速耗尽

用法:
    python test_navigator.py                    # 显示下一个待测试项
    python test_navigator.py --list             # 罗列所有模块
    python test_navigator.py --module auth      # 筛选指定模块的下一个测试
    python test_navigator.py --status           # 显示测试进度统计
    python test_navigator.py --feature node_005 # 显示指定功能的详细信息
    python test_navigator.py --pass node_005 1  # 标记 node_005 的步骤1为通过
    python test_navigator.py --pass node_005    # 标记 node_005 的所有步骤为通过
"""

import json
import os
import sys
import argparse
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, List, Any


class TestNavigator:
    """测试导航器类"""

    def __init__(self, base_dir: Optional[str] = None):
        if base_dir is None:
            base_dir = Path(__file__).parent
        self.base_dir = Path(base_dir)
        self.todo_list_path = self.base_dir / "test_todo_list.json"
        self.sessions_dir = self.base_dir / "test_sessions"
        self.config_path = self.base_dir / "test_config.json"

    def load_test_data(self) -> Dict[str, Any]:
        """加载测试数据（优先从会话文件加载）"""
        # 尝试加载最新的会话文件
        session_file = self._get_latest_session()
        if session_file:
            with open(session_file, 'r', encoding='utf-8') as f:
                return json.load(f), session_file
        # 否则加载模板文件
        with open(self.todo_list_path, 'r', encoding='utf-8') as f:
            return json.load(f), None

    def _get_latest_session(self) -> Optional[Path]:
        """获取最新的会话文件"""
        if not self.sessions_dir.exists():
            return None
        sessions = list(self.sessions_dir.glob("session_*.json"))
        if not sessions:
            return None
        return max(sessions, key=lambda x: x.stat().st_mtime)

    def list_modules(self) -> List[Dict[str, Any]]:
        """罗列所有模块及其进度"""
        data, session_file = self.load_test_data()
        modules = []

        for module in data.get("modules", []):
            module_id = module.get("id", "unknown")
            module_name = module.get("name", "未命名")
            features = module.get("features", [])

            total_features = len(features)
            passed_features = sum(1 for f in features if f.get("pass", False))

            total_steps = 0
            passed_steps = 0
            for feature in features:
                steps = feature.get("test_steps", [])
                total_steps += len(steps)
                passed_steps += sum(1 for s in steps if s.get("pass", False))

            modules.append({
                "id": module_id,
                "name": module_name,
                "total_features": total_features,
                "passed_features": passed_features,
                "total_steps": total_steps,
                "passed_steps": passed_steps,
                "progress": f"{passed_features}/{total_features}",
                "is_complete": passed_features == total_features
            })

        return modules

    def get_next_test(self, module_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """获取下一个待测试项"""
        data, session_file = self.load_test_data()

        for module in data.get("modules", []):
            # 如果指定了模块，只查找该模块
            if module_id and module.get("id") != module_id:
                continue

            for feature in module.get("features", []):
                if feature.get("pass", False):
                    continue

                # 找到第一个未通过的步骤
                for step in feature.get("test_steps", []):
                    if not step.get("pass", False):
                        return {
                            "module_id": module.get("id"),
                            "module_name": module.get("name"),
                            "feature_id": feature.get("id"),
                            "feature_name": feature.get("name"),
                            "feature_description": feature.get("description"),
                            "feature_priority": feature.get("priority", "P1"),
                            "page_url": feature.get("page_url", ""),
                            "api_endpoint": feature.get("api_endpoint", ""),
                            "prerequisites": feature.get("prerequisites", []),
                            "current_step": step,
                            "all_steps": feature.get("test_steps", []),
                            "step_index": step.get("step", 1),
                            "total_steps": len(feature.get("test_steps", [])),
                            "session_file": str(session_file) if session_file else None
                        }

        return None

    def get_feature_detail(self, feature_id: str) -> Optional[Dict[str, Any]]:
        """获取指定功能的详细信息"""
        data, session_file = self.load_test_data()

        for module in data.get("modules", []):
            for feature in module.get("features", []):
                if feature.get("id") == feature_id:
                    passed_steps = sum(1 for s in feature.get("test_steps", []) if s.get("pass", False))
                    total_steps = len(feature.get("test_steps", []))

                    return {
                        "module_id": module.get("id"),
                        "module_name": module.get("name"),
                        "feature": feature,
                        "passed_steps": passed_steps,
                        "total_steps": total_steps,
                        "is_complete": feature.get("pass", False)
                    }

        return None

    def mark_step_passed(self, feature_id: str, step_num: Optional[int] = None) -> bool:
        """标记指定步骤或整个功能为通过"""
        session_file = self._get_latest_session()
        if not session_file:
            print("❌ 错误: 没有找到会话文件")
            return False

        with open(session_file, 'r', encoding='utf-8') as f:
            data = json.load(f)

        found = False
        for module in data.get("modules", []):
            for feature in module.get("features", []):
                if feature.get("id") == feature_id:
                    found = True
                    if step_num is not None:
                        # 标记单个步骤
                        for step in feature.get("test_steps", []):
                            if step.get("step") == step_num:
                                step["pass"] = True
                                print(f"[PASS] 已标记 {feature_id} 步骤 {step_num} 为通过")
                                break
                        else:
                            print(f"[ERROR] 未找到步骤 {step_num}")
                            return False
                    else:
                        # 标记所有步骤
                        for step in feature.get("test_steps", []):
                            step["pass"] = True
                        print(f"[PASS] 已标记 {feature_id} 的所有步骤为通过")

                    # 检查是否所有步骤都通过，如果是则标记功能为通过
                    all_passed = all(s.get("pass", False) for s in feature.get("test_steps", []))
                    if all_passed:
                        feature["pass"] = True
                        print(f"[DONE] 功能 {feature_id} 已全部完成！")
                    break
            if found:
                break

        if not found:
            print(f"[ERROR] 未找到功能: {feature_id}")
            return False

        # 保存更新后的数据
        with open(session_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        print(f"[SAVE] 已更新会话文件: {session_file}")
        return True

    def mark_current_step_passed(self, module_id: Optional[str] = None) -> bool:
        """标记当前待测试的步骤为通过"""
        next_test = self.get_next_test(module_id)
        if not next_test:
            print("[DONE] 没有待测试的步骤")
            return False

        feature_id = next_test['feature_id']
        step_num = next_test['step_index']
        return self.mark_step_passed(feature_id, step_num)

    def get_status(self) -> Dict[str, Any]:
        """获取整体测试进度统计"""
        data, session_file = self.load_test_data()

        total_modules = len(data.get("modules", []))
        passed_modules = 0
        total_features = 0
        passed_features = 0
        total_steps = 0
        passed_steps = 0

        priority_stats = {"P0": {"total": 0, "passed": 0}, "P1": {"total": 0, "passed": 0}, "P2": {"total": 0, "passed": 0}}

        for module in data.get("modules", []):
            features = module.get("features", [])
            module_passed = all(f.get("pass", False) for f in features)
            if module_passed:
                passed_modules += 1

            for feature in features:
                total_features += 1
                if feature.get("pass", False):
                    passed_features += 1

                priority = feature.get("priority", "P1")
                if priority in priority_stats:
                    priority_stats[priority]["total"] += 1
                    if feature.get("pass", False):
                        priority_stats[priority]["passed"] += 1

                for step in feature.get("test_steps", []):
                    total_steps += 1
                    if step.get("pass", False):
                        passed_steps += 1

        return {
            "session_file": str(session_file) if session_file else "无会话文件",
            "modules": {"total": total_modules, "passed": passed_modules},
            "features": {"total": total_features, "passed": passed_features},
            "steps": {"total": total_steps, "passed": passed_steps},
            "priority_stats": priority_stats,
            "completion_rate": f"{passed_features / total_features * 100:.1f}%" if total_features > 0 else "0%"
        }


def print_modules(navigator: TestNavigator):
    """打印所有模块列表"""
    modules = navigator.list_modules()

    print("\n" + "=" * 60)
    print("[MODULES] 测试模块列表")
    print("=" * 60)

    for i, m in enumerate(modules, 1):
        status = "[DONE]" if m["is_complete"] else "[RUNNING]"
        print(f"\n{i}. {status} [{m['id']}] {m['name']}")
        print(f"   功能进度: {m['progress']} ({m['passed_features']}/{m['total_features']})")
        print(f"   步骤进度: {m['passed_steps']}/{m['total_steps']}")

    print("\n" + "-" * 60)
    print("使用方法: python test_navigator.py --module <模块ID>")
    print("=" * 60 + "\n")


def print_next_test(navigator: TestNavigator, module_id: Optional[str] = None):
    """打印下一个待测试项"""
    next_test = navigator.get_next_test(module_id)

    if not next_test:
        if module_id:
            print(f"\n[DONE] 模块 [{module_id}] 的所有测试已完成！")
        else:
            print("\n[DONE] 所有测试已完成！")
        return

    print("\n" + "=" * 70)
    print("[NEXT] 下一个待测试项")
    print("=" * 70)

    print(f"\n[MODULE] 模块: [{next_test['module_id']}] {next_test['module_name']}")
    print(f"[FEATURE] 功能: [{next_test['feature_id']}] {next_test['feature_name']}")
    print(f"[DESC] 描述: {next_test['feature_description']}")
    print(f"[PRIORITY] 优先级: {next_test['feature_priority']}")

    if next_test['page_url']:
        print(f"[PAGE] 页面: {next_test['page_url']}")
    if next_test['api_endpoint']:
        print(f"[API] API: {next_test['api_endpoint']}")
    if next_test['prerequisites']:
        print(f"[DEPS] 前置依赖: {', '.join(next_test['prerequisites'])}")

    print(f"\n[PROGRESS] 进度: 步骤 {next_test['step_index']}/{next_test['total_steps']}")

    if next_test['session_file']:
        print(f"[FILE] 会话文件: {next_test['session_file']}")

    print("\n" + "-" * 70)
    print("[CURRENT] 当前步骤详情:")
    print("-" * 70)

    step = next_test['current_step']
    print(f"步骤 {step.get('step', '?')}: {step.get('action', '未知操作')}")

    if step.get('mcp_tool'):
        print(f"  MCP工具: {step.get('mcp_tool')}")
        if step.get('mcp_params'):
            print(f"  参数: {json.dumps(step.get('mcp_params'), ensure_ascii=False, indent=4)}")

    if step.get('expected_result'):
        print(f"  预期结果: {step.get('expected_result')}")
    if step.get('verify'):
        print(f"  验证点: {step.get('verify')}")

    print("\n" + "-" * 70)
    print("[STEPS] 完整步骤列表:")
    print("-" * 70)

    for s in next_test['all_steps']:
        status = "[PASS]" if s.get('pass', False) else "[TODO]"
        current = ">>>" if s.get('step') == step.get('step') else "   "
        print(f"{current} {status} 步骤 {s.get('step', '?')}: {s.get('action', '未知')}")

    print("=" * 70 + "\n")


def print_feature_detail(navigator: TestNavigator, feature_id: str):
    """打印指定功能的详细信息"""
    detail = navigator.get_feature_detail(feature_id)

    if not detail:
        print(f"\n[ERROR] 未找到功能: {feature_id}")
        return

    feature = detail['feature']

    print("\n" + "=" * 70)
    print(f"[FEATURE] 功能详情: [{feature_id}]")
    print("=" * 70)

    print(f"\n[MODULE] 模块: [{detail['module_id']}] {detail['module_name']}")
    print(f"[NAME] 功能: {feature.get('name', '未命名')}")
    print(f"[DESC] 描述: {feature.get('description', '无描述')}")
    print(f"[PRIORITY] 优先级: {feature.get('priority', 'P1')}")
    print(f"[STATUS] 状态: {'已完成' if detail['is_complete'] else '进行中'}")
    print(f"[PROGRESS] 进度: {detail['passed_steps']}/{detail['total_steps']} 步骤")

    if feature.get('page_url'):
        print(f"[PAGE] 页面: {feature.get('page_url')}")
    if feature.get('api_endpoint'):
        print(f"[API] API: {feature.get('api_endpoint')}")
    if feature.get('prerequisites'):
        print(f"[DEPS] 前置依赖: {', '.join(feature.get('prerequisites', []))}")

    print("\n" + "-" * 70)
    print("[STEPS] 测试步骤:")
    print("-" * 70)

    for step in feature.get('test_steps', []):
        status = "[PASS]" if step.get('pass', False) else "[TODO]"
        print(f"\n{status} 步骤 {step.get('step', '?')}: {step.get('action', '未知操作')}")

        if step.get('mcp_tool'):
            print(f"   MCP工具: {step.get('mcp_tool')}")
        if step.get('expected_result'):
            print(f"   预期结果: {step.get('expected_result')}")
        if step.get('verify'):
            print(f"   验证点: {step.get('verify')}")

    print("\n" + "=" * 70 + "\n")


def print_status(navigator: TestNavigator):
    """打印测试进度统计"""
    status = navigator.get_status()

    print("\n" + "=" * 60)
    print("[STATUS] 测试进度统计")
    print("=" * 60)

    print(f"\n[FILE] 会话文件: {status['session_file']}")

    print(f"\n[MODULE] 模块进度: {status['modules']['passed']}/{status['modules']['total']}")
    print(f"[FEATURE] 功能进度: {status['features']['passed']}/{status['features']['total']}")
    print(f"[STEP] 步骤进度: {status['steps']['passed']}/{status['steps']['total']}")
    print(f"[RATE] 完成率: {status['completion_rate']}")

    print("\n" + "-" * 60)
    print("按优先级统计:")
    print("-" * 60)

    for priority, stats in status['priority_stats'].items():
        pct = f"{stats['passed'] / stats['total'] * 100:.1f}%" if stats['total'] > 0 else "0%"
        print(f"  {priority}: {stats['passed']}/{stats['total']} ({pct})")

    print("\n" + "=" * 60 + "\n")


def main():
    parser = argparse.ArgumentParser(
        description="测试导航器 - 自动分析测试 JSON 文件，提供下一个需要测试的端到端测试内容",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python test_navigator.py                    # 显示下一个待测试项
  python test_navigator.py --list             # 罗列所有模块
  python test_navigator.py --module auth      # 筛选指定模块的下一个测试
  python test_navigator.py --status           # 显示测试进度统计
  python test_navigator.py --feature node_005 # 显示指定功能的详细信息
        """
    )

    parser.add_argument('--list', '-l', action='store_true', help='罗列所有模块')
    parser.add_argument('--module', '-m', type=str, help='筛选指定模块的下一个测试')
    parser.add_argument('--status', '-s', action='store_true', help='显示测试进度统计')
    parser.add_argument('--feature', '-f', type=str, help='显示指定功能的详细信息')
    parser.add_argument('--pass', '-p', nargs='+', metavar=('FEATURE_ID', 'STEP'), dest='mark_pass', help='标记步骤为通过。用法: --pass feature_id [step_num]')
    parser.add_argument('--pass-current', '-c', action='store_true', help='标记当前待测试的步骤为通过')

    args = parser.parse_args()

    navigator = TestNavigator()

    try:
        if args.list:
            print_modules(navigator)
        elif args.status:
            print_status(navigator)
        elif args.feature:
            print_feature_detail(navigator, args.feature)
        elif args.mark_pass:
            feature_id = args.mark_pass[0]
            step_num = int(args.mark_pass[1]) if len(args.mark_pass) > 1 else None
            navigator.mark_step_passed(feature_id, step_num)
        elif args.pass_current:
            if not args.module:
                print("[ERROR] --pass-current 必须配合 --module 使用")
                print("   用法: python test_navigator.py --pass-current --module <模块ID>")
                sys.exit(1)
            navigator.mark_current_step_passed(args.module)
        elif args.module:
            print_next_test(navigator, args.module)
        else:
            print_next_test(navigator)
    except FileNotFoundError as e:
        print(f"\n[ERROR] 找不到测试文件 - {e}")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"\n[ERROR] JSON 解析失败 - {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
