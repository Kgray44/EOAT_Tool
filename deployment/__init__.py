"""EOAT Atlas release packaging and read-only deployment preflight tools.

This package intentionally has no production deployment implementation.  The
only remote transport exposed by Phase 2 is the allowlisted read-only SSH
executor in :mod:`deployment.server_updater`.
"""

from .common import CheckStatus

__all__ = ["CheckStatus"]
