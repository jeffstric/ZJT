"""
MiniMax H3 数字人 RunningHub v1 版本驱动实现

支持图片 + 音频 + 提示词生成数字人视频。
webapp_id: 2087200340012785665

参数注入节点 nodeId：
  - 提示词        → nodeId 214 fieldName=value  (文本描述动作)
  - 音频          → nodeId 215 fieldName=audio
  - 图片          → nodeId 209 fieldName=image
  - 视频时长(秒)  → nodeId 212 fieldName=value
  - 最长边长度    → nodeId 213 fieldName=value
  - 开始说话秒数  → nodeId 229 fieldName=value
"""
import asyncio
import json
import os
import subprocess
import time
from typing import Dict, Any, Optional
import traceback
from .base_video_driver import BaseVideoDriver
from config.config_util import get_config, get_dynamic_config_value
from config.unified_config import TaskTypeId
from utils.sentry_util import SentryUtil, AlertLevel
from utils.file_storage import RunningHubFileStorage
from utils.runninghub_error import is_upstream_congested_error
from .exceptions import ImageExpiredError


# 支持的最长边选项
SUPPORTED_MAX_EDGES = {720, 1280, 1920}
DEFAULT_MAX_EDGE = 1280
DEFAULT_DURATION = 10
DEFAULT_START_SECOND = 0
# 10s 为生产稳定档；11-15s 在 webapp 默认实例显存边界上随机 OOM，不放开
SUPPORTED_DURATIONS = {4, 5, 6, 7, 8, 9, 10}

# 分段编排（extra_config.dh_segments 存在时走 sync_mode 全流水线：
# 逐段生成→下载→ffmpeg 拼接→本地落盘，见 docs/marketing_agent_digital_human_duration_routing_plan.md）
SEGMENT_POLL_INTERVAL_SECONDS = 20
SEGMENT_POLL_MAX_TRIES = 60  # 单段轮询上限 20 分钟
SEGMENT_SUBMIT_RETRY = 1     # 段提交/生成失败后的自动重试次数
# 15s 段在默认实例显存边界上偶发 OOM，整条流水线失败后按此稳定段长降档重切重跑
SEGMENT_FALLBACK_MAX_SEG = 10


class _SegmentedPipelineError(Exception):
    """分段流水线内部失败（携带用户可读原因），由降档/失败出口统一处理。"""


class _SegmentedCongestedError(Exception):
    """上游拥堵（api queue limit / TASK_QUEUE_MAXED）：应回队延迟重试而非降档重跑。"""


class DigitalHumanMinimaxH3RunninghubV1Driver(BaseVideoDriver):
    """
    MiniMax H3 数字人 RunningHub v1 版本驱动
    支持图片 + 音频 + 提示词生成数字人视频
    """

    def __init__(self):
        super().__init__(
            driver_name="digital_human_minimax_h3_runninghub_v1",
            driver_type=TaskTypeId.DIGITAL_HUMAN_MINIMAX_H3,
        )

        self._api_key = get_dynamic_config_value("runninghub", "api_key", default="")
        self._host = get_dynamic_config_value("runninghub", "host", default="")
        # 2026-10-16 更换为锁镜头版工作流（fixed camera，见
        # docs/marketing_agent_digital_human_duration_routing_plan.md）：
        # 214 提示词须为英文 integrated_multimodal_description 格式
        # （由 prepare 侧 VL 生成，经 confirm 透传）
        self._webapp_id = "2111473047642398722"  # MiniMax H3 数字人 webapp ID（锁镜头版）
        self._timeout = get_dynamic_config_value("timeout", "request_timeout", default=30)

        self._is_local = get_dynamic_config_value("server", "is_local", default=False)
        self._config = get_config()

        self._storage = RunningHubFileStorage(
            host=self._host,
            api_key=self._api_key,
            config=self._config,
            logger=self.logger,
        )

        self._validate_required({
            "RunningHub API Key": self._api_key,
            "RunningHub Host": self._host,
        })

    def _send_alert(self, alert_type: str, message: str, context: Optional[Dict[str, Any]] = None):
        SentryUtil.send_alert(
            alert_type=alert_type,
            message=message,
            level=AlertLevel.ERROR,
            context=context,
        )

    def _validate_submit_response(self, result: Any) -> tuple[bool, Optional[str]]:
        if not isinstance(result, dict):
            return False, f"响应不是字典类型，实际类型: {type(result)}"

        if "taskId" not in result:
            return False, f"响应缺少 'taskId' 字段，实际字段: {list(result.keys())}"

        if "status" not in result:
            return False, f"响应缺少 'status' 字段，实际字段: {list(result.keys())}"

        return True, None

    def _parse_extra_config(self, ai_tool) -> Dict[str, Any]:
        if not ai_tool.extra_config:
            return {}
        try:
            config = (
                ai_tool.extra_config
                if isinstance(ai_tool.extra_config, dict)
                else json.loads(ai_tool.extra_config)
            )
            return config if isinstance(config, dict) else {}
        except (json.JSONDecodeError, TypeError):
            self.logger.warning(f"无法解析 extra_config: {ai_tool.extra_config}")
            return {}

    def _resolve_duration(self, ai_tool) -> int:
        duration = ai_tool.duration or DEFAULT_DURATION
        try:
            duration = int(duration)
        except (TypeError, ValueError):
            duration = DEFAULT_DURATION
        if duration not in SUPPORTED_DURATIONS:
            self.logger.warning(f"不支持的时长 {duration}，回退到默认 {DEFAULT_DURATION}")
            return DEFAULT_DURATION
        return duration

    def _resolve_max_edge(self, extra_config: Dict[str, Any]) -> int:
        # 优先 max_edge；否则从 resolution（480P/720P/1080P）映射
        raw = extra_config.get("max_edge")
        if raw is None or raw == "":
            resolution = str(
                extra_config.get("resolution")
                or extra_config.get("video_resolution")
                or ""
            ).strip().upper()
            res_map = {"480P": 720, "720P": 1280, "1080P": 1920}
            raw = res_map.get(resolution, DEFAULT_MAX_EDGE)
        try:
            max_edge = int(raw)
        except (TypeError, ValueError):
            max_edge = DEFAULT_MAX_EDGE
        if max_edge not in SUPPORTED_MAX_EDGES:
            self.logger.warning(f"不支持的最长边 {max_edge}，回退到默认 {DEFAULT_MAX_EDGE}")
            return DEFAULT_MAX_EDGE
        return max_edge

    def _resolve_start_second(self, extra_config: Dict[str, Any]) -> int:
        raw = extra_config.get("start_second", DEFAULT_START_SECOND)
        try:
            start_second = int(raw)
        except (TypeError, ValueError):
            start_second = DEFAULT_START_SECOND
        if start_second < 0:
            start_second = DEFAULT_START_SECOND
        return start_second

    async def build_create_request(self, ai_tool) -> Dict[str, Any]:
        """
        构建创建 MiniMax H3 数字人任务的完整请求参数

        节点映射：
        - 提示词 → nodeId 214 (value)
        - 音频   → nodeId 215 (audio)
        - 图片   → nodeId 209 (image)
        - 时长   → nodeId 212 (value)
        - 最长边 → nodeId 213 (value)
        - 开始说话秒数 → nodeId 229 (value)
        """
        extra_config = self._parse_extra_config(ai_tool)
        duration = self._resolve_duration(ai_tool)
        max_edge = self._resolve_max_edge(extra_config)
        start_second = self._resolve_start_second(extra_config)

        audio_url = ai_tool.audio_path or ai_tool.message or ""
        if audio_url:
            self.logger.info(f"准备上传音频到 RunningHub: {audio_url}")
            result = await self._storage.upload_file("", audio_url)
            if result.success:
                audio_url = result.key if result.key else result.url
                self.logger.info(f"音频上传完成，使用 fileName: {audio_url}")
            else:
                raise RuntimeError(f"音频上传到 RunningHub 失败: {result.error}")

        image_path = ai_tool.image_path
        if image_path:
            if "," in image_path:
                image_path = image_path.split(",")[0].strip()
            self.logger.info(f"准备上传图片到 RunningHub 图床: {image_path}")
            result = await self._storage.upload_file("", image_path)
            if result.success:
                image_path = result.url if result.url else result.key
                self.logger.info(f"图片上传完成，使用 URL: {image_path}")
            else:
                raise RuntimeError(f"图片上传到 RunningHub 失败: {result.error}")

        node_info_list = [
            {
                "nodeId": "214",
                "fieldName": "value",
                "fieldValue": ai_tool.prompt or "",
                "description": "value",
            },
            {
                "nodeId": "215",
                "fieldName": "audio",
                "fieldValue": audio_url,
                "description": "audio",
            },
            {
                "nodeId": "209",
                "fieldName": "image",
                "fieldValue": image_path,
                "description": "image",
            },
            {
                "nodeId": "212",
                "fieldName": "value",
                "fieldValue": str(duration),
                "description": "value",
            },
            {
                "nodeId": "213",
                "fieldName": "value",
                "fieldValue": str(max_edge),
                "description": "value",
            },
            {
                "nodeId": "229",
                "fieldName": "value",
                "fieldValue": str(start_second),
                "description": "value",
            },
        ]

        return {
            "url": f"{self._host}/openapi/v2/run/ai-app/{self._webapp_id}",
            "method": "POST",
            "json": {
                "nodeInfoList": node_info_list,
                "instanceType": "default",
                "usePersonalQueue": "false",
            },
            "headers": {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._api_key}",
            },
        }

    def build_check_query(self, project_id: str) -> Dict[str, Any]:
        return {
            "url": f"{self._host}/task/openapi/status",
            "method": "POST",
            "json": {
                "apiKey": self._api_key,
                "taskId": project_id,
            },
            "headers": {
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        }

    def _upload_to_runninghub_sync(self, path_or_url: str):
        """同步上传到 RunningHub（分段编排运行于 to_thread，不能 await 异步 upload_file）。

        复用 storage 的本地映射（/upload/、localhost URL → 本地路径）与
        _sync_upload_file；纯外链先下载到临时文件。
        """
        local_file = self._storage._resolve_to_local_file(path_or_url)
        if not local_file or not os.path.exists(local_file):
            import requests as _requests
            resp = _requests.get(path_or_url, timeout=120)
            resp.raise_for_status()
            local_file = os.path.join('temp', f"dhseg_download_{time.strftime('%H%M%S%f')}.bin")
            os.makedirs(os.path.dirname(local_file), exist_ok=True)
            with open(local_file, 'wb') as f:
                f.write(resp.content)
        return self._storage._sync_upload_file(local_file)

    def _submit_segmented_sync(self, ai_tool, segment_paths: list, extra_config: Dict[str, Any]) -> Dict[str, Any]:
        """分段拼接入口（同步，运行于 to_thread）。

        首选按端点切好的段（confirm 侧静音切分，段长=常量 15s）跑全流水线；
        段长 >10s 时处于 webapp 默认实例显存边界（偶发 torch.OutOfMemoryError），
        全流水线失败后自动降档按 10s 稳定档用完整音频重切重跑一次。
        """
        try:
            return self._run_segment_pipeline(ai_tool, segment_paths, extra_config)
        except _SegmentedCongestedError as e:
            # 上游拥堵：与单段路径同款可重试结果（调度器回队，不降档、不退款）
            self.logger.warning(f"[分段] 上游拥堵，交回调度器延迟重试: {e}")
            return {
                "success": False,
                "error": "上游服务繁忙，正在自动排队重试…",
                "error_type": "USER",
                "retry": True,
                "retry_reason": "UPSTREAM_CONGESTED",
            }
        except _SegmentedPipelineError as e:
            durations = extra_config.get("dh_segment_durations") or []
            if durations and max(durations) > 10:
                self.logger.warning(
                    f"[分段] 段长 {max(durations)}s 流水线失败（{e}），自动降档 10s 稳定档重切重跑")
                try:
                    fallback = self._run_segment_pipeline(ai_tool, None, extra_config,
                                                          fallback_max_seg=10)
                except _SegmentedPipelineError as e2:
                    return self._segmented_failure(f"降档 10s 重跑仍失败: {e2}", retried=True)
                fallback["fallback_used"] = True
                return fallback
            return self._segmented_failure(str(e), retried=True)

    def _run_segment_pipeline(self, ai_tool, segment_paths: Optional[list],
                              extra_config: Dict[str, Any],
                              fallback_max_seg: Optional[int] = None) -> Dict[str, Any]:
        """单次分段全流水线：逐段提交 → 并行轮询 → 下载 → ffmpeg concat → 落盘。

        Args:
            segment_paths: 端点切好的段音频路径列表；为 None 时降档模式——
                用 ai_tool.audio_path 完整音频按 fallback_max_seg 重切。
        Raises:
            _SegmentedPipelineError: 任一环节最终失败。
        """
        from utils.audio_duration_util import _get_ffmpeg_path

        motion_prompt = (ai_tool.prompt or "").strip() or "角色面向镜头说话，固定镜头。"
        max_edge = self._resolve_max_edge(extra_config)

        if segment_paths:
            segment_durations = extra_config.get("dh_segment_durations") or []
            segments = [
                {"path": p,
                 "duration": int(segment_durations[i]) if i < len(segment_durations) else DEFAULT_DURATION}
                for i, p in enumerate(segment_paths)
            ]
            tag = "seg"
        else:
            # 降档模式：完整音频按稳定段长重切
            from utils.audio_duration_util import get_audio_duration_seconds
            from utils.audio_segment_util import split_audio_into_segments

            audio_local = self._storage._resolve_to_local_file(ai_tool.audio_path or "")
            if not audio_local or not os.path.exists(audio_local):
                raise _SegmentedPipelineError("降档重切需要完整驱动音频，但无法映射到本地文件")
            total = get_audio_duration_seconds(audio_local)
            if not total:
                raise _SegmentedPipelineError("降档重切时音频时长探测失败")
            seg_dir = os.path.join('temp', f"h3seg_fallback_{ai_tool.id}")
            plan = split_audio_into_segments(audio_local, float(total), seg_dir,
                                             max_seg=fallback_max_seg or 10)
            segments = plan["segments"]
            self.logger.info(f"[分段] 降档重切完成: {len(segments)} 段 cuts={plan['cuts']}")

        image_path = ai_tool.image_path
        if image_path:
            if "," in image_path:
                image_path = image_path.split(",")[0].strip()
            self.logger.info(f"[分段] 上传角色图（各段共用首帧）: {image_path}")
            result = self._upload_to_runninghub_sync(image_path)
            if not result.success:
                raise _SegmentedPipelineError(f"角色图上传到 RunningHub 失败: {result.error}")
            image_url = result.url if result.url else result.key
        else:
            raise _SegmentedPipelineError("分段任务缺少角色图")

        # 1. 逐段提交（失败自动重试一次；偶发 LoadImageFromUrl 拉图失败重试即可恢复）
        task_ids: list = []
        for idx, seg in enumerate(segments, start=1):
            audio_key = self._upload_segment_audio(seg["path"])
            if not audio_key:
                raise _SegmentedPipelineError(f"第 {idx} 段音频上传 RunningHub 失败")
            last_err = ""
            for attempt in range(1 + SEGMENT_SUBMIT_RETRY):
                task_id, last_err = self._submit_one_segment(
                    image_url, audio_key, seg["duration"], motion_prompt, max_edge)
                if task_id:
                    task_ids.append(task_id)
                    self.logger.info(f"[分段] seg_{idx} 提交成功 taskId={task_id} "
                                     f"duration={seg['duration']} attempt={attempt}")
                    break
                self.logger.warning(f"[分段] seg_{idx} 第 {attempt + 1} 次提交失败: {last_err}")
                time.sleep(5)
            else:
                raise _SegmentedPipelineError(f"第 {idx} 段任务提交失败: {last_err}")

        # 2. 并行等待各段完成（轮询；FAILED 段自动重提一次）
        seg_files: list = []
        for idx, task_id in enumerate(task_ids, start=1):
            seg_file = os.path.join('temp', f"h3seg_{ai_tool.id}_seg_{idx}.mp4")
            ok, err = self._wait_and_download_segment(task_id, seg_file, f"seg_{idx}")
            if not ok:
                # 段生成失败：重提一次（换新任务），仍失败则整体失败
                self.logger.warning(f"[分段] seg_{idx} 生成失败（{err}），自动重提一次")
                audio_key = self._upload_segment_audio(segments[idx - 1]["path"])
                if not audio_key:
                    raise _SegmentedPipelineError(f"第 {idx} 段重试时音频上传失败")
                new_task_id, last_err = self._submit_one_segment(
                    image_url, audio_key, segments[idx - 1]["duration"],
                    motion_prompt, max_edge)
                if not new_task_id:
                    raise _SegmentedPipelineError(f"第 {idx} 段生成失败且重提失败: {last_err}")
                ok, err = self._wait_and_download_segment(new_task_id, seg_file, f"seg_{idx}r")
                if not ok:
                    raise _SegmentedPipelineError(f"第 {idx} 段重试后仍失败: {err}")
            seg_files.append(seg_file)

        # 3. 拼接（重编码保证时间戳/参数一致；webapp 每次运行的输出分辨率随机
        #    （实测同参数出现过 960×1280 与 512×704），先统一缩放到首段尺寸再 concat）
        probe = subprocess.run(
            ['bin/ffmpeg/ffprobe', '-v', 'error', '-select_streams', 'v:0',
             '-show_entries', 'stream=width,height', '-of', 'json', seg_files[0]],
            capture_output=True, text=True, timeout=60)
        vstream = (json.loads(probe.stdout or '{}').get('streams') or [{}])[0]
        out_w = int(vstream.get('width') or 960)
        out_h = int(vstream.get('height') or 1280)
        out_h += out_h % 2
        date_str = time.strftime('%Y-%m-%d')
        out_dir = os.path.join('upload', 'cache', date_str)
        os.makedirs(out_dir, exist_ok=True)
        out_name = f"{ai_tool.id}_h3seg_{time.strftime('%H%M%S')}.mp4"
        out_path = os.path.join(out_dir, out_name)
        inputs = []
        for f in seg_files:
            inputs += ['-i', f]
        scale_chain = ';'.join(
            f'[{i}:v]scale={out_w}:{out_h},format=yuv420p[v{i}]'
            for i in range(len(seg_files)))
        concat_filter = scale_chain + ';' \
            + ''.join(f'[v{i}][{i}:a]' for i in range(len(seg_files))) \
            + f'concat=n={len(seg_files)}:v=1:a=1[v][a]'
        r = subprocess.run(
            [_get_ffmpeg_path(), '-y', '-loglevel', 'error', *inputs,
             '-filter_complex', concat_filter, '-map', '[v]', '-map', '[a]',
             '-c:v', 'libx264', '-preset', 'fast', '-crf', '18', '-c:a', 'aac', out_path],
            capture_output=True, text=True, timeout=600)
        if r.returncode != 0 or not os.path.isfile(out_path):
            raise _SegmentedPipelineError(f"分段视频拼接失败: {r.stderr[-300:]}")
        self.logger.info(f"[分段] 拼接完成: {out_path} ({out_w}x{out_h})")

        # 4. sync_mode 返回本地路径（visual_task 检测 /upload/ 前缀直接落库）
        return {
            "sync_mode": True,
            "result_url": f"/upload/cache/{date_str}/{out_name}",
            "success": True,
        }

    def _segmented_failure(self, message: str, retried: bool = False) -> Dict[str, Any]:
        """分段流水线的标准失败返回（sync 模式无 retry 重试意义，直接失败并退款走原机制）。"""
        self.logger.error(f"[分段] 流水线失败: {message}")
        return {
            "success": False,
            "error": f"分段数字人生成失败: {message}" + ("（已自动重试）" if retried else ""),
            "error_type": "SYSTEM",
            "retry": False,
        }

    def _upload_segment_audio(self, seg_path: str) -> Optional[str]:
        result = self._upload_to_runninghub_sync(seg_path)
        if not result.success:
            self.logger.warning(f"[分段] 段音频上传失败: {result.error}")
            return None
        return result.key if result.key else result.url

    def _submit_one_segment(self, image_url: str, audio_key: str, duration: int,
                            motion_prompt: str, max_edge: int) -> tuple:
        """提交单段任务，返回 (taskId, error_message)。"""
        node_info_list = [
            {"nodeId": "214", "fieldName": "value", "fieldValue": motion_prompt, "description": "value"},
            {"nodeId": "215", "fieldName": "audio", "fieldValue": audio_key, "description": "audio"},
            {"nodeId": "209", "fieldName": "image", "fieldValue": image_url, "description": "image"},
            {"nodeId": "212", "fieldName": "value", "fieldValue": str(duration), "description": "value"},
            {"nodeId": "213", "fieldName": "value", "fieldValue": str(max_edge), "description": "value"},
            {"nodeId": "229", "fieldName": "value", "fieldValue": "0", "description": "value"},
        ]
        result = self._request(
            url=f"{self._host}/openapi/v2/run/ai-app/{self._webapp_id}",
            method="POST",
            json={"nodeInfoList": node_info_list,
                  "instanceType": "default",
                  "usePersonalQueue": "false"},
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {self._api_key}"},
        )
        error_code = result.get("errorCode", "")
        error_message = result.get("errorMessage", "")
        if error_code or error_message:
            if is_upstream_congested_error(error_code):
                # 上游拥堵：交由调度器释放槽位回队延迟重试，不走降档重跑
                raise _SegmentedCongestedError(f"{error_message or error_code}")
            return None, f"{error_message or error_code}"
        task_id = result.get("taskId")
        if not task_id:
            return None, "响应未返回 taskId"
        return task_id, ""

    def _poll_segment_status(self, task_id: str) -> tuple:
        """查询单段状态，返回 (SUCCESS/FAILED/RUNNING, 错误信息)。"""
        result = self._request(**self.build_check_query(task_id))
        if result.get("code") != 0:
            # 业务错误（鉴权/参数类）：立即失败，不空转到轮询超时
            return "FAILED", result.get("msg") or "查询状态失败"
        data = result.get("data")
        status = data.get("status") if isinstance(data, dict) else data
        if status == "SUCCESS":
            return "SUCCESS", ""
        if status == "FAILED":
            failed_reason = ""
            if isinstance(data, dict):
                fr = data.get("failedReason") or {}
                failed_reason = str(fr.get("exception_type") or "")
            return "FAILED", failed_reason or "上游任务失败"
        return "RUNNING", ""

    def _fetch_segment_video_url(self, task_id: str) -> Optional[str]:
        result = self._request(
            url=f"{self._host}/task/openapi/outputs",
            method="POST",
            json={"apiKey": self._api_key, "taskId": task_id},
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        for item in (result.get("data") or []):
            if item.get("fileType") == "mp4" and item.get("fileUrl"):
                return item["fileUrl"]
        return None

    def _wait_and_download_segment(self, task_id: str, out_path: str, tag: str) -> tuple:
        """轮询单段到终态并下载 mp4，返回 (ok, error_message)。"""
        import requests as _requests
        video_url = None
        for _ in range(SEGMENT_POLL_MAX_TRIES):
            time.sleep(SEGMENT_POLL_INTERVAL_SECONDS)
            status, poll_err = self._poll_segment_status(task_id)
            self.logger.info(f"[分段] {tag} taskId={task_id} status={status}")
            if status == "SUCCESS":
                video_url = self._fetch_segment_video_url(task_id)
                if not video_url:
                    return False, "任务成功但 outputs 无 mp4"
                break
            if status == "FAILED":
                return False, poll_err or "上游任务失败"
        else:
            return False, "轮询超时"
        os.makedirs(os.path.dirname(out_path) or '.', exist_ok=True)
        resp = _requests.get(video_url, timeout=300)
        if resp.status_code != 200 or len(resp.content) < 1024:
            return False, f"下载成片失败 HTTP {resp.status_code}"
        with open(out_path, 'wb') as f:
            f.write(resp.content)
        self.logger.info(f"[分段] {tag} 下载完成 {len(resp.content)} bytes -> {out_path}")
        return True, ""

    async def submit_task(self, ai_tool) -> Dict[str, Any]:
        try:
            prompt_preview = (ai_tool.prompt or "")[:50]

            # 分段拼接模式（口播 >15s）：extra_config.dh_segments 由端点写入，
            # 在本调用内完成「逐段提交→轮询→下载→拼接」全流水线，
            # 以 sync_mode 返回本地成片路径（visual_task 直接落库，无需轮询）。
            extra_config = self._parse_extra_config(ai_tool)
            segment_paths = extra_config.get("dh_segments") or []
            if segment_paths:
                self.logger.info(
                    f"Segmented MiniMax H3 pipeline: text='{prompt_preview}...', "
                    f"segments={len(segment_paths)}, "
                    f"durations={extra_config.get('dh_segment_durations')}"
                )
                return await asyncio.to_thread(
                    self._submit_segmented_sync, ai_tool, segment_paths, extra_config
                )

            self.logger.info(
                f"Submitting MiniMax H3 digital human task: text='{prompt_preview}...', "
                f"duration={ai_tool.duration}"
            )

            request_params = await self.build_create_request(ai_tool)

            try:
                result = self._request(**request_params)
            except (ConnectionError, TimeoutError) as network_error:
                self.logger.warning(f"Network error during task submission: {str(network_error)}")
                return {
                    "success": False,
                    "error": "网络连接异常，请稍后重试",
                    "error_type": "USER",
                    "retry": True,
                }

            self.logger.info(f"API response: {result}")

            is_valid, validation_error = self._validate_submit_response(result)
            if not is_valid:
                self._send_alert(
                    alert_type="INVALID_RESPONSE_FORMAT",
                    message=f"submit_task 响应格式错误: {validation_error}",
                    context={
                        "api": "create_digital_human_minimax_h3",
                        "response": result,
                        "ai_tool_id": ai_tool.id,
                    },
                )
                return {
                    "success": False,
                    "error": "服务异常，请联系技术支持",
                    "error_type": "SYSTEM",
                    "error_detail": f"API响应格式错误: {validation_error}",
                    "retry": False,
                }

            error_code = result.get("errorCode", "")
            error_message = result.get("errorMessage", "")
            if error_code or error_message:
                if is_upstream_congested_error(error_code):
                    self.logger.warning(
                        f"Digital Human(MiniMax H3) upstream congested, will auto-retry: "
                        f"errorCode={error_code}, errorMessage={error_message}"
                    )
                    return self._build_upstream_congested_result()
                self.logger.warning(
                    f"API returned error: errorCode={error_code}, errorMessage={error_message}"
                )
                return {
                    "success": False,
                    "error": f"任务提交失败: {error_message or error_code}",
                    "error_type": "USER",
                    "retry": False,
                }

            task_id = result.get("taskId")
            if not task_id:
                return {
                    "success": False,
                    "error": "服务异常，请联系技术支持",
                    "error_type": "SYSTEM",
                    "error_detail": "API未返回任务ID",
                    "retry": False,
                }

            return {
                "success": True,
                "project_id": task_id,
            }

        except ImageExpiredError as e:
            self.logger.warning(f"输入图片已过期: {str(e)}")
            return {
                "success": False,
                "error": str(e),
                "error_type": "USER",
                "retry": False,
            }

        except Exception as e:
            self.logger.error(f"Unexpected exception in submit_task: {str(e)}")
            self.logger.error(traceback.format_exc())

            self._send_alert(
                alert_type="UNEXPECTED_EXCEPTION",
                message=f"submit_task 发生未预期异常: {str(e)}",
                context={
                    "exception": str(e),
                    "traceback": traceback.format_exc(),
                    "ai_tool_id": getattr(ai_tool, "id", None),
                },
            )

            return {
                "success": False,
                "error": "服务异常，请联系技术支持",
                "error_type": "SYSTEM",
                "error_detail": f"未预期异常: {str(e)}",
                "retry": False,
            }

    def check_status(self, project_id: str) -> Dict[str, Any]:
        try:
            self.logger.info(f"Checking task status: project_id={project_id}")

            status_params = self.build_check_query(project_id)

            try:
                status_result = self._request(**status_params)
            except (ConnectionError, TimeoutError) as network_error:
                self.logger.warning(f"Network error during status check: {str(network_error)}")
                return {
                    "status": "RUNNING",
                    "message": "网络连接异常，稍后将重试",
                }

            if not isinstance(status_result, dict) or "code" not in status_result:
                self._send_alert(
                    alert_type="INVALID_RESPONSE_FORMAT",
                    message="status API 响应格式异常",
                    context={
                        "api": "check_status",
                        "response": status_result,
                        "project_id": project_id,
                    },
                )
                return {
                    "status": "FAILED",
                    "error": "服务异常，请联系技术支持",
                    "error_type": "SYSTEM",
                    "error_detail": "RunningHub 响应格式错误",
                }

            if status_result.get("code") != 0:
                error_msg = status_result.get("msg", "查询状态失败")
                return {
                    "status": "FAILED",
                    "error": error_msg,
                    "error_type": "USER",
                }

            task_status = status_result.get("data", "")

            if task_status == "SUCCESS":
                outputs_params = {
                    "url": f"{self._host}/task/openapi/outputs",
                    "method": "POST",
                    "json": {
                        "apiKey": self._api_key,
                        "taskId": project_id,
                    },
                    "headers": {
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                    },
                }

                try:
                    outputs_result = self._request(**outputs_params)
                except Exception as e:
                    self.logger.error(f"Failed to get outputs: {str(e)}")
                    return {
                        "status": "FAILED",
                        "error": "获取结果失败",
                        "error_type": "SYSTEM",
                        "error_detail": f"获取输出失败: {str(e)}",
                    }

                result_url = None
                if outputs_result.get("code") == 0:
                    outputs_data = outputs_result.get("data", [])
                    self.logger.info(f"Outputs data: {outputs_data}")
                    if outputs_data:
                        for item in outputs_data:
                            file_type = item.get("fileType")
                            file_url = item.get("fileUrl")
                            if file_type == "mp4" and file_url:
                                result_url = file_url
                                break

                return {
                    "status": "SUCCESS",
                    "result_url": result_url,
                }
            elif task_status == "FAILED":
                return {
                    "status": "FAILED",
                    "error": "任务失败",
                    "error_type": "USER",
                }
            else:
                return {
                    "status": "RUNNING",
                    "message": "任务处理中...",
                }

        except Exception as e:
            self.logger.error(f"Unexpected exception in check_status: {str(e)}")
            self.logger.error(traceback.format_exc())

            self._send_alert(
                alert_type="UNEXPECTED_EXCEPTION",
                message=f"check_status 发生未预期异常: {str(e)}",
                context={
                    "exception": str(e),
                    "traceback": traceback.format_exc(),
                    "project_id": project_id,
                },
            )

            return {
                "status": "FAILED",
                "error": "服务异常，请联系技术支持",
                "error_type": "SYSTEM",
                "error_detail": f"未预期异常: {str(e)}",
            }
