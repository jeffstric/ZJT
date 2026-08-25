"""
技能加载器 - 从文件系统或数据库加载技能配置
支持用户级自定义：优先加载用户自定义内容，回退到文件系统默认值
"""

import os
import re
import logging
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class SkillLoader:
    """技能加载器类"""

    # 类级别：额外技能目录列表（企业版等）
    _extra_skills_dirs: list = []

    @classmethod
    def add_skills_dir(cls, path: str):
        """注册额外的技能目录（如企业版技能目录），同名技能优先使用额外目录"""
        dir_path = Path(path)
        if dir_path.exists() and dir_path.is_dir():
            if dir_path not in cls._extra_skills_dirs:
                cls._extra_skills_dirs.append(dir_path)
                logger.info(f"已注册额外技能目录: {dir_path}")
        else:
            logger.warning(f"额外技能目录不存在: {path}")

    def __init__(self, skills_dir: str = None, user_id: int = None):
        """初始化技能加载器

        Args:
            skills_dir: 技能目录路径，默认为 skills 目录
            user_id: 用户ID，传入后优先加载该用户的自定义 skill
        """
        if skills_dir is None:
            skills_dir = os.path.join(os.path.dirname(__file__), 'skills')
            project_skills = Path(__file__).resolve().parents[1] / 'agents' / 'skills'
            self.add_skills_dir(str(project_skills))

        self.skills_dir = Path(skills_dir)
        self.user_id = user_id
        self.skills_metadata = {}  # 只存储元数据
        self.skills_full_cache = {}  # 缓存完整技能内容
        self._load_all_skills_metadata()

    def _load_all_skills_metadata(self):
        """加载所有技能的元数据（从文件系统），额外目录同名技能覆盖主目录"""
        # 先加载主目录
        if self.skills_dir.exists():
            for skill_dir in self.skills_dir.iterdir():
                if skill_dir.is_dir():
                    skill_file = skill_dir / 'SKILL.md'
                    if skill_file.exists():
                        skill_name = skill_dir.name
                        metadata = self._parse_skill_metadata(skill_file)
                        if metadata:
                            self.skills_metadata[skill_name] = metadata

        # 再加载额外目录（覆盖同名技能）
        for extra_dir in self._extra_skills_dirs:
            if extra_dir.exists():
                for skill_dir in extra_dir.iterdir():
                    if skill_dir.is_dir():
                        skill_file = skill_dir / 'SKILL.md'
                        if skill_file.exists():
                            skill_name = skill_dir.name
                            metadata = self._parse_skill_metadata(skill_file)
                            if metadata:
                                if skill_name in self.skills_metadata:
                                    logger.info(f"企业版技能覆盖: {skill_name}")
                                self.skills_metadata[skill_name] = metadata

        logger.info(f"已加载 {len(self.skills_metadata)} 个技能元数据: {', '.join(self.skills_metadata.keys())}")

    def _parse_skill_metadata(self, skill_file: Path) -> Optional[Dict]:
        """解析技能文件的元数据（仅YAML front matter）

        Args:
            skill_file: SKILL.md 文件路径

        Returns:
            技能元数据字典
        """
        try:
            content = skill_file.read_text(encoding='utf-8')

            # 解析 YAML front matter
            yaml_match = re.match(r'^---\s*\n(.*?)\n---\s*\n(.*)$', content, re.DOTALL)

            if not yaml_match:
                return None

            yaml_content = yaml_match.group(1)

            # 解析 YAML 字段（仅元数据）
            metadata = {
                'name': None,
                'description': None,
                'allowed-tools': None
            }

            for line in yaml_content.split('\n'):
                if ':' in line:
                    key, value = line.split(':', 1)
                    key = key.strip()
                    value = value.strip()
                    if key in metadata:
                        metadata[key] = value

            return metadata

        except Exception as e:
            logger.error(f"解析技能元数据失败 {skill_file}: {e}")
            return None

    def _parse_skill_file(self, skill_file: Path) -> Optional[Dict]:
        """解析技能文件

        Args:
            skill_file: SKILL.md 文件路径

        Returns:
            技能数据字典
        """
        try:
            content = skill_file.read_text(encoding='utf-8')

            # 解析 YAML front matter
            yaml_match = re.match(r'^---\s*\n(.*?)\n---\s*\n(.*)$', content, re.DOTALL)

            if not yaml_match:
                return None

            yaml_content = yaml_match.group(1)
            markdown_content = yaml_match.group(2)

            # 解析 YAML 字段
            skill_data = {
                'name': None,
                'description': None,
                'prompt': markdown_content.strip()
            }

            for line in yaml_content.split('\n'):
                if ':' in line:
                    key, value = line.split(':', 1)
                    key = key.strip()
                    value = value.strip()
                    if key in ['name', 'description']:
                        skill_data[key] = value

            return skill_data

        except Exception as e:
            logger.error(f"解析技能文件失败 {skill_file}: {e}")
            return None

    def _load_from_db(self, user_id: int, skill_name: str) -> Optional[Dict]:
        """从数据库加载用户自定义的 skill

        Args:
            user_id: 用户ID
            skill_name: 技能名称

        Returns:
            技能数据字典，如果用户未自定义返回 None
        """
        try:
            from model.skill_definitions import SkillDefinitionsModel
            skill_def = SkillDefinitionsModel.get_user_skill(user_id, skill_name)
            if skill_def and skill_def.prompt_content:
                # 获取文件系统中的元数据作为补充
                file_metadata = self.skills_metadata.get(skill_name, {})
                return {
                    'name': skill_def.display_name or file_metadata.get('name') or skill_name,
                    'description': skill_def.description or file_metadata.get('description', ''),
                    'prompt': skill_def.prompt_content
                }
        except Exception as e:
            logger.warning(f"从数据库加载技能失败 ({skill_name}, user_id={user_id}): {e}")
        return None

    def get_skill_metadata(self, skill_name: str) -> Optional[Dict]:
        """获取指定技能的元数据

        Args:
            skill_name: 技能名称

        Returns:
            技能元数据字典，如果不存在返回 None
        """
        return self.skills_metadata.get(skill_name)

    def get_skill_full_content(self, skill_name: str) -> Optional[Dict]:
        """获取指定技能的完整内容（按需加载）

        优先级：内存缓存 → 用户自定义DB → 文件系统

        Args:
            skill_name: 技能名称

        Returns:
            完整技能数据字典，如果不存在返回 None
        """
        # 检查缓存
        if skill_name in self.skills_full_cache:
            return self.skills_full_cache[skill_name]

        # 如果有 user_id，优先从数据库加载用户自定义
        if self.user_id:
            db_data = self._load_from_db(self.user_id, skill_name)
            if db_data:
                self.skills_full_cache[skill_name] = db_data
                return db_data

        # 检查技能是否在文件系统中存在
        if skill_name not in self.skills_metadata:
            return None

        # 优先从额外目录查找，再从主目录查找
        skill_file = None
        for extra_dir in self._extra_skills_dirs:
            candidate = extra_dir / skill_name / 'SKILL.md'
            if candidate.exists():
                skill_file = candidate
                break
        if skill_file is None:
            skill_file = self.skills_dir / skill_name / 'SKILL.md'
        if skill_file.exists():
            skill_data = self._parse_skill_file(skill_file)
            if skill_data:
                self.skills_full_cache[skill_name] = skill_data
                return skill_data

        return None

    def get_skill(self, skill_name: str) -> Optional[Dict]:
        """获取指定技能（向后兼容，返回完整内容）

        Args:
            skill_name: 技能名称

        Returns:
            技能数据字典，如果不存在返回 None
        """
        return self.get_skill_full_content(skill_name)

    def get_skill_prompt(self, skill_name: str) -> Optional[str]:
        """获取技能的提示词（按需加载完整内容）

        Args:
            skill_name: 技能名称

        Returns:
            技能提示词，如果不存在返回 None
        """
        skill = self.get_skill_full_content(skill_name)
        return skill['prompt'] if skill else None

    def list_skills(self) -> list:
        """列出所有技能名称"""
        return list(self.skills_metadata.keys())

    def get_all_skills_metadata(self) -> Dict:
        """获取所有技能元数据"""
        return self.skills_metadata

    def get_all_skills(self) -> Dict:
        """获取所有技能数据（向后兼容，会加载所有完整内容）"""
        all_skills = {}
        for skill_name in self.skills_metadata.keys():
            skill_data = self.get_skill_full_content(skill_name)
            if skill_data:
                all_skills[skill_name] = skill_data
        return all_skills

    def invalidate_cache(self, skill_name: str = None):
        """清除缓存（供 API 调用，在用户编辑 skill 后刷新）

        Args:
            skill_name: 指定清除某个 skill 的缓存，None 则清除全部
        """
        if skill_name:
            self.skills_full_cache.pop(skill_name, None)
        else:
            self.skills_full_cache.clear()

    def build_skills_summary(self) -> str:
        """构建技能摘要（渐进式披露 - 仅显示元数据）

        Returns:
            技能摘要字符串
        """
        if not self.skills_metadata:
            return ""

        summary_parts = [
            "## 🔒 可用技能（渐进式披露）",
            "",
            "🚨 **严重警告**: 以下只是技能概述，绝不包含完整指导！",
            "",
            "**强制执行流程**：",
            "1. 🛑 **立即停止** - 发现相关任务时不要直接工作",
            "2. 📞 **强制调用** - 必须先调用 `skill` 工具: `skill(SkillName=\"技能名\")`",
            "3. ⏳ **等待加载** - 等待完整技能内容返回",
            "4. ✅ **开始工作** - 基于完整指导执行任务",
            "",
            "⚠️ **违反后果**: 直接工作将导致错误的规则和过时的指导！",
            "",
            "📋 **技能概述列表**（仅用于识别，非执行指导）：",
            ""
        ]

        # 按技能名称排序
        sorted_skills = sorted(self.skills_metadata.items())

        for skill_name, metadata in sorted_skills:
            description = metadata.get('description', '无描述')
            # 计算支持文件数量
            skill_dir = self.skills_dir / skill_name
            support_files = 0
            if skill_dir.exists():
                support_files = len([f for f in skill_dir.iterdir() if f.is_file() and f.name != 'SKILL.md'])

            if support_files > 0:
                summary_parts.append(f"- **{skill_name}**: {description} ({support_files} supporting files)")
            else:
                summary_parts.append(f"- **{skill_name}**: {description}")

        return '\n'.join(summary_parts)

    def build_system_prompt(self, skill_name: str, additional_context: str = None) -> str:
        """构建包含技能的系统提示词（按需加载完整内容）

        Args:
            skill_name: 技能名称
            additional_context: 额外的上下文信息

        Returns:
            完整的系统提示词
        """
        skill = self.get_skill_full_content(skill_name)

        if not skill:
            raise ValueError(f"技能不存在: {skill_name}")

        prompt_parts = []

        # 添加技能描述
        if skill['description']:
            prompt_parts.append(f"# 技能: {skill['name']}")
            prompt_parts.append(f"{skill['description']}\n")

        # 添加技能提示词
        prompt_parts.append(skill['prompt'])

        # 添加额外上下文
        if additional_context:
            prompt_parts.append(f"\n## 额外上下文\n{additional_context}")

        return '\n\n'.join(prompt_parts)


def demo():
    """演示如何使用技能加载器"""
    loader = SkillLoader()

    print("\n" + "=" * 60)
    print("技能摘要（用于系统提示词）:")
    print("=" * 60)
    print(loader.build_skills_summary())

    print("\n" + "=" * 60)
    print("示例：获取 character-creator 技能的提示词")
    print("=" * 60)

    if 'character-creator' in loader.list_skills():
        print("\n" + "=" * 60)
        print("示例：按需加载完整技能内容")
        print("=" * 60)

        # 先显示元数据
        metadata = loader.get_skill_metadata('character-creator')
        print(f"\n元数据: {metadata}")

        # 按需加载完整内容
        prompt = loader.get_skill_prompt('character-creator')
        print(f"\n完整提示词长度: {len(prompt)} 字符")
        print("\n✅ 完整技能内容已成功加载（实际使用中会传递给AI）")

        print("\n" + "=" * 60)
        print("示例：构建完整的系统提示词")
        print("=" * 60)

        system_prompt = loader.build_system_prompt(
            'character-creator',
            additional_context="当前剧本类型：悬疑剧"
        )
        print(f"\n系统提示词长度: {len(system_prompt)} 字符")


if __name__ == '__main__':
    demo()
