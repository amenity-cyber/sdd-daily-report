"""自定义异常类型与错误处理策略。"""


class ConfigError(Exception):
    """配置缺失或格式不正确。"""


class CollectorError(Exception):
    """采集层失败（外部 API 超时、鉴权失败、限流等）。"""


class GeneratorError(Exception):
    """生成层失败（模板渲染、数据整理等）。"""


class NotifierError(Exception):
    """推送层失败（SMTP / 飞书 webhook 发送失败）。"""


# design.md §6.1 错误处理策略常量
API_TIMEOUT_RETRIES = 3
API_TIMEOUT_INTERVAL_SECONDS = 5
LARK_TOKEN_REFRESH_RETRIES = 1
NOTIFY_RETRIES = 2
