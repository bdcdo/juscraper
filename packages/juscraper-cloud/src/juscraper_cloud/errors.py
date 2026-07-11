class ProxyConfigurationError(ValueError):
    """Raised when a proxy route is invalid or cannot be applied."""


class RemoteTransportError(RuntimeError):
    """Raised when a remote transport fails."""


class RemoteQuotaError(RemoteTransportError):
    """Raised when a remote transport quota is exhausted."""


class BrowserChallengeError(RemoteTransportError):
    """Raised when a browser transport cannot solve a challenge."""
