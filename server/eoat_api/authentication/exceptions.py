class AuthenticationConfigurationError(RuntimeError):
    pass


class AuthenticationUnavailableError(RuntimeError):
    """A safe internal category; its message is never shown to sign-in users."""

    def __init__(self, message: str, *, reason_code: str = "AUTHENTICATION_UNAVAILABLE"):
        super().__init__(message)
        self.reason_code = reason_code
