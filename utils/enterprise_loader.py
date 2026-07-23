import json
import os
import sys
import logging
import importlib

from config.version import get_app_version
from config.config_util import get_config_value

logger = logging.getLogger(__name__)

ENTERPRISE_DIR = "enterprise"
VERSION_FILE = "version.json"


def _parse_version(v: str) -> tuple:
    """将版本号字符串解析为元组，用于比较"""
    return tuple(int(x) for x in v.split('.'))


def _version_in_range(v: str, min_v: str, max_v: str) -> bool:
    """检查版本 v 是否在 [min_v, max_v] 范围内（闭区间）"""
    pv = _parse_version(v)
    pmin = _parse_version(min_v)
    pmax = _parse_version(max_v)
    return pmin <= pv <= pmax


class EnterpriseLoader:
    def __init__(self):
        self.loaded = False
        self.enterprise_version = None

    def _get_project_root(self) -> str:
        return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    def discover(self) -> bool:
        """检测 enterprise 模块是否存在且版本兼容"""
        edition_mode = get_config_value('edition', 'mode', default='community')
        if edition_mode != 'enterprise':
            logger.info('Enterprise mode is disabled by configuration')
            return False

        project_root = self._get_project_root()
        enterprise_path = os.path.join(project_root, ENTERPRISE_DIR)

        if not os.path.isdir(enterprise_path):
            logger.info("Enterprise module not found, running in community/basic mode")
            return False

        version_file = os.path.join(enterprise_path, VERSION_FILE)
        if not os.path.isfile(version_file):
            logger.warning("Enterprise directory exists but version.json not found, skipping")
            return False

        try:
            with open(version_file, 'r', encoding='utf-8') as f:
                ent_data = json.load(f)
        except Exception as e:
            logger.error(f"Failed to read enterprise version.json: {e}")
            return False

        ent_version = ent_data.get("version", "0.0.0")
        min_core = ent_data.get("min_core_version", "0.0.0")
        max_core = ent_data.get("max_core_version", "99.99.99")

        core_version = get_app_version()

        # 检查核心版本是否满足 enterprise 要求（若 enterprise 未声明则跳过）
        if "min_core_version" in ent_data or "max_core_version" in ent_data:
            if not _version_in_range(core_version, min_core, max_core):
                logger.error(
                    f"Core version {core_version} not in enterprise requirement "
                    f"[{min_core}, {max_core}]"
                )
                return False

        # 检查 enterprise 版本是否满足主仓库要求
        min_ent = get_config_value("enterprise", "min_version", default="0.0.0")
        max_ent = get_config_value("enterprise", "max_version", default="99.99.99")

        if not _version_in_range(ent_version, min_ent, max_ent):
            logger.error(
                f"Enterprise version {ent_version} not in manifest requirement "
                f"[{min_ent}, {max_ent}]"
            )
            return False

        self.enterprise_version = ent_version
        logger.info(f"Enterprise module discovered: version {ent_version}")
        return True

    def load(self, app):
        """加载 enterprise 模块"""
        if self.loaded:
            return

        try:
            # 确保项目根目录在 sys.path 中，使 Python 能找到 enterprise 包
            project_root = self._get_project_root()
            if project_root not in sys.path:
                sys.path.insert(0, project_root)

            enterprise_module = importlib.import_module("enterprise")
            enterprise_module.register(app)
            self.loaded = True
            logger.info("Enterprise module loaded successfully")
        except Exception as e:
            logger.error(f"Failed to load enterprise module: {e}")
            try:
                from task.runninghub_key_pool import reset_provider
                reset_provider()
            except Exception:
                pass
            try:
                from services.registration_quota import reset_provider as reset_registration_quota
                reset_registration_quota()
            except Exception:
                pass


enterprise_loader = EnterpriseLoader()
