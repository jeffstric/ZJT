#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试用例 ID 重复检查脚本
检查 auto_test/test_modules 目录下所有 JSON 文件中的测试用例 ID 是否存在重复
"""

import json
import os
import argparse
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
                'file': file_name,
                'prerequisites': feature.get('prerequisites', [])
            })
    
    return feature_ids


def check_prerequisites_dependencies(all_ids):
    """检查测试用例的prerequisites依赖是否存在"""
    # 创建所有存在的ID集合
    existing_ids = {feature['id'] for feature in all_ids}
    
    missing_dependencies = []
    
    for feature in all_ids:
        if feature['prerequisites']:
            for prereq_id in feature['prerequisites']:
                if prereq_id not in existing_ids:
                    missing_dependencies.append({
                        'feature_id': feature['id'],
                        'feature_name': feature['name'],
                        'file': feature['file'],
                        'missing_prereq': prereq_id
                    })
    
    return missing_dependencies


def check_duplicate_ids(show_details=False):
    """检查重复的测试用例 ID 和依赖关系
    
    Args:
        show_details (bool): 是否显示详细的依赖关系列表
    """
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
    
    # 检查重复ID
    duplicates = {id_val: info_list for id_val, info_list in id_count.items() if len(info_list) > 1}
    
    duplicate_found = False
    if duplicates:
        duplicate_found = True
        print(f"\n[ERROR] 发现 {len(duplicates)} 个重复的测试用例 ID:")
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
        print("\n[OK] 未发现重复的测试用例 ID")
        print("所有测试用例 ID 都是唯一的")
    
    # 检查依赖关系
    print("\n" + "=" * 60)
    print("检查测试用例依赖关系...")
    print("=" * 60)
    
    missing_dependencies = check_prerequisites_dependencies(all_ids)
    
    dependency_error = False
    if missing_dependencies:
        dependency_error = True
        print(f"\n[ERROR] 发现 {len(missing_dependencies)} 个缺失的依赖关系:")
        print("=" * 60)
        
        for missing in missing_dependencies:
            print(f"\n测试用例: {missing['feature_id']} ({missing['feature_name']})")
            print(f"文件: {missing['file']}")
            print(f"缺失依赖: {missing['missing_prereq']}")
        
        print("\n" + "=" * 60)
        print("修复建议:")
        print("1. 检查缺失的依赖ID是否拼写错误")
        print("2. 确认依赖的测试用例是否已创建")
        print("3. 如果依赖用例在其他模块中，请确认模块文件存在")
    else:
        print("\n[OK] 所有测试用例的依赖关系都正确")
        print("未发现缺失的依赖")
    
    # 统计依赖关系
    print("\n" + "=" * 60)
    print("依赖关系统计:")
    print("=" * 60)
    
    total_with_deps = sum(1 for feature in all_ids if feature['prerequisites'])
    total_deps = sum(len(feature['prerequisites']) for feature in all_ids)
    
    print(f"有依赖的测试用例: {total_with_deps} 个")
    print(f"总依赖关系数量: {total_deps} 个")
    
    if show_details and total_with_deps > 0:
        print("\n依赖关系详情:")
        for feature in all_ids:
            if feature['prerequisites']:
                print(f"  {feature['id']} -> {', '.join(feature['prerequisites'])}")
    
    print("\n" + "=" * 60)
    if duplicate_found or dependency_error:
        print("[FAILED] 检查完成 - 发现问题需要修复")
        return False
    else:
        print("[PASSED] 检查完成 - 所有验证通过")
        return True


def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description='测试用例 ID 重复检查工具',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''使用示例:
  python check_duplicate_ids.py              # 基本检查
  python check_duplicate_ids.py --details    # 显示详细依赖关系'''
    )
    parser.add_argument(
        '--details', '-d',
        action='store_true',
        help='显示详细的依赖关系列表'
    )
    
    args = parser.parse_args()
    
    print("测试用例 ID 重复检查工具")
    print("=" * 60)
    check_duplicate_ids(show_details=args.details)


if __name__ == '__main__':
    main()
