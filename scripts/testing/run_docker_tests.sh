#!/bin/bash
# =============================================================================
# Docker 测试运行脚本
# 在 Docker 容器中运行单元测试
# =============================================================================

set -e

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

log_step() {
    echo -e "${BLUE}[$1]${NC} $2"
}

# 测试服务名称
TEST_SERVICE="zjt_test"
COMPOSE_FILE="docker-compose-test.yml"

# 主函数
main() {
    log_info "========================================"
    log_info " ComfyUI Server Docker 测试"
    log_info "========================================"

    # 检查 docker-compose 文件是否存在
    COMPOSE_PATH="$(dirname "$0")/../../docker/$COMPOSE_FILE"
    if [ ! -f "$COMPOSE_PATH" ]; then
        log_error "找不到 $COMPOSE_PATH"
        exit 1
    fi

    cd "$(dirname "$0")/../../docker"

    # 清理旧的测试容器
    log_step "1/4" "清理旧的测试容器..."
    docker compose -f "$COMPOSE_FILE" down -v 2>/dev/null || true

    # 启动测试环境（容器会自动运行测试并退出）
    log_step "2/4" "启动测试环境..."
    docker compose -f "$COMPOSE_FILE" up --build
    TEST_EXIT_CODE=$?

    # 显示测试结果摘要
    log_step "3/4" "显示测试结果..."
    echo ""
    docker logs $TEST_SERVICE 2>&1 | grep -E "(测试执行摘要|总计:|通过|失败|错误|OK|ERROR|步骤)" | tail -30
    echo ""

    # 关闭测试环境
    log_step "4/4" "清理测试环境..."
    docker compose -f "$COMPOSE_FILE" down -v

    # 显示最终结果
    echo ""
    if [ "$TEST_EXIT_CODE" -eq 0 ]; then
        log_info "========================================"
        log_info " 所有测试通过！"
        log_info "========================================"
    else
        log_error "========================================"
        log_error " 测试失败，退出码: $TEST_EXIT_CODE"
        log_error "========================================"
    fi

    exit $TEST_EXIT_CODE
}

# 捕获信号
trap 'log_warn "收到停止信号，正在关闭..."; docker compose -f "$COMPOSE_FILE" down -v 2>/dev/null; exit 1' SIGTERM SIGINT

# 执行主函数
main "$@"
