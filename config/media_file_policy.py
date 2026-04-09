"""媒体文件过期策略配置

内置策略:
- never_expire: 永不过期，用户上传的重要文件
- media_cache: 跟随 media_cache 清理规则
"""


class MediaFilePolicy:
    """过期策略"""

    # 永不过期
    NEVER_EXPIRE = "never_expire"
    # 跟随 media_cache 规则
    MEDIA_CACHE = "media_cache"


class MediaFilePolicyConfig:
    """媒体文件策略配置"""

    # 内置策略定义
    POLICIES = {
        MediaFilePolicy.NEVER_EXPIRE: {
            "name": "永不过期",
            "description": "用户上传的重要文件，永远不自动删除",
            "max_days": None,  # None 表示永不过期
        },
        MediaFilePolicy.MEDIA_CACHE: {
            "name": "跟随媒体缓存",
            "description": "跟随 media_cache 的清理规则",
            "max_days": None,  # 通过 media_cache 配置获取
        },
    }

    @classmethod
    def get_policy(cls, policy_code: str) -> dict:
        """获取策略配置"""
        return cls.POLICIES.get(policy_code, cls.POLICIES[MediaFilePolicy.MEDIA_CACHE])

    @classmethod
    def get_max_days(cls, policy_code: str, default_days: int = 30) -> int:
        """获取过期天数"""
        policy = cls.get_policy(policy_code)
        if policy_code == MediaFilePolicy.MEDIA_CACHE:
            # 从 media_cache 配置获取
            from config.config_util import get_dynamic_config_value
            return get_dynamic_config_value("media_cache", "max_days", default=default_days)
        return policy.get("max_days") or default_days
