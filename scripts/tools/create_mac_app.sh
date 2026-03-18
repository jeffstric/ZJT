#!/bin/bash
# 创建 macOS 应用程序脚本
# 使用方法: 在项目根目录运行 bash scripts/tools/create_mac_app.sh

APP_NAME="ZJT Server"

# 获取脚本所在目录
SCRIPT_PATH="${BASH_SOURCE[0]}"

# 解析绝对路径
if [[ -L "$SCRIPT_PATH" ]]; then
    SCRIPT_PATH="$(readlink "$SCRIPT_PATH")"
fi
SCRIPT_DIR="$(cd "$(dirname "$SCRIPT_PATH")" && pwd)"

# .app 创建在项目根目录（从 scripts/tools 向上两级）
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

# 验证项目目录是否正确（检查是否存在 start.command）
if [[ ! -f "$PROJECT_DIR/start.command" ]]; then
    echo "错误: 未找到 start.command 文件"
    echo "当前项目目录: $PROJECT_DIR"
    echo "请确保在项目根目录中运行此脚本"
    exit 1
fi

APP_DIR="$PROJECT_DIR/${APP_NAME}.app"

echo "=========================================="
echo "  创建 macOS 应用程序"
echo "=========================================="
echo ""
echo "正在创建: ${APP_NAME}.app"

# 创建应用程序目录结构
mkdir -p "$APP_DIR/Contents/MacOS"
mkdir -p "$APP_DIR/Contents/Resources"

# 创建 Info.plist
cat > "$APP_DIR/Contents/Info.plist" << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleExecutable</key>
    <string>launcher</string>
    <key>CFBundleIconFile</key>
    <string>AppIcon</string>
    <key>CFBundleIdentifier</key>
    <string>com.zjt.server</string>
    <key>CFBundleName</key>
    <string>ZJT Server</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleShortVersionString</key>
    <string>1.0</string>
    <key>CFBundleVersion</key>
    <string>1</string>
    <key>LSMinimumSystemVersion</key>
    <string>10.13</string>
    <key>NSHighResolutionCapable</key>
    <true/>
</dict>
</plist>
EOF

# 创建启动脚本
cat > "$APP_DIR/Contents/MacOS/launcher" << 'EOF'
#!/bin/bash
# 获取项目根目录
PROJECT_DIR="$(cd "$(dirname "$0")/../../.." && pwd)"
START_SCRIPT="$PROJECT_DIR/start.command"

# 在新终端窗口中运行 start.command
open -a Terminal "$START_SCRIPT"
EOF

# 设置执行权限
chmod +x "$APP_DIR/Contents/MacOS/launcher"

echo ""
echo "=========================================="
echo "  ✓ 应用程序创建成功!"
echo "=========================================="
echo ""
echo "应用位置: ${APP_DIR}"
echo ""
echo "使用方法:"
echo "  1. 双击 '${APP_NAME}.app' 启动服务"
echo "  2. 可以拖到 Dock 栏方便快速启动"
echo "  3. 可以拖到应用程序文件夹"
echo ""

# 自动在 Finder 中打开并选中应用
open -R "$APP_DIR"
