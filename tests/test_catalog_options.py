from __future__ import annotations

import pytest
from fastapi import HTTPException

from server.eoat_api.app import catalog_options
from server.eoat_api.contracts import CatalogOption
from server.eoat_api.repositories import parse_machine_catalog_value


class _Repository:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, int]] = []

    def catalog_options(self, kind: str, query: str, limit: int):
        self.calls.append((kind, query, limit))
        if kind == "invalid":
            raise ValueError(kind)
        return [CatalogOption(value="P4", label="Plant 4")]


def test_catalog_options_are_bounded_and_server_authoritative() -> None:
    repository = _Repository()

    result = catalog_options("plant", query="P4", limit=25, repo=repository)

    assert result == [CatalogOption(value="P4", label="Plant 4")]
    assert repository.calls == [("plant", "P4", 25)]


def test_catalog_options_reject_unknown_selector_kind() -> None:
    with pytest.raises(HTTPException) as raised:
        catalog_options("invalid", repo=_Repository())

    assert raised.value.status_code == 404


def test_plant_qualified_machine_selector_values_do_not_silently_collapse() -> None:
    assert parse_machine_catalog_value("P4::27") == ("P4", "27")
    assert parse_machine_catalog_value("27") == (None, "27")
    assert parse_machine_catalog_value("P4::../27") == (None, "")
