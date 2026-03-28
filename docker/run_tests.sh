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

# 测试服务名称
TEST_SERVICE="zjt_test"
MYSQL_SERVICE="zjt_mysql_test"
COMPOSE_FILE="docker-compose-test.yml"

# 主函数
main() {
    log_info "========================================"
    log_info " ComfyUI Server Docker 测试"
    log_info "========================================"

    # 检查 docker-compose 文件是否存在
    if [ ! -f "$COMPOSE_FILE" ]; then
        log_error "找不到 $COMPOSE_FILE"
        exit 1
    fi

    # 清理旧的测试容器
    log_info "清理旧的测试容器..."
    docker compose -f "$COMPOSE_FILE" down -v 2>/dev/null || true

    # 启动测试环境（容器会自动运行测试并退出）
    log_info "启动测试环境..."
    docker compose -f "$COMPOSE_FILE" up --build

    # 获取测试容器退出码
    TEST_EXIT_CODE=$(docker inspect -f '{{.State.ExitCode}}' $TEST_SERVICE 2>/dev/null || echo "1")

    # 显示测试结果
    if [ "$TEST_EXIT_CODE" -eq 0 ]; then
        log_info "========================================"
        log_info " 所有测试通过！"
        log_info "========================================"
    else
        log_error "========================================"
        log_error " 测试失败，退出码: $TEST_EXIT_CODE"
        log_error "========================================"
    fi

    # 显示测试日志
    log_info "========================================"
    log_info " 测试日志"
    log_info "========================================"
    docker logs $TEST_SERVICE 2>&1 | tail -100

    # 关闭测试环境
    log_info "关闭测试环境..."
    docker compose -f "$COMPOSE_FILE" down -v

    exit $TEST_EXIT_CODE
}

# 捕获信号
trap 'log_warn "收到停止信号，正在关闭..."; docker compose -f "$COMPOSE_FILE" down -v 2>/dev/null; exit 1' SIGTERM SIGINT

# 执行主函数
main "$@"
