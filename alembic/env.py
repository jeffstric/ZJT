"""
Alembic 环境配置
从项目配置文件动态读取数据库连接信息
"""
import sys
import os
from logging.config import fileConfig

from sqlalchemy import engine_from_config
from sqlalchemy import pool
from sqlalchemy import text

from alembic import context

# 添加项目根目录到 path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from model.database import DB_CONFIG

# Alembic Config 对象
config = context.config

# 设置日志
if config.config_file_name is not None:
    import configparser
    file_config = configparser.ConfigParser()
    file_config.read(config.config_file_name, encoding='utf-8')
    fileConfig(file_config, disable_existing_loggers=False)

# 构建数据库连接字符串
def get_database_url():
    """从 DB_CONFIG 构建 SQLAlchemy 连接字符串"""
    host = DB_CONFIG.get('host', 'localhost')
    port = DB_CONFIG.get('port', 3306)
    user = DB_CONFIG.get('user', 'root')
    password = DB_CONFIG.get('password', '')
    database = DB_CONFIG.get('database', 'test')
    charset = DB_CONFIG.get('charset', 'utf8mb4')
    
    # 使用 pymysql 驱动
    return f"mysql+pymysql://{user}:{password}@{host}:{port}/{database}?charset={charset}"


# 不使用 ORM 模型，设置为 None
target_metadata = None


def run_migrations_offline() -> None:
    """
    离线模式运行迁移
    生成 SQL 脚本而不实际执行
    """
    url = get_database_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """
    在线模式运行迁移
    直接连接数据库执行
    """
    # 动态设置数据库 URL
    configuration = config.get_section(config.config_ini_section)
    configuration["sqlalchemy.url"] = get_database_url()
    
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection, 
            target_metadata=target_metadata
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
