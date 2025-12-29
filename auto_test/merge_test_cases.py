#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试用例合并脚本
将多个模块文件合并为一个完整的 test_todo_list.json
用于测试启动时加载
"""

import json
import os
from pathlib import Path
from typing import Dict, List, Any


def merge_test_cases(output_file: str = "test_todo_list.json") -> bool:
    """合并测试用例
    
    Args:
        output_file: 输出文件名
        
    Returns:
        bool: 是否成功
    """
    script_dir = Path(__file__).parent
    modules_dir = script_dir / "test_modules"
    output_path = script_dir / output_file
    
    print("[INFO] 开始合并测试用例...")
    
    # 检查模块目录是否存在
    if not modules_dir.exists():
        print(f"[ERROR] 模块目录不存在: {modules_dir}")
        return False
    
    # 读取索引文件
    index_file = modules_dir / "index.json"
    if not index_file.exists():
        print(f"[ERROR] 索引文件不存在: {index_file}")
        return False
    
    with open(index_file, 'r', encoding='utf-8') as f:
        index_data = json.load(f)
    
    module_list = index_data.get('modules', [])
    print(f"[INFO] 找到 {len(module_list)} 个模块")
    
    # 加载所有模块
    modules = []
    for module_info in module_list:
        module_file = modules_dir / module_info['file']
        
        if not module_file.exists():
            print(f"[WARN] 模块文件不存在: {module_file}")
            continue
        
        with open(module_file, 'r', encoding='utf-8') as f:
            module_data = json.load(f)
        
        modules.append(module_data)
        print(f"[OK] 加载模块: {module_info['id']} ({module_info['feature_count']} 个功能)")
    
    # 构建完整数据结构
    merged_data = {
        "modules": modules
    }
    
    # 写入输出文件
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(merged_data, f, ensure_ascii=False, indent=2)
    
    # 计算文件大小
    file_size = output_path.stat().st_size / 1024
    
    print(f"\n[SUCCESS] 合并完成！")
    print(f"[INFO] 输出文件: {output_path}")
    print(f"[INFO] 文件大小: {file_size:.1f} KB")
    print(f"[INFO] 模块数量: {len(modules)}")
    
    # 统计总数
    total_features = sum(len(m.get('features', [])) for m in modules)
    total_steps = sum(
        len(f.get('test_steps', []))
        for m in modules
        for f in m.get('features', [])
    )
    
    print(f"[INFO] 功能总数: {total_features}")
    print(f"[INFO] 步骤总数: {total_steps}")
    
    return True


if __name__ == "__main__":
    try:
        success = merge_test_cases()
        exit(0 if success else 1)
    except Exception as e:
        print(f"[ERROR] 合并失败: {e}")
        import traceback
        traceback.print_exc()
        exit(1)
