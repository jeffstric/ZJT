#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
统一的日志配置模块
将日志输出到 logs 目录，按日期分割文件
Windows 兼容：使用日期命名的文件，避免运行时重命名导致的权限问题
"""

import logging
import os
from datetime import datetime

# 确保 logs 目录存在
LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs')
os.makedirs(LOG_DIR, exist_ok=True)

# 日志格式
LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
DATE_FORMAT = '%Y-%m-%d %H:%M:%S'


class DailyFileHandler(logging.FileHandler):
    """
    按日期命名的文件处理器
    每天自动写入不同的文件，避免 Windows 上的文件锁定问题
    文件名格式：{base_name}.{date}.log 或 {base_name}.log（当天）
    """
    
    def __init__(self, base_name, encoding='utf-8'):
        """
        Args:
            base_name: 基础文件名（不含扩展名），如 'app' 或 'api_requests'
            encoding: 文件编码
        """
        self.base_name = base_name
        self.current_date = None
        self._encoding = encoding
        
        # 初始化时获取当前日期的文件路径
        filename = self._get_current_filename()
        super().__init__(filename, mode='a', encoding=encoding)
    
    def _get_current_filename(self):
        """获取当前日期对应的文件名"""
        today = datetime.now().strftime('%Y-%m-%d')
        return os.path.join(LOG_DIR, f'{self.base_name}.{today}.log')
    
    def emit(self, record):
        """写入日志时检查是否需要切换文件"""
        today = datetime.now().strftime('%Y-%m-%d')
        
        # 如果日期变了，切换到新文件
        if today != self.current_date:
            self.current_date = today
            
            # 关闭旧文件
            if self.stream:
                self.stream.close()
                self.stream = None
            
            # 更新文件路径并重新打开
            self.baseFilename = self._get_current_filename()
            self.stream = self._open()
        
        super().emit(record)


def setup_logger(name=None, level=logging.INFO):
    """
    设置日志记录器
    
    Args:
        name: logger 名称，默认为 None（root logger）
        level: 日志级别，默认为 INFO
    
    Returns:
        配置好的 logger 对象
    """
    logger = logging.getLogger(name)
    
    # 如果 logger 已经有 handlers，说明已经配置过，直接返回
    if logger.handlers:
        return logger
    
    logger.setLevel(level)
    
    # 创建格式化器
    formatter = logging.Formatter(LOG_FORMAT, DATE_FORMAT)
    
    # 控制台处理器
    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    # 文件处理器 - 按天分割（使用自定义的 DailyFileHandler）
    file_handler = DailyFileHandler('app', encoding='utf-8')
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    
    # API 请求日志 - 单独的文件
    # 为 runninghub_request 和 duomi_api_requset 添加 API 日志处理器
    if name in ['runninghub_request', 'duomi_api_requset', 'api_requests']:
        api_handler = DailyFileHandler('api_requests', encoding='utf-8')
        api_handler.setLevel(level)
        api_handler.setFormatter(formatter)
        logger.addHandler(api_handler)
    
    return logger


# 配置根 logger
setup_logger(level=logging.INFO)
