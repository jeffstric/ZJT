"""
Video generation task processing

⚠️ 核心模块 - 视频/图片生成任务的提交、状态检查、失败处理、重试调度全链路
修改此文件前务必理解以下架构：

【双状态系统】
  AI_TOOL_STATUS_*  → ai_tools 表（任务主记录，含 project_id、result_url 等）
  TASK_STATUS_*     → tasks 表（调度记录，含 try_count、next_trigger 等）
  两套状态值必须保持一一对应同步更新，否则会导致调度器行为异常。
  对应关系：PENDING↔QUEUED, PROCESSING↔PROCESSING, COMPLETED↔COMPLETED,
            FAILED↔FAILED, SYNC_QUEUED↔SYNC_QUEUED,
            WAITING_PARAM_PREPARE↔WAITING_PARAM_PREPARE,
            WAITING_BEFORE_FINISH↔WAITING_BEFORE_FINISH

【任务生命周期】
  _submit_new_task() → 提交任务（6条退出路径，见函数内注释）
  _check_task_status() → 轮询 PROCESSING 任务状态
  _check_pipeline_stage() → 处理流水线阶段（PARAM_PREPARE / BEFORE_FINISH）
  _handle_task_failure() → 统一失败入口（企业版重试 / 社区版直接失败 + 退费）
  process_task_with_retry() → 调度器主循环（RunningHub 槽位控制 + 过期检查 + 卡死恢复）

【企业版 vs 社区版】
  _enterprise_failure_handler 由企业版模块注册，社区版为 None。
  企业版失败时先尝试 before_finish 切换备用实现方，社区版直接失败+退费。
"""
import logging
import json
from datetime import datetime, timedelta
import uuid
from perseids_server.client import make_perseids_request
from config.constant import TASK_COMPUTING_POWER
from config.config_util import get_dynamic_config_value
from model import TasksModel, AIToolsModel, RunningHubSlotsModel
from model.runninghub_slots import RunningHubSlot
from config.constant import (
    TASK_TYPE_GENERATE_VIDEO,
    AI_TOOL_STATUS_PENDING,
    AI_TOOL_STATUS_PROCESSING,
    AI_TOOL_STATUS_COMPLETED,
    AI_TOOL_STATUS_FAILED,
    AI_TOOL_STATUS_SYNC_QUEUED,
    AI_TOOL_STATUS_WAITING_PARAM_PREPARE,
    AI_TOOL_STATUS_WAITING_BEFORE_FINISH,
    TASK_STATUS_QUEUED,
    TASK_STATUS_PROCESSING,
    TASK_STATUS_COMPLETED,
    TASK_STATUS_FAILED,
    TASK_STATUS_SYNC_QUEUED,
    TASK_STATUS_WAITING_PARAM_PREPARE,
    TASK_STATUS_WAITING_BEFORE_FINISH,
    RUNNINGHUB_TASK_TYPES,
    RUNNINGHUB_UPSTREAM_CONGEST_RETRY_DELAY_DEFAULT
)
from model.ai_tool_pipeline_steps import PipelineStepStatus, PipelineStage
from model.ai_tools_log import AIToolsLogModel, AIToolsLogEvent

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 企业版失败重试处理器钩子
# 企业版模块加载时通过 register_enterprise_failure_handler() 注册
# 社区版不注册，_enterprise_failure_handler 保持 None
_enterprise_failure_handler = None


def register_enterprise_failure_handler(handler):
    """
    注册企业版失败重试处理器

    由 enterprise/__init__.py 在加载时调用，将 before_finish 重试逻辑
    注入到主任务处理流程中。社区版不调用此函数，重试逻辑不生效。

    Args:
        handler: 重试处理函数，签名为:
            handler(task_id, ai_tool_type, reason, user_id, project_id=None) -> bool|None
            返回 True 表示已进入重试流程，返回 None/False 表示无可用重试
    """
    global _enterprise_failure_handler
    _enterprise_failure_handler = handler
    logger.info("[Enterprise] Failure retry handler registered")

def _is_test_mode_enabled():
    """动态获取测试模式状态"""
    return get_dynamic_config_value("test_mode", "enabled", default=False)

def _get_max_retry_count():
    """动态获取最大重试次数"""
    return get_dynamic_config_value("task_queue", "max_retry_count", default=30)

def _get_task_expire_days():
    """动态获取任务过期天数"""
    return get_dynamic_config_value("task_queue", "task_expire_days", default=7)

def _is_expire_check_enabled():
    """动态获取是否启用过期检查"""
    return get_dynamic_config_value("task_queue", "enable_expire_check", default=True)


def _normalize_failure_reason(reason):
    """将外部驱动返回的失败原因转换成可写入数据库的字符串。"""
    if reason is None:
        return "任务失败"
    if isinstance(reason, str):
        return reason
    if isinstance(reason, dict):
        message = reason.get("message")
        if isinstance(message, str) and message:
            return message
    try:
        return json.dumps(reason, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(reason)

if _is_test_mode_enabled():
    logger.info("=" * 60)
    logger.info("TEST MODE ENABLED - Using mock API responses")
    logger.info("=" * 60)


def calculate_next_retry_delay(try_count):
    """
    Calculate next retry delay time
    
    Args:
        try_count: Number of attempts made
    
    Returns:
        Delay in seconds, maximum 360 seconds
    """
    base_delay = 3
    max_delay = 360
    delay_seconds = base_delay * (2 ** (try_count - 1))
    return min(delay_seconds, max_delay)


def _refund_computing_power(ai_tool, reason: str):
    """
    退还算力 - 两层回退机制

    ⚠️ 退费金额计算优先级：
      1. get_computing_power_for_task() → 考虑实现方修饰符、分辨率等上下文（推荐）
      2. TASK_COMPUTING_POWER[type] → 旧静态配置回退（不含修饰符，可能金额不准）

    ⚠️ 此函数在异步上下文中被同步调用（_handle_task_failure 是同步函数），
    内部的 make_perseids_request 是同步 HTTP 请求，会短暂阻塞事件循环。

    Args:
        ai_tool: AITool 对象
        reason: 退还原因（仅用于日志）
    """
    try:
        user_id = ai_tool.user_id
        ai_tool_type = ai_tool.type
        task_id = ai_tool.id

        if not user_id:
            logger.warning(f"Task {task_id} has no user_id, skipping refund")
            return

        computing_power = None

        # 优先使用新的算力计算工具（考虑修饰符）
        try:
            from utils.computing_power import (
                build_context_from_task_record,
                get_computing_power_for_task,
                get_implementation_for_user
            )
            from config.unified_config import get_implementation_name

            context = build_context_from_task_record(ai_tool)
            # 优先使用任务创建时保存的实现方，回退到用户当前偏好
            impl_id = getattr(ai_tool, 'implementation', None)
            impl_name = get_implementation_name(impl_id) if impl_id else None
            implementation = impl_name if impl_name and impl_name != 'unknown' else get_implementation_for_user(ai_tool_type, user_id)

            computing_power = get_computing_power_for_task(
                task_type=ai_tool_type,
                duration=getattr(ai_tool, 'duration', 5),
                user_id=user_id,
                implementation=implementation,
                context=context
            )

            if computing_power:
                logger.info(f"Refund with modifiers: context={context}, implementation={implementation}")
        except Exception as e:
            logger.warning(f"Modifier-aware refund failed for task {task_id}, falling back: {e}")

        # 回退：使用旧的 TASK_COMPUTING_POWER 配置
        if not computing_power:
            computing_power_config = TASK_COMPUTING_POWER.get(ai_tool_type)
            if isinstance(computing_power_config, dict):
                duration = getattr(ai_tool, 'duration', 5) or 5
                computing_power = computing_power_config.get(duration)
                if not computing_power:
                    computing_power = list(computing_power_config.values())[0]
            else:
                computing_power = computing_power_config

        if not computing_power:
            logger.warning(f"Task {task_id} type {ai_tool_type} has no computing power config")
            return

        transaction_id = str(uuid.uuid4())
        logger.info(f"Refunding {computing_power} computing power for user {user_id}, reason: {reason}")

        success, message, response_data = make_perseids_request(
            endpoint='get_auth_token_by_user_id',
            method='POST',
            data={"user_id": user_id}
        )

        if not success:
            logger.error(f"Failed to get auth token for user {user_id}: {message}")
            return

        auth_token = response_data['token']
        headers = {'Authorization': f'Bearer {auth_token}'}

        success, message, response_data = make_perseids_request(
            endpoint='user/calculate_computing_power',
            method='POST',
            headers=headers,
            data={
                "computing_power": computing_power,
                "behavior": "increase",
                "transaction_id": transaction_id
            }
        )

        if success:
            logger.info(f"Task {task_id} refund ({computing_power}) processed successfully")
        else:
            logger.error(f"Task {task_id} refund ({computing_power}) failed: {message}")

    except Exception as e:
        logger.error(f"Failed to process refund for task {ai_tool.id}: {e}")


async def _submit_new_task(ai_tool):
    """
    使用驱动架构提交新任务 (status == AI_TOOL_STATUS_PENDING)

    ⚠️ 6条退出路径（修改时请逐一确认影响）：
      1. Pipeline PARAM_PREPARE → WAITING_PARAM_PREPARE, return True
      2. Sync mode → 提交到进程池, SYNC_QUEUED, return True
      3. Mock 短路 → 直接 PROCESSING, return True
      4. Driver 创建失败 → FAILED + 退费, return False
      5. 同步 API 成功 → 直接 COMPLETED（含媒体下载缓存）, return True
      6. 异步提交成功 → PROCESSING + project_id, return True
      7. 提交失败 → _handle_task_failure（企业版重试 / 社区版失败+退费）

    Args:
        ai_tool: AITool 对象

    Returns:
        bool: True 表示成功，False 表示失败
    """
    from task.visual_drivers import VideoDriverFactory
    from config.unified_config import UnifiedConfigRegistry, get_implementation_id, get_implementation_name
    from task.sync_task_executor import get_sync_task_executor

    ai_tool_type = ai_tool.type
    # ⚠️ 命名陷阱：task_id 实际上是 ai_tools 表的 id，不是 tasks 表的 id
    # tasks 表的 id 在 process_task_with_retry 中通过 task.id 获取
    # 后续重构应改为 ai_tools_id 以避免混淆
    task_id = ai_tool.id

    if _is_test_mode_enabled():
        logger.info(f"[TEST MODE] [DRIVER] Submitting task {task_id} (type: {ai_tool_type})")

    try:
        from task.mock_interceptor import is_mock_enabled, visual_async_submit_result
        mock_enabled = is_mock_enabled()

        # 0a. 检查 param_prepare 步骤（流水线预处理阶段）
        from task.pipeline_processor import PipelineProcessor
        pending_prep = PipelineProcessor.get_pending_steps(task_id, PipelineStage.PARAM_PREPARE)
        if pending_prep:
            AIToolsModel.update(task_id, status=AI_TOOL_STATUS_WAITING_PARAM_PREPARE)
            TasksModel.update_by_task_id(task_id, status=TASK_STATUS_WAITING_PARAM_PREPARE)
            logger.info(f"Task {task_id} has {len(pending_prep)} param_prepare steps, entering pipeline")
            return True  # 调度器会自动分发 PENDING 步骤

        # 0b. 获取 implementation 并立即记录（确保无论后续成功/失败/异常都有记录）
        # 优先使用已记录的 implementation（如由 retry driver 设置），回退到用户偏好
        implementation_name = None
        if ai_tool.implementation:
            existing_impl_name = get_implementation_name(ai_tool.implementation)
            if existing_impl_name and existing_impl_name != 'unknown':
                implementation_name = existing_impl_name
                logger.info(f"Using recorded implementation {existing_impl_name} (id: {ai_tool.implementation}) for task {task_id}")

        if not implementation_name:
            implementation_name = VideoDriverFactory.get_implementation_for_user(ai_tool_type, ai_tool.user_id)

        if implementation_name:
            implementation_id = get_implementation_id(implementation_name)
            if implementation_id > 0:
                AIToolsModel.update(task_id, implementation=implementation_id)
                logger.info(f"Recorded implementation {implementation_name} (id: {implementation_id}) for task {task_id}")
                AIToolsLogModel.log(task_id, AIToolsLogEvent.IMPLEMENTATION_SELECTED,
                                   user_id=ai_tool.user_id,
                                   implementation=implementation_id,
                                   message=f"选用实现方: {implementation_name}",
                                   detail={'impl_name': implementation_name, 'impl_id': implementation_id})

                # 仅在首次提交时记录实现方尝试（attempt_number=1）
                # 重试由 ImplementationRetryPipelineDriver 记录（attempt_number>=2）
                if not ai_tool.implementation:
                    try:
                        from model.implementation_attempts import ImplementationAttemptModel
                        ImplementationAttemptModel.create(
                            ai_tool_id=task_id,
                            implementation=implementation_id,
                            attempt_number=1,
                            status=0,
                            started_at=datetime.now()
                        )
                    except Exception as e:
                        logger.warning(f"Failed to record implementation attempt for task {task_id}: {e}")
            else:
                logger.warning(f"Implementation name '{implementation_name}' not found in IMPLEMENTATION_TO_ID mapping for task {task_id}")

            impl_config = UnifiedConfigRegistry.get_implementation(implementation_name)

            # 检查是否为同步模式 - 分流到进程池
            if impl_config and impl_config.sync_mode:
                executor = get_sync_task_executor()
                if executor.is_running():
                    submitted = executor.submit(task_id, ai_tool_type, implementation_name)
                    if submitted:
                        AIToolsModel.update(task_id, status=AI_TOOL_STATUS_SYNC_QUEUED)
                        TasksModel.update_by_task_id(task_id, status=TASK_STATUS_SYNC_QUEUED)
                        logger.info(f"[SyncTask] Task {task_id} submitted to sync task executor (sync_mode implementation: {impl_config.name})")
                        return True

                    logger.error(
                        f"[SyncTask] Submit failed for task {task_id} implementation={implementation_name}; outer retry will backoff"
                    )
                    return False
                else:
                    logger.warning(f"[SyncTask] Sync task executor not running, falling back to normal processing")

        # ===== E2E Mock 短路（保留 param_prepare 与 sync_mode 调度之后，仅拦截普通异步 driver）=====
        if mock_enabled:
            mock = visual_async_submit_result(ai_tool_type)
            project_id = mock["project_id"]
            AIToolsModel.update(task_id, project_id=project_id, status=AI_TOOL_STATUS_PROCESSING)
            TasksModel.update_by_task_id(task_id, status=TASK_STATUS_PROCESSING)
            logger.info(f"[MOCK] visual async submit short-circuit task={task_id} pid={project_id}")
            return True
        # ==============================================================================

        # 1. 优先使用记录的 implementation 创建驱动，确保重试时使用正确的实现方
        driver = None
        if ai_tool.implementation:
            impl_name = get_implementation_name(ai_tool.implementation)
            if impl_name and impl_name != 'unknown':
                driver = VideoDriverFactory.create_driver_by_implementation(impl_name)

        if not driver:
            driver = VideoDriverFactory.create_driver_by_type(ai_tool_type, user_id=ai_tool.user_id)

        if not driver:
            # 获取详细的错误原因
            create_error = VideoDriverFactory.get_last_create_error()
            if create_error:
                error_message = create_error.get("message", f"不支持的任务类型: {ai_tool_type}")
                logger.error(f"Failed to create driver for type {ai_tool_type}: {error_message}")
            else:
                error_message = f"不支持的任务类型: {ai_tool_type}"
                logger.error(f"Unsupported driver type: {ai_tool_type}")
            # 更新任务状态为失败
            AIToolsModel.update(task_id, status=AI_TOOL_STATUS_FAILED, message=error_message, completed_time=datetime.now())
            TasksModel.update_by_task_id(task_id, status=TASK_STATUS_FAILED)
            # 释放 RunningHub 槽位（如果是 RunningHub 任务且已获取槽位）
            if ai_tool_type in RUNNINGHUB_TASK_TYPES:
                task = TasksModel.get_by_task_id(task_id)
                if task:
                    RunningHubSlotsModel.release_slot(task.id, source=RunningHubSlot.SOURCE_TASK)
                    logger.info(f"Released RunningHub slot for failed driver creation, task {task_id}")
            # 退还算力
            _refund_computing_power(ai_tool, error_message)
            return False

        logger.info(f"Using driver: {driver.driver_name} for task {task_id}")
        
        # 2. 调用驱动提交任务
        import inspect
        if inspect.iscoroutinefunction(driver.submit_task):
            result = await driver.submit_task(ai_tool)
        else:
            result = driver.submit_task(ai_tool)
        
        # 3. 处理提交结果
        if not result.get("success"):
            error = result.get("error", "未知错误")
            error_type = result.get("error_type", "SYSTEM")
            error_detail = result.get("error_detail", "")

            logger.error(f"Task {task_id} submission failed: {error}")
            if error_detail:
                logger.error(f"Error detail: {error_detail}")
            AIToolsLogModel.log(task_id, AIToolsLogEvent.UPSTREAM_FAILED,
                               user_id=ai_tool.user_id,
                               message=f"提交失败: {error}",
                               detail={'error': error, 'error_type': error_type,
                                       'error_detail': error_detail})
            
            # 上游并发超限/限流（api queue limit reached / TASK_QUEUE_MAXED 等）：
            # 释放本地槽位、状态回 QUEUED、延迟重试，不消耗 try_count、不退算力、不切换实现方。
            # 复用本地槽位满的延迟出队机制（list_by_type_and_status 带 next_trigger <= NOW 过滤）。
            if result.get("retry") and result.get("retry_reason") == "UPSTREAM_CONGESTED" \
                    and ai_tool_type in RUNNINGHUB_TASK_TYPES:
                rh_task = TasksModel.get_by_task_id(task_id)
                if rh_task:
                    RunningHubSlotsModel.release_slot(rh_task.id, source=RunningHubSlot.SOURCE_TASK)
                delay = get_dynamic_config_value(
                    "runninghub", "upstream_congest_retry_delay",
                    default=RUNNINGHUB_UPSTREAM_CONGEST_RETRY_DELAY_DEFAULT
                )
                next_trigger = datetime.now() + timedelta(seconds=delay)
                TasksModel.update_by_task_id(
                    task_id, status=TASK_STATUS_QUEUED, next_trigger=next_trigger
                )
                logger.info(f"Task {task_id} upstream congested, re-queued, will retry in {delay}s")
                return True  # 返回 True → 外层 process_task_with_retry 不增加 try_count

            # 处理需要重试的情况（通常是网络异常）
            if result.get("retry"):
                logger.warning(f"Task {task_id} will retry later due to network error")
                # 返回 False，让 process_task_with_retry 增加重试计数并设置延迟
                return False
            
            # 提交失败：尝试通过 before_finish 切换备用实现方重试
            # 无论是 USER 错误还是 SYSTEM 错误，都尝试重试
            # 因为不同供应商的审核策略、网络状况、API 行为都不同
            return _handle_task_failure(
                task_id=task_id, ai_tool_type=ai_tool_type,
                reason=error if error_type == "USER" else "服务异常，请联系技术支持",
                user_id=ai_tool.user_id
            )
        
        # 4. 提交成功，检查是否同步模式
        if result.get("sync_mode"):
            # 同步 API 直接返回结果，无需轮询
            result_url = result.get("result_url")

            # 判断是否已经是本地路径（以 /upload/ 开头）
            # 如果是，则跳过下载，直接使用
            is_local_path = result_url and result_url.startswith("/upload/")

            if is_local_path:
                # 已经是本地路径，无需下载
                final_url = result_url
                logger.info(f"Sync task result is already local: {result_url}")
            else:
                # 下载并缓存媒体文件
                from utils.media_cache import download_and_cache

                # 判断媒体类型（根据URL扩展名）
                media_type = "video"  # 默认为视频
                if result_url:
                    ext = result_url.split('?')[0].split('.')[-1].lower()
                    if ext in ['jpg', 'jpeg', 'png', 'gif', 'webp']:
                        media_type = "image"

                AIToolsLogModel.log(task_id, AIToolsLogEvent.DOWNLOAD_STARTED,
                                   user_id=ai_tool.user_id,
                                   message="开始下载结果文件（同步任务）",
                                   detail={'source_url': result_url, 'media_type': media_type})
                download_start = datetime.now()
                # 下载并缓存，如果失败则使用原URL
                cached_url = await download_and_cache(result_url, task_id, media_type)
                final_url = cached_url if cached_url else result_url
                download_ms = int((datetime.now() - download_start).total_seconds() * 1000)

                logger.info(f"Sync task media cached: {result_url} -> {final_url}")
                AIToolsLogModel.log(task_id, AIToolsLogEvent.DOWNLOAD_COMPLETED,
                                   user_id=ai_tool.user_id,
                                   message="下载/缓存完成（同步任务）",
                                   duration_ms=download_ms,
                                   detail={'source_url': result_url, 'final_url': final_url})

            AIToolsModel.update_with_cdn_sync(task_id, result_url=final_url, status=AI_TOOL_STATUS_COMPLETED, completed_time=datetime.now())
            TasksModel.update_by_task_id(task_id, status=TASK_STATUS_COMPLETED)

            # 标记当前实现方尝试为成功
            try:
                from model.implementation_attempts import ImplementationAttemptModel, ATTEMPT_STATUS_SUCCESS
                ImplementationAttemptModel.mark_active_attempt_completed(task_id, ATTEMPT_STATUS_SUCCESS)
            except Exception as e:
                logger.warning(f"Failed to mark attempt as success for sync task {task_id}: {e}")

            logger.info(f"Sync task {task_id} completed with result: {final_url}")
            AIToolsLogModel.log(task_id, AIToolsLogEvent.TASK_COMPLETED,
                               user_id=ai_tool.user_id, status_to=AI_TOOL_STATUS_COMPLETED,
                               message="任务完成（同步任务）",
                               detail={'result_url': final_url})
            return True

        # 5. 异步模式，更新数据库
        project_id = result.get("project_id")

        if not project_id:
            logger.error(f"Task {task_id} submitted but no project_id returned")
            # 尝试通过 before_finish 切换备用实现方重试
            return _handle_task_failure(
                task_id=task_id, ai_tool_type=ai_tool_type,
                reason="服务异常，未返回任务ID",
                user_id=ai_tool.user_id
            )
        
        # 更新 AITools 和 Tasks 表状态
        AIToolsModel.update(task_id, project_id=project_id, status=AI_TOOL_STATUS_PROCESSING)
        TasksModel.update_by_task_id(task_id, status=TASK_STATUS_PROCESSING)
        
        # 如果是 RunningHub 任务，更新槽位的 project_id
        is_runninghub = ai_tool_type in RUNNINGHUB_TASK_TYPES
        if is_runninghub:
            task = TasksModel.get_by_task_id(task_id)
            if task:
                RunningHubSlotsModel.update_project_id(task.id, project_id, source=RunningHubSlot.SOURCE_TASK)
                logger.info(f"Updated RunningHub slot project_id for task {task_id}")
        
        logger.info(f"Task {task_id} submitted successfully with project_id: {project_id}")
        AIToolsLogModel.log(task_id, AIToolsLogEvent.SUBMITTED,
                           user_id=ai_tool.user_id, project_id=project_id,
                           status_to=AI_TOOL_STATUS_PROCESSING,
                           implementation=ai_tool.implementation,
                           message=f"已提交到上游，project_id={project_id}",
                           detail={'project_id': project_id, 'driver': driver.driver_name})
        return True

    except Exception as e:
        # 捕获所有未预期的异常
        logger.error(f"Unexpected exception in _submit_new_task_with_driver for task {task_id}: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        AIToolsLogModel.log(task_id, AIToolsLogEvent.EXCEPTION,
                           user_id=getattr(ai_tool, 'user_id', None),
                           message=f"提交流程异常: {str(e)}")
        
        # 更新任务状态为失败
        AIToolsModel.update(task_id, status=AI_TOOL_STATUS_FAILED, message="服务异常，请联系技术支持", completed_time=datetime.now())
        TasksModel.update_by_task_id(task_id, status=TASK_STATUS_FAILED)

        # 退还算力
        _refund_computing_power(ai_tool, "任务提交异常")

        return False


async def _check_task_status(ai_tool):
    """
    使用驱动架构检查任务状态 (status == AI_TOOL_STATUS_PROCESSING)

    ⚠️ 关键逻辑：
      - 先检查是否在同步执行器中运行（跳过，避免干扰）
      - 孤儿检测：PROCESSING + 无 project_id + 不在同步执行器 → 重置为 PENDING
      - Mock 短路：直接返回成功
      - 正常流程：调用驱动 check_status，根据结果更新状态

    Args:
        ai_tool: AITool 对象

    Returns:
        bool: True 表示任务已完成（成功或失败），False 表示仍在处理中
    """
    from task.visual_drivers import VideoDriverFactory
    from task.sync_task_executor import get_sync_task_executor
    
    project_id = ai_tool.project_id
    ai_tool_type = ai_tool.type
    task_id = ai_tool.id
    
    # 检查任务是否正在同步执行器中运行
    # 同步任务在执行器中会被设置为 PROCESSING 状态但没有 project_id，这是正常的
    executor = get_sync_task_executor()
    if executor.is_task_running(task_id):
        logger.debug(f"Task {task_id} is running in sync executor, skip status check")
        return False
    
    if not project_id:
        # ⚠️ 孤儿任务恢复：PROCESSING + 无 project_id + 不在同步执行器
        # 常见原因：同步执行器子进程崩溃/超时，结果未写回数据库
        # 处理：重置为 PENDING/QUEUED，try_count 清零，让调度器重新提交
        # 注意：不清零 try_count 可能导致快速触发 max_retry 失败
        logger.warning(f"AI tool {task_id} has no project_id while status=PROCESSING and not in sync executor, resetting to PENDING")
        AIToolsModel.update(task_id, status=AI_TOOL_STATUS_PENDING)
        TasksModel.update_by_task_id(task_id, status=TASK_STATUS_QUEUED, try_count=0, next_trigger=datetime.now())
        return True
    
    if _is_test_mode_enabled() and isinstance(project_id, str) and project_id.startswith("mock_task_"):
        logger.info(f"[TEST MODE] [DRIVER] Checking status for mock task {project_id}")

    # ===== E2E Mock 短路 =====
    from task.mock_interceptor import is_mock_enabled, is_mock_id, visual_async_status_result
    if is_mock_enabled() and is_mock_id(project_id):
        mock = visual_async_status_result(ai_tool_type)
        result_url = mock.get("result_url")
        if result_url:
            return await _handle_task_success(project_id, task_id, result_url)
        return _handle_task_failure(
            task_id, ai_tool_type, "mock 未配置 result_url", ai_tool.user_id, project_id=project_id)
    # =========================

    try:
        # 1. 优先使用任务提交时记录的 implementation 创建驱动，确保状态查询与提交使用同一实现方
        driver = None
        if ai_tool.implementation:
            from config.unified_config import get_implementation_name
            impl_name = get_implementation_name(ai_tool.implementation)
            if impl_name and impl_name != 'unknown':
                driver = VideoDriverFactory.create_driver_by_implementation(impl_name)
                if driver:
                    logger.info(f"Using recorded implementation {impl_name} (id: {ai_tool.implementation}) for status check, task {task_id}")

        # 如果没有记录的 implementation 或创建失败，回退到根据任务类型创建
        if not driver:
            driver = VideoDriverFactory.create_driver_by_type(ai_tool_type, user_id=ai_tool.user_id)

        if not driver:
            # 获取详细的错误原因
            create_error = VideoDriverFactory.get_last_create_error()
            if create_error:
                error_message = create_error.get("message", f"不支持的任务类型: {ai_tool_type}")
                logger.error(f"Failed to create driver for type {ai_tool_type}: {error_message}")
            else:
                error_message = f"不支持的任务类型: {ai_tool_type}"
                logger.error(f"Unsupported driver type: {ai_tool_type}")
            # 更新任务状态为失败
            AIToolsModel.update(task_id, status=AI_TOOL_STATUS_FAILED, message=error_message, completed_time=datetime.now())
            TasksModel.update_by_task_id(task_id, status=TASK_STATUS_FAILED)
            # 释放 RunningHub 槽位（如果是 RunningHub 任务）
            if ai_tool_type in RUNNINGHUB_TASK_TYPES:
                if project_id:
                    RunningHubSlotsModel.release_slot_by_project_id(project_id)
                else:
                    task = TasksModel.get_by_task_id(task_id)
                    if task:
                        RunningHubSlotsModel.release_slot(task.id, source=RunningHubSlot.SOURCE_TASK)
                logger.info(f"Released RunningHub slot for failed driver creation in check_status, task {task_id}")
            return True  # 返回 True 表示任务已完成（失败）
        
        logger.info(f"Checking status for task {task_id} using driver: {driver.driver_name}")
        
        # 2. 调用驱动检查状态
        result = driver.check_status(project_id)

        # 记录每次状态轮询（含 running），便于排查轮询静默/调度积压
        AIToolsLogModel.log(task_id, AIToolsLogEvent.STATUS_CHECK,
                           user_id=ai_tool.user_id, project_id=project_id,
                           implementation=ai_tool.implementation,
                           message=f"状态轮询: {result.get('status')}",
                           detail={'state': result.get('status'),
                                   'progress': result.get('progress'),
                                   'message': result.get('message'),
                                   'error': result.get('error')})

        # 3. 处理状态检查结果
        status = result.get("status")
        
        if status == "SUCCESS":
            # 任务成功完成
            result_url = result.get("result_url")        
            if not result_url:
                logger.error(f"Task {task_id} succeeded but no result URL returned")
                return _handle_task_failure(task_id, ai_tool_type, "任务成功但未返回结果URL", ai_tool.user_id, project_id=project_id)
            
            logger.info(f"Task {task_id} completed successfully, result_url: {result_url}")
            AIToolsLogModel.log(task_id, AIToolsLogEvent.UPSTREAM_SUCCEEDED,
                               user_id=ai_tool.user_id, project_id=project_id,
                               implementation=ai_tool.implementation,
                               message="上游返回成功",
                               detail={'result_url': result_url})
            return await _handle_task_success(project_id, task_id, result_url)

        elif status == "FAILED":
            # 任务失败
            error = result.get("error", "任务失败")
            error_type = result.get("error_type", "SYSTEM")

            logger.error(f"Task {task_id} failed: {error} (type: {error_type})")
            AIToolsLogModel.log(task_id, AIToolsLogEvent.UPSTREAM_FAILED,
                               user_id=ai_tool.user_id, project_id=project_id,
                               implementation=ai_tool.implementation,
                               message=f"上游返回失败: {error}",
                               detail={'error': error, 'error_type': error_type})
            return _handle_task_failure(task_id, ai_tool_type, error, ai_tool.user_id, project_id=project_id)
            
        elif status == "RUNNING":
            # 任务仍在处理中
            message = result.get("message", "任务处理中...")
            logger.info(f"Task {task_id} still processing: {message}")
            return False  # 返回 False 表示仍在处理中
            
        else:
            # 未知状态
            logger.warning(f"Task {task_id} returned unknown status: {status}")
            return False  # 继续等待
        
    except Exception as e:
        # 捕获所有未预期的异常
        logger.error(f"Unexpected exception in _check_task_status_with_driver for task {task_id}: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        AIToolsLogModel.log(task_id, AIToolsLogEvent.EXCEPTION,
                           user_id=getattr(ai_tool, 'user_id', None), project_id=project_id,
                           message=f"状态检查异常: {str(e)}")

        # 不立即标记为失败，继续重试
        return False


def _check_pipeline_stage(ai_tool, stage):
    """
    检查流水线阶段状态，推进 ai_tool

    ⚠️ 两个阶段行为不同（极易混淆，修改前务必理解）：
      PARAM_PREPARE（预处理）:
        - 任何步骤失败 → 整个任务 FAILED + 退费（不允许重试）
        - 全部完成 → 应用结果，回到 PENDING 提交正式任务
      BEFORE_FINISH（失败重试）:
        - 步骤失败但仍有待处理步骤 → 继续等待（还有重试机会）
        - 所有步骤失败/无剩余 → 最终 FAILED + 退费
        - 全部完成 → implementation_retry_driver 已将 ai_tool 设回 PENDING

    Args:
        ai_tool: AITool 对象
        stage: PipelineStage 阶段名称

    Returns:
        bool: True 表示阶段已完成（ai_tool 状态已推进），False 表示仍在处理中
    """
    from task.pipeline_processor import PipelineProcessor

    all_steps = PipelineProcessor.get_all_steps(ai_tool.id, stage)
    if not all_steps:
        # 无步骤，直接回到主流程
        if stage == PipelineStage.PARAM_PREPARE:
            AIToolsModel.update(ai_tool.id, status=AI_TOOL_STATUS_PENDING)
            TasksModel.update_by_task_id(ai_tool.id, status=TASK_STATUS_QUEUED)
        return True

    has_pending_or_processing = any(
        s.status in (PipelineStepStatus.PENDING, PipelineStepStatus.PROCESSING)
        for s in all_steps
    )
    has_failed = any(
        s.status in (PipelineStepStatus.FAILED, PipelineStepStatus.TIMEOUT)
        for s in all_steps
    )

    if has_failed:
        if stage == PipelineStage.PARAM_PREPARE:
            # 预处理失败 → 整个任务失败
            failed_step = next(
                (s for s in all_steps if s.status in (PipelineStepStatus.FAILED, PipelineStepStatus.TIMEOUT)),
                None
            )
            error_msg = failed_step.error_message if failed_step else "数据预处理失败"
            AIToolsModel.update(ai_tool.id, status=AI_TOOL_STATUS_FAILED, message=f"数据预处理失败: {error_msg}", completed_time=datetime.now())
            TasksModel.update_by_task_id(ai_tool.id, status=TASK_STATUS_FAILED)
            _refund_computing_power(ai_tool, f"数据预处理失败: {error_msg}")
            logger.info(f"Task {ai_tool.id} failed: param_prepare step failed")
        elif stage == PipelineStage.BEFORE_FINISH:
            # 检查是否还有待处理的重试步骤
            remaining = PipelineProcessor.get_pending_steps(ai_tool.id, stage)
            if remaining:
                # 还有重试机会，继续等待
                return False
            # 所有重试耗尽 → 最终失败
            AIToolsModel.update(
                ai_tool.id,
                status=AI_TOOL_STATUS_FAILED,
                message=ai_tool.message or "所有重试失败",
                completed_time=datetime.now()
            )
            TasksModel.update_by_task_id(ai_tool.id, status=TASK_STATUS_FAILED)
            _refund_computing_power(ai_tool, "所有重试失败")

            # 标记当前实现方尝试为失败
            try:
                from model.implementation_attempts import ImplementationAttemptModel, ATTEMPT_STATUS_FAILED
                ImplementationAttemptModel.mark_active_attempt_completed(
                    ai_tool.id, ATTEMPT_STATUS_FAILED, error_message="所有重试失败"
                )
            except Exception as e:
                logger.warning(f"Failed to mark attempt as failed for task {ai_tool.id}: {e}")

            logger.info(f"Task {ai_tool.id} failed: all retry attempts exhausted")
        return True

    if has_pending_or_processing:
        # 还有步骤在处理中或待处理，继续等待
        return False

    # 所有步骤已完成
    if stage == PipelineStage.PARAM_PREPARE:
        # 预处理完成：应用结果并回到 PENDING
        PipelineProcessor.apply_results(ai_tool, stage)
        AIToolsModel.update(ai_tool.id, status=AI_TOOL_STATUS_PENDING)
        TasksModel.update_by_task_id(ai_tool.id, status=TASK_STATUS_QUEUED)
        logger.info(f"Task {ai_tool.id} param_prepare completed, returning to PENDING")
    elif stage == PipelineStage.BEFORE_FINISH:
        # before_finish 的 implementation_retry 驱动已将 ai_tool 设回 PENDING
        # 此处无需额外操作
        logger.info(f"Task {ai_tool.id} before_finish completed, re-submitting with new implementation")
    return True


async def _handle_task_success(project_id, task_id, media_url):
    """
    Handle successful task completion
    
    Args:
        project_id: Project ID
        task_id: Task ID
        media_url: Result media URL
    
    Returns:
        bool: True if handled successfully
    """
    try:
        # 下载并缓存媒体文件
        from utils.media_cache import download_and_cache
        
        # 判断媒体类型（根据任务类型或URL扩展名）
        media_type = "video"  # 默认为视频
        if media_url:
            ext = media_url.split('?')[0].split('.')[-1].lower()
            if ext in ['jpg', 'jpeg', 'png', 'gif', 'webp']:
                media_type = "image"
        
        # 下载并缓存，如果失败则使用原URL
        # mock 本地路径短路（download_and_cache 不识别 /upload/ 本地路径，见方案 §5.1 改动 C）
        is_local_path = media_url and media_url.startswith("/upload/")
        download_ms = None
        if is_local_path:
            final_url = media_url
            logger.info(f"[MOCK] local path, skip download_and_cache: {media_url}")
        else:
            # 派发到下载队列，解耦主循环：置 DOWNLOADING + tasks 退出主队列 + 入队。
            # M1：仅 DB 异常才 fallback 同步下载；正在处理/正常入队都直接 return True
            # （终态 COMPLETED + mark attempt + TASK_COMPLETED 日志由 worker 完成）
            from config.constant import AI_TOOL_STATUS_DOWNLOADING
            from model.download_queue import DownloadQueueModel
            AIToolsModel.update_by_project_id(project_id=project_id, status=AI_TOOL_STATUS_DOWNLOADING)
            TasksModel.update_by_task_id(task_id, status=TASK_STATUS_COMPLETED)
            AIToolsLogModel.log(task_id, AIToolsLogEvent.DOWNLOAD_STARTED,
                               project_id=project_id,
                               message="上游成功，已派发到下载队列",
                               detail={'source_url': media_url, 'media_type': media_type})
            try:
                enqueue_result = DownloadQueueModel.enqueue(
                    ai_tool_id=task_id,
                    task_id=task_id,
                    remote_url=media_url,
                    media_type=media_type,
                    project_id=project_id,
                )
                logger.info(f"Task {task_id} dispatched to download_queue (result={enqueue_result})，"
                            f"ai_tools -> DOWNLOADING，主循环立即返回")
                return True
            except Exception as dispatch_err:
                # DB 异常：fallback 同步下载，任务不丢（state 已是 DOWNLOADING，下方共用更新会改回 COMPLETED）
                logger.warning(f"dispatch to download_queue failed for task {task_id}, "
                               f"fallback to sync download: {dispatch_err}")
                download_start = datetime.now()
                cached_url = await download_and_cache(media_url, task_id, media_type)
                final_url = cached_url if cached_url else media_url
                download_ms = int((datetime.now() - download_start).total_seconds() * 1000)

        logger.info(f"Media cached: {media_url} -> {final_url}")
        AIToolsLogModel.log(task_id, AIToolsLogEvent.DOWNLOAD_COMPLETED,
                           project_id=project_id,
                           message="下载/缓存完成",
                           duration_ms=download_ms,
                           detail={'source_url': media_url, 'final_url': final_url})
        
        AIToolsModel.update_by_project_id_with_cdn_sync(
            project_id=project_id,
            result_url=final_url,
            status=AI_TOOL_STATUS_COMPLETED,
            completed_time=datetime.now()
        )
        TasksModel.update_by_task_id(task_id, status=TASK_STATUS_COMPLETED)

        # 标记当前实现方尝试为成功
        try:
            from model.implementation_attempts import ImplementationAttemptModel, ATTEMPT_STATUS_SUCCESS
            ImplementationAttemptModel.mark_active_attempt_completed(task_id, ATTEMPT_STATUS_SUCCESS)
        except Exception as e:
            logger.warning(f"Failed to mark attempt as success for task {task_id}: {e}")

        logger.info(f"Task {project_id} completed successfully")
        AIToolsLogModel.log(task_id, AIToolsLogEvent.TASK_COMPLETED,
                           project_id=project_id, status_to=AI_TOOL_STATUS_COMPLETED,
                           message="任务完成",
                           detail={'result_url': final_url})
        return True
    except Exception as db_error:
        logger.error(f"Failed to update records for success task {project_id}: {db_error}")
        return False
    finally:
        # 无论如何都释放 RunningHub 槽位
        RunningHubSlotsModel.release_slot_by_project_id(project_id)
        logger.info(f"Released RunningHub slot for project_id: {project_id}")


def _handle_task_failure(task_id, ai_tool_type, reason, user_id, project_id=None):
    """
    统一失败处理入口 - 所有任务失败最终汇聚于此

    ⚠️ 处理流程（修改时必须保持此顺序）：
      1. 企业版重试：_enterprise_failure_handler 尝试 before_finish 切换备用实现方
         → 成功则进入 WAITING_BEFORE_FINISH，由 pipeline 驱动重试
         → 失败/异常则继续走社区版流程
      2. 社区版兜底：标记 FAILED + 退还算力 + 释放 RunningHub 槽位

    ⚠️ 退费两层回退：
      优先：get_computing_power_for_task()（考虑实现方修饰符、分辨率等上下文）
      回退：TASK_COMPUTING_POWER[ai_tool_type]（旧静态配置，不含修饰符）

    Args:
        task_id: Task ID (ai_tools.id)
        ai_tool_type: AI tool type
        reason: Failure reason
        user_id: User ID for refund tracking
        project_id: Project ID (可选，提交阶段失败时为 None)

    Returns:
        bool: True if handled successfully
    """
    # 尝试企业版重试处理器（before_finish 切换备用实现方）
    reason = _normalize_failure_reason(reason)

    if _enterprise_failure_handler:
        try:
            result = _enterprise_failure_handler(task_id, ai_tool_type, reason, user_id, project_id=project_id)
            if result:
                return True  # 企业版已处理（进入重试流程）
        except Exception as e:
            logger.warning(f"Enterprise failure handler error for task {task_id}: {e}")
            # 不阻断原有失败处理流程

    # 社区版 / 企业版兜底：直接标记失败
    try:
        from model.implementation_attempts import ImplementationAttemptModel, ATTEMPT_STATUS_FAILED
        ImplementationAttemptModel.mark_active_attempt_completed(
            task_id, ATTEMPT_STATUS_FAILED, error_message=reason
        )
    except Exception as e:
        logger.warning(f"Failed to mark attempt as failed for task {task_id}: {e}")

    try:
        if project_id:
            AIToolsModel.update_by_project_id(
                project_id=project_id,
                status=AI_TOOL_STATUS_FAILED,
                message=reason,
                completed_time=datetime.now()
            )
        else:
            AIToolsModel.update(
                task_id,
                status=AI_TOOL_STATUS_FAILED,
                message=reason,
                completed_time=datetime.now()
            )
        TasksModel.update_by_task_id(task_id, status=TASK_STATUS_FAILED)
        
        # 释放 RunningHub 槽位
        is_runninghub = ai_tool_type in RUNNINGHUB_TASK_TYPES
        if is_runninghub:
            if project_id:
                RunningHubSlotsModel.release_slot_by_project_id(project_id)
            else:
                # 如果没有 project_id（提交失败），通过 task_id 释放
                task = TasksModel.get_by_task_id(task_id)
                if task:
                    RunningHubSlotsModel.release_slot(task.id, source=RunningHubSlot.SOURCE_TASK)
        
    except Exception as db_error:
        logger.error(f"Failed to update records for failed task {project_id}: {db_error}")
        return False
    
    # Refund computing power (note: auth_token not available in background task)
    try:
        # 获取 AI 工具详情
        ai_tool = AIToolsModel.get_by_id(task_id)
        if not ai_tool:
            logger.error(f"AI tool {task_id} not found for refund")
            return False

        computing_power = None

        # 优先使用新的算力计算工具（考虑修饰符）
        try:
            from utils.computing_power import (
                build_context_from_task_record,
                get_computing_power_for_task,
                get_implementation_for_user
            )
            from config.unified_config import get_implementation_name

            context = build_context_from_task_record(ai_tool)
            # 优先使用任务创建时保存的实现方，回退到用户当前偏好
            impl_id = getattr(ai_tool, 'implementation', None)
            impl_name = get_implementation_name(impl_id) if impl_id else None
            implementation = impl_name if impl_name and impl_name != 'unknown' else get_implementation_for_user(ai_tool_type, user_id)

            computing_power = get_computing_power_for_task(
                task_type=ai_tool_type,
                duration=ai_tool.duration if ai_tool else 5,
                user_id=user_id,
                implementation=implementation,
                context=context
            )

            if computing_power:
                logger.info(f"Refund with modifiers: context={context}, implementation={implementation}")
        except Exception as e:
            logger.warning(f"Modifier-aware refund failed for task {task_id}, falling back: {e}")

        # 回退：使用旧的 TASK_COMPUTING_POWER 配置
        if not computing_power:
            computing_power_config = TASK_COMPUTING_POWER.get(ai_tool_type)
            if isinstance(computing_power_config, dict):
                duration = ai_tool.duration if ai_tool else 5
                computing_power = computing_power_config.get(duration)
                if not computing_power:
                    computing_power = list(computing_power_config.values())[0]
            else:
                computing_power = computing_power_config

        if computing_power:
            transaction_id = str(uuid.uuid4())
            logger.info(f"Refunding computing power for user {user_id}")

            success, message, response_data = make_perseids_request(
                endpoint='get_auth_token_by_user_id',
                method='POST',
                data={
                    "user_id": user_id
                }
            )

            if not success:
                logger.error(f"Failed to get auth token for user {user_id}: {message}")
                return False

            auth_token = response_data['token']
            headers = {'Authorization': f'Bearer {auth_token}'}

            # 发起请求，增加算力（补回）
            success, message, response_data = make_perseids_request(
                endpoint='user/calculate_computing_power',
                method='POST',
                headers=headers,
                data={
                    "computing_power": computing_power,
                    "behavior": "increase",
                    "transaction_id": transaction_id
                }
            )
            if success:
                logger.info(f"Task {project_id} failed, computing power refund ({computing_power}) processed successfully")
            else:
                logger.error(f"Task {project_id} failed, computing power refund ({computing_power}) failed: {message}")
    except Exception as refund_error:
        logger.error(f"Failed to process refund for task {project_id}: {refund_error}")
    
    logger.info(f"Task {project_id} failed: {reason}")
    return True


async def process_generate_video(task):
    """
    单个视频/图片生成任务的状态分发入口

    ⚠️ 状态分发表（此处是任务生命周期的核心路由）：
      PENDING(0)              → _submit_new_task()    提交到驱动
      PROCESSING(1)           → _check_task_status()  轮询外部API状态
      WAITING_PARAM_PREPARE(3)→ _check_pipeline_stage(PARAM_PREPARE)  预处理流水线
      WAITING_BEFORE_FINISH(5)→ _check_pipeline_stage(BEFORE_FINISH) 失败重试流水线
      其他状态 → 警告日志（不应出现，说明状态机有bug）

    注意：此函数由 process_task_with_retry 通过 asyncio.run() 调用
    """
    try:
        logger.info(f"Processing video generation task: {task.task_id}")
        ai_tool = AIToolsModel.get_by_id(task.task_id)
        logger.info(f"AI tool {task.task_id} is {ai_tool}")

        if not ai_tool:
            logger.error(f"Failed to get AI tool record by ID {task.task_id}")
            return False

        status = ai_tool.status

        if status == AI_TOOL_STATUS_PENDING:
            return await _submit_new_task(ai_tool)
        elif status == AI_TOOL_STATUS_PROCESSING:
            return await _check_task_status(ai_tool)
        elif status == AI_TOOL_STATUS_WAITING_PARAM_PREPARE:
            return _check_pipeline_stage(ai_tool, PipelineStage.PARAM_PREPARE)
        elif status == AI_TOOL_STATUS_WAITING_BEFORE_FINISH:
            return _check_pipeline_stage(ai_tool, PipelineStage.BEFORE_FINISH)
        else:
            logger.warning(f"Unexpected status {status} for task {task.task_id}")
            return False

    except Exception as e:
        logger.error(f"Failed to process video generation task: {str(e)}")
        return False


def _check_task_expiration(task):
    """
    检查任务是否已过期
    
    Args:
        task: Task对象
    
    Returns:
        bool: True表示任务已过期
    """
    if not _is_expire_check_enabled():
        return False
    
    if not task.created_at:
        return False
    
    task_age = datetime.now() - task.created_at
    if task_age.days >= _get_task_expire_days():
        logger.warning(f"Task {task.task_id} expired (created {task_age.days} days ago)")
        return True
    
    return False


def _check_max_retry_exceeded(task):
    """
    检查任务是否超过最大重试次数
    
    Args:
        task: Task对象
    
    Returns:
        bool: True表示超过最大重试次数
    """
    if task.try_count and task.try_count >= _get_max_retry_count():
        logger.warning(f"Task {task.task_id} exceeded max retry count ({task.try_count}/{_get_max_retry_count()})")
        return True
    
    return False


def process_task_with_retry(task_type, process_func):
    """
    调度器主循环 - 每次触发时处理指定类型的所有待处理任务

    ⚠️ 处理顺序（每个 task 按此顺序检查）：
      1. 过期检查 → FAILED + 释放槽位
      2. 最大重试次数 → FAILED + 退费 + 释放槽位
      3. RunningHub 槽位控制（QUEUED 任务需先获取槽位才能提交）
      4. 状态分发：
         - QUEUED(0) → _submit_new_task() 提交
         - PROCESSING(1) → _check_task_status() 轮询状态
         - WAITING_PARAM_PREPARE/WAITING_BEFORE_FINISH → _check_pipeline_stage()
      5. 失败处理 → _handle_task_failure()

    ⚠️ RunningHub 槽位机制：
      QUEUED 状态的 RunningHub 任务必须先通过 try_acquire_slot 获取槽位
      获取失败则跳过本次调度（延迟到下次重试），避免超发请求

    ⚠️ 卡死恢复（函数末尾）：
      检测 WAITING_BEFORE_FINISH 状态但 ai_tools 已 PENDING/FAILED 的任务
      说明 pipeline 步骤完成但 tasks 表状态未同步，自动修复

    Args:
        task_type: Task type
        process_func: Specific task processing function

    Returns:
        Tuple of (has_task, process_result)
    """
    try:
        # Query tasks by type with status 0 (队列中) or 1 (处理中)
        tasks = TasksModel.list_by_type_and_status(task_type, status_list=[0, 1])
        
        if not tasks:
            logger.info(f"No pending {task_type} tasks with status 0 or 1")
            return False, False
        
        logger.info(f"Found {len(tasks)} tasks to process for type: {task_type}")
        
        # Loop through all tasks
        processed_count = 0
        success_count = 0
        delayed_count = 0
        expired_count = 0
        
        for task in tasks:
            try:
                logger.info(f"Start processing task: task_id={task.task_id}, table_id={task.id}, status={task.status}, try_count={task.try_count}")
                ai_tool = None  # 预初始化，保证下方 except 中可安全引用
                
                # 检查任务是否过期
                if _check_task_expiration(task):
                    # 标记任务为失败
                    TasksModel.update_by_task_id(task.task_id, status=TASK_STATUS_FAILED)
                    AIToolsModel.update(task.task_id, status=AI_TOOL_STATUS_FAILED, message="任务已过期", completed_time=datetime.now())

                    # 标记当前实现方尝试为失败
                    try:
                        from model.implementation_attempts import ImplementationAttemptModel, ATTEMPT_STATUS_FAILED
                        ImplementationAttemptModel.mark_active_attempt_completed(
                            task.task_id, ATTEMPT_STATUS_FAILED, error_message="任务已过期"
                        )
                    except Exception as e:
                        logger.warning(f"Failed to mark attempt as failed for expired task {task.task_id}: {e}")

                    # 释放 RunningHub 槽位
                    ai_tool = AIToolsModel.get_by_id(task.task_id)
                    if ai_tool and ai_tool.type in RUNNINGHUB_TASK_TYPES:
                        if ai_tool.project_id:
                            RunningHubSlotsModel.release_slot_by_project_id(ai_tool.project_id)
                        else:
                            RunningHubSlotsModel.release_slot(task.id, source=RunningHubSlot.SOURCE_TASK)

                    expired_count += 1
                    logger.info(f"Task {task.task_id} marked as expired")
                    continue
                
                # 检查是否超过最大重试次数
                if _check_max_retry_exceeded(task):
                    # 标记任务为失败
                    TasksModel.update_by_task_id(task.task_id, status=TASK_STATUS_FAILED)
                    AIToolsModel.update(task.task_id, status=AI_TOOL_STATUS_FAILED, message=f"超过最大重试次数({_get_max_retry_count()})", completed_time=datetime.now())

                    # 标记当前实现方尝试为失败
                    try:
                        from model.implementation_attempts import ImplementationAttemptModel, ATTEMPT_STATUS_FAILED
                        ImplementationAttemptModel.mark_active_attempt_completed(
                            task.task_id, ATTEMPT_STATUS_FAILED, error_message=f"超过最大重试次数({_get_max_retry_count()})"
                        )
                    except Exception as e:
                        logger.warning(f"Failed to mark attempt as failed for max-retry task {task.task_id}: {e}")

                    # 获取 AI 工具详情用于退还算力和释放槽位
                    ai_tool = AIToolsModel.get_by_id(task.task_id)
                    if ai_tool:
                        # 退还算力（考虑修饰符，带回退机制）
                        try:
                            computing_power = None

                            # 优先使用新的算力计算工具（考虑修饰符）
                            try:
                                from utils.computing_power import (
                                    build_context_from_task_record,
                                    get_computing_power_for_task,
                                    get_implementation_for_user
                                )
                                from config.unified_config import get_implementation_name

                                context = build_context_from_task_record(ai_tool)
                                # 优先使用任务创建时保存的实现方，回退到用户当前偏好
                                impl_id = getattr(ai_tool, 'implementation', None)
                                impl_name = get_implementation_name(impl_id) if impl_id else None
                                implementation = impl_name if impl_name and impl_name != 'unknown' else get_implementation_for_user(ai_tool.type, ai_tool.user_id)

                                computing_power = get_computing_power_for_task(
                                    task_type=ai_tool.type,
                                    duration=ai_tool.duration if ai_tool else 5,
                                    user_id=ai_tool.user_id,
                                    implementation=implementation,
                                    context=context
                                )
                            except Exception as e:
                                logger.warning(f"Modifier-aware refund failed for task {task.task_id}, falling back: {e}")

                            # 回退：使用旧的 TASK_COMPUTING_POWER 配置
                            if not computing_power:
                                computing_power = TASK_COMPUTING_POWER.get(ai_tool.type)

                            if computing_power:
                                transaction_id = str(uuid.uuid4())
                                logger.info(f"Refunding computing power for user {ai_tool.user_id}")

                                success, message, response_data = make_perseids_request(
                                    endpoint='get_auth_token_by_user_id',
                                    method='POST',
                                    data={
                                        "user_id": ai_tool.user_id
                                    }
                                )
                                if success:
                                    auth_token = response_data['token']
                                    headers = {'Authorization': f'Bearer {auth_token}'}
                                    success, message, response_data = make_perseids_request(
                                        endpoint='user/calculate_computing_power',
                                        method='POST',
                                        headers=headers,
                                        data={
                                            "computing_power": computing_power,
                                            "behavior": "increase",
                                            "transaction_id": transaction_id
                                        }
                                    )
                                    if success:
                                        logger.info(f"Task {task.task_id} exceeded max retry, refunded {computing_power} computing power")
                        except Exception as e:
                            logger.error(f"Failed to refund computing power for task {task.task_id}: {e}")
                        
                        # 释放 RunningHub 槽位
                        if ai_tool.type in RUNNINGHUB_TASK_TYPES:
                            if ai_tool.project_id:
                                RunningHubSlotsModel.release_slot_by_project_id(ai_tool.project_id)
                            else:
                                RunningHubSlotsModel.release_slot(task.id, source=RunningHubSlot.SOURCE_TASK)
                    
                    expired_count += 1
                    logger.info(f"Task {task.task_id} marked as failed due to max retry exceeded")
                    AIToolsLogModel.log(task.task_id, AIToolsLogEvent.MAX_RETRY_EXCEEDED,
                                       user_id=ai_tool.user_id, project_id=ai_tool.project_id,
                                       status_to=AI_TOOL_STATUS_FAILED,
                                       message=f"超过最大重试次数({_get_max_retry_count()})，终态失败")
                    continue
                
                # 获取 AI 工具详情
                ai_tool = AIToolsModel.get_by_id(task.task_id)
                if not ai_tool:
                    logger.error(f"AI tool {task.task_id} not found")
                    continue
                
                is_runninghub = ai_tool.type in RUNNINGHUB_TASK_TYPES

                # ⚠️ RunningHub 槽位控制：QUEUED 状态必须先获取槽位
                # 获取失败 → 延迟30秒后重试，不计入 try_count
                # 非 RunningHub 任务（如火山引擎等同步/异步 API）不经过此逻辑
                if is_runninghub and task.status == TASK_STATUS_QUEUED:
                    # 尝试获取槽位
                    slot_acquired = RunningHubSlotsModel.try_acquire_slot(
                        task_id=task.id,
                        task_type=ai_tool.type,
                        source=RunningHubSlot.SOURCE_TASK
                    )
                    
                    if not slot_acquired:
                        # 槽位已满，延迟此任务
                        delay_seconds = 30  # 延迟30秒
                        next_trigger = datetime.now() + timedelta(seconds=delay_seconds)
                        TasksModel.update_by_task_id(
                            task.task_id,
                            next_trigger=next_trigger
                        )
                        logger.info(f"Task {task.task_id} delayed by {delay_seconds}s due to slot limit, next_trigger: {next_trigger}")
                        AIToolsLogModel.log(task.task_id, AIToolsLogEvent.SLOT_DELAYED,
                                           user_id=ai_tool.user_id, project_id=ai_tool.project_id,
                                           message=f"槽位已满，延迟 {delay_seconds}s",
                                           detail={'delay_seconds': delay_seconds})
                        delayed_count += 1
                        continue  # 跳过此任务，处理下一个

                # ⚠️ 关键状态转换：QUEUED → PROCESSING
                # 此处仅更新 tasks 表，ai_tools 表的状态由 _submit_new_task / _check_task_status 内部更新
                # 两表状态必须同步，否则会导致调度器重复提交或遗漏任务
                if task.status == TASK_STATUS_QUEUED:
                    TasksModel.update_by_task_id(task.task_id, status=TASK_STATUS_PROCESSING)
                    logger.info(f"Updated task {task.task_id} status to TASK_STATUS_PROCESSING (处理中)")
                    AIToolsLogModel.log(task.task_id, AIToolsLogEvent.TASK_STARTED,
                                       user_id=ai_tool.user_id, project_id=ai_tool.project_id,
                                       implementation=ai_tool.implementation,
                                       try_count=task.try_count,
                                       status_to=AI_TOOL_STATUS_PROCESSING,
                                       message="调度器接管，开始处理",
                                       detail={'task_table_id': task.id, 'try_count': task.try_count})
                
                # Call the specific processing function
                # 检查是否为协程函数
                import asyncio
                import inspect
                if inspect.iscoroutinefunction(process_func):
                    # 异步函数，使用 asyncio.run
                    success = asyncio.run(process_func(task))
                else:
                    # 同步函数，直接调用
                    success = process_func(task)
                processed_count += 1
                
                if success:
                    logger.info(f"Task completed successfully: {task.task_id}")
                    success_count += 1
                else:
                    # Failed - increment retry count and update status to -1 (处理失败)
                    new_try_count = (task.try_count or 0) + 1
                    delay_seconds = calculate_next_retry_delay(new_try_count)
                    next_trigger = datetime.now() + timedelta(seconds=delay_seconds)
                    
                    TasksModel.update_by_task_id(
                        task.task_id,
                        try_count=new_try_count,
                        next_trigger=next_trigger
                    )
                    logger.info(f"Task failed: {task.task_id}, retry count: {new_try_count}, next trigger: {next_trigger}")
                    AIToolsLogModel.log(task.task_id, AIToolsLogEvent.RETRY_SCHEDULED,
                                       user_id=ai_tool.user_id if ai_tool else None,
                                       project_id=ai_tool.project_id if ai_tool else None,
                                       try_count=new_try_count,
                                       message=f"处理失败，安排重试（第 {new_try_count} 次）",
                                       detail={'try_count': new_try_count,
                                               'delay_seconds': delay_seconds,
                                               'next_trigger': next_trigger.isoformat() if next_trigger else None})

            except Exception as e:
                logger.error(f"Error processing task {task.task_id}: {str(e)}")
                import traceback
                logger.error(traceback.format_exc())
                new_try_count = (task.try_count or 0) + 1
                delay_seconds = calculate_next_retry_delay(new_try_count)
                next_trigger = datetime.now() + timedelta(seconds=delay_seconds)
                TasksModel.update_by_task_id(
                    task.task_id,
                    try_count=new_try_count,
                    next_trigger=next_trigger,
                )
                logger.info(
                    f"Task exception backoff: {task.task_id}, retry count: {new_try_count}, next trigger: {next_trigger}"
                )
                AIToolsLogModel.log(task.task_id, AIToolsLogEvent.EXCEPTION,
                                   user_id=ai_tool.user_id if ai_tool else None,
                                   project_id=ai_tool.project_id if ai_tool else None,
                                   try_count=new_try_count,
                                   message=f"处理异常退避: {str(e)}",
                                   detail={'try_count': new_try_count,
                                           'delay_seconds': delay_seconds,
                                           'next_trigger': next_trigger.isoformat() if next_trigger else None})
                
        logger.info(f"Summary: processed={processed_count}, succeeded={success_count}, delayed={delayed_count}, expired={expired_count}")

        # ⚠️ 卡死恢复机制：修复 tasks 表与 ai_tools 表状态不同步的问题
        # 场景：pipeline before_finish 步骤完成后，implementation_retry_driver 更新了 ai_tools.status
        #       但 tasks.status 仍停留在 WAITING_BEFORE_FINISH(5)，导致任务永远不被调度
        # 修复：检测到 ai_tools 已 PENDING 但 tasks 仍 WAITING → 同步 tasks 为 QUEUED
        try:
            stuck_tasks = TasksModel.list_by_type_and_status(
                task_type, status_list=[TASK_STATUS_WAITING_BEFORE_FINISH]
            )
            if stuck_tasks:
                for st in stuck_tasks:
                    st_ai_tool = AIToolsModel.get_by_id(st.task_id)
                    if not st_ai_tool:
                        continue
                    if st_ai_tool.status == AI_TOOL_STATUS_PENDING:
                        # pipeline 步骤已完成但 tasks.status 未更新 → 修复
                        TasksModel.update_by_task_id(st.task_id, status=TASK_STATUS_QUEUED)
                        logger.info(f"Recovered stuck task {st.task_id}: tasks.status 5->0")
                    elif st_ai_tool.status == AI_TOOL_STATUS_FAILED:
                        # 任务已失败但 tasks.status 未同步
                        TasksModel.update_by_task_id(st.task_id, status=TASK_STATUS_FAILED)
                        logger.info(f"Recovered stuck task {st.task_id}: tasks.status 5->FAILED")
        except Exception as e:
            logger.warning(f"Recovery check error: {e}")

        return processed_count > 0, success_count > 0
            
    except Exception as e:
        logger.error(f"Task processing error: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return False, False


def generate_video_task(app=None):
    """Video generation task entry point"""
    process_task_with_retry(TASK_TYPE_GENERATE_VIDEO, process_generate_video)
