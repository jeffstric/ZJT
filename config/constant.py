#!/usr/bin/env python
# -*- coding: utf-8 -*-

# 任务类型
TASK_TYPE_GENERATE_VIDEO = 'generate_video'

TASK_TYPE_GENERATE_AUDIO = 'generate_audio'

# 1: 图片编辑, 2: Sora2文生视频, 3: Sora2图生视频, 4: 高清放大, 5: ai视频高清修复, 6: 图生视频高清修复，7：图片编辑(nano-banana-pro), 8: 创建角色卡, 
# 9: AI音频生成, 10: LTX2.0图生视频, 11: Wan2.2图生视频（5秒=12，10秒=24）, 12: 可灵图生视频（5秒=38，10秒=55）, 13: 数字人生成, 14: Vidu图生视频（5秒=8）
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
    11: {5: 6, 10: 12},  # Wan2.2根据时长区分算力，原先是5:12 10:24，现在由于sora挂掉，需要它先半价。
    12: {5: 38, 10: 70},  # 可灵根据时长区分算力
    13: 12,  # 数字人生成
    14: {5: 16, 8: 22},  # Vidu根据时长区分算力
}

# 视频模型时长选项配置
# 注意：时长选项必须与 TASK_COMPUTING_POWER 中对应任务类型的 key 保持一致
# ltx2 -> 任务类型10, wan22 -> 任务类型11, kling -> 任务类型12, vidu -> 任务类型14, sora2 -> 任务类型3
VIDEO_MODEL_DURATION_OPTIONS = {
    'ltx2': [5, 8, 10],  # LTX2.0 固定算力，支持5/8/10秒
    'wan22': list(TASK_COMPUTING_POWER[11].keys()),  # 从算力配置中自动获取时长选项
    'kling': list(TASK_COMPUTING_POWER[12].keys()),  # 从算力配置中自动获取时长选项
    'vidu': list(TASK_COMPUTING_POWER[14].keys()),   # 从算力配置中自动获取时长选项
    'sora2': [10, 15],  # Sora2 固定算力，支持10/15秒
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