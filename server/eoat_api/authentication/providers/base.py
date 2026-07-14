from __future__ import annotations

from abc import ABC, abstractmethod

from ..identity_models import AuthenticatedIdentity, ProviderHealth


class AuthenticationProvider(ABC):
    name: str

    @abstractmethod
    def begin_login(self, context: dict) -> dict:
        raise NotImplementedError

    @abstractmethod
    def complete_login(self, response: dict) -> AuthenticatedIdentity:
        raise NotImplementedError

    @abstractmethod
    def health_check(self) -> ProviderHealth:
        raise NotImplementedError

    def logout(self, _session_identifier: str) -> None:
        return None
