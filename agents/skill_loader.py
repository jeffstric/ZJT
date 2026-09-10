"""
SOP 加载器 - 从文件系统加载 SOP 流程文件和工具配置

职责：
1. 初始化时扫描 sops/ 目录，解析每个 SOP 的 front matter（精简索引）
2. 按需加载 SOP 完整内容
3. 从 sops_config.json 读取 SOP 对应的额外工具列表
"""

import os
import re
import json
import logging
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class SopLoader:
    """SOP 加载器类"""

    # 类级别：额外 SOP 目录列表（企业版等）
    _extra_sops_dirs: list = []

    @classmethod
    def add_sops_dir(cls, path: str):
        """注册额外的 SOP 目录（如企业版 SOP 目录），同名 SOP 优先使用额外目录"""
        dir_path = Path(path)
        if dir_path.exists() and dir_path.is_dir():
            if dir_path not in cls._extra_sops_dirs:
                cls._extra_sops_dirs.append(dir_path)
                logger.info(f"已注册额外 SOP 目录: {dir_path}")
        else:
            logger.warning(f"额外 SOP 目录不存在: {path}")

    def __init__(self, sops_dir: str, include_extra_sops: bool = True):
        """
        Args:
            sops_dir: SOP 目录路径，如 agents/skills/marketing-pm/sops/
            include_extra_sops: 是否合并类级别注册的额外 SOP 目录（企业版 add_sops_dir）。
                剧本创作链路（session_type=1）必须传 False：SOP 索引是目录枚举后注入
                system prompt 的，若混入企业版营销 SOP（sop-video-clone 等），剧本 PM 会
                向用户宣称其不具备的营销视频能力（call_agent 阶段才会被
                allowed_expert_types 拦截）。营销链路保持默认 True 以获得企业版覆盖。
        """
        self.sops_dir = Path(sops_dir)
        self.include_extra_sops = include_extra_sops
        self.sops_config = self._load_sops_config()
        self.sops_metadata = self._load_all_sops_metadata()

    def _load_sops_config(self) -> dict:
        """加载 sops_config.json"""
        config_file = self.sops_dir / 'sops_config.json'
        if not config_file.exists():
            logger.warning(f"sops_config.json 不存在: {config_file}")
            return {}
        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"加载 sops_config.json 失败: {e}")
            return {}

    def _load_all_sops_metadata(self) -> Dict[str, Dict[str, str]]:
        """扫描 sops/ 目录和额外目录，解析每个 .md 的 front matter（name + description）
        额外目录同名 SOP 覆盖主目录
        """
        metadata = {}
        # 先加载主目录
        if self.sops_dir.exists():
            for sop_file in self.sops_dir.glob('*.md'):
                try:
                    sop_data = self._parse_front_matter(sop_file)
                    if sop_data and sop_data.get('name'):
                        metadata[sop_data['name']] = {
                            'name': sop_data['name'],
                            'description': sop_data.get('description', ''),
                            'file': str(sop_file)
                        }
                except Exception as e:
                    logger.warning(f"解析 SOP 文件失败 {sop_file}: {e}")

        # 再加载额外目录（覆盖同名 SOP）；include_extra_sops=False 的实例（剧本链路）完全隔离
        if self.include_extra_sops:
            for extra_dir in self._extra_sops_dirs:
                if extra_dir.exists():
                    for sop_file in extra_dir.glob('*.md'):
                        try:
                            sop_data = self._parse_front_matter(sop_file)
                            if sop_data and sop_data.get('name'):
                                if sop_data['name'] in metadata:
                                    logger.info(f"企业版 SOP 覆盖: {sop_data['name']}")
                                metadata[sop_data['name']] = {
                                    'name': sop_data['name'],
                                    'description': sop_data.get('description', ''),
                                    'file': str(sop_file)
                                }
                        except Exception as e:
                            logger.warning(f"解析额外 SOP 文件失败 {sop_file}: {e}")

        logger.info(f"已加载 {len(metadata)} 个 SOP 元数据: {', '.join(metadata.keys())}")
        return metadata

    def _parse_front_matter(self, file_path: Path) -> Optional[Dict[str, str]]:
        """解析 markdown 文件的 YAML front matter"""
        try:
            content = file_path.read_text(encoding='utf-8')
            yaml_match = re.match(r'^---\s*\n(.*?)\n---\s*\n', content, re.DOTALL)
            if not yaml_match:
                return None

            yaml_content = yaml_match.group(1)
            result = {}
            for line in yaml_content.split('\n'):
                if ':' in line:
                    key, value = line.split(':', 1)
                    result[key.strip()] = value.strip()
            return result
        except Exception as e:
            logger.error(f"解析 front matter 失败 {file_path}: {e}")
            return None

    def list_sops(self) -> List[str]:
        """列出所有可用的 SOP 名称"""
        return list(self.sops_metadata.keys())

    def get_sop_metadata(self, sop_name: str) -> Optional[Dict[str, str]]:
        """获取 SOP 精简信息（仅 name + description）"""
        return self.sops_metadata.get(sop_name)

    def build_sops_index(self) -> str:
        """构建所有 SOP 的精简索引文本（用于拼接到 system prompt）

        Returns:
            格式化的 SOP 索引表格字符串
        """
        if not self.sops_metadata:
            return ""

        lines = [
            "| SOP 名称 | 描述 |",
            "|-----------|------|"
        ]
        for name, meta in sorted(self.sops_metadata.items()):
            desc = meta.get('description', '无描述')
            lines.append(f"| {name} | {desc} |")

        return '\n'.join(lines)

    def get_sop_content(self, sop_name: str) -> Optional[str]:
        """加载 SOP 的完整 markdown 正文（不含 front matter）

        Args:
            sop_name: SOP 名称

        Returns:
            SOP 正文内容，不存在返回 None
        """
        meta = self.sops_metadata.get(sop_name)
        if not meta:
            return None

        sop_file = Path(meta['file'])
        if not sop_file.exists():
            return None

        try:
            content = sop_file.read_text(encoding='utf-8')
            # 去掉 YAML front matter
            match = re.match(r'^---\s*\n.*?\n---\s*\n(.*)$', content, re.DOTALL)
            if match:
                return match.group(1).strip()
            # 如果没有 front matter，返回全部内容
            return content.strip()
        except Exception as e:
            logger.error(f"读取 SOP 内容失败 {sop_name}: {e}")
            return None

    def get_sop_tools(self, sop_name: str) -> List[str]:
        """获取 SOP 对应的额外工具列表（从 sops_config.json）

        Args:
            sop_name: SOP 名称

        Returns:
            工具名称列表
        """
        sop_config = self.sops_config.get(sop_name, {})
        return sop_config.get('allowed_tools', [])

    def load_skill_with_index(self, skill_content: str) -> str:
        """将 SKILL.md 内容中的 {{SOP_INDEX}} 占位符替换为实际的 SOP 索引

        Args:
            skill_content: SKILL.md 的原始内容

        Returns:
            替换后的内容
        """
        index = self.build_sops_index()
        return skill_content.replace('{{SOP_INDEX}}', index)
