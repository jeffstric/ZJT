"""
基础使用示例
"""

import os
import sys

# 添加src目录到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from core import JianyingMultiTrackLibrary
from utils import seconds_to_microseconds
from config import Config


def main():
    """基础示例"""
    print("剪映多轨道草稿生成库 - 基础示例")
    print("=" * 50)
    
    # 检查ffmpeg可用性
    config = Config()
    from media_utils import MediaUtils
    media_utils = MediaUtils(config)
    
    ffmpeg_available, ffprobe_available = media_utils.check_ffmpeg_availability()
    print(f"FFmpeg 可用: {ffmpeg_available}")
    print(f"FFprobe 可用: {ffprobe_available}")
    
    if not ffprobe_available:
        print("⚠️ 警告: ffprobe不可用，将使用回退机制")
        print("建议安装FFmpeg或在config.json中配置正确的路径")
    
    # 创建库实例
    library = JianyingMultiTrackLibrary(
        draft_name="基础示例项目",
        output_dir="./output",
        config=config
    )
    
    # 创建轨道
    video_track = library.create_video_track("主视频")
    audio_track = library.create_audio_track("背景音乐")
    
    print(f"\n创建了视频轨道: {video_track}")
    print(f"创建了音频轨道: {audio_track}")
    
    # 模拟添加媒体文件（这里使用虚拟文件路径）
    # 在实际使用中，请替换为真实的媒体文件路径
    
    # 添加视频片段（自动获取时长）
    try:
        video_material = library.add_video_to_track(
            track_id=video_track,
            file_path="sample_video.mp4",  # 替换为真实路径
            start_time=0
            # duration参数省略，将自动获取文件时长
        )
        print(f"✅ 添加视频素材: {video_material}")
    except Exception as e:
        print(f"⚠️ 添加视频失败: {e}")
    
    # 添加音频片段（自动获取时长）
    try:
        audio_material = library.add_audio_to_track(
            track_id=audio_track,
            file_path="sample_audio.mp3",  # 替换为真实路径
            start_time=0,
            volume=0.5
            # duration参数省略，将自动获取文件时长
        )
        print(f"✅ 添加音频素材: {audio_material}")
    except Exception as e:
        print(f"⚠️ 添加音频失败: {e}")
    
    # 生成草稿
    try:
        from draft_generator import DraftGenerator
        generator = DraftGenerator(library)
        draft_path = generator.generate_draft(
            copy_media_files=True,
            media_source_dir="./"
        )
        print(f"\n🎉 草稿生成成功: {draft_path}")
    except Exception as e:
        print(f"❌ 草稿生成失败: {e}")


if __name__ == "__main__":
    main()
