from __future__ import annotations

from dataclasses import dataclass

from .page_registry import PAGE_SPECS, page_specs_by_section


@dataclass(frozen=True)
class NavItem:
    label: str
    page_key: str


@dataclass(frozen=True)
class NavSection:
    label: str
    items: list[NavItem]


NAV_SECTIONS = [
    NavSection(section_label, [NavItem(spec.label, spec.key) for spec in specs])
    for section_label, specs in page_specs_by_section()
]

NAV_ITEMS = [item for section in NAV_SECTIONS for item in section.items]

assert [item.page_key for item in NAV_ITEMS] == [spec.key for spec in PAGE_SPECS]
