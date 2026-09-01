from __future__ import annotations

from io import BytesIO

import cv2
import numpy
from fastapi.testclient import TestClient
from pypdf import PdfReader

from server.eoat_api.app import app, repository
from server.eoat_api.contracts import EOATProfile
from server.eoat_api.qr_label_pdf import PAGE_HEIGHT, PAGE_WIDTH, generate_eoat_qr_label_pdf


class _Repository:
    def eoat(self, identifier: str):
        if identifier == "MISSING":
            return None
        return EOATProfile(business_identifier=identifier, is_active=True, row_version=1)


def _client() -> TestClient:
    app.dependency_overrides[repository] = _Repository
    return TestClient(app)


def _image_xobjects(page) -> list[object]:
    resources = page["/Resources"].get_object()
    xobjects = resources["/XObject"].get_object()
    return [item.get_object() for item in xobjects.values() if item.get_object().get("/Subtype") == "/Image"]


def test_qr_label_pdf_is_single_page_exact_geometry_and_contains_the_identifier():
    with _client() as client:
        response = client.get("/api/v1/eoats/CL-EOAT-0047/qr-label.pdf")
    app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/pdf")
    assert response.headers["content-disposition"] == 'inline; filename="EOAT_Atlas_Label_CL-EOAT-0047.pdf"'
    assert response.content.startswith(b"%PDF-")
    reader = PdfReader(BytesIO(response.content))
    assert len(reader.pages) == 1
    page = reader.pages[0]
    assert tuple(float(value) for value in page.mediabox) == (0.0, 0.0, float(PAGE_WIDTH), float(PAGE_HEIGHT))
    assert tuple(float(value) for value in page.cropbox) == (0.0, 0.0, float(PAGE_WIDTH), float(PAGE_HEIGHT))
    assert "EOAT Atlas" in (page.extract_text() or "")
    assert "CL-EOAT-0047" in (page.extract_text() or "")
    assert _image_xobjects(page)


def test_qr_label_pdf_uses_the_canonical_profile_url_and_is_deterministic():
    first, payload = generate_eoat_qr_label_pdf("LONG-EOAT-IDENTIFIER-0000000047", "https://atlas.example")
    second, repeat_payload = generate_eoat_qr_label_pdf("LONG-EOAT-IDENTIFIER-0000000047", "https://atlas.example")

    assert payload == "https://atlas.example/eoats/LONG-EOAT-IDENTIFIER-0000000047"
    assert repeat_payload == payload
    assert first == second
    text = PdfReader(BytesIO(first)).pages[0].extract_text() or ""
    assert "LONG-EOAT-IDENTIFIER-0000000047" in text.replace("\n", "")

    scannable_pdf, scannable_payload = generate_eoat_qr_label_pdf("CL-EOAT-0047", "https://atlas.example")
    image = next(iter(PdfReader(BytesIO(scannable_pdf)).pages[0].images)).image.convert("RGB")
    encoded, _points, _straight = cv2.QRCodeDetector().detectAndDecode(
        cv2.cvtColor(numpy.array(image), cv2.COLOR_RGB2BGR)
    )
    assert encoded == scannable_payload


def test_qr_label_pdf_returns_the_governed_not_found_response():
    with _client() as client:
        response = client.get("/api/v1/eoats/MISSING/qr-label.pdf")
    app.dependency_overrides.clear()

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["detail"]["code"] == "NOT_FOUND"
