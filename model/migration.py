"""
数据库迁移执行模块
提供应用启动时自动执行 Alembic 迁移的功能
"""
import os
import sys
import logging
from pathlib import Path
 
logger = logging.getLogger(__name__)
 
# 项目根目录
APP_DIR = Path(__file__).parent.parent
 
 
def get_alembic_config():
    """获取 Alembic 配置"""
    import yaml
    from config_util import get_config_path
 
    config_file = APP_DIR / get_config_path()
 
    if not config_file.exists():
        return {"auto_migrate": False}
 
    with open(config_file, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)
 
    return config.get('alembic', {"auto_migrate": False})
 
 
def run_migrations() -> bool:
    """
    执行数据库迁移到最新版本
 
    Returns:
        bool: 迁移是否成功
    """
    try:
        from alembic.config import Config
        from alembic import command
 
        # 构建 alembic.ini 路径
        alembic_ini = APP_DIR / "alembic.ini"
 
        if not alembic_ini.exists():
            logger.warning(f"Alembic config not found: {alembic_ini}")
            return False
 
        # 创建 Alembic 配置
        alembic_cfg = Config(str(alembic_ini))
 
        # 设置脚本路径（相对于项目根目录）
        alembic_cfg.set_main_option("script_location", str(APP_DIR / "alembic"))
 
        logger.info("Running database migrations...")
 
        # 执行迁移到最新版本
        command.upgrade(alembic_cfg, "head")
 
        logger.info("Database migrations completed successfully")
        return True
 
    except ImportError as e:
        logger.warning(f"Alembic not installed, skipping migrations: {e}")
        return False
    except Exception as e:
        logger.error(f"Database migration failed: {e}")
        raise
 
 
def get_current_revision() -> str:
    """
    获取当前数据库版本
 
    Returns:
        str: 当前版本号，如果没有版本则返回 None
    """
    try:
        from alembic.config import Config
        from alembic import command
        from alembic.script import ScriptDirectory
        from alembic.runtime.migration import MigrationContext
        from sqlalchemy import create_engine
 
        from model.database import DB_CONFIG
 
        # 构建连接字符串
        host = DB_CONFIG.get('host', 'localhost')
        port = DB_CONFIG.get('port', 3306)
        user = DB_CONFIG.get('user', 'root')
        password = DB_CONFIG.get('password', '')
        database = DB_CONFIG.get('database', 'test')
        charset = DB_CONFIG.get('charset', 'utf8mb4')
 
        url = f"mysql+pymysql://{user}:{password}@{host}:{port}/{database}?charset={charset}"
 
        engine = create_engine(url)
        with engine.connect() as conn:
            context = MigrationContext.configure(conn)
            return context.get_current_revision()
 
    except Exception as e:
        logger.error(f"Failed to get current revision: {e}")
        return None
 
 
def stamp_head() -> bool:
    """
    将数据库标记为最新版本（不执行迁移）
    用于初始化已有数据库
 
    Returns:
        bool: 是否成功
    """
    try:
        from alembic.config import Config
        from alembic import command
 
        alembic_ini = APP_DIR / "alembic.ini"
 
        if not alembic_ini.exists():
            logger.warning(f"Alembic config not found: {alembic_ini}")
            return False
 
        alembic_cfg = Config(str(alembic_ini))
        alembic_cfg.set_main_option("script_location", str(APP_DIR / "alembic"))
 
        logger.info("Stamping database as head...")
        command.stamp(alembic_cfg, "head")
 
        logger.info("Database stamped as head successfully")
        return True
 
    except Exception as e:
        logger.error(f"Failed to stamp head: {e}")
        raise
 