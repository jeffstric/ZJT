#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
统一的日志配置模块
将日志输出到 logs 目录，按日期分割文件
"""

import logging
import os
from logging.handlers import TimedRotatingFileHandler
from datetime import datetime

# 确保 logs 目录存在
LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs')
os.makedirs(LOG_DIR, exist_ok=True)

# 日志格式
LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
DATE_FORMAT = '%Y-%m-%d %H:%M:%S'

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
    
    # 文件处理器 - 按天分割
    log_file = os.path.join(LOG_DIR, 'app.log')
    file_handler = TimedRotatingFileHandler(
        log_file,
        when='midnight',
        interval=1,
        backupCount=30,  # 保留30天的日志
        encoding='utf-8'
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)
    file_handler.suffix = '%Y-%m-%d'
    logger.addHandler(file_handler)
    
    # API 请求日志 - 单独的文件
    api_log_file = os.path.join(LOG_DIR, 'api_requests.log')
    api_handler = TimedRotatingFileHandler(
        api_log_file,
        when='midnight',
        interval=1,
        backupCount=30,
        encoding='utf-8'
    )
    api_handler.setLevel(level)
    api_handler.setFormatter(formatter)
    api_handler.suffix = '%Y-%m-%d'
    
    # 为 runninghub_request 和 duomi_api_requset 添加 API 日志处理器
    if name in ['runninghub_request', 'duomi_api_requset']:
        logger.addHandler(api_handler)
    
    return logger


# 配置根 logger
setup_logger(level=logging.INFO)
