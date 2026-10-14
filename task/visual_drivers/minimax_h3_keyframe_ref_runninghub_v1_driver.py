"""
MiniMax H3 首帧参考混合生视频 RunningHub v1

webapp_id: 2108549232725680129
画布保持参考模式（image_mode=multi_reference）。本驱动按优化前原文里的
「图N是首帧 / 图N是尾帧」把 reference_images 填进三个固定槽：

  - node 137 image  Picture 1：精确起始关键帧；没有首帧时是第一张参考，或空
  - node 156 image  Picture 2：角色/场景/道具参考，永远不是尾帧
  - node 187 image  Picture 3：精确结束关键帧；没有尾帧时是第二张参考，或空
  - node 157 audio  Audio 1，fieldValue 取 fileName；没有音频时为字符串 None
  - node 188 audio  Audio 2，同样取 fileName；没有第二路时为字符串 None
  - 原文（优化前）无引号台词时两路音频都不上传、都填 None：音色参考必须绑台词
  - node 138 value  优化后的提示词
  - node 132 value  时长（秒）
  - node 115 aspect_ratio / megapixels

空槽 fieldValue 为 ""。这个应用没有 ImpactSwitch，也没有参考视频节点。
"""
from typing import Any, Dict, List

from config.constant import MAX_VOICE_REFERENCE_AUDIOS
from config.unified_config import TaskTypeId
from task.pipeline_drivers.h3_prompt_optimize_util import (
    assign_h3_keyframe_ref_pictures,
    has_quoted_dialogue,
    h3_slot_source_prompt,
)
from .minimax_h3_reference_runninghub_v1_driver import (
    _VOICE_NOTE_LINE_RE,
    ASPECT_RATIO_FIELD_DATA,
    MinimaxH3ReferenceRunninghubV1Driver,
)

_WEBAPP_ID = "2108549232725680129"
_PICTURE_NODE_IDS = ("137", "156", "187")
_AUDIO_NODE_IDS = ("157", "188")
_EMPTY_AUDIO_FIELD_VALUE = "None"


class MinimaxH3KeyframeRefRunninghubV1Driver(MinimaxH3ReferenceRunninghubV1Driver):
    """RunningHub「全能参考+首帧+音频」应用。提交和查询复用参考生视频驱动。"""

    def __init__(self):
        super().__init__()
        self.driver_name = "minimax_h3_keyframe_ref_runninghub_v1"
        self.driver_type = TaskTypeId.MINIMAX_H3_KEYFRAME_REF_TO_VIDEO
        self._webapp_id = _WEBAPP_ID

    async def build_create_request(self, ai_tool) -> Dict[str, Any]:
        image_urls = [str(item).strip() for item in self.get_reference_images(ai_tool) if str(item or "").strip()]
        extra_config = self._parse_extra_config(ai_tool)
        slot_prompt = h3_slot_source_prompt(extra_config, getattr(ai_tool, "prompt", None) or "")
        plan = assign_h3_keyframe_ref_pictures(image_urls, slot_prompt)
        pictures = [plan["picture_1"], plan["picture_2"], plan["picture_3"]]
        if not any(pictures):
            raise ValueError("MiniMax H3 首帧参考生视频至少需要一张图片")

        unused = plan.get("unused_urls") or []
        if unused:
            self.logger.warning(
                "MiniMax H3 首帧参考混合模型图片槽已满，已忽略 %s 张参考图",
                len(unused),
            )

        uploaded_by_url: Dict[str, str] = {}
        for index, image_url in enumerate(pictures):
            if not image_url or image_url in uploaded_by_url:
                continue
            uploaded_by_url[image_url] = await self._upload_image_to_runninghub(
                image_url,
                f"Picture{index + 1}",
            )

        # 无对白镜头不上传音频（必须在上传循环之前清空，否则文件已传完、音频槽
        # 仍会拿到 fileName）：<Audio N> 只有绑到要说新台词的角色身上才是音色参考，
        # 没有目标台词时连上的语音会被当成成片声音。台词有无优先取优化步骤的
        # LLM 语义判断（extra_config.h3_prompt_optimize.has_dialogue，能识别无引号
        # 台词、排除引号店名），旧任务/优化禁用/回退原文时回退正则引号判断。
        audios = self._split_reference_paths(getattr(ai_tool, "audio_path", None))
        if len(audios) > MAX_VOICE_REFERENCE_AUDIOS:
            self.logger.warning(
                "MiniMax H3 首帧参考混合模型最多保留 %s 个参考音频，已忽略其余 %s 个",
                MAX_VOICE_REFERENCE_AUDIOS,
                len(audios) - MAX_VOICE_REFERENCE_AUDIOS,
            )
            audios = audios[:MAX_VOICE_REFERENCE_AUDIOS]
        _prompt_meta = extra_config.get("h3_prompt_optimize") if isinstance(extra_config, dict) else None
        _llm_flag = _prompt_meta.get("has_dialogue") if isinstance(_prompt_meta, dict) else None
        _has_dialogue = _llm_flag if isinstance(_llm_flag, bool) else has_quoted_dialogue(slot_prompt)
        if audios and not _has_dialogue:
            self.logger.info(
                "MiniMax H3 首帧参考混合模型镜头无对白（has_dialogue=%s），跳过 %s 个参考音频，音频槽填 None",
                _llm_flag,
                len(audios),
            )
            audios = []
        videos = self._split_reference_paths(getattr(ai_tool, "video_path", None))
        if videos:
            self.logger.warning(
                "MiniMax H3 首帧参考混合模型不支持参考视频，已忽略 %s 个",
                len(videos),
            )

        uploaded_audios: List[str] = []
        for index, audio in enumerate(audios):
            uploaded_audios.append(await self._upload_reference_media(audio, f"参考音频{index + 1}"))

        prompt_meta = extra_config.get("h3_prompt_optimize") if isinstance(extra_config, dict) else None
        if isinstance(prompt_meta, dict) and prompt_meta.get("optimized_prompt"):
            prompt_text = str(prompt_meta.get("optimized_prompt") or "")
        else:
            prompt_text = getattr(ai_tool, "prompt", None) or ""
        # 无对白且文本中残留音色说明句时剥掉（优化回退原文/旧任务兜底）：
        # 「角色说话时请保持相同音色」会诱导视频模型让角色发声。
        if not _has_dialogue and "参考音频说明" in prompt_text:
            prompt_text = _VOICE_NOTE_LINE_RE.sub("", prompt_text).strip()
            self.logger.info("MiniMax H3 首帧参考混合模型无对白，已剥除提示词中的参考音频说明句")

        duration = getattr(ai_tool, "duration", None) or 5
        ratio = getattr(ai_tool, "ratio", None) or "9:16"
        aspect_ratio_value = self._ratio_to_aspect_ratio_value(ratio)
        megapixels_value = self._get_megapixels(extra_config)
        roles = plan.get("roles") or {}

        node_info_list: List[Dict[str, Any]] = []
        for index, node_id in enumerate(_PICTURE_NODE_IDS):
            source = pictures[index]
            role = roles.get(f"picture_{index + 1}") or "empty"
            node_info_list.append({
                "nodeId": node_id,
                "fieldName": "image",
                "fieldValue": uploaded_by_url.get(source, "") if source else "",
                "description": f"Picture{index + 1} {role}",
            })
        for index, node_id in enumerate(_AUDIO_NODE_IDS):
            node_info_list.append({
                "nodeId": node_id,
                "fieldName": "audio",
                "fieldValue": uploaded_audios[index] if index < len(uploaded_audios) else _EMPTY_AUDIO_FIELD_VALUE,
                "description": f"<Audio {index + 1}>",
            })
        node_info_list.append({
            "nodeId": "138",
            "fieldName": "value",
            "fieldValue": prompt_text,
            "description": "提示词",
        })
        node_info_list.append({
            "nodeId": "132",
            "fieldName": "value",
            "fieldValue": str(duration),
            "description": "视频秒数",
        })
        node_info_list.append({
            "nodeId": "115",
            "fieldName": "aspect_ratio",
            "fieldData": ASPECT_RATIO_FIELD_DATA,
            "fieldValue": aspect_ratio_value,
            "description": "长宽比",
        })
        node_info_list.append({
            "nodeId": "115",
            "fieldName": "megapixels",
            "fieldValue": megapixels_value,
            "description": "视频分辨率",
        })

        self.logger.info(
            "MiniMax H3 首帧参考请求: duration=%ss ratio=%s megapixels=%s roles=%s audios=%s prompt_len=%s",
            duration,
            ratio,
            megapixels_value,
            roles,
            len(uploaded_audios),
            len(prompt_text),
        )
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
