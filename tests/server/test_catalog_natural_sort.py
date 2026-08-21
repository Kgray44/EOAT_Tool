from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from server.eoat_api.repositories import AtlasRepository, natural_identifier_key


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _CatalogSession:
    """A small repository seam that proves sorting happens before pagination."""

    def __init__(self, rows):
        self.rows = rows
        self.execute_calls = 0

    def execute(self, *_args, **_kwargs):
        self.execute_calls += 1
        return _Rows(self.rows if self.execute_calls == 1 else [])


def _timestamp(day: int = 1):
    return datetime(2026, 8, day, tzinfo=timezone.utc)


def _machine(number: str, *, name: str | None = None):
    return SimpleNamespace(
        machine_number=number,
        machine_name=name,
        manufacturer=None,
        model=None,
        is_active=True,
        row_version=1,
        updated_at=_timestamp(),
    )


def _tool(identifier: str):
    return SimpleNamespace(
        business_identifier=identifier,
        tool_number=identifier,
        mold_number=None,
        display_name=None,
        is_active=True,
        row_version=1,
        updated_at=_timestamp(),
    )


def _eoat(identifier: str):
    return SimpleNamespace(
        id=hash(identifier),
        business_identifier=identifier,
        legacy_identifier=None,
        display_name=None,
        number_of_parts_picked=None,
        is_active=True,
        row_version=1,
        updated_at=_timestamp(),
    )


def test_natural_identifier_key_orders_numeric_and_alphanumeric_segments():
    assert sorted(["P4-EOAT-19", "P4-EOAT-2", "P4-EOAT-11"], key=natural_identifier_key) == [
        "P4-EOAT-2",
        "P4-EOAT-11",
        "P4-EOAT-19",
    ]


def test_machine_catalog_naturally_sorts_before_pagination_and_keeps_plant_tie_breaker():
    rows = [
        (_machine("19"), "P4", None, None, None),
        (_machine("11"), "P4", None, None, None),
        (_machine("2"), "P9", None, None, None),
        (_machine("1"), "P9", None, None, None),
        (_machine("2"), "P4", None, None, None),
    ]
    first, first_page = AtlasRepository(_CatalogSession(rows)).list_machines(active=None, page=1, page_size=3)
    second, second_page = AtlasRepository(_CatalogSession(rows)).list_machines(active=None, page=2, page_size=3)

    assert [(item.machine_number, item.plant_code) for item in first] == [
        ("1", "P9"),
        ("2", "P4"),
        ("2", "P9"),
    ]
    assert [(item.machine_number, item.plant_code) for item in second] == [
        ("11", "P4"),
        ("19", "P4"),
    ]
    assert (first_page.total, first_page.pages, second_page.page) == (5, 2, 2)


def test_tool_and_eoat_catalogs_use_the_same_natural_default_ordering():
    tools, _ = AtlasRepository(
        _CatalogSession([(_tool(value), None) for value in ("TOOL-19", "TOOL-2", "TOOL-11")])
    ).list_tools(active=None)
    eoats, _ = AtlasRepository(
        _CatalogSession([(_eoat(value), None, None, None, None) for value in ("P4-EOAT-19", "P4-EOAT-2", "P4-EOAT-11")])
    ).list_eoats(active=None)

    assert [item.business_identifier for item in tools] == ["TOOL-2", "TOOL-11", "TOOL-19"]
    assert [item.business_identifier for item in eoats] == ["P4-EOAT-2", "P4-EOAT-11", "P4-EOAT-19"]


def test_machine_identifier_desc_remains_an_explicit_alternate_sort():
    items, _ = AtlasRepository(
        _CatalogSession([(_machine(value), "P4", None, None, None) for value in ("1", "11", "2")])
    ).list_machines(active=None, sort="machine_number_desc")

    assert [item.machine_number for item in items] == ["11", "2", "1"]


def test_global_search_interprets_machine_prefix_without_weakening_entity_search():
    requested: list[tuple[str, str]] = []
    repo = object.__new__(AtlasRepository)

    def list_eoats(*, search: str, **_kwargs):
        requested.append(("eoat", search))
        return [SimpleNamespace(business_identifier="P4-EOAT-11", display_name=None, eoat_type=None)], None

    def list_machines(*, search: str, **_kwargs):
        requested.append(("machine", search))
        return [SimpleNamespace(machine_number="11", machine_name="Machine 11", plant_code="P4", area="Molding")], None

    def list_tools(*, search: str, **_kwargs):
        requested.append(("tool", search))
        return [SimpleNamespace(business_identifier="TOOL-11", display_name=None, mold_number=None)], None

    repo.list_eoats = list_eoats  # type: ignore[method-assign]
    repo.list_machines = list_machines  # type: ignore[method-assign]
    repo.list_tools = list_tools  # type: ignore[method-assign]

    results = repo.search("machine 11")

    assert requested == [("eoat", "11"), ("machine", "11"), ("tool", "11")]
    assert [(item.category, item.identifier, item.subtitle) for item in results] == [("machine", "11", "P4 · Molding")]
