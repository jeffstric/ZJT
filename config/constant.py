#!/usr/bin/env python
# -*- coding: utf-8 -*-

# 任务类型
TASK_TYPE_GENERATE_VIDEO = 'generate_video'

TASK_TYPE_GENERATE_AUDIO = 'generate_audio'

# 1: 图片编辑, 2: AI视频生成, 3: 图片生成视频, 4: 高清放大, 5: ai视频高清修复, 6: 图生视频高清修复，7：图片编辑(nano-banana-pro), 8: 创建角色卡, 9: AI音频生成
TASK_COMPUTING_POWER = {
    1: 2,
    2: 8,
    3: 8,
    4: 1,
    5: 10,
    6: 10,
    7: 6,
    8: 20,
    9: 5
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