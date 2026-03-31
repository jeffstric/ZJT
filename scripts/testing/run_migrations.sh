#!/bin/bash
# =============================================================================
# 数据库迁移脚本
# 执行 Alembic 数据库迁移到最新版本
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

# 获取当前脚本所在目录的项目根目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

log_info "项目根目录: $PROJECT_ROOT"
log_info "开始执行数据库迁移..."

# 切换到项目根目录
cd "$PROJECT_ROOT"

# 检查 alembic 配置文件是否存在
if [ ! -f "alembic.ini" ]; then
    log_error "未找到 alembic.ini 配置文件"
    exit 1
fi

if [ ! -d "alembic" ]; then
    log_error "未找到 alembic 目录"
    exit 1
fi

# 检查数据库连接配置
if [ -z "$DB_HOST" ] || [ -z "$DB_PORT" ] || [ -z "$DB_USER" ] || [ -z "$DB_PASSWORD" ] || [ -z "$DB_NAME" ]; then
    log_warn "数据库环境变量未完全设置，尝试从配置文件读取..."
    
    # 从配置文件读取数据库配置
    if [ -f "config_${comfyui_env:-prod}.yml" ]; then
        log_info "从配置文件读取数据库配置: config_${comfyui_env:-prod}.yml"
    else
        log_error "未找到配置文件且环境变量未设置"
        exit 1
    fi
fi

# 执行数据库迁移
log_info "执行 Alembic 数据库迁移..."

python3 -c "
import sys
import os
from alembic.config import Config
from alembic import command

try:
    # 设置 Alembic 配置
    alembic_cfg = Config('alembic.ini')
    
    # 构建数据库连接字符串
    db_host = os.environ.get('DB_HOST', 'localhost')
    db_port = os.environ.get('DB_PORT', '3306')
    db_user = os.environ.get('DB_USER', 'root')
    db_password = os.environ.get('DB_PASSWORD', '')
    db_name = os.environ.get('DB_NAME', 'zjt')
    
    db_url = f'mysql+pymysql://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}?charset=utf8mb4'
    
    print(f'[INFO] 数据库连接: mysql+pymysql://{db_user}:***@{db_host}:{db_port}/{db_name}')
    
    # 设置数据库连接
    alembic_cfg.set_main_option('sqlalchemy.url', db_url)
    
    # 执行迁移到最新版本
    command.upgrade(alembic_cfg, 'head')
    
    print('[INFO] 数据库迁移完成')
    
except ImportError as e:
    print(f'[ERROR] 缺少必要的 Python 包: {e}')
    print('[INFO] 请确保已安装: pip install alembic pymysql')
    sys.exit(1)
except Exception as e:
    print(f'[ERROR] 数据库迁移失败: {e}')
    sys.exit(1)
"

if [ $? -eq 0 ]; then
    log_info "数据库迁移成功完成"
else
    log_error "数据库迁移失败"
    exit 1
fi
