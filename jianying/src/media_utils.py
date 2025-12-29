"""
媒体文件处理工具模块
"""

import os
import subprocess
from typing import Optional, Tuple
from config import Config


class MediaUtils:
    """媒体文件处理工具类"""
    
    def __init__(self, config: Optional[Config] = None):
        """
        初始化媒体工具
        
        Args:
            config: 配置对象，如果为None则使用默认配置
        """
        self.config = config or Config()
    
    def get_media_duration(self, file_path: str) -> int:
        """
        获取媒体文件时长（微秒）
        
        Args:
            file_path: 媒体文件路径
            
        Returns:
            时长（微秒）
        """
        # 检查文件是否存在
        if not os.path.exists(file_path):
            print(f"⚠️ 文件不存在: {file_path}")
            return self._get_fallback_duration(file_path)
        
        # 尝试使用ffprobe获取准确时长
        duration = self._get_duration_with_ffprobe(file_path)
        if duration is not None:
            return duration
        
        # 如果ffprobe失败，使用回退机制
        if self.config.fallback_enabled:
            print(f"⚠️ ffprobe获取时长失败，使用回退机制: {file_path}")
            return self._get_fallback_duration(file_path)
        else:
            raise RuntimeError(f"无法获取媒体文件时长: {file_path}")
    
    def _get_duration_with_ffprobe(self, file_path: str) -> Optional[int]:
        """
        使用ffprobe获取媒体文件时长
        
        Args:
            file_path: 媒体文件路径
            
        Returns:
            时长（微秒），如果失败返回None
        """
        try:
            cmd = [
                self.config.ffprobe_path,
                '-v', 'quiet',
                '-show_entries', 'format=duration',
                '-of', 'default=noprint_wrappers=1:nokey=1',
                file_path
            ]
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.config.ffmpeg_timeout
            )
            
            if result.returncode == 0 and result.stdout.strip():
                duration_seconds = float(result.stdout.strip())
                duration_microseconds = int(duration_seconds * 1000000)
                print(f"✅ 获取到准确时长: {file_path} -> {duration_seconds:.3f}秒")
                return duration_microseconds
            else:
                print(f"⚠️ ffprobe返回错误: {result.stderr}")
                return None
                
        except subprocess.TimeoutExpired:
            print(f"⚠️ ffprobe超时: {file_path}")
            return None
        except subprocess.CalledProcessError as e:
            print(f"⚠️ ffprobe执行失败: {e}")
            return None
        except FileNotFoundError:
            print(f"⚠️ 找不到ffprobe: {self.config.ffprobe_path}")
            return None
        except (ValueError, OSError) as e:
            print(f"⚠️ ffprobe处理错误: {e}")
            return None
    
    def _get_fallback_duration(self, file_path: str) -> int:
        """
        回退机制：当无法获取准确时长时抛出错误
        
        Args:
            file_path: 媒体文件路径
            
        Returns:
            时长（微秒）
            
        Raises:
            RuntimeError: 当无法获取媒体文件时长时
        """
        filename = os.path.basename(file_path).lower()
        
        # 检查是否为支持的格式
        video_formats = self.config.get('media.supported_video_formats', [])
        audio_formats = self.config.get('media.supported_audio_formats', [])
        
        is_supported = False
        for ext in video_formats + audio_formats:
            if filename.endswith(ext.lower()):
                is_supported = True
                break
        
        if is_supported:
            raise RuntimeError(
                f"无法获取媒体文件时长: {file_path}\n"
                f"请确保:\n"
                f"1. FFmpeg/FFprobe已正确安装并配置\n"
                f"2. 媒体文件完整且未损坏\n"
                f"3. 文件路径正确且可访问"
            )
        else:
            raise RuntimeError(
                f"不支持的媒体格式: {file_path}\n"
                f"支持的视频格式: {video_formats}\n"
                f"支持的音频格式: {audio_formats}"
            )
    
    def get_media_info(self, file_path: str) -> dict:
        """
        获取媒体文件详细信息
        
        Args:
            file_path: 媒体文件路径
            
        Returns:
            媒体信息字典
        """
        info = {
            'file_path': file_path,
            'exists': os.path.exists(file_path),
            'duration_microseconds': 0,
            'duration_seconds': 0.0,
            'width': 0,
            'height': 0,
            'fps': 0.0,
            'format': '',
            'size_bytes': 0
        }
        
        if not info['exists']:
            return info
        
        # 获取文件大小
        try:
            info['size_bytes'] = os.path.getsize(file_path)
        except OSError:
            pass
        
        # 获取时长
        info['duration_microseconds'] = self.get_media_duration(file_path)
        info['duration_seconds'] = info['duration_microseconds'] / 1000000.0
        
        # 尝试获取视频信息
        video_info = self._get_video_info_with_ffprobe(file_path)
        if video_info:
            info.update(video_info)
        
        return info
    
    def _get_video_info_with_ffprobe(self, file_path: str) -> Optional[dict]:
        """
        使用ffprobe获取视频信息
        
        Args:
            file_path: 视频文件路径
            
        Returns:
            视频信息字典，如果失败返回None
        """
        try:
            cmd = [
                self.config.ffprobe_path,
                '-v', 'quiet',
                '-select_streams', 'v:0',
                '-show_entries', 'stream=width,height,r_frame_rate,codec_name',
                '-of', 'json',
                file_path
            ]
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.config.ffmpeg_timeout
            )
            
            if result.returncode == 0 and result.stdout.strip():
                import json
                data = json.loads(result.stdout)
                
                if 'streams' in data and len(data['streams']) > 0:
                    stream = data['streams'][0]
                    
                    # 计算帧率
                    fps = 0.0
                    if 'r_frame_rate' in stream:
                        fps_str = stream['r_frame_rate']
                        if '/' in fps_str:
                            num, den = fps_str.split('/')
                            if int(den) != 0:
                                fps = float(num) / float(den)
                    
                    return {
                        'width': stream.get('width', 0),
                        'height': stream.get('height', 0),
                        'fps': fps,
                        'format': stream.get('codec_name', '')
                    }
            
            return None
            
        except (subprocess.TimeoutExpired, subprocess.CalledProcessError, 
                FileNotFoundError, ValueError, OSError, json.JSONDecodeError):
            return None
    
    def check_ffmpeg_availability(self) -> Tuple[bool, bool]:
        """
        检查ffmpeg和ffprobe是否可用
        
        Returns:
            (ffmpeg_available, ffprobe_available)
        """
        ffmpeg_available = self._check_command_available(self.config.ffmpeg_path)
        ffprobe_available = self._check_command_available(self.config.ffprobe_path)
        
        return ffmpeg_available, ffprobe_available
    
    def _check_command_available(self, command: str) -> bool:
        """
        检查命令是否可用
        
        Args:
            command: 命令名称或路径
            
        Returns:
            是否可用
        """
        try:
            result = subprocess.run(
                [command, '-version'],
                capture_output=True,
                text=True,
                timeout=5
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, subprocess.CalledProcessError, 
                FileNotFoundError, OSError):
            return False
