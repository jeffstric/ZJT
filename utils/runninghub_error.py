"""
RunningHub 错误识别工具

用于识别 RunningHub 上游「并发超限 / 队列上限」类临时性可重试错误，
驱动层据此返回自动延迟重试标记，避免直接判失败、退算力。

背景：当多个系统共用同一个 RunningHub 账号时，本地 runninghub_slots 槽位表
无法感知其他系统占用的并发，可能出现本地「还有空槽」、上游账号实际并发已满，
RunningHub 服务端随之返回 errorCode=421（api queue limit reached）。
这类错误本质是临时性拥堵，应当延迟重试而非直接失败。
"""
from config.constant import RUNNINGHUB_QUEUE_LIMIT_ERROR_CODE


def is_upstream_congested_error(error_code) -> bool:
    """
    识别 RunningHub 上游并发超限 / 队列上限类可重试错误

    通过 RunningHub 响应的 errorCode 精确判断：当 errorCode 等于
    config/constant.py 中 RUNNINGHUB_QUEUE_LIMIT_ERROR_CODE（'421'）时，
    视为上游拥堵，返回 True。

    Args:
        error_code: RunningHub 响应的 errorCode（字符串或数字）

    Returns:
        bool: True 表示属于上游拥堵类可重试错误
    """
    return str(error_code) == RUNNINGHUB_QUEUE_LIMIT_ERROR_CODE
