"""
Driver exceptions
"""


class DriverConfigError(Exception):
    """驱动配置缺失异常"""
    
    def __init__(self, driver_name: str, missing_configs: list):
        self.driver_name = driver_name
        self.missing_configs = missing_configs
        self.message = f"驱动 {driver_name} 缺少必要配置: {', '.join(missing_configs)}"
        super().__init__(self.message)
