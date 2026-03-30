#!/bin/bash
# Mac 首次安装脚本 - 双击运行
# 此脚本会创建可双击的启动应用

cd "$(dirname "$0")"

echo ""
echo "=========================================="
echo "  ZJT Server - Mac 首次安装"
echo "=========================================="
echo ""
echo "正在创建启动应用..."
echo ""

# 执行创建应用脚本
bash scripts/tools/create_mac_app.sh

# 设置 .app 可执行权限
echo "正在设置可执行权限..."
chmod -R +x "ZJT Server.app"

echo ""
echo "安装完成!"
echo ""
echo "下次启动请双击: ZJT Server.app"
echo ""
read -p "按回车键关闭此窗口..."
