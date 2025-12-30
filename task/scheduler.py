from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
import logging
from task.video_task import generate_video_task
from task.audio_task import generate_audio_task
from functools import partial


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 全局调度器实例
scheduler = None


def init_scheduler(app):
    """
    初始化定时任务调度器
    """
    global scheduler
    scheduler = BackgroundScheduler()
    
    # 创建一个带有app参数的任务函数
    task_with_app_video = partial(generate_video_task, app=app)
    task_with_app_audio = partial(generate_audio_task, app=app)
    
    logger.info('启用视频生成任务')
    scheduler.add_job(
        func=task_with_app_video,
        trigger=IntervalTrigger(seconds=11),
        id='generate_video',
        name='Generate video every 11 seconds',
        replace_existing=True,
        max_instances=1,
        coalesce=True
    )

    logger.info('启用音频生成任务')
    scheduler.add_job(
        func=task_with_app_audio,
        trigger=IntervalTrigger(seconds=7),
        id='generate_audio',
        name='Generate audio every 7 seconds',
        replace_existing=True,
        max_instances=1,
        coalesce=True
    )

    # 启动调度器
    scheduler.start()
    logger.info("定时任务启动成功")

def shutdown_scheduler():
    """
    关闭调度器
    """
    global scheduler
    if scheduler:
        scheduler.shutdown()
