"""
API客户端模块
包含所有外部API的客户端实现
"""

from api.clients.duomi_client import (
    create_image_to_video,
    create_image_to_video_veo,
    create_ai_image,
    create_text_to_image,
    create_character,
    get_character_task_result,
    get_ai_task_result,
    create_kling_image_to_video,
    get_kling_task_status,
)

from api.clients.vidu_client import (
    create_vidu_image_to_video,
    create_vidu_text_to_video,
    create_vidu_start_end_to_video,
    get_vidu_task_status,
)

from api.clients.runninghub_client import (
    RunningHubClient,
    TaskStatus,
    run_ai_app_task,
    run_image_edit_task,
    create_image_edit_nodes,
    create_ltx2_image_to_video,
    create_wan22_image_to_video,
    create_digital_human,
    check_ltx2_task_status,
)
