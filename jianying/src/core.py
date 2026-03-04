"""
剪映多轨道草稿生成库核心模块
"""

import os
import json
import uuid
import shutil
from datetime import datetime
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional

from jianying_config import JianyingConfig
from media_utils import MediaUtils


@dataclass
class MediaSegment:
    """媒体片段"""
    file_path: str
    start_time: int
    duration: int
    source_start: int = 0
    volume: float = 1.0
    speed: float = 1.0
    visible: bool = True


@dataclass
class Track:
    """轨道"""
    track_id: str
    track_type: str
    name: str = ""
    segments: List[MediaSegment] = field(default_factory=list)
    is_default_name: bool = True


class JianyingMultiTrackLibrary:
    """剪映多轨道草稿生成库"""

    def __init__(self, draft_name: str, output_dir: str, config: Optional[JianyingConfig] = None,
                 material_path_prefix: Optional[str] = None,
                 width: int = 1920, height: int = 1080, fps: int = 30):
        """
        初始化多轨道草稿生成器
        
        Args:
            draft_name: 草稿名称
            output_dir: 输出目录
            config: 配置对象
            width: 画布宽度
            height: 画布高度
            fps: 帧率
        """
        self.config = config or JianyingConfig()
        self.media_utils = MediaUtils(self.config)
        
        self.draft_name = draft_name
        self.output_dir = output_dir
        self.material_path_prefix = material_path_prefix
        self.width = width or 1920  # 默认1920x1080分辨率
        self.height = height or 1080
        self.fps = fps or 30  # 默认30fps
        self.draft_id = str(uuid.uuid4()).upper()

        # 轨道管理
        self.video_tracks: List[Track] = []
        self.audio_tracks: List[Track] = []
        
        # 素材管理
        self.video_materials: Dict[str, Dict[str, Any]] = {}
        self.audio_materials: Dict[str, Dict[str, Any]] = {}
        self.speeds: List[Dict[str, Any]] = []
        self.meta_materials: List[Dict[str, Any]] = []
        
        # 时间轴管理
        self.total_duration = 0

    def _generate_id(self, prefix: str = "") -> str:
        """生成唯一ID"""
        return f"{prefix}{uuid.uuid4().hex.upper()[:16]}"

    def _build_material_path(self, filename: str) -> str:
        """构建素材在草稿中的目标路径（写入draft_content中）"""
        if self.material_path_prefix:
            base = self.material_path_prefix.rstrip("\\/")
            return f"{base}\\{self.draft_name}\\Resources\\local\\{filename}"
        local_path = os.path.join(self.output_dir, self.draft_name, "Resources", "local", filename)
        return local_path.replace('/', '\\')

    def _create_speed(self, speed: float = 1.0) -> str:
        """创建速度配置并返回ID"""
        speed_id = self._generate_id()
        self.speeds.append({
            "curve_speed": None,
            "id": speed_id,
            "mode": 0,
            "speed": speed,
            "type": "speed"
        })
        return speed_id

    def get_media_duration(self, file_path: str) -> int:
        """
        获取媒体文件时长（微秒）
        
        Args:
            file_path: 媒体文件路径
            
        Returns:
            时长（微秒）
        """
        return self.media_utils.get_media_duration(file_path)

    def create_video_track(self, name: str = "") -> str:
        """创建新的视频轨道"""
        track_id = self._generate_id("VIDEO_TRACK_")
        track = Track(
            track_id=track_id,
            track_type="video",
            name=name,
            is_default_name=(name == "")
        )
        self.video_tracks.append(track)
        return track_id

    def create_audio_track(self, name: str = "") -> str:
        """创建新的音频轨道"""
        track_id = self._generate_id("AUDIO_TRACK_")
        track = Track(
            track_id=track_id,
            track_type="audio",
            name=name,
            is_default_name=(name == "")
        )
        self.audio_tracks.append(track)
        return track_id

    def add_video_to_track(self, track_id: str, file_path: str, start_time: int, 
                          duration: int = None, source_start: int = 0, width: int = None, 
                          height: int = None, speed: float = 1.0, volume: float = 1.0, 
                          is_placeholder: bool = False) -> str:
        """向指定视频轨道添加视频片段"""
        # 查找轨道
        track = None
        for t in self.video_tracks:
            if t.track_id == track_id:
                track = t
                break
        
        if not track:
            raise ValueError(f"视频轨道 {track_id} 不存在")

        # 如果没有指定时长，自动获取
        if duration is None:
            duration = self.get_media_duration(file_path)

        # 创建素材
        material_id = self._generate_id("VIDEO_MAT_")
        filename = os.path.basename(file_path)
        # 素材路径使用用户提供的剪影目录前缀
        material_path = self._build_material_path(filename)

        # 使用配置中的默认值
        video_width = width or self.width
        video_height = height or self.height

        # 添加到素材库
        if material_id not in self.video_materials:
            self.video_materials[material_id] = {
                "audio_fade": None,
                "category_id": "",
                "category_name": "local",
                "check_flag": 63487,
                "crop": {
                    "lower_left_x": 0.0, "lower_left_y": 1.0,
                    "lower_right_x": 1.0, "lower_right_y": 1.0,
                    "upper_left_x": 0.0, "upper_left_y": 0.0,
                    "upper_right_x": 1.0, "upper_right_y": 0.0
                },
                "crop_ratio": "free",
                "crop_scale": 1.0,
                "duration": duration,
                "height": video_height,
                "id": material_id,
                "local_material_id": "",
                "material_id": material_id,
                "material_name": filename,
                "media_path": "",
                "path": material_path,
                "type": "video",
                "width": video_width
            }

            # 添加元数据
            self.meta_materials.append({
                "create_time": int(datetime.now().timestamp()),
                "duration": duration,
                "extra_info": "",
                "file_Path": material_path,
                "height": video_height,
                "id": material_id,
                "import_time": int(datetime.now().timestamp()),
                "import_time_ms": int(datetime.now().timestamp() * 1000),
                "item_source": 0,
                "md5": "",
                "metetype": "video",
                "roughcut_time_range": None,
                "sub_time_range": None,
                "width": video_width
            })

        # 创建片段
        segment = MediaSegment(
            file_path=file_path,
            start_time=start_time,
            duration=duration,
            source_start=source_start,
            volume=volume if not is_placeholder else 0.0,  # 占位符静音
            speed=speed,
            visible=not is_placeholder  # 占位符不可见
        )
        track.segments.append(segment)

        # 更新总时长
        end_time = start_time + duration
        if end_time > self.total_duration:
            self.total_duration = end_time

        return material_id

    def add_audio_to_track(self, track_id: str, file_path: str, start_time: int,
                          duration: int = None, source_start: int = 0, volume: float = 1.0,
                          speed: float = 1.0) -> str:
        """向指定音频轨道添加音频片段"""
        # 查找轨道
        track = None
        for t in self.audio_tracks:
            if t.track_id == track_id:
                track = t
                break
        
        if not track:
            raise ValueError(f"音频轨道 {track_id} 不存在")

        # 如果没有指定时长，自动获取
        if duration is None:
            duration = self.get_media_duration(file_path)

        # 创建素材
        material_id = self._generate_id("AUDIO_MAT_")
        filename = os.path.basename(file_path)
        # 素材路径使用用户提供的剪影目录前缀
        material_path = self._build_material_path(filename)

        # 添加到素材库
        if material_id not in self.audio_materials:
            self.audio_materials[material_id] = {
                "app_id": 0,
                "category_id": "",
                "category_name": "local",
                "check_flag": 1,
                "duration": duration,
                "effect_id": "",
                "formula_id": "",
                "id": material_id,
                "intensifies_path": "",
                "local_material_id": "",
                "music_id": "",
                "name": filename,
                "path": material_path,
                "request_id": "",
                "resource_id": "",
                "source_platform": 0,
                "team_id": "",
                "text_id": "",
                "tone_category_id": "",
                "tone_category_name": "",
                "tone_effect_id": "",
                "tone_effect_name": "",
                "tone_speaker": "",
                "tone_type": "",
                "type": "extract_music",
                "video_id": "",
                "wave_points": []
            }

            # 添加元数据
            self.meta_materials.append({
                "create_time": int(datetime.now().timestamp()),
                "duration": duration,
                "extra_info": "",
                "file_Path": material_path,
                "height": 0,
                "id": material_id,
                "import_time": int(datetime.now().timestamp()),
                "import_time_ms": int(datetime.now().timestamp() * 1000),
                "item_source": 0,
                "md5": "",
                "metetype": "music",
                "roughcut_time_range": None,
                "sub_time_range": None,
                "width": 0
            })

        # 创建片段
        segment = MediaSegment(
            file_path=file_path,
            start_time=start_time,
            duration=duration,
            source_start=source_start,
            volume=volume,
            speed=speed
        )
        track.segments.append(segment)

        # 更新总时长
        end_time = start_time + duration
        if end_time > self.total_duration:
            self.total_duration = end_time

        return material_id
