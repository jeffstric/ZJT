"""
配置管理模块
"""

import json
import os
from typing import Dict, Any, Optional


class Config:
    """配置管理类"""
    
    def __init__(self, config_path: Optional[str] = None):
        """
        初始化配置
        
        Args:
            config_path: 配置文件路径，默认为项目根目录下的config.json
        """
        if config_path is None:
            # 获取当前文件所在目录的上级目录（项目根目录）
            current_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            config_path = os.path.join(current_dir, "config.json")
        
        self.config_path = config_path
        self._config = self._load_config()
    
    def _load_config(self) -> Dict[str, Any]:
        """加载配置文件"""
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            print(f"⚠️ 配置文件加载失败: {e}")
            return self._get_default_config()
    
    def _get_default_config(self) -> Dict[str, Any]:
        """获取默认配置"""
        return {
            "ffmpeg": {
                "ffmpeg_path": "ffmpeg",
                "ffprobe_path": "ffprobe",
                "timeout": 30,
                "fallback_enabled": True
            },
            "media": {
                "supported_video_formats": [".mp4", ".avi", ".mov", ".mkv", ".wmv", ".flv"],
                "supported_audio_formats": [".mp3", ".wav", ".aac", ".m4a", ".ogg", ".flac"]
            }
        }
    
    def get(self, key: str, default: Any = None) -> Any:
        """
        获取配置值
        
        Args:
            key: 配置键，支持点号分隔的嵌套键，如 'ffmpeg.ffprobe_path'
            default: 默认值
            
        Returns:
            配置值
        """
        keys = key.split('.')
        value = self._config
        
        try:
            for k in keys:
                value = value[k]
            return value
        except (KeyError, TypeError):
            return default
    
    def set(self, key: str, value: Any) -> None:
        """
        设置配置值
        
        Args:
            key: 配置键，支持点号分隔的嵌套键
            value: 配置值
        """
        keys = key.split('.')
        config = self._config
        
        # 导航到目标位置
        for k in keys[:-1]:
            if k not in config:
                config[k] = {}
            config = config[k]
        
        # 设置值
        config[keys[-1]] = value
    
    def save(self) -> None:
        """保存配置到文件"""
        try:
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(self._config, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"⚠️ 配置文件保存失败: {e}")
    
    @property
    def ffmpeg_path(self) -> str:
        """获取ffmpeg路径"""
        return self.get('ffmpeg.ffmpeg_path', 'ffmpeg')
    
    @property
    def ffprobe_path(self) -> str:
        """获取ffprobe路径"""
        return self.get('ffmpeg.ffprobe_path', 'ffprobe')
    
    @property
    def ffmpeg_timeout(self) -> int:
        """获取ffmpeg超时时间"""
        return self.get('ffmpeg.timeout', 30)
    
    @property
    def fallback_enabled(self) -> bool:
        """是否启用回退机制"""
        return self.get('ffmpeg.fallback_enabled', True)
    
    def update_ffmpeg_paths(self, ffmpeg_path: str = None, ffprobe_path: str = None) -> None:
        """
        更新ffmpeg路径配置
        
        Args:
            ffmpeg_path: ffmpeg可执行文件路径
            ffprobe_path: ffprobe可执行文件路径
        """
        if ffmpeg_path:
            self.set('ffmpeg.ffmpeg_path', ffmpeg_path)
        if ffprobe_path:
            self.set('ffmpeg.ffprobe_path', ffprobe_path)
        self.save()
