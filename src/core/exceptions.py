class RedditMonitorError(Exception):
    def __init__(self, message: str, details: str | None = None):
        self.message = message
        self.details = details
        super().__init__(self.message)

    def __repr__(self) -> str:
        if self.details:
            return f"{type(self).__name__}({self.message!r}, details={self.details!r})"
        return f"{type(self).__name__}({self.message!r})"


class RedditAPIError(RedditMonitorError):
    pass


class ConfigurationError(RedditMonitorError):
    pass


class GeminiAPIError(RedditMonitorError):
    pass


class GeminiServiceError(RedditMonitorError):
    pass


class WebhookServiceError(RedditMonitorError):
    pass
