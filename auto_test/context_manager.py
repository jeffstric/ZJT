#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
上下文管理器 - 用于智能体上下文精简和重新调用
"""

import json
import os
import time
from datetime import datetime
from typing import Dict, Any, Optional

class ContextManager:
    """上下文管理器，负责监控和管理智能体的上下文状态"""
    
    def __init__(self, config_file: str = "context_config.json"):
        self.config_file = config_file
        self.session_file = "context_session.json"
        self.load_config()
        self.load_session()
    
    def load_config(self):
        """加载上下文管理配置"""
        default_config = {
            "max_modules_per_session": 10,  # 每个会话最大测试模块数
            "max_context_tokens": 50000,    # 估算的最大上下文token数
            "cleanup_strategy": "module_count",  # 清理策略: module_count, token_estimate, time_based
            "auto_restart": True,           # 是否自动重启
            "preserve_state": True,         # 是否保留状态信息
            "restart_command": "/orchestrator"  # 重启命令
        }
        
        if os.path.exists(self.config_file):
            with open(self.config_file, 'r', encoding='utf-8') as f:
                self.config = json.load(f)
        else:
            self.config = default_config
            self.save_config()
    
    def save_config(self):
        """保存配置"""
        with open(self.config_file, 'w', encoding='utf-8') as f:
            json.dump(self.config, f, indent=2, ensure_ascii=False)
    
    def load_session(self):
        """加载会话状态"""
        if os.path.exists(self.session_file):
            with open(self.session_file, 'r', encoding='utf-8') as f:
                self.session = json.load(f)
        else:
            self.reset_session()
    
    def save_session(self):
        """保存会话状态"""
        with open(self.session_file, 'w', encoding='utf-8') as f:
            json.dump(self.session, f, indent=2, ensure_ascii=False)
    
    def reset_session(self):
        """重置会话状态"""
        self.session = {
            "modules_completed": 0,
            "session_start_time": datetime.now().isoformat(),
            "last_restart_time": None,
            "restart_count": 0,
            "current_module": None,
            "context_size_estimate": 0
        }
        self.save_session()
    
    def update_module_completion(self, module_id: str):
        """更新模块完成状态"""
        self.session["modules_completed"] += 1
        self.session["current_module"] = module_id
        self.session["context_size_estimate"] += 1000  # 估算每个模块增加1000 tokens
        self.save_session()
    
    def should_cleanup_context(self) -> bool:
        """判断是否需要清理上下文"""
        strategy = self.config["cleanup_strategy"]
        
        if strategy == "module_count":
            return self.session["modules_completed"] >= self.config["max_modules_per_session"]
        elif strategy == "token_estimate":
            return self.session["context_size_estimate"] >= self.config["max_context_tokens"]
        elif strategy == "time_based":
            # 基于时间的策略（每30分钟重启一次）
            if self.session["last_restart_time"]:
                last_restart = datetime.fromisoformat(self.session["last_restart_time"])
                return (datetime.now() - last_restart).seconds > 1800
            return False
        
        return False
    
    def get_restart_info(self) -> Dict[str, Any]:
        """获取重启信息"""
        return {
            "should_restart": self.should_cleanup_context(),
            "modules_completed": self.session["modules_completed"],
            "restart_count": self.session["restart_count"],
            "restart_command": self.config["restart_command"],
            "preserve_state": self.config["preserve_state"]
        }
    
    def prepare_restart(self) -> str:
        """准备重启，返回重启消息"""
        self.session["restart_count"] += 1
        self.session["last_restart_time"] = datetime.now().isoformat()
        
        restart_msg = f"""
## 上下文清理和重新调用

已完成 {self.session['modules_completed']} 个测试模块，达到上下文清理阈值。

**重启信息：**
- 重启次数: {self.session['restart_count']}
- 当前模块: {self.session.get('current_module', 'N/A')}
- 预计上下文大小: {self.session['context_size_estimate']} tokens

**执行重启命令:** `{self.config['restart_command']}`

上下文将被清理，测试将从下一个未处理的模块继续。
"""
        
        # 重置模块计数，但保留其他状态
        self.session["modules_completed"] = 0
        self.session["context_size_estimate"] = 0
        self.save_session()
        
        return restart_msg
    
    def get_status(self) -> Dict[str, Any]:
        """获取当前状态"""
        return {
            "config": self.config,
            "session": self.session,
            "should_cleanup": self.should_cleanup_context()
        }

def main():
    """命令行接口"""
    import argparse
    
    parser = argparse.ArgumentParser(description="上下文管理器")
    parser.add_argument("--check", action="store_true", help="检查是否需要清理上下文")
    parser.add_argument("--update", type=str, help="更新模块完成状态")
    parser.add_argument("--restart", action="store_true", help="准备重启")
    parser.add_argument("--status", action="store_true", help="显示状态")
    parser.add_argument("--reset", action="store_true", help="重置会话")
    parser.add_argument("--config", type=str, help="设置配置项 (key=value)")
    
    args = parser.parse_args()
    
    manager = ContextManager()
    
    if args.check:
        result = manager.should_cleanup_context()
        print(f"需要清理上下文: {result}")
        if result:
            print(manager.get_restart_info())
    
    elif args.update:
        manager.update_module_completion(args.update)
        print(f"已更新模块完成状态: {args.update}")
        
        # 检查是否需要重启
        if manager.should_cleanup_context():
            print("\n" + "="*50)
            print(manager.prepare_restart())
            print("="*50)
    
    elif args.restart:
        print(manager.prepare_restart())
    
    elif args.status:
        status = manager.get_status()
        print(json.dumps(status, indent=2, ensure_ascii=False))
    
    elif args.reset:
        manager.reset_session()
        print("会话状态已重置")
    
    elif args.config:
        key, value = args.config.split('=', 1)
        try:
            # 尝试转换为适当的类型
            if value.lower() in ['true', 'false']:
                value = value.lower() == 'true'
            elif value.isdigit():
                value = int(value)
        except:
            pass
        
        manager.config[key] = value
        manager.save_config()
        print(f"配置已更新: {key} = {value}")
    
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
