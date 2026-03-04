#!/bin/bash
# 单元测试一键执行脚本 (Shell 版本)

cd "$(dirname "$0")"

echo "=================================="
echo "单元测试一键执行"
echo "=================================="

# 检查 Python
if ! command -v python3 &> /dev/null; then
    echo "[ERROR] Python3 未安装"
    exit 1
fi

# 执行测试
python3 run_unit_tests.py "$@"

exit_code=$?

if [ $exit_code -eq 0 ]; then
    echo ""
    echo "[OK] 所有测试通过"
else
    echo ""
    echo "[FAILED] 部分测试失败"
fi

exit $exit_code
