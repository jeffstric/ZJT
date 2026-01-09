#!/usr/bin/env python
# -*- coding: utf-8 -*-

# 任务类型
TASK_TYPE_GENERATE_VIDEO = 'generate_video'

TASK_TYPE_GENERATE_AUDIO = 'generate_audio'

# 1: 图片编辑, 2: Sora2文生视频, 3: Sora2图生视频, 4: 高清放大, 5: ai视频高清修复, 6: 图生视频高清修复，7：图片编辑(nano-banana-pro), 8: 创建角色卡, 9: AI音频生成, 10: LTX2.0图生视频, 11: Wan2.2图生视频（5秒=12，10秒=24）, 12: 可灵图生视频（5秒=38，10秒=55）
TASK_COMPUTING_POWER = {
    1: 2,
    2: 8,
    3: 8,
    4: 1,
    5: 10,
    6: 10,
    7: 6,
    8: 20,
    9: 5,
    10: 6,
    11: {5: 12, 10: 24},  # Wan2.2根据时长区分算力
    12: {5: 38, 10: 70},  # 可灵根据时长区分算力
}

AUTHENTICATION_ID = 'aa63d4090d59401b9862223087c25b98'

RECHARGE_PACKAGES = [
    {
        "package_id": 1,
        "computing_power": 100,
        "price": 0.1,
        "description": "首充福利"
    },
    {
        "package_id": 2,
        "computing_power": 200,
        "price": 9.9,
        "description": "标准套餐"
    },
    {
        "package_id": 3,
        "computing_power": 1250,
        "price": 49.9,
        "description": "进阶套餐"
    }
]