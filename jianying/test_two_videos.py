"""
测试脚本：使用两个视频文件生成草稿
- 第一个视频：G:\code\jianying_project\assert\2.mp4 (5秒片段，从0开始)
- 第二个视频：G:\code\jianying_project\assert\1.mp4 (完整视频)
"""

import os
import sys

# 添加src目录到路径
src_path = os.path.join(os.path.dirname(__file__), 'src')
sys.path.insert(0, src_path)

# 导入模块
import core
import utils
import config
import draft_generator
import media_utils

JianyingMultiTrackLibrary = core.JianyingMultiTrackLibrary
seconds_to_microseconds = utils.seconds_to_microseconds
Config = config.Config
DraftGenerator = draft_generator.DraftGenerator
MediaUtils = media_utils.MediaUtils


def main():
    """测试两个视频文件的草稿生成"""
    print("剪映多轨道草稿生成库 - 两视频测试")
    print("=" * 50)
    
    # 定义视频文件路径
    video1_path = r"G:\code\jianying_project\assert\2.mp4"  # 5秒片段
    video2_path = r"G:\code\jianying_project\assert\1.mp4"  # 完整视频
    
    # 验证文件是否存在
    print("🔍 验证媒体文件...")
    if not os.path.exists(video1_path):
        print(f"❌ 第一个视频文件不存在: {video1_path}")
        return
    else:
        print(f"✅ 找到第一个视频: {video1_path}")
    
    if not os.path.exists(video2_path):
        print(f"❌ 第二个视频文件不存在: {video2_path}")
        return
    else:
        print(f"✅ 找到第二个视频: {video2_path}")
    
    # 创建配置和库实例
    config = Config()
    library = JianyingMultiTrackLibrary(
        draft_name="两视频测试项目",
        output_dir="./output",
        config=config
    )
    
    print(f"\n📋 创建草稿项目: {library.draft_name}")
    print(f"📁 输出目录: {library.output_dir}")
    
    # 检查ffprobe可用性
    from media_utils import MediaUtils
    media_utils = MediaUtils(config)
    ffmpeg_available, ffprobe_available = media_utils.check_ffmpeg_availability()
    print(f"\n🔧 FFmpeg 可用: {ffmpeg_available}")
    print(f"🔧 FFprobe 可用: {ffprobe_available}")
    
    if not ffprobe_available:
        print("⚠️ 警告: ffprobe不可用，可能无法获取准确的媒体时长")
    
    # 创建单个视频轨道
    video_track = library.create_video_track("主视频轨道")
    print(f"\n🎬 创建视频轨道: {video_track}")
    
    try:
        # 添加第一个视频片段 (2.mp4, 5秒)
        print(f"\n📹 添加第一个视频片段...")
        print(f"   文件: {os.path.basename(video1_path)}")
        print(f"   时长: 5秒")
        print(f"   开始时间: 0秒")
        
        video1_material = library.add_video_to_track(
            track_id=video_track,
            file_path=video1_path,
            start_time=0,  # 从0开始
            duration=seconds_to_microseconds(5)  # 5秒片段
        )
        print(f"✅ 第一个视频片段添加成功: {video1_material}")
        
        # 获取第二个视频的完整时长
        print(f"\n📹 获取第二个视频的时长...")
        video2_duration = library.get_media_duration(video2_path)
        video2_duration_seconds = video2_duration / 1000000
        print(f"   检测到时长: {video2_duration_seconds:.2f}秒")
        
        # 添加第二个视频片段 (1.mp4, 完整)
        print(f"\n📹 添加第二个视频片段...")
        print(f"   文件: {os.path.basename(video2_path)}")
        print(f"   时长: {video2_duration_seconds:.2f}秒 (完整)")
        print(f"   开始时间: 5秒 (接在第一个视频后)")
        
        video2_material = library.add_video_to_track(
            track_id=video_track,
            file_path=video2_path,
            start_time=seconds_to_microseconds(5),  # 从5秒开始，接在第一个视频后
            duration=video2_duration  # 使用完整时长
        )
        print(f"✅ 第二个视频片段添加成功: {video2_material}")
        
        # 显示项目信息
        print(f"\n📊 项目统计:")
        print(f"   视频轨道数: 1")
        print(f"   视频片段数: 2")
        print(f"   总时长: {library.total_duration / 1000000:.2f}秒")
        
        # 生成草稿
        print(f"\n🚀 开始生成草稿...")
        generator = DraftGenerator(library)
        draft_path = generator.generate_draft(
            copy_media_files=True,
            media_source_dir=r"G:\code\jianying_project\assert"
        )
        
        print(f"\n🎉 草稿生成成功!")
        print(f"📁 草稿路径: {draft_path}")
        
        # 检查生成的文件
        print(f"\n📋 生成的文件:")
        for root, dirs, files in os.walk(draft_path):
            level = root.replace(draft_path, '').count(os.sep)
            indent = '  ' * level
            print(f"{indent}{os.path.basename(root)}/")
            subindent = '  ' * (level + 1)
            for file in files:
                file_path = os.path.join(root, file)
                try:
                    file_size = os.path.getsize(file_path)
                    if file_size > 1024 * 1024:
                        size_str = f"{file_size / (1024 * 1024):.1f}MB"
                    elif file_size > 1024:
                        size_str = f"{file_size / 1024:.1f}KB"
                    else:
                        size_str = f"{file_size}B"
                    print(f"{subindent}{file} ({size_str})")
                except OSError:
                    print(f"{subindent}{file} (无法获取大小)")
        
        print(f"\n✅ 测试完成! 可以将草稿导入剪映中查看效果。")
        
    except Exception as e:
        print(f"\n❌ 生成草稿失败: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
