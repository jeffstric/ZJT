#!/bin/bash

# ZJT Mac 启动脚本
# 支持 M 芯片和 Intel 芯片

set -e

# 设置环境变量
export comfyui_env=${comfyui_env:-prod}
export PYTHONUTF8=1

# 获取脚本所在目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo ""
echo "========================================"
echo "  ZJT Server Startup (macOS)"
echo "  Environment: $comfyui_env"
echo "========================================"
echo ""

# 检测 CPU 架构
ARCH=$(uname -m)
echo "[INFO] Detected CPU architecture: $ARCH"

case "$ARCH" in
    arm64|x86_64)
        # 支持 M 芯片和 Intel 芯片
        ;;
    *)
        echo "[ERROR] Unsupported CPU architecture: $ARCH"
        exit 1
        ;;
esac

# [1/4] 检查 uv 包管理器
echo ""
echo "[1/4] Checking uv package manager..."
UV_CMD="$SCRIPT_DIR/bin/uv/uv"

if [ ! -f "$UV_CMD" ]; then
    echo "[ERROR] uv not found: $UV_CMD"
    echo "[INFO] Please ensure uv is installed in bin/uv/ directory"
    exit 1
fi

echo "[OK] uv found"

# [2/4] 检查配置文件
echo ""
echo "[2/4] Checking configuration file..."
ENV_FILE="$SCRIPT_DIR/config_${comfyui_env}.yml"

if [ ! -f "$ENV_FILE" ]; then
    echo "[INFO] Configuration file not found: $ENV_FILE"
    echo "[INFO] Creating from config.example.yml..."

    # 复制示例配置文件
    if [ -f "$SCRIPT_DIR/config.example.yml" ]; then
        cp "$SCRIPT_DIR/config.example.yml" "$ENV_FILE"

        # 更新 ffmpeg/ffprobe 路径为 Mac 格式（无 .exe 后缀）
        sed -i '' 's|bin/ffmpeg/ffmpeg\.exe|bin/ffmpeg/ffmpeg|g' "$ENV_FILE"
        sed -i '' 's|bin/ffmpeg/ffprobe\.exe|bin/ffmpeg/ffprobe|g' "$ENV_FILE"

        echo "[OK] Configuration file created: $ENV_FILE"
        echo "[INFO] Please review and update the configuration if needed"
    else
        echo "[ERROR] config.example.yml not found"
        exit 1
    fi
else
    echo "[OK] Configuration file found: $ENV_FILE"
fi

# [3/4] 检查 MySQL 路径
echo ""
echo "[3/4] Checking MySQL..."
MYSQL_BIN_DIR="$SCRIPT_DIR/bin/mysql/bin"

if [ ! -d "$MYSQL_BIN_DIR" ]; then
    echo "[ERROR] MySQL binary directory not found: $MYSQL_BIN_DIR"
    echo "[INFO] Please ensure MySQL is installed in bin/mysql/ directory"
    exit 1
fi

MYSQLD="$MYSQL_BIN_DIR/mysqld"
MYSQL="$MYSQL_BIN_DIR/mysql"

if [ ! -f "$MYSQLD" ]; then
    echo "[ERROR] mysqld not found: $MYSQLD"
    exit 1
fi

if [ ! -f "$MYSQL" ]; then
    echo "[ERROR] mysql not found: $MYSQL"
    exit 1
fi

echo "[OK] MySQL found"

# [4/4] 启动服务
echo ""
echo "[4/4] Starting services..."

# 使用 uv 启动 Mac 启动管理器
# 让 uv 自动选择合适的 Python 版本(系统 Python 或自动下载)
echo "[INFO] Starting with uv (auto-detect Python)..."
"$UV_CMD" run --with-requirements requirements.txt scripts/launchers/start_mac.py

echo ""
echo "========================================"
echo "  ZJT Server stopped"
echo "========================================"
