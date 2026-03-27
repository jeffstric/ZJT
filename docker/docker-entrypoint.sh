#!/bin/bash
# =============================================================================
# Docker Entrypoint Script
# 等待 MySQL 就绪，初始化配置，然后启动应用
# =============================================================================

set -e

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# 等待 MySQL 就绪
wait_for_mysql() {
    log_info "等待 MySQL 数据库就绪..."

    local max_attempts=30
    local attempt=1

    while [ $attempt -le $max_attempts ]; do
        if mysqladmin ping -h"${DB_HOST}" -P"${DB_PORT}" -u"${DB_USER}" -p"${DB_PASSWORD}" --skip-ssl --silent 2>/dev/null; then
            log_info "MySQL 数据库已就绪！"
            return 0
        fi

        log_warn "等待 MySQL... ($attempt/$max_attempts)"
        sleep 2
        ((attempt++))
    done

    log_error "MySQL 数据库连接超时！"
    exit 1
}

# 创建配置文件
create_config() {
    local config_file="/app/config_${comfyui_env}.yml"

    if [ ! -f "$config_file" ]; then
        log_info "创建配置文件: $config_file"
        cp /app/config.example.yml "$config_file"

        # 使用 Python 更新数据库配置
        python3 -c "
import yaml
import os

config_file = '${config_file}'
with open(config_file, 'r', encoding='utf-8') as f:
    config = yaml.safe_load(f)

if config is None:
    config = {}

if 'database' not in config:
    config['database'] = {}

config['database']['host'] = os.environ.get('DB_HOST', 'mysql')
config['database']['port'] = int(os.environ.get('DB_PORT', '3306'))
config['database']['user'] = os.environ.get('DB_USER', 'root')
config['database']['password'] = os.environ.get('DB_PASSWORD', '3bTgThWP2xeX')
config['database']['database'] = os.environ.get('DB_NAME', 'zjt')

with open(config_file, 'w', encoding='utf-8') as f:
    yaml.dump(config, f, default_flow_style=False, allow_unicode=True)

print('[INFO] 已更新数据库配置')
" 2>&1 | head -1
    else
        log_info "配置文件已存在: $config_file"
    fi
}

# 执行数据库迁移
run_migrations() {
    log_info "检查是否需要执行数据库迁移..."

    # 检查 alembic 配置
    if [ -f "/app/alembic.ini" ] && [ -d "/app/alembic" ]; then
        # 读取配置文件中的 auto_migrate 设置
        local auto_migrate=$(python3 -c "
import yaml
try:
    with open('/app/config_${comfyui_env}.yml', 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)
        print(config.get('alembic', {}).get('auto_migrate', False))
except:
    print(False)
" 2>/dev/null || echo "False")

        if [ "$auto_migrate" = "True" ] || [ "$auto_migrate" = "true" ]; then
            log_info "执行数据库迁移..."
            python3 -c "
from alembic.config import Config
from alembic import command
import sys

try:
    alembic_cfg = Config('/app/alembic.ini')
    alembic_cfg.set_main_option('sqlalchemy.url', f'mysql+pymysql://${DB_USER}:${DB_PASSWORD}@${DB_HOST}:${DB_PORT}/${DB_NAME}?charset=utf8mb4')
    command.upgrade(alembic_cfg, 'head')
    print('[INFO] 数据库迁移完成')
except Exception as e:
    print(f'[ERROR] 数据库迁移失败: {e}')
    sys.exit(1)
" || {
                log_error "数据库迁移失败！"
                exit 1
            }
        else
            log_info "自动数据库迁移已禁用 (alembic.auto_migrate = false)"
        fi
    else
        log_warn "未找到 Alembic 配置，跳过数据库迁移"
    fi
}

# 主函数
main() {
    log_info "========================================"
    log_info " ComfyUI Server Docker 启动"
    log_info " 环境: ${comfyui_env}"
    log_info "========================================"

    # 等待 MySQL 就绪
    wait_for_mysql

    # 创建配置文件
    create_config

    # 执行数据库迁移
    # run_migrations  # 迁移已在 run_prod.py 中执行

    # 启动应用
    log_info "启动应用服务..."
    log_info "========================================"

    # 始终通过 run_prod.py 启动，它会执行迁移并启动服务
    exec python3 /app/scripts/running/run_prod.py
}

# 捕获信号并传递给子进程
trap 'echo "收到停止信号，正在关闭..."; exit 0' SIGTERM SIGINT

# 执行主函数
main "$@"
