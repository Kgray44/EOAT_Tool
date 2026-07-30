class AuthenticationConfigurationError(RuntimeError):
    pass


class AuthenticationUnavailableError(RuntimeError):
    pass


class InvalidCredentialsError(AuthenticationUnavailableError):
    """Authentication failed without disclosing account-existence details."""


class DirectoryProtocolError(AuthenticationUnavailableError):
    """A directory transport, TLS, or protocol operation failed safely."""
