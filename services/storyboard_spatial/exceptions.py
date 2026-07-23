class StoryboardEnterpriseFeatureRequired(RuntimeError):
    """Raised when a community edition process tries to use enterprise spatial features."""

    error_code = "enterprise_only"

    def __init__(self, message: str = "效果模式仅商业版支持，请购买商业版后使用"):
        super().__init__(message)
        self.message = message
