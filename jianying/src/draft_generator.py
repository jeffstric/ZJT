"""
草稿生成模块
"""

import os
import json
import shutil
from datetime import datetime
from typing import Dict, Any, List, Optional


class DraftGenerator:
    """草稿生成器"""
    
    def __init__(self, library):
        """
        初始化草稿生成器
        
        Args:
            library: JianyingMultiTrackLibrary实例
        """
        self.library = library
    
    def generate_draft(self, copy_media_files: bool = True, media_source_dir: Optional[str] = None) -> str:
        """
        生成草稿文件
        
        Args:
            copy_media_files: 是否复制媒体文件到草稿目录
            media_source_dir: 媒体文件源目录
            
        Returns:
            草稿文件夹路径
        """
        draft_path = os.path.join(self.library.output_dir, self.library.draft_name)
        os.makedirs(draft_path, exist_ok=True)
        
        # 创建Resources/local目录结构
        resources_path = os.path.join(draft_path, "Resources")
        local_resources_path = os.path.join(resources_path, "local")
        os.makedirs(local_resources_path, exist_ok=True)
        
        # 写入 draft_content.json
        content_path = os.path.join(draft_path, "draft_content.json")
        with open(content_path, "w", encoding="utf-8") as f:
            json.dump(self._build_draft_content(), f, ensure_ascii=False, indent=2)

        # 写入 draft_meta_info.json
        meta_path = os.path.join(draft_path, "draft_meta_info.json")
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(self._build_draft_meta_info(), f, ensure_ascii=False, indent=2)

        # 复制媒体文件
        if copy_media_files:
            self._copy_media_files(local_resources_path, media_source_dir)

        print(f"✅ 多轨道草稿已生成: {draft_path}")
        print(f"   - 视频轨道数: {len(self.library.video_tracks)}")
        print(f"   - 音频轨道数: {len(self.library.audio_tracks)}")
        print(f"   - 总时长: {self.library.total_duration / 1000000:.2f} 秒")
        
        return draft_path
    
    def _copy_media_files(self, local_resources_path: str, media_source_dir: Optional[str]):
        """复制媒体文件到草稿目录"""
        copied_files = []
        
        # 收集所有需要复制的文件
        all_files = set()
        for track in self.library.video_tracks + self.library.audio_tracks:
            for segment in track.segments:
                all_files.add(segment.file_path)
        
        for file_path in all_files:
            filename = os.path.basename(file_path)
            
            # 确定源文件路径
            if os.path.isabs(file_path) and os.path.exists(file_path):
                src_path = file_path
            elif media_source_dir and os.path.exists(os.path.join(media_source_dir, filename)):
                src_path = os.path.join(media_source_dir, filename)
            elif os.path.exists(filename):
                src_path = filename
            else:
                print(f"⚠️ 警告: 找不到文件 {file_path}")
                continue
            
            # 复制文件到Resources/local目录
            dst_path = os.path.join(local_resources_path, filename)
            try:
                shutil.copy2(src_path, dst_path)
                copied_files.append(filename)
            except Exception as e:
                print(f"⚠️ 复制文件失败 {filename}: {e}")

        if copied_files:
            print(f"✅ 已复制 {len(copied_files)} 个媒体文件")
    
    def _build_draft_content(self) -> Dict[str, Any]:
        """构建草稿内容"""
        return {
            "canvas_config": {
                "height": self.library.height,
                "ratio": "original",
                "width": self.library.width
            },
            "color_space": 0,
            "config": {
                "adjust_max_index": 1,
                "attachment_info": [],
                "combination_max_index": 1,
                "export_range": None,
                "extract_audio_last_index": 1,
                "lyrics_recognition_id": "",
                "lyrics_sync": True,
                "lyrics_taskinfo": [],
                "maintrack_adsorb": True,
                "material_save_mode": 0,
                "multi_language_current": "none",
                "multi_language_list": [],
                "multi_language_main": "none",
                "multi_language_mode": "none",
                "original_sound_last_index": 1,
                "record_audio_last_index": 1,
                "sticker_max_index": 1,
                "subtitle_keywords_config": None,
                "subtitle_recognition_id": "",
                "subtitle_sync": True,
                "subtitle_taskinfo": [],
                "system_font_list": [],
                "video_mute": False,
                "zoom_info_params": None
            },
            "cover": None,
            "create_time": int(datetime.now().timestamp() * 1000000),
            "duration": self.library.total_duration,
            "extra_info": None,
            "fps": float(self.library.fps),
            "free_render_index_mode_on": False,
            "group_container": None,
            "id": self.library.draft_id,
            "keyframe_graph_list": [],
            "keyframes": {
                "adjusts": [],
                "audios": [],
                "effects": [],
                "filters": [],
                "handwrites": [],
                "stickers": [],
                "texts": [],
                "videos": []
            },
            "last_modified_platform": {
                "app_id": 3704,
                "app_source": "lv",
                "app_version": "5.9.0",
                "os": "windows"
            },
            "materials": self._build_materials(),
            "mutable_config": None,
            "name": "",
            "new_version": "110.0.0",
            "relationships": [],
            "render_index_track_mode_on": False,
            "retouch_cover": None,
            "source": "default",
            "static_cover_image_path": "",
            "time_marks": None,
            "tracks": self._build_tracks(),
            "update_time": int(datetime.now().timestamp() * 1000000),
            "version": 360000
        }
    
    def _build_materials(self) -> Dict[str, Any]:
        """构建素材信息"""
        return {
            "ai_translates": [],
            "audio_balances": [],
            "audio_effects": [],
            "audio_fades": [],
            "audio_track_indexes": [],
            "audios": list(self.library.audio_materials.values()),
            "beats": [],
            "canvases": [],
            "chromas": [],
            "color_curves": [],
            "digital_humans": [],
            "drafts": [],
            "effects": [],
            "flowers": [],
            "green_screens": [],
            "handwrites": [],
            "hsl": [],
            "images": [],
            "log_color_wheels": [],
            "loudnesses": [],
            "manual_deformations": [],
            "masks": [],
            "material_animations": [],
            "material_colors": [],
            "multi_language_refs": [],
            "placeholders": [],
            "plugin_effects": [],
            "primary_color_wheels": [],
            "realtime_denoises": [],
            "shapes": [],
            "smart_crops": [],
            "smart_relights": [],
            "sound_channel_mappings": [],
            "speeds": self.library.speeds,
            "stickers": [],
            "tail_leaders": [],
            "text_templates": [],
            "texts": [],
            "time_marks": [],
            "transitions": [],
            "video_effects": [],
            "video_trackings": [],
            "videos": list(self.library.video_materials.values()),
            "vocal_beautifys": [],
            "vocal_separations": []
        }
    
    def _build_tracks(self) -> List[Dict[str, Any]]:
        """构建轨道信息"""
        tracks = []
        
        # 添加视频轨道
        for track in self.library.video_tracks:
            track_data = {
                "attribute": 0,
                "flag": 0,
                "id": track.track_id,
                "is_default_name": track.is_default_name,
                "name": track.name,
                "segments": self._build_video_segments(track),
                "type": "video"
            }
            tracks.append(track_data)
        
        # 添加音频轨道
        for track in self.library.audio_tracks:
            track_data = {
                "attribute": 0,
                "flag": 0,
                "id": track.track_id,
                "is_default_name": track.is_default_name,
                "name": track.name,
                "segments": self._build_audio_segments(track),
                "type": "audio"
            }
            tracks.append(track_data)
        
        return tracks
    
    def _build_video_segments(self, track) -> List[Dict[str, Any]]:
        """构建视频片段信息"""
        segments = []
        
        for segment in track.segments:
            # 找到对应的素材ID
            material_id = None
            filename = os.path.basename(segment.file_path)
            
            for mat_id, material in self.library.video_materials.items():
                if material.get('material_name') == filename:
                    material_id = mat_id
                    break
            
            if not material_id:
                continue
            
            # 创建速度配置
            speed_id = self.library._create_speed(segment.speed)
            
            segment_data = {
                "cartoon": False,
                "clip": {
                    "alpha": 1.0,
                    "flip": {"horizontal": False, "vertical": False},
                    "rotation": 0.0,
                    "scale": {"x": 1.0, "y": 1.0},
                    "transform": {"x": 0.0, "y": 0.0}
                },
                "common_keyframes": [],
                "enable_adjust": True,
                "enable_color_curves": True,
                "enable_color_match_reference": False,
                "enable_color_wheels": True,
                "enable_lut": True,
                "enable_smart_color_match": False,
                "extra_material_refs": [],
                "group_id": "",
                "hdr_settings": None,
                "id": self.library._generate_id("SEGMENT_"),
                "intensifies_audio": False,
                "is_placeholder": False,
                "is_tone_modify": False,
                "keyframe_refs": [],
                "last_nonzero_volume": 1.0,
                "material_id": material_id,
                "render_index": 4000000,
                "reverse": False,
                "source_timerange": {
                    "duration": segment.duration,
                    "start": segment.source_start
                },
                "speed": segment.speed,
                "target_timerange": {
                    "duration": int(segment.duration / segment.speed),
                    "start": segment.start_time
                },
                "template_id": "",
                "template_scene": "default",
                "track_attribute": 0,
                "track_render_index": 0,
                "uniform_scale": None,
                "visible": segment.visible,
                "volume": segment.volume
            }
            segments.append(segment_data)
        
        return segments
    
    def _build_audio_segments(self, track) -> List[Dict[str, Any]]:
        """构建音频片段信息"""
        segments = []
        
        for segment in track.segments:
            # 找到对应的素材ID
            material_id = None
            filename = os.path.basename(segment.file_path)
            
            for mat_id, material in self.library.audio_materials.items():
                if material.get('name') == filename:
                    material_id = mat_id
                    break
            
            if not material_id:
                continue
            
            # 创建速度配置
            speed_id = self.library._create_speed(segment.speed)
            
            segment_data = {
                "cartoon": False,
                "clip": None,
                "common_keyframes": [],
                "enable_adjust": True,
                "enable_color_curves": True,
                "enable_color_match_reference": False,
                "enable_color_wheels": True,
                "enable_lut": True,
                "enable_smart_color_match": False,
                "extra_material_refs": [],
                "group_id": "",
                "hdr_settings": None,
                "id": self.library._generate_id("SEGMENT_"),
                "intensifies_audio": False,
                "is_placeholder": False,
                "is_tone_modify": False,
                "keyframe_refs": [],
                "last_nonzero_volume": segment.volume,
                "material_id": material_id,
                "render_index": 4000000,
                "reverse": False,
                "source_timerange": {
                    "duration": segment.duration,
                    "start": segment.source_start
                },
                "speed": segment.speed,
                "target_timerange": {
                    "duration": int(segment.duration / segment.speed),
                    "start": segment.start_time
                },
                "template_id": "",
                "template_scene": "default",
                "track_attribute": 0,
                "track_render_index": 0,
                "uniform_scale": None,
                "visible": True,
                "volume": segment.volume
            }
            segments.append(segment_data)
        
        return segments
    
    def _build_draft_meta_info(self) -> Dict[str, Any]:
        """构建草稿元信息"""
        
        return {
            "create_time": int(datetime.now().timestamp()),
            "draft_fold_path": "",
            "draft_id": self.library.draft_id,
            "draft_name": self.library.draft_name,
            "draft_removable_storage_device": "",
            "draft_root_path": "",
            "duration": self.library.total_duration,
            "height": self.library.height,
            "width": self.library.width,
            "fps": float(self.library.fps),
            "import_time": int(datetime.now().timestamp()),
            "import_time_ms": int(datetime.now().timestamp() * 1000),
            "last_modified_time": int(datetime.now().timestamp()),
            "materials": self.library.meta_materials,
            "platform": {
                "app_id": 3704,
                "app_source": "lv",
                "app_version": "5.9.0",
                "os": "windows"
            },
            "resolution": f"{self.library.width}*{self.library.height}",
            "source": "default",
            "tm_draft_create": int(datetime.now().timestamp()),
            "tm_draft_modified": int(datetime.now().timestamp()),
            "version": "110.0.0"
        }
