#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试导航器 - 自动分析会话文件，提供下一个需要测试的端到端测试内容
避免 LLM 大模型上下文快速耗尽

用法:
    python test_navigator.py                    # 显示下一个待测试项
    python test_navigator.py --list             # 罗列所有模块
    python test_navigator.py --module auth      # 筛选指定模块的下一个测试
    python test_navigator.py --status           # 显示测试进度统计
    python test_navigator.py --feature node_005 # 显示指定功能的详细信息
    python test_navigator.py --mark node_005 1 --set-pass true --set-processed true  # 标记步骤状态
    python test_navigator.py --mark node_005 --set-pass false --set-processed true    # 标记整个功能为已处理但未通过
    python test_navigator.py --skip-processed   # 跳过已处理(is_processed=true)的测试
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
        self.sessions_dir = self.base_dir / "test_sessions"
        self.config_path = self.base_dir / "test_config.json"

    def load_test_data(self) -> Dict[str, Any]:
        """加载测试数据（仅从会话文件加载）"""
        # 尝试加载最新的会话文件
        session_file = self._get_latest_session()
        if session_file:
            with open(session_file, 'r', encoding='utf-8-sig') as f:
                return json.load(f), session_file
        # 如果没有会话文件，抛出错误
        raise FileNotFoundError("未找到会话文件，请先创建会话文件")

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
            # 功能完成条件：所有步骤都已处理完毕（无论通过与否）
            completed_features = sum(1 for f in features if all(s.get("is_processed", False) for s in f.get("test_steps", [])))

            total_steps = 0
            processed_steps = 0
            for feature in features:
                steps = feature.get("test_steps", [])
                total_steps += len(steps)
                processed_steps += sum(1 for s in steps if s.get("is_processed", False))

            modules.append({
                "id": module_id,
                "name": module_name,
                "total_features": total_features,
                "passed_features": completed_features,
                "total_steps": total_steps,
                "passed_steps": processed_steps,
                "progress": f"{completed_features}/{total_features}",
                "is_complete": completed_features == total_features
            })

        return modules

    def get_next_test(self, module_id: Optional[str] = None, skip_processed: bool = False) -> Optional[Dict[str, Any]]:
        """获取下一个待测试项

        Args:
            module_id: 指定模块ID，只查找该模块
            skip_processed: 如果为True，跳过is_processed=True的测试（即使pass=False）
        """
        data, session_file = self.load_test_data()

        for module in data.get("modules", []):
            # 如果指定了模块，只查找该模块
            if module_id and module.get("id") != module_id:
                continue

            for feature in module.get("features", []):
                if feature.get("pass", False):
                    continue
                # 如果启用skip_processed，跳过已处理的feature
                if skip_processed and feature.get("is_processed", False):
                    continue

                # 找到第一个未通过的步骤
                for step in feature.get("test_steps", []):
                    if not step.get("pass", False):
                        # 如果启用skip_processed，跳过已处理的step
                        if skip_processed and step.get("is_processed", False):
                            continue
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

    def mark_step(self, feature_id: str, set_pass: bool, set_processed: bool, step_num: Optional[int] = None, remark: Optional[str] = None) -> bool:
        """标记指定步骤或整个功能的状态

        Args:
            feature_id: 功能ID
            set_pass: 必填，设置pass字段的值
            set_processed: 必填，设置is_processed字段的值
            step_num: 可选，步骤号。不传则标记整个功能
            remark: 必填，备注信息（防止测试工程师走捷径）
        """
        # 强制要求提供备注，防止测试工程师走捷径
        if not remark or remark.strip() == "":
            print("[ERROR] 必须提供备注信息！这是为了确保测试工程师真正执行了测试。")
            print("[ERROR] 备注应包含：测试过程、观察结果、验证要点等具体信息。")
            print("[ERROR] 示例：'成功登录，界面显示用户信息，token验证通过'")
            return False
        
        # 检查备注长度，确保不是敷衍的短备注
        if len(remark.strip()) < 5:
            print("[ERROR] 备注信息过短！请提供详细的测试过程和结果描述（至少5个字符）。")
            print("[ERROR] 这是为了确保测试工程师提供真实的测试证据。")
            return False
        session_file = self._get_latest_session()
        if not session_file:
            print("[ERROR] 没有找到会话文件")
            return False

        with open(session_file, 'r', encoding='utf-8-sig') as f:
            data = json.load(f)

        found = False
        for module in data.get("modules", []):
            for feature in module.get("features", []):
                if feature.get("id") == feature_id:
                    found = True
                    # 记录操作时间戳
                    current_time = datetime.now().isoformat()
                    
                    if step_num is not None:
                        # 标记单个步骤
                        for step in feature.get("test_steps", []):
                            if step.get("step") == step_num:
                                step["pass"] = set_pass
                                step["is_processed"] = set_processed
                                step["remark"] = remark
                                step["marked_at"] = current_time  # 记录标记时间
                                step["marked_by"] = "test_engineer"  # 标记操作者
                                
                                pass_str = "PASS" if set_pass else "FAIL"
                                proc_str = "PROCESSED" if set_processed else "UNPROCESSED"
                                msg = f"[MARK] 已标记 {feature_id} 步骤 {step_num}: pass={set_pass}, is_processed={set_processed}"
                                msg += f", 备注: {remark}"
                                msg += f", 时间: {current_time}"
                                print(msg)
                                break
                        else:
                            print(f"[ERROR] 未找到步骤 {step_num}")
                            return False
                    else:
                        # 标记所有步骤（批量操作需要特别记录）
                        batch_operation_log = {
                            "operation_type": "batch_mark_all_steps",
                            "feature_id": feature_id,
                            "timestamp": current_time,
                            "set_pass": set_pass,
                            "set_processed": set_processed,
                            "remark": remark,
                            "step_count": len(feature.get("test_steps", []))
                        }
                        
                        for step in feature.get("test_steps", []):
                            step["pass"] = set_pass
                            step["is_processed"] = set_processed
                            step["remark"] = remark
                            step["marked_at"] = current_time
                            step["marked_by"] = "test_engineer"
                            step["batch_operation"] = True  # 标记为批量操作
                        
                        # 记录批量操作到功能级别
                        if "batch_operations" not in feature:
                            feature["batch_operations"] = []
                        feature["batch_operations"].append(batch_operation_log)
                        
                        msg = f"[MARK] 已批量标记 {feature_id} 的所有步骤: pass={set_pass}, is_processed={set_processed}"
                        msg += f", 备注: {remark}"
                        msg += f", 时间: {current_time}"
                        msg += f" [WARNING] 批量操作已记录，请确保真实测试过所有步骤！"
                        print(msg)

                    # 检查是否所有步骤都通过，如果是则标记功能为通过
                    all_passed = all(s.get("pass", False) for s in feature.get("test_steps", []))
                    if all_passed:
                        feature["pass"] = True
                        feature["completed_at"] = current_time  # 记录功能完成时间
                        print(f"[DONE] 功能 {feature_id} 已全部通过! 完成时间: {current_time}")

                    # 检查是否所有步骤都已处理
                    all_processed = all(s.get("is_processed", False) for s in feature.get("test_steps", []))
                    if all_processed:
                        feature["is_processed"] = True
                        feature["processed_at"] = current_time  # 记录处理完成时间
                        print(f"[INFO] 功能 {feature_id} 已全部标记为已处理，时间: {current_time}")
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

    def mark_batch(self, feature_id: str, batch_config: Dict[str, Any]) -> bool:
        """批量标记多个步骤为不同状态
        
        Args:
            feature_id: 功能ID
            batch_config: 批量配置，格式：{
                "remark": "整体备注信息",
                "steps": [{"step": 1, "pass": true, "processed": true, "remark": "步骤备注"}, ...]
            }
            
        Returns:
            bool: 是否成功
        """
        # 检查配置格式
        if not isinstance(batch_config, dict):
            print("[ERROR] 批量配置必须是字典格式！")
            return False
            
        remark = batch_config.get("remark", "")
        step_configs = batch_config.get("steps", [])
        
        # 强制要求提供备注
        if not remark or remark.strip() == "":
            print("[ERROR] 必须在JSON中提供remark字段！这是为了确保测试工程师真正执行了测试。")
            print("[ERROR] 备注应包含：测试过程、观察结果、验证要点等具体信息。")
            return False
        
        if len(remark.strip()) < 10:
            print("[ERROR] 备注信息过短！请提供详细的测试过程和结果描述（至少10个字符）。")
            return False
            
        if not step_configs:
            print("[ERROR] 必须提供步骤配置信息！")
            return False
            
        session_file = self._get_latest_session()
        if not session_file:
            print("[ERROR] 没有找到会话文件")
            return False

        with open(session_file, 'r', encoding='utf-8-sig') as f:
            data = json.load(f)

        found = False
        current_time = datetime.now().isoformat()
        
        for module in data.get("modules", []):
            for feature in module.get("features", []):
                if feature.get("id") == feature_id:
                    found = True
                    
                    # 记录批量混合操作
                    batch_operation_log = {
                        "operation_type": "batch_mark_mixed_steps",
                        "feature_id": feature_id,
                        "timestamp": current_time,
                        "step_configs": step_configs,
                        "remark": remark,
                        "step_count": len(step_configs)
                    }
                    
                    # 应用步骤配置
                    updated_steps = []
                    for config in step_configs:
                        step_num = config.get("step")
                        set_pass = config.get("pass", False)
                        set_processed = config.get("processed", True)
                        step_remark = config.get("remark", remark)  # 优先使用步骤级备注，否则使用整体备注
                        
                        for step in feature.get("test_steps", []):
                            if step.get("step") == step_num:
                                step["pass"] = set_pass
                                step["is_processed"] = set_processed
                                step["remark"] = step_remark
                                step["marked_at"] = current_time
                                step["marked_by"] = "test_engineer"
                                step["batch_operation"] = True
                                updated_steps.append(f"步骤{step_num}({'通过' if set_pass else '失败'})")
                                break
                        else:
                            print(f"[WARNING] 未找到步骤 {step_num}")
                    
                    # 记录批量操作到功能级别
                    if "batch_operations" not in feature:
                        feature["batch_operations"] = []
                    feature["batch_operations"].append(batch_operation_log)
                    
                    # 检查功能状态
                    all_passed = all(s.get("pass", False) for s in feature.get("test_steps", []))
                    if all_passed:
                        feature["pass"] = True
                        feature["completed_at"] = current_time
                        print(f"[DONE] 功能 {feature_id} 已全部通过! 完成时间: {current_time}")
                    
                    all_processed = all(s.get("is_processed", False) for s in feature.get("test_steps", []))
                    if all_processed:
                        feature["is_processed"] = True
                        feature["processed_at"] = current_time
                        print(f"[INFO] 功能 {feature_id} 已全部标记为已处理，时间: {current_time}")
                    
                    print(f"[MARK] 已批量标记 {feature_id}: {', '.join(updated_steps)}")
                    print(f"[MARK] 备注: {remark}")
                    print(f"[MARK] 时间: {current_time}")
                    print(f"[WARNING] 批量混合操作已记录，请确保真实测试过所有步骤！")
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
            # 模块完成条件：所有功能都已处理完毕（无论通过与否）
            module_completed = all(
                all(s.get("is_processed", False) for s in f.get("test_steps", []))
                for f in features
            )
            if module_completed:
                passed_modules += 1

            for feature in features:
                total_features += 1
                # 功能完成条件：所有步骤都已处理完毕（无论通过与否）
                feature_completed = all(s.get("is_processed", False) for s in feature.get("test_steps", []))
                if feature_completed:
                    passed_features += 1

                priority = feature.get("priority", "P1")
                if priority in priority_stats:
                    priority_stats[priority]["total"] += 1
                    if feature_completed:
                        priority_stats[priority]["passed"] += 1

                for step in feature.get("test_steps", []):
                    total_steps += 1
                    # 步骤完成条件：已处理完毕（无论通过与否）
                    if step.get("is_processed", False):
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


def print_next_test(navigator: TestNavigator, module_id: Optional[str] = None, skip_processed: bool = False):
    """打印下一个待测试项"""
    next_test = navigator.get_next_test(module_id, skip_processed)

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
        processed = "[PROCESSED]" if s.get('is_processed', False) else ""
        current = ">>>" if s.get('step') == step.get('step') else "   "
        print(f"{current} {status} {processed} 步骤 {s.get('step', '?')}: {s.get('action', '未知')}")

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
        processed = "[PROCESSED]" if step.get('is_processed', False) else ""
        print(f"\n{status} {processed} 步骤 {step.get('step', '?')}: {step.get('action', '未知操作')}")

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
  python test_navigator.py --mark node_005 1 --set-pass true --set-processed true --remark "步骤测试通过"  # 标记单个步骤
  python test_navigator.py --mark node_005 --set-pass false --set-processed true --remark "功能测试失败"   # 标记整个功能
  python test_navigator.py --mark-batch auth_001 --batch-config '{"remark":"步骤1通过，步骤2失败","steps":[{"step":1,"pass":true,"processed":true},{"step":2,"pass":false,"processed":true}]}'  # 批量混合标记
  python test_navigator.py --skip-processed   # 跳过已处理的测试
        """
    )

    parser.add_argument('--list', '-l', action='store_true', help='罗列所有模块')
    parser.add_argument('--module', '-m', type=str, help='筛选指定模块的下一个测试')
    parser.add_argument('--status', '-s', action='store_true', help='显示测试进度统计')
    parser.add_argument('--feature', '-f', type=str, help='显示指定功能的详细信息')
    parser.add_argument('--mark', nargs='+', metavar=('FEATURE_ID', 'STEP'), help='标记步骤状态。用法: --mark feature_id [step_num]，必须配合 --set-pass 和 --set-processed 使用')
    parser.add_argument('--set-pass', type=str, choices=['true', 'false'], help='必填，设置pass字段的值')
    parser.add_argument('--set-processed', type=str, choices=['true', 'false'], help='必填，设置is_processed字段的值')
    parser.add_argument('--remark', '-r', type=str, help='为标记的步骤添加备注信息')
    parser.add_argument('--mark-batch', type=str, help='批量混合标记功能ID，配合 --batch-config 使用')
    parser.add_argument('--batch-config', type=str, help='批量配置JSON字符串，格式: "{\"remark\":\"整体备注\",\"steps\":[{\"step\":1,\"pass\":true,\"processed\":true,\"remark\":\"步骤备注\"}]}"')
    parser.add_argument('--skip-processed', action='store_true', help='跳过已处理(is_processed=True)的测试项')

    args = parser.parse_args()

    navigator = TestNavigator()

    try:
        if args.list:
            print_modules(navigator)
        elif args.status:
            print_status(navigator)
        elif args.feature:
            print_feature_detail(navigator, args.feature)
        elif args.mark_batch:
            # 批量混合标记功能
            if not args.batch_config:
                print("[ERROR] --mark-batch 必须配合 --batch-config 使用")
                print("   用法: python test_navigator.py --mark-batch <feature_id> --batch-config '<json>'")
                print("   示例: python test_navigator.py --mark-batch auth_001 --batch-config '{\"remark\":\"步骤1-3通过，步骤4-6失败\",\"steps\":[{\"step\":1,\"pass\":true,\"processed\":true},{\"step\":2,\"pass\":false,\"processed\":true}]}'")
                sys.exit(1)
            
            try:
                batch_config = json.loads(args.batch_config)
                navigator.mark_batch(args.mark_batch, batch_config)
            except json.JSONDecodeError as e:
                print(f"[ERROR] 批量配置JSON格式错误: {e}")
                print("   正确格式: '{\"remark\":\"整体备注\",\"steps\":[{\"step\":1,\"pass\":true,\"processed\":true,\"remark\":\"步骤备注\"}]}'")
                sys.exit(1)
        elif args.mark:
            # 检查必填参数
            if args.set_pass is None or args.set_processed is None:
                print("[ERROR] --mark 必须配合 --set-pass 和 --set-processed 使用")
                print("   用法: python test_navigator.py --mark <feature_id> [step_num] --set-pass <true|false> --set-processed <true|false>")
                print("   示例: python test_navigator.py --mark node_005 1 --set-pass true --set-processed true")
                sys.exit(1)
            feature_id = args.mark[0]
            step_num = int(args.mark[1]) if len(args.mark) > 1 else None
            set_pass = args.set_pass.lower() == 'true'
            set_processed = args.set_processed.lower() == 'true'
            remark = args.remark
            navigator.mark_step(feature_id, set_pass, set_processed, step_num, remark)
        elif args.module:
            print_next_test(navigator, args.module, args.skip_processed)
        else:
            print_next_test(navigator, skip_processed=args.skip_processed)
    except FileNotFoundError as e:
        print(f"\n[ERROR] 找不到测试文件 - {e}")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"\n[ERROR] JSON 解析失败 - {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
