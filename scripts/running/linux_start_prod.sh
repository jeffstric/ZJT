#!/bin/bash
export comfyui_env=prod

# === 启动前检查更新 ===
echo "[upgrade] Checking for updates..."
python3 scripts/upgrade_check.py
UPGRADE_RC=$?
if [ $UPGRADE_RC -eq 2 ]; then
    echo "[ERROR] 更新检查遇到严重错误"
    exit 1
elif [ $UPGRADE_RC -eq 1 ]; then
    echo "[INFO] 更新检查未完成（网络/源不可用），继续使用本地版本"
elif [ $UPGRADE_RC -eq 10 ]; then
    echo "[INFO] 代码已更新，正在重新启动..."
    exec "$0" "$@"
fi
# ======================

# 使用统一启动器管理 scheduler 和 gunicorn
python3 run_prod.py
