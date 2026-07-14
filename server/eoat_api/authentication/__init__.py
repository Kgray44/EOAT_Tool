"""Settings-only enterprise authentication boundary.

Normal EOAT Atlas operations deliberately do not require a user session.
"""

from .configuration import AuthenticationConfiguration
from .service import AuthenticationService

__all__ = ["AuthenticationConfiguration", "AuthenticationService"]
