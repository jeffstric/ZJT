#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试用例 ID 重复检查脚本
检查 auto_test/test_modules 目录下所有 JSON 文件中的测试用例 ID 是否存在重复
"""

import json
import os
from collections import defaultdict
from pathlib import Path


def load_test_module(file_path):
    """加载测试模块 JSON 文件"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"错误：无法加载文件 {file_path}: {e}")
        return None


def extract_feature_ids(test_module, file_name):
    """从测试模块中提取所有 feature ID"""
    feature_ids = []
    
    if not test_module or 'features' not in test_module:
        return feature_ids
    
    for feature in test_module['features']:
        if 'id' in feature:
            feature_ids.append({
                'id': feature['id'],
                'name': feature.get('name', ''),
                'file': file_name
            })
    
    return feature_ids


def check_duplicate_ids():
    """检查重复的测试用例 ID"""
    test_modules_dir = Path(__file__).parent / 'test_modules'
    
    if not test_modules_dir.exists():
        print(f"错误：目录不存在 {test_modules_dir}")
        return
    
    # 收集所有 ID
    all_ids = []
    id_count = defaultdict(list)
    
    print("正在扫描测试模块文件...")
    print("=" * 60)
    
    # 遍历所有 JSON 文件
    json_files = list(test_modules_dir.glob('*.json'))
    if not json_files:
        print("未找到任何 JSON 文件")
        return
    
    for json_file in sorted(json_files):
        if json_file.name == 'index.json':
            continue  # 跳过索引文件
            
        print(f"扫描文件: {json_file.name}")
        
        test_module = load_test_module(json_file)
        if test_module is None:
            continue
            
        feature_ids = extract_feature_ids(test_module, json_file.name)
        
        for feature_info in feature_ids:
            all_ids.append(feature_info)
            id_count[feature_info['id']].append(feature_info)
    
    print(f"\n总共扫描了 {len(json_files)-1} 个测试模块文件")
    print(f"总共找到 {len(all_ids)} 个测试用例")
    print("=" * 60)
    
    # 检查重复
    duplicates = {id_val: info_list for id_val, info_list in id_count.items() if len(info_list) > 1}
    
    if duplicates:
        print(f"\n发现 {len(duplicates)} 个重复的测试用例 ID:")
        print("=" * 60)
        
        for duplicate_id, info_list in duplicates.items():
            print(f"\n重复 ID: {duplicate_id}")
            print(f"出现次数: {len(info_list)}")
            
            for i, info in enumerate(info_list, 1):
                print(f"  {i}. 文件: {info['file']}")
                print(f"     名称: {info['name']}")
        
        print("\n" + "=" * 60)
        print("建议修复方案:")
        
        for duplicate_id, info_list in duplicates.items():
            print(f"\n对于重复 ID '{duplicate_id}':")
            for i, info in enumerate(info_list):
                if i == 0:
                    print(f"  保持: {info['file']} - {info['name']}")
                else:
                    # 生成建议的新 ID
                    base_id = duplicate_id.rstrip('_0123456789')
                    suggested_id = f"{base_id}_{i}"
                    print(f"  修改: {info['file']} - {info['name']}")
                    print(f"        建议新 ID: {suggested_id}")
    else:
        print("\n✓ 未发现重复的测试用例 ID")
        print("所有测试用例 ID 都是唯一的")
    
    print("\n" + "=" * 60)
    print("扫描完成")


def main():
    """主函数"""
    print("测试用例 ID 重复检查工具")
    print("=" * 60)
    check_duplicate_ids()


if __name__ == '__main__':
    main()
