#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
配置检查工具模块

提供通用的配置检查功能，用于判断数据库中是否存在特定配置
"""

import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


def check_api_aggregator_config_exists(site_id: str) -> bool:
    """
    检查数据库中是否存在指定站点的API聚合器配置
    
    Args:
        site_id: 站点ID (如 site_1, site_2, ...)
        
    Returns:
        bool: 如果配置存在且完整返回True，否则返回False
    """
    try:
        from config.config_util import get_dynamic_config_value
        
        # 读取站点配置
        api_key = get_dynamic_config_value("api_aggregator", site_id, "api_key", default="")
        base_url = get_dynamic_config_value("api_aggregator", site_id, "base_url", default="")

        # site_0 base_url 为硬编码，只需检查 api_key
        if site_id == "site_0":
            return bool(api_key)

        # 检查配置是否完整
        return bool(api_key and base_url)
        
    except Exception as e:
        logger.warning(f"检查API聚合器配置 {site_id} 时出错: {e}")
        return False


def check_implementation_config_exists(implementation_name: str) -> bool:
    """
    检查指定实现方的配置是否存在

    Args:
        implementation_name: 实现方名称

    Returns:
        bool: 如果配置存在且完整返回True，否则返回False
    """
    try:
        from config.config_util import get_dynamic_config_value

        # 对于API聚合器实现方，检查对应的站点配置
        if implementation_name.startswith('gemini_image_preview_site') and implementation_name.endswith('_v1'):
            # 提取站点ID，如 gemini_image_preview_site1_v1 -> site_1
            site_num = implementation_name.replace('gemini_image_preview_site', '').replace('_v1', '')
            site_id = f"site_{site_num}"
            return check_api_aggregator_config_exists(site_id)

        # 对于多米平台实现方，检查 token 是否配置
        if '_duomi_' in implementation_name:
            token = get_dynamic_config_value("duomi", "token", default="")
            return bool(token)

        # 对于 RunningHub 供应商，检查 api_key 是否配置
        if 'runninghub' in implementation_name.lower():
            api_key = get_dynamic_config_value("runninghub", "api_key", default="")
            return bool(api_key)

        # 对于 Vidu 供应商，检查 api_key 是否配置
        if 'vidu' in implementation_name.lower():
            api_key = get_dynamic_config_value("vidu", "api_key", default="")
            return bool(api_key)

        # 对于火山引擎供应商，检查配置是否存在
        if 'volcengine' in implementation_name.lower():
            # 火山引擎需要 ARN 和 API Key
            arn = get_dynamic_config_value("seedream", "function_arn", default="")
            api_key = get_dynamic_config_value("seedream", "api_key", default="")
            return bool(arn and api_key)

        # 对于其他实现方，检查驱动类是否可导入
        from config.unified_config import UnifiedConfigRegistry
        impl_config = UnifiedConfigRegistry.get_implementation(implementation_name)
        if not impl_config:
            return False

        # 检查驱动类是否可导入
        try:
            module_path, class_name = impl_config.driver_class.rsplit('.', 1) if '.' in impl_config.driver_class else ('task.visual_drivers', impl_config.driver_class)
            module = __import__(module_path, fromlist=[class_name])
            driver_class = getattr(module, class_name)

            # 尝试实例化驱动来检查配置
            if hasattr(driver_class, '__init__'):
                # 对于需要参数的驱动，这里只检查类是否存在
                return True
            else:
                return True

        except (ImportError, AttributeError):
            return False

    except Exception as e:
        logger.warning(f"检查实现方配置 {implementation_name} 时出错: {e}")
        return False


def get_available_api_aggregator_sites() -> Dict[str, Dict[str, Any]]:
    """
    获取所有可用的API聚合器站点信息
    
    Returns:
        Dict: 站点ID -> 站点信息映射
    """
    sites = {}
    for site_id in ['site_0', 'site_1', 'site_2', 'site_3', 'site_4', 'site_5']:
        if check_api_aggregator_config_exists(site_id):
            try:
                from config.config_util import get_dynamic_config_value
                site_name = get_dynamic_config_value("api_aggregator", site_id, "name", default=site_id)
                sites[site_id] = {
                    'site_id': site_id,
                    'site_name': site_name,
                    'implementation_name': f'gemini_image_preview_{site_id}_v1'
                }
            except Exception as e:
                logger.warning(f"获取站点 {site_id} 信息时出错: {e}")
    
    return sites
