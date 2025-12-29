#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试报告生成器
生成 HTML 格式的测试结果报告，避免 Claude Code 输出 token 限制

用法:
    python generate_report.py                    # 生成报告到当前目录
    python generate_report.py --archive          # 生成报告并归档到时间目录
    python generate_report.py --archive --name "登录测试"  # 指定归档名称
"""

import json
import os
import shutil
import argparse
from datetime import datetime
from pathlib import Path

def load_json(file_path):
    """加载 JSON 文件"""
    try:
        with open(file_path, 'r', encoding='utf-8-sig') as f:
            return json.load(f)
    except FileNotFoundError:
        return None
    except json.JSONDecodeError:
        return None

def get_latest_session():
    """获取最新的测试会话文件"""
    sessions_dir = Path("test_sessions")
    if not sessions_dir.exists():
        return None
    
    session_files = list(sessions_dir.glob("session_*.json"))
    if not session_files:
        return None
    
    # 按文件名排序，获取最新的
    latest_session = max(session_files, key=lambda x: x.name)
    return load_json(latest_session)

def count_features(session_data):
    """统计 features 的通过情况，包含失败详情"""
    if not session_data or 'modules' not in session_data:
        return {}
    
    stats = {}
    for module in session_data['modules']:
        module_id = module['id']
        module_name = module['name']
        
        total_features = len(module.get('features', []))
        passed_features = sum(1 for f in module.get('features', []) if f.get('pass', False))
        
        # 统计 test_steps
        total_steps = 0
        passed_steps = 0
        failed_features = []
        failed_steps = []
        passed_steps_with_remarks = []
        
        for feature in module.get('features', []):
            feature_id = feature.get('id', 'unknown')
            feature_name = feature.get('name', 'Unknown Feature')
            feature_passed = feature.get('pass', False)
            
            steps = feature.get('test_steps', [])
            total_steps += len(steps)
            
            feature_step_failures = []
            for step in steps:
                step_passed = step.get('pass', False)
                if step_passed:
                    passed_steps += 1
                    # 收集通过步骤的备注信息
                    step_remark = step.get('remark', '')
                    if step_remark:
                        passed_steps_with_remarks.append({
                            'feature_id': feature_id,
                            'feature_name': feature_name,
                            'step': step.get('step', '?'),
                            'action': step.get('action', 'Unknown Action'),
                            'remark': step_remark,
                            'expected_result': step.get('expected_result', step.get('verify', ''))
                        })
                else:
                    # 收集失败步骤信息
                    step_info = {
                        'step': step.get('step', '?'),
                        'action': step.get('action', 'Unknown Action'),
                        'error': step.get('error', '测试未通过'),
                        'expected_result': step.get('expected_result', step.get('verify', '')),
                        'remark': step.get('remark', '')
                    }
                    feature_step_failures.append(step_info)
                    failed_steps.append({
                        'feature_id': feature_id,
                        'feature_name': feature_name,
                        **step_info
                    })
            
            # 如果 feature 未通过，记录失败信息
            if not feature_passed:
                failed_features.append({
                    'id': feature_id,
                    'name': feature_name,
                    'description': feature.get('description', ''),
                    'priority': feature.get('priority', 'P2'),
                    'failed_steps': feature_step_failures,
                    'total_steps': len(steps),
                    'passed_steps': len(steps) - len(feature_step_failures)
                })
        
        stats[module_id] = {
            'name': module_name,
            'features': {'total': total_features, 'passed': passed_features},
            'steps': {'total': total_steps, 'passed': passed_steps},
            'failed_features': failed_features,
            'failed_steps': failed_steps,
            'passed_steps_with_remarks': passed_steps_with_remarks
        }
    
    return stats

def generate_html_report(output_dir: Path = None):
    """生成 HTML 测试报告

    Args:
        output_dir: 输出目录，默认为当前目录
    """
    if output_dir is None:
        output_dir = Path(".")
    else:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
    
    # 加载数据
    progress = load_json('test_progress.json')
    session_data = get_latest_session()
    
    if not progress:
        return "[ERROR] 未找到 test_progress.json 文件"
    
    # 统计数据
    stats = count_features(session_data) if session_data else {}
    
    # 获取测试名称
    test_title = session_data.get('title', '自动化测试') if session_data else '自动化测试'
    test_description = session_data.get('description', '') if session_data else ''
    test_version = session_data.get('version', '') if session_data else ''
    
    # 生成 HTML
    html_content = f"""
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{test_title} - 测试报告</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; margin: 20px; background: #f5f5f5; }}
        .container {{ max-width: 1200px; margin: 0 auto; background: white; padding: 30px; border-radius: 8px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }}
        h1 {{ color: #2c3e50; border-bottom: 3px solid #3498db; padding-bottom: 10px; }}
        h2 {{ color: #34495e; margin-top: 30px; }}
        .summary {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 20px; margin: 20px 0; }}
        .card {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 20px; border-radius: 8px; text-align: center; }}
        .card.completed {{ background: linear-gradient(135deg, #11998e 0%, #38ef7d 100%); }}
        .card.in-progress {{ background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%); }}
        .card.pending {{ background: linear-gradient(135deg, #4facfe 0%, #00f2fe 100%); }}
        .card h3 {{ margin: 0 0 10px 0; font-size: 1.2em; }}
        .card .number {{ font-size: 2em; font-weight: bold; }}
        .module {{ margin: 20px 0; border: 1px solid #ddd; border-radius: 8px; overflow: hidden; }}
        .module-header {{ background: #ecf0f1; padding: 15px; font-weight: bold; display: flex; justify-content: space-between; align-items: center; }}
        .module-content {{ padding: 15px; }}
        .status-badge {{ padding: 4px 12px; border-radius: 20px; font-size: 0.8em; font-weight: bold; }}
        .status-completed {{ background: #2ecc71; color: white; }}
        .status-in-progress {{ background: #f39c12; color: white; }}
        .status-pending {{ background: #95a5a6; color: white; }}
        .progress-bar {{ width: 100%; height: 20px; background: #ecf0f1; border-radius: 10px; overflow: hidden; margin: 10px 0; }}
        .progress-fill {{ height: 100%; background: linear-gradient(90deg, #2ecc71, #27ae60); transition: width 0.3s ease; }}
        .stats {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }}
        .stat-item {{ text-align: center; }}
        .timestamp {{ color: #7f8c8d; font-size: 0.9em; margin-top: 20px; }}
        table {{ width: 100%; border-collapse: collapse; margin-top: 10px; }}
        th, td {{ padding: 8px 12px; text-align: left; border-bottom: 1px solid #ddd; }}
        th {{ background: #f8f9fa; font-weight: 600; }}
        .feature-passed {{ color: #27ae60; }}
        .feature-failed {{ color: #e74c3c; }}
        .failures-section {{ margin-top: 30px; }}
        .failure-alert {{ background: #fff5f5; border: 2px solid #fed7d7; border-radius: 8px; padding: 20px; margin: 15px 0; }}
        .failure-title {{ color: #c53030; font-weight: bold; font-size: 1.1em; margin-bottom: 10px; }}
        .failure-item {{ background: white; border-left: 4px solid #e53e3e; padding: 15px; margin: 10px 0; border-radius: 0 4px 4px 0; }}
        .failure-header {{ font-weight: bold; color: #2d3748; margin-bottom: 8px; }}
        .failure-details {{ color: #4a5568; line-height: 1.5; }}
        .error-message {{ background: #fed7d7; color: #c53030; padding: 8px 12px; border-radius: 4px; margin: 5px 0; font-family: monospace; }}
        .remark-message {{ background: #e6fffa; color: #2c7a7b; padding: 8px 12px; border-radius: 4px; margin: 5px 0; border-left: 4px solid #38b2ac; }}
        .passed-steps-section {{ margin-top: 20px; }}
        .passed-step-item {{ background: #f0fff4; border-left: 4px solid #38a169; padding: 12px; margin: 8px 0; border-radius: 0 4px 4px 0; }}
        .passed-step-header {{ font-weight: bold; color: #2d3748; margin-bottom: 5px; }}
        .passed-step-details {{ color: #4a5568; line-height: 1.4; font-size: 0.9em; }}
        .priority-badge {{ display: inline-block; padding: 2px 8px; border-radius: 12px; font-size: 0.8em; font-weight: bold; }}
        .priority-p0 {{ background: #fed7d7; color: #c53030; }}
        .priority-p1 {{ background: #feebc8; color: #c05621; }}
        .priority-p2 {{ background: #e6fffa; color: #2c7a7b; }}
        .no-failures {{ text-align: center; color: #38a169; font-size: 1.1em; padding: 20px; }}
        .failure-summary {{ background: #f7fafc; padding: 15px; border-radius: 8px; margin-bottom: 20px; }}
        .collapsible {{ cursor: pointer; user-select: none; padding: 10px; background: #f8f9fa; border-radius: 4px; margin: 5px 0; }}
        .collapsible:hover {{ background: #e9ecef; }}
        .collapsible::before {{ content: '▶ '; font-size: 0.8em; margin-right: 5px; }}
        .collapsible.active::before {{ content: '▼ '; }}
        .collapse-content {{ display: none; padding: 10px; border-left: 3px solid #dee2e6; margin-left: 10px; }}
        .collapse-content.active {{ display: block; }}
        .test-header {{ background: #f8f9fa; padding: 20px; border-radius: 8px; margin-bottom: 20px; }}
        .test-title {{ font-size: 1.8em; color: #2c3e50; margin: 0 0 10px 0; }}
        .test-meta {{ color: #6c757d; font-size: 0.9em; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="test-header">
            <h1 class="test-title">🧪 {test_title}</h1>
            <div class="test-meta">
                {f'<strong>描述:</strong> {test_description}<br>' if test_description else ''}
                {f'<strong>版本:</strong> {test_version}<br>' if test_version else ''}
                <strong>报告生成时间:</strong> {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
            </div>
        </div>
        
        <div class="summary">
"""
    
    # 计算总体统计 - 根据实际测试完成情况重新计算状态
    total_modules = len(progress.get('modules', []))
    completed_modules = 0
    in_progress_modules = 0
    pending_modules = 0
    
    for module in progress.get('modules', []):
        module_id = module['id']
        original_status = module.get('status', 'pending')
        
        # 根据实际测试数据重新判断状态
        if module_id in stats:
            module_stats = stats[module_id]
            features_total = module_stats['features']['total']
            features_passed = module_stats['features']['passed']
            steps_total = module_stats['steps']['total']
            steps_passed = module_stats['steps']['passed']
            
            # 只有当所有功能和步骤都完成时才算已完成
            if features_total > 0 and features_passed == features_total and steps_total > 0 and steps_passed == steps_total:
                completed_modules += 1
            elif features_passed > 0 or steps_passed > 0:
                in_progress_modules += 1
            else:
                pending_modules += 1
        else:
            # 没有测试数据，按原状态计算
            if original_status == 'completed':
                completed_modules += 1
            elif original_status == 'in_progress':
                in_progress_modules += 1
            else:
                pending_modules += 1
    
    # 统计总失败数
    total_failed_features = sum(len(module_stats.get('failed_features', [])) for module_stats in stats.values())
    total_failed_steps = sum(len(module_stats.get('failed_steps', [])) for module_stats in stats.values())
    
    # 总体进度卡片
    html_content += f"""
            <div class="card completed">
                <h3>已完成模块</h3>
                <div class="number">{completed_modules}</div>
            </div>
            <div class="card in-progress">
                <h3>进行中模块</h3>
                <div class="number">{in_progress_modules}</div>
            </div>
            <div class="card pending">
                <h3>待测试模块</h3>
                <div class="number">{pending_modules}</div>
            </div>
            <div class="card">
                <h3>总体进度</h3>
                <div class="number">{completed_modules}/{total_modules}</div>
            </div>
        </div>
"""
    
    # 如果有失败项，显示失败摘要
    if total_failed_features > 0 or total_failed_steps > 0:
        html_content += f"""
        <div class="failures-section">
            <div class="failure-alert">
                <div class="failure-title">[WARNING] 发现 {total_failed_features} 个功能失败，{total_failed_steps} 个步骤失败</div>
                <div class="failure-summary">
                    <strong>需要关注的失败项目：</strong>
                    <ul>
"""
        
        # 按优先级列出失败的功能
        high_priority_failures = []
        for module_id, module_stats in stats.items():
            for failed_feature in module_stats.get('failed_features', []):
                if failed_feature['priority'] == 'P0':
                    high_priority_failures.append(f"{module_stats['name']} - {failed_feature['name']}")
        
        if high_priority_failures:
            for failure in high_priority_failures[:5]:  # 只显示前5个
                html_content += f"<li><strong>{failure}</strong></li>"
            if len(high_priority_failures) > 5:
                html_content += f"<li>... 还有 {len(high_priority_failures) - 5} 个高优先级失败项</li>"
        else:
            html_content += "<li>暂无高优先级 (P0) 失败项</li>"
        
        html_content += """
                    </ul>
                </div>
            </div>
        </div>
"""
    
    html_content += """
        <h2>[MODULES] 模块详情</h2>
"""
    
    # 模块详情
    for module in progress.get('modules', []):
        module_id = module['id']
        module_name = module['name']
        original_status = module.get('status', 'pending')
        
        # 根据实际测试数据重新判断状态
        actual_status = original_status
        if module_id in stats:
            module_stats = stats[module_id]
            features_total = module_stats['features']['total']
            features_passed = module_stats['features']['passed']
            steps_total = module_stats['steps']['total']
            steps_passed = module_stats['steps']['passed']
            
            # 重新计算实际状态
            if features_total > 0 and features_passed == features_total and steps_total > 0 and steps_passed == steps_total:
                actual_status = 'completed'
            elif features_passed > 0 or steps_passed > 0:
                actual_status = 'in_progress'
            else:
                actual_status = 'pending'
        
        status_class = f"status-{actual_status.replace('_', '-')}"
        status_text = {'completed': '[DONE] 已完成', 'in_progress': '[RUNNING] 进行中', 'pending': '[PENDING] 待测试'}.get(actual_status, actual_status)
        
        html_content += f"""
        <div class="module">
            <div class="module-header">
                <span>{module_name} ({module_id})</span>
                <span class="status-badge {status_class}">{status_text}</span>
            </div>
            <div class="module-content">
"""
        
        # 如果有统计数据，显示详细信息
        if module_id in stats:
            module_stats = stats[module_id]
            features_total = module_stats['features']['total']
            features_passed = module_stats['features']['passed']
            steps_total = module_stats['steps']['total']
            steps_passed = module_stats['steps']['passed']
            
            features_percent = (features_passed / features_total * 100) if features_total > 0 else 0
            steps_percent = (steps_passed / steps_total * 100) if steps_total > 0 else 0
            
            html_content += f"""
                <div class="stats">
                    <div class="stat-item">
                        <h4>功能点 (Features)</h4>
                        <div class="progress-bar">
                            <div class="progress-fill" style="width: {features_percent}%"></div>
                        </div>
                        <p>{features_passed}/{features_total} ({features_percent:.1f}%)</p>
                    </div>
                    <div class="stat-item">
                        <h4>测试步骤 (Steps)</h4>
                        <div class="progress-bar">
                            <div class="progress-fill" style="width: {steps_percent}%"></div>
                        </div>
                        <p>{steps_passed}/{steps_total} ({steps_percent:.1f}%)</p>
                    </div>
                </div>
"""
        else:
            html_content += "<p>暂无详细统计数据</p>"
        
        html_content += """
            </div>
        </div>
"""
        
        # 如果有失败的功能，显示详细失败信息（可折叠）
        if module_id in stats and stats[module_id].get('failed_features'):
            failed_features = stats[module_id]['failed_features']
            failure_count = len(failed_features)
            html_content += f"""
                <div class="failures-section">
                    <div class="collapsible" onclick="toggleCollapse(this)">
                        [ERROR] 失败项目详情 ({failure_count} 个失败项) - 点击展开/收起
                    </div>
                    <div class="collapse-content">
"""
            
            for failed_feature in failed_features:
                priority_class = f"priority-{failed_feature['priority'].lower()}"
                html_content += f"""
                        <div class="failure-item">
                            <div class="failure-header">
                                [FAILED] {failed_feature['id']} - {failed_feature['name']}
                                <span class="priority-badge {priority_class}">{failed_feature['priority']}</span>
                            </div>
                            <div class="failure-details">
                                <strong>描述:</strong> {failed_feature['description']}<br>
                                <strong>进度:</strong> {failed_feature['passed_steps']}/{failed_feature['total_steps']} 步骤通过
                            </div>
"""
                
                # 显示失败的步骤（也可折叠）
                if failed_feature['failed_steps']:
                    step_count = len(failed_feature['failed_steps'])
                    html_content += f"""
                            <div class="collapsible" onclick="toggleCollapse(this)" style="margin-top: 10px; font-size: 0.9em;">
                                失败步骤详情 ({step_count} 个失败步骤) - 点击展开/收起
                            </div>
                            <div class="collapse-content">
"""
                    for step in failed_feature['failed_steps']:
                        html_content += f"""
                                <div class="error-message">
                                    <strong>步骤 {step['step']}:</strong> {step['action']}<br>
                                    <strong>错误:</strong> {step['error']}<br>
                                    <strong>期望结果:</strong> {step['expected_result']}
                                    {f'<br><strong>备注:</strong> {step["remark"]}' if step.get('remark') else ''}
                                </div>
"""
                    html_content += """
                            </div>
"""
                
                html_content += """
                        </div>
"""
            
            html_content += """
                    </div>
                </div>
"""
        
        # 显示通过步骤的备注信息（如果有的话）
        if module_id in stats and stats[module_id].get('passed_steps_with_remarks'):
            passed_remarks = stats[module_id]['passed_steps_with_remarks']
            remark_count = len(passed_remarks)
            html_content += f"""
                <div class="passed-steps-section">
                    <div class="collapsible" onclick="toggleCollapse(this)">
                        [INFO] 测试备注详情 ({remark_count} 个步骤有备注) - 点击展开/收起
                    </div>
                    <div class="collapse-content">
"""
            
            for remark_step in passed_remarks:
                html_content += f"""
                        <div class="passed-step-item">
                            <div class="passed-step-header">
                                [PASSED] 步骤 {remark_step['step']}: {remark_step['action']}
                            </div>
                            <div class="passed-step-details">
                                <strong>期望结果:</strong> {remark_step['expected_result']}
                            </div>
                            <div class="remark-message">
                                <strong>测试备注:</strong> {remark_step['remark']}
                            </div>
                        </div>
"""
            
            html_content += """
                    </div>
                </div>
"""
    
    # 结尾
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    html_content += f"""
        <div class="timestamp">
            [TIME] 报告生成时间: {current_time}
        </div>
    </div>
    
    <script>
        function toggleCollapse(element) {{
            element.classList.toggle('active');
            var content = element.nextElementSibling;
            content.classList.toggle('active');
        }}
    </script>
</body>
</html>
"""
    
    # 保存 HTML 文件
    report_path = output_dir / "test_report.html"
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write(html_content)

    return report_path

def archive_test_results(custom_name: str = None):
    """归档测试结果到时间目录

    创建格式为 "YYYY-MM-DD_HH-MM[_自定义名称]" 的目录，包含：
    - test_report.html: 测试报告
    - session_data.json: 测试会话数据
    - test_progress.json: 测试进度数据

    Args:
        custom_name: 可选的自定义名称，会附加到目录名后

    Returns:
        归档目录的路径
    """
    base_dir = Path(__file__).parent
    reports_dir = base_dir / "test_reports"
    reports_dir.mkdir(exist_ok=True)

    # 生成时间戳目录名
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
    if custom_name:
        # 清理自定义名称中的特殊字符
        safe_name = custom_name.replace("/", "-").replace("\\", "-").replace(":", "-")
        dir_name = f"{timestamp}_{safe_name}"
    else:
        dir_name = timestamp

    archive_dir = reports_dir / dir_name
    archive_dir.mkdir(exist_ok=True)

    print(f"[INFO] 创建归档目录: {archive_dir}")

    # 1. 生成 HTML 报告到归档目录
    report_path = generate_html_report(archive_dir)
    print(f"[SUCCESS] 测试报告已生成: {report_path}")

    # 2. 复制最新的会话文件
    sessions_dir = base_dir / "test_sessions"
    if sessions_dir.exists():
        session_files = list(sessions_dir.glob("session_*.json"))
        if session_files:
            latest_session = max(session_files, key=lambda x: x.stat().st_mtime)
            dest_session = archive_dir / "session_data.json"
            shutil.copy2(latest_session, dest_session)
            print(f"[SUCCESS] 会话数据已复制: {dest_session}")

    # 3. 复制 test_progress.json
    progress_file = base_dir / "test_progress.json"
    if progress_file.exists():
        dest_progress = archive_dir / "test_progress.json"
        shutil.copy2(progress_file, dest_progress)
        print(f"[SUCCESS] 进度数据已复制: {dest_progress}")

    # 4. 生成归档摘要文件
    summary = {
        "archive_time": datetime.now().isoformat(),
        "custom_name": custom_name,
        "files": [
            "test_report.html",
            "session_data.json",
            "test_progress.json"
        ]
    }
    summary_path = archive_dir / "archive_info.json"
    with open(summary_path, 'w', encoding='utf-8') as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print(f"[DONE] 测试结果已归档到: {archive_dir.absolute()}")
    return archive_dir


def main():
    parser = argparse.ArgumentParser(
        description="测试报告生成器 - 生成 HTML 格式的测试结果报告",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python generate_report.py                    # 生成报告到当前目录
  python generate_report.py --archive          # 生成报告并归档到时间目录
  python generate_report.py --archive --name "登录测试"  # 指定归档名称
        """
    )

    parser.add_argument('--archive', '-a', action='store_true',
                        help='归档测试结果到时间目录 (test_reports/YYYY-MM-DD_HH-MM/)')
    parser.add_argument('--name', '-n', type=str,
                        help='自定义归档名称，会附加到目录名后')

    args = parser.parse_args()

    if args.archive:
        archive_test_results(args.name)
    else:
        report_path = generate_html_report()
        print(f"[SUCCESS] 测试报告已生成: {report_path.absolute()}")


if __name__ == "__main__":
    main()
