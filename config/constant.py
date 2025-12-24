#!/usr/bin/env python
# -*- coding: utf-8 -*-

# 任务类型
TASK_TYPE_GENERATE_VIDEO = 'generate_video'

# 1: 图片编辑, 2: AI视频生成, 3: 图片生成视频, 4: 高清放大, 5: ai视频高清修复, 6: 图生视频高清修复，7：图片编辑(nano-banana-pro), 8: 创建角色卡
TASK_COMPUTING_POWER = {
    1: 2,
    2: 20,
    3: 20,
    4: 1,
    5: 10,
    6: 10,
    7: 6,
    8: 20
}