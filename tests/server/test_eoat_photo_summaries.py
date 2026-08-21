from __future__ import annotations

from types import SimpleNamespace

from server.eoat_api.repositories import AtlasRepository


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _PhotoSummarySession:
    def __init__(self, eoat_rows, photo_rows):
        self._eoat_rows = eoat_rows
        self._photo_rows = photo_rows
        self._execute_count = 0

    def scalar(self, *_args, **_kwargs):
        return len(self._eoat_rows)

    def execute(self, *_args, **_kwargs):
        self._execute_count += 1
        return _Rows(self._eoat_rows if self._execute_count == 1 else self._photo_rows)


def _eoat(eoat_id: int = 7):
    return SimpleNamespace(
        id=eoat_id,
        business_identifier="EOAT-PHOTO-7",
        legacy_identifier=None,
        display_name="Photo fixture",
        number_of_parts_picked=None,
        is_active=True,
        row_version=1,
        updated_at=0,
    )


def test_list_eoats_uses_explicit_profile_photo_and_real_web_availability(monkeypatch):
    session = _PhotoSummarySession(
        [(_eoat(), None, None, None, None)],
        [
            (7, "fallback-photo", "C:/photos/fallback.jpg", "fallback.jpg", False, True, 0),
            (7, "explicit-profile", "C:/photos/profile.png", "profile.png", True, False, 99),
        ],
    )
    checked_paths: list[str] = []
    monkeypatch.setattr(
        "server.eoat_api.repositories.content_is_available",
        lambda path: checked_paths.append(path) or path.endswith("profile.png"),
    )

    items, _pagination = AtlasRepository(session).list_eoats(active=None)

    assert items[0].photo_document_uuid == "explicit-profile"
    assert items[0].photo_available_through_web is True
    assert checked_paths == ["C:/photos/profile.png"]


def test_list_eoats_reports_a_selected_photo_as_unavailable_when_its_file_is_not_browser_safe(monkeypatch):
    session = _PhotoSummarySession(
        [(_eoat(), None, None, None, None)],
        [(7, "unavailable-photo", "C:/photos/missing.jpg", "missing.jpg", False, False, 0)],
    )
    monkeypatch.setattr("server.eoat_api.repositories.content_is_available", lambda _path: False)

    items, _pagination = AtlasRepository(session).list_eoats(active=None)

    assert items[0].photo_document_uuid == "unavailable-photo"
    assert items[0].photo_available_through_web is False


class _GallerySession:
    def __init__(self, document_rows, selection_rows):
        self._document_rows = document_rows
        self._selection_rows = selection_rows
        self._execute_count = 0

    def execute(self, *_args, **_kwargs):
        self._execute_count += 1
        return _Rows(self._document_rows if self._execute_count == 1 else self._selection_rows)

    def scalars(self, *_args, **_kwargs):
        return []


def test_eoat_photo_gallery_starts_with_the_same_server_selected_photo():
    secondary = SimpleNamespace(
        id=10,
        document_uuid="secondary-photo",
        document_number=None,
        title="Secondary",
        description=None,
        file_name="a-secondary.jpg",
        storage_path="C:/photos/secondary.jpg",
        mime_type="image/jpeg",
    )
    selected = SimpleNamespace(
        id=11,
        document_uuid="selected-photo",
        document_number=None,
        title="Selected",
        description=None,
        file_name="z-selected.jpg",
        storage_path="C:/photos/selected.jpg",
        mime_type="image/jpeg",
    )
    secondary_photo = SimpleNamespace(photo_view_type=None, captured_at=None, caption=None, is_profile_photo=False)
    selected_photo = SimpleNamespace(photo_view_type=None, captured_at=None, caption=None, is_profile_photo=True)
    session = _GallerySession(
        [(secondary, secondary_photo), (selected, selected_photo)],
        [
            (7, "secondary-photo", "C:/photos/secondary.jpg", "a-secondary.jpg", False, False, 0),
            (7, "selected-photo", "C:/photos/selected.jpg", "z-selected.jpg", True, False, 0),
        ],
    )

    photos = AtlasRepository(session).documents("eoat", 7, photos_only=True)

    assert [photo.document_uuid for photo in photos] == ["selected-photo", "secondary-photo"]
