"""
剪映配置管理模块
使用主配置的 bin 配置项获取 ffmpeg 路径
"""

import json
import os
import sys
import yaml
from typing import Dict, Any, Optional

# 添加项目根目录到路径，以便导入 config_util
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

from config.config_util import resolve_bin_path, get_config_path


def get_main_config() -> Dict[str, Any]:
    """
    加载主配置文件

    Returns:
        主配置字典
    """
    try:
        # 获取项目根目录
        current_dir = os.path.dirname(os.path.abspath(__file__))

        # 使用 config_util 的 get_config_path 获取配置文件名
        config_file = get_config_path()
        config_path = os.path.join(current_dir, config_file)

        if os.path.exists(config_path):
            with open(config_path, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f) or {}
    except Exception as e:
        print(f"加载主配置文件失败: {e}")

    return {}


class JianyingConfig:
    """剪映配置管理类"""
    
    def __init__(self, config_path: Optional[str] = None):
        """
        初始化配置
        
        Args:
            config_path: 配置文件路径，默认为jianying目录下的config.json
        """
        if config_path is None:
            # 获取当前文件所在目录（项目根目录）
            current_dir = os.path.dirname(os.path.abspath(__file__))
            config_path = os.path.join(current_dir, "jianying", "config.json")
        
        self.config_path = config_path
        self._config = self._load_config()
    
    def _load_config(self) -> Dict[str, Any]:
        """加载配置文件，并从主配置补充 ffmpeg 路径"""
        # 先从主配置获取默认配置（包含正确的 ffmpeg 路径）
        config = self._get_default_config()
        
        # 尝试加载 jianying/config.json，合并其他配置项
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                json_config = json.load(f)
                # 合并配置：保留 json 中的其他配置，但 ffmpeg 路径已从主配置读取
                if 'ffmpeg' in json_config:
                    # 只保留 timeout 和 fallback_enabled，路径保持从主配置读取的值
                    config['ffmpeg']['timeout'] = json_config['ffmpeg'].get('timeout', 30)
                    config['ffmpeg']['fallback_enabled'] = json_config['ffmpeg'].get('fallback_enabled', True)
                if 'media' in json_config:
                    config['media'] = json_config['media']
        except (FileNotFoundError, json.JSONDecodeError) as e:
            print(f"配置文件加载失败，使用默认配置: {e}")
        
        return config
    
    def _get_default_config(self) -> Dict[str, Any]:
        """获取默认配置，使用主配置的 bin 配置项"""
        # 从主配置获取 ffmpeg 路径
        main_config = get_main_config()
        bin_config = main_config.get("bin", {})
        
        ffmpeg_path = bin_config.get("ffmpeg", "ffmpeg")
        ffprobe_path = bin_config.get("ffprobe", "ffprobe")
        
        return {
            "ffmpeg": {
                "ffmpeg_path": ffmpeg_path,
                "ffprobe_path": ffprobe_path,
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
            print(f"配置文件保存失败: {e}")
    
    @property
    def ffmpeg_path(self) -> str:
        """获取ffmpeg路径（自动解析相对路径）"""
        raw_path = self.get('ffmpeg.ffmpeg_path', 'ffmpeg')
        # 获取项目根目录用于解析相对路径
        app_dir = os.path.dirname(os.path.abspath(__file__))
        return resolve_bin_path(raw_path, app_dir)
    
    @property
    def ffprobe_path(self) -> str:
        """获取ffprobe路径（自动解析相对路径）"""
        raw_path = self.get('ffmpeg.ffprobe_path', 'ffprobe')
        # 获取项目根目录用于解析相对路径
        app_dir = os.path.dirname(os.path.abspath(__file__))
        return resolve_bin_path(raw_path, app_dir)
    
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
