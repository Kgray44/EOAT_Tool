class DataGatewayError(RuntimeError):
    """Normalized desktop data-boundary error."""


class ApiUnavailableError(DataGatewayError):
    pass


class IncompatibleServerError(DataGatewayError):
    pass


class CacheUnavailableError(DataGatewayError):
    pass


class WriteBlockedError(DataGatewayError):
    pass


class PermissionDeniedError(DataGatewayError):
    pass


class AuthenticationRequiredError(PermissionDeniedError):
    pass


class ValidationError(DataGatewayError):
    def __init__(self, message: str, *, details=None):
        super().__init__(message)
        self.details = details


class ConcurrencyConflictError(DataGatewayError):
    def __init__(self, message: str, *, current_record_version: int | None = None, details=None):
        super().__init__(message)
        self.current_record_version = current_record_version
        self.details = details
