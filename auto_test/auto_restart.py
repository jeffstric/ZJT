#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
自动重启脚本 - 用于智能体上下文清理后的自动重新调用
"""

import json
import os
import sys
import time
from datetime import datetime
from context_manager import ContextManager

class AutoRestart:
    """自动重启管理器"""
    
    def __init__(self):
        self.context_manager = ContextManager()
        self.restart_log_file = "restart_log.json"
        self.load_restart_log()
    
    def load_restart_log(self):
        """加载重启日志"""
        if os.path.exists(self.restart_log_file):
            with open(self.restart_log_file, 'r', encoding='utf-8') as f:
                self.restart_log = json.load(f)
        else:
            self.restart_log = {
                "restarts": [],
                "total_restarts": 0,
                "last_restart": None
            }
    
    def save_restart_log(self):
        """保存重启日志"""
        with open(self.restart_log_file, 'w', encoding='utf-8') as f:
            json.dump(self.restart_log, f, indent=2, ensure_ascii=False)
    
    def log_restart(self, reason: str, modules_completed: int):
        """记录重启信息"""
        restart_info = {
            "timestamp": datetime.now().isoformat(),
            "reason": reason,
            "modules_completed": modules_completed,
            "restart_count": self.restart_log["total_restarts"] + 1
        }
        
        self.restart_log["restarts"].append(restart_info)
        self.restart_log["total_restarts"] += 1
        self.restart_log["last_restart"] = restart_info
        self.save_restart_log()
        
        return restart_info
    
    def should_auto_restart(self) -> tuple[bool, str]:
        """检查是否应该自动重启"""
        if not self.context_manager.config.get("auto_restart", True):
            return False, "自动重启已禁用"
        
        if self.context_manager.should_cleanup_context():
            strategy = self.context_manager.config["cleanup_strategy"]
            modules = self.context_manager.session["modules_completed"]
            
            if strategy == "module_count":
                return True, f"已完成 {modules} 个模块，达到清理阈值"
            elif strategy == "token_estimate":
                tokens = self.context_manager.session["context_size_estimate"]
                return True, f"估算上下文大小 {tokens} tokens，达到清理阈值"
            elif strategy == "time_based":
                return True, "达到时间清理阈值"
        
        return False, "未达到清理条件"
    
    def generate_restart_message(self) -> str:
        """生成重启消息"""
        should_restart, reason = self.should_auto_restart()
        
        if not should_restart:
            return f"无需重启: {reason}"
        
        # 记录重启
        restart_info = self.log_restart(
            reason, 
            self.context_manager.session["modules_completed"]
        )
        
        # 准备重启
        restart_msg = self.context_manager.prepare_restart()
        
        # 生成完整的重启消息
        full_message = f"""
## 自动上下文清理和重启

**重启原因:** {reason}

**重启统计:**
- 本次重启编号: #{restart_info['restart_count']}
- 重启时间: {restart_info['timestamp']}
- 已完成模块数: {restart_info['modules_completed']}

{restart_msg}

**重要提醒:**
- 当前上下文将被清理
- 测试进度已保存，将从下一个未处理模块继续
- 请执行重启命令: `{self.context_manager.config['restart_command']}`

---

**自动重启已触发，请立即执行重启命令继续测试流程。**
"""
        
        return full_message
    
    def get_restart_command(self) -> str:
        """获取重启命令"""
        return self.context_manager.config.get("restart_command", "/orchestrator")
    
    def check_and_restart(self) -> dict:
        """检查并准备重启"""
        should_restart, reason = self.should_auto_restart()
        
        result = {
            "should_restart": should_restart,
            "reason": reason,
            "restart_command": self.get_restart_command(),
            "message": ""
        }
        
        if should_restart:
            result["message"] = self.generate_restart_message()
        
        return result

def main():
    """命令行接口"""
    import argparse
    
    parser = argparse.ArgumentParser(description="自动重启管理器")
    parser.add_argument("--check", action="store_true", help="检查是否需要重启")
    parser.add_argument("--message", action="store_true", help="生成重启消息")
    parser.add_argument("--log", action="store_true", help="显示重启日志")
    parser.add_argument("--clear-log", action="store_true", help="清除重启日志")
    
    args = parser.parse_args()
    
    restart_manager = AutoRestart()
    
    if args.check:
        result = restart_manager.check_and_restart()
        print(f"需要重启: {result['should_restart']}")
        print(f"原因: {result['reason']}")
        if result['should_restart']:
            print(f"重启命令: {result['restart_command']}")
    
    elif args.message:
        result = restart_manager.check_and_restart()
        if result['should_restart']:
            print(result['message'])
        else:
            print(f"无需重启: {result['reason']}")
    
    elif args.log:
        print(json.dumps(restart_manager.restart_log, indent=2, ensure_ascii=False))
    
    elif args.clear_log:
        restart_manager.restart_log = {
            "restarts": [],
            "total_restarts": 0,
            "last_restart": None
        }
        restart_manager.save_restart_log()
        print("重启日志已清除")
    
    else:
        # 默认行为：检查并输出结果
        result = restart_manager.check_and_restart()
        if result['should_restart']:
            print(result['message'])
            # 输出重启命令供复制
            print(f"\n执行重启命令: {result['restart_command']}")
        else:
            print(f"当前无需重启: {result['reason']}")

if __name__ == "__main__":
    main()
