#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试状态重置脚本
清理上次测试的状态，以便开始新一轮测试

用法:
    python reset_test_session.py           # 重置测试状态（会先归档当前结果）
    python reset_test_session.py --force   # 强制重置，不归档
    python reset_test_session.py --keep-session  # 保留会话文件，只重置进度
"""

import json
import os
import shutil
import argparse
from datetime import datetime
from pathlib import Path


def reset_test_session(force: bool = False, keep_session: bool = False):
    """重置测试状态

    Args:
        force: 强制重置，不先归档当前结果
        keep_session: 保留会话文件，只重置进度状态
    """
    base_dir = Path(__file__).parent

    # 1. 如果不是强制模式，先归档当前结果
    if not force:
        try:
            from generate_report import archive_test_results
            print("[INFO] 正在归档当前测试结果...")
            archive_test_results()
            print("")
        except Exception as e:
            print(f"[WARNING] 归档失败: {e}")
            print("[INFO] 继续重置操作...")

    # 2. 重置 test_progress.json
    progress_file = base_dir / "test_progress.json"
    if progress_file.exists():
        with open(progress_file, 'r', encoding='utf-8-sig') as f:
            progress = json.load(f)

        # 重置所有模块状态为 pending
        for module in progress.get('modules', []):
            module['status'] = 'pending'

        with open(progress_file, 'w', encoding='utf-8') as f:
            json.dump(progress, f, ensure_ascii=False, indent=2)

        print(f"[SUCCESS] 已重置进度文件: {progress_file}")

    # 3. 处理会话文件
    sessions_dir = base_dir / "test_sessions"
    if sessions_dir.exists() and not keep_session:
        session_files = list(sessions_dir.glob("session_*.json"))
        if session_files:
            for session_file in session_files:
                session_file.unlink()
                print(f"[SUCCESS] 已删除会话文件: {session_file.name}")

            # 从 test_todo_list.json 创建新的会话文件
            todo_list_file = base_dir / "test_todo_list.json"
            if todo_list_file.exists():
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                new_session_file = sessions_dir / f"session_{timestamp}.json"
                shutil.copy2(todo_list_file, new_session_file)
                print(f"[SUCCESS] 已创建新会话文件: {new_session_file.name}")
    elif keep_session:
        # 只重置会话文件中的 pass 和 is_processed 状态
        if sessions_dir.exists():
            session_files = list(sessions_dir.glob("session_*.json"))
            if session_files:
                latest_session = max(session_files, key=lambda x: x.stat().st_mtime)
                with open(latest_session, 'r', encoding='utf-8-sig') as f:
                    session_data = json.load(f)

                # 重置所有状态
                for module in session_data.get('modules', []):
                    module['pass'] = False
                    module['is_processed'] = False
                    for feature in module.get('features', []):
                        feature['pass'] = False
                        feature['is_processed'] = False
                        for step in feature.get('test_steps', []):
                            step['pass'] = False
                            step['is_processed'] = False
                            if 'remark' in step:
                                step['remark'] = ''

                with open(latest_session, 'w', encoding='utf-8') as f:
                    json.dump(session_data, f, ensure_ascii=False, indent=2)

                print(f"[SUCCESS] 已重置会话状态: {latest_session.name}")

    # 4. 删除旧的报告文件（根目录下的）
    old_report = base_dir / "test_report.html"
    if old_report.exists():
        old_report.unlink()
        print(f"[SUCCESS] 已删除旧报告: test_report.html")

    print("")
    print("[DONE] 测试状态已重置，可以开始新一轮测试")
    print("       运行 'python test_navigator.py --status' 查看状态")


def main():
    parser = argparse.ArgumentParser(
        description="测试状态重置脚本 - 清理上次测试状态，准备新一轮测试",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python reset_test_session.py           # 重置测试状态（会先归档当前结果）
  python reset_test_session.py --force   # 强制重置，不归档
  python reset_test_session.py --keep-session  # 保留会话文件结构，只重置状态
        """
    )

    parser.add_argument('--force', '-f', action='store_true',
                        help='强制重置，不先归档当前测试结果')
    parser.add_argument('--keep-session', '-k', action='store_true',
                        help='保留会话文件，只重置其中的pass/is_processed状态')

    args = parser.parse_args()

    reset_test_session(force=args.force, keep_session=args.keep_session)


if __name__ == "__main__":
    main()