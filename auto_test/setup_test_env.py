#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
自动化测试环境初始化脚本
支持 Windows 和 Linux 系统
"""

import os
import sys
import json
import shutil
import subprocess
from pathlib import Path


def print_info(msg):
    """打印信息"""
    print(f"[INFO] {msg}")


def print_ok(msg):
    """打印成功信息"""
    print(f"[OK] {msg}")


def print_skip(msg):
    """打印跳过信息"""
    print(f"[SKIP] {msg}")


def print_warn(msg):
    """打印警告信息"""
    print(f"[WARN] {msg}")


def print_error(msg):
    """打印错误信息"""
    print(f"[ERROR] {msg}")


def main():
    """主函数"""
    # 获取脚本所在目录
    script_dir = Path(__file__).parent.absolute()
    os.chdir(script_dir)
    
    print_info("开始初始化测试环境...")
    print_info(f"当前系统: {sys.platform}")
    print_info(f"工作目录: {script_dir}")
    
    # 1. 创建 test_sessions 目录
    test_sessions_dir = script_dir / "test_sessions"
    if not test_sessions_dir.exists():
        test_sessions_dir.mkdir(parents=True, exist_ok=True)
        print_ok("已创建 test_sessions 目录")
    else:
        print_skip("test_sessions 目录已存在")
    
    # 2. 创建 test_assets 目录
    test_assets_dir = script_dir / "test_assets"
    if not test_assets_dir.exists():
        test_assets_dir.mkdir(parents=True, exist_ok=True)
        print_ok("已创建 test_assets 目录")
    else:
        print_skip("test_assets 目录已存在")
    
    # 3. 创建 test_config.json（如果不存在）
    config_file = script_dir / "test_config.json"
    example_config_file = script_dir / "test_config.example.json"
    
    if not config_file.exists():
        if example_config_file.exists():
            # 读取示例配置
            with open(example_config_file, 'r', encoding='utf-8') as f:
                config_data = json.load(f)
            
            # 修正路径为当前系统格式
            if 'test_assets' in config_data:
                # 将 Windows 路径替换为当前系统路径
                config_data['test_assets']['test_image'] = str(test_assets_dir / "test_image.jpg")
                config_data['test_assets']['test_video'] = str(test_assets_dir / "test.mp4")
            
            # 写入配置文件
            with open(config_file, 'w', encoding='utf-8') as f:
                json.dump(config_data, f, ensure_ascii=False, indent=2)
            
            print_ok("已创建 test_config.json（从 example 复制）")
            print_warn("请编辑 test_config.json 填写实际的服务器地址和登录凭证")
        else:
            print_error("test_config.example.json 不存在，无法创建配置文件")
            sys.exit(1)
    else:
        print_skip("test_config.json 已存在")
    
    # 4. 检查测试资源文件
    test_image = test_assets_dir / "test_image.jpg"
    if not test_image.exists():
        print_warn("test_assets/test_image.jpg 不存在，请手动添加测试图片")
    
    test_video = test_assets_dir / "test.mp4"
    if not test_video.exists():
        print_warn("test_assets/test.mp4 不存在，请手动添加测试视频")
    
    # 5. 合并测试用例（仅在 test_todo_list.json 不存在时）
    modules_dir = script_dir / "test_modules"
    test_todo_list = script_dir / "test_todo_list.json"
    
    if modules_dir.exists() and (modules_dir / "index.json").exists():
        if not test_todo_list.exists():
            print_info("test_todo_list.json 不存在，从模块文件合并...")
            try:
                result = subprocess.run(
                    [sys.executable, str(script_dir / "merge_test_cases.py")],
                    capture_output=True,
                    timeout=30
                )
                if result.returncode == 0:
                    print_ok("测试用例已合并")
                else:
                    print_error("测试用例合并失败")
                    sys.exit(1)
            except Exception as e:
                print_error(f"测试用例合并失败: {e}")
                sys.exit(1)
        else:
            print_ok("test_todo_list.json 已存在，跳过合并（保留测试进度）")
    
    # 6. 验证 Python 脚本
    test_navigator = script_dir / "test_navigator.py"
    if test_navigator.exists():
        try:
            result = subprocess.run(
                [sys.executable, str(test_navigator), "--status"],
                capture_output=True,
                timeout=10
            )
            if result.returncode == 0:
                print_ok("test_navigator.py 可正常执行")
            else:
                print_error("test_navigator.py 执行失败，请检查 Python 环境")
                sys.exit(1)
        except Exception as e:
            print_error(f"test_navigator.py 执行失败: {e}")
            sys.exit(1)
    else:
        print_error("test_navigator.py 不存在")
        sys.exit(1)
    
    # 输出完成信息
    print()
    print("=" * 50)
    print("[SUCCESS] 测试环境初始化完成！")
    print("=" * 50)
    print()
    print("下一步操作：")
    print("1. 编辑 test_config.json 填写：")
    print("   - base_url: 测试服务器地址")
    print("   - credentials: 登录凭证")
    print("2. 添加测试资源文件到 test_assets/ 目录：")
    print("   - test_image.jpg")
    print("   - test.mp4")
    print("3. 运行 python test_navigator.py --status 查看测试状态")
    print()
    print("提示：")
    print("- 测试用例已模块化，存储在 test_modules/ 目录")
    print("- 查看 test_modules/README_modular_tests.md 了解模块化结构")
    print("- 修改测试用例请编辑 test_modules/ 中的模块文件")
    print("- 修改后运行 python merge_test_cases.py 重新合并")
    print("- 注意：合并会覆盖 test_todo_list.json，请在测试完成后操作")
    print("- 修改后运行 python merge_test_cases.py 重新合并")
    print("- 注意：合并会覆盖 test_todo_list.json，请在测试完成后操作")
    print()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print()
        print_error("用户中断执行")
        sys.exit(1)
    except Exception as e:
        print()
        print_error(f"执行失败: {e}")
        sys.exit(1)
