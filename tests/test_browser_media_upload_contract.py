from __future__ import annotations

from base64 import b64encode

import pytest
from pydantic import ValidationError

from server.eoat_api import write_routes
from server.eoat_api.errors import APIError


def test_browser_upload_openapi_uses_the_exact_base64_ceiling() -> None:
    schema = write_routes.BrowserMediaUpload.model_json_schema()

    assert write_routes.MAX_BROWSER_UPLOAD_BYTES == 20 * 1024 * 1024
    assert write_routes.MAX_BROWSER_UPLOAD_BASE64_CHARACTERS == 27_962_028
    assert schema["properties"]["content_base64"]["maxLength"] == write_routes.MAX_BROWSER_UPLOAD_BASE64_CHARACTERS


def test_browser_upload_model_rejects_content_beyond_the_encoded_ceiling() -> None:
    payload = {
        "entity_type": "eoat",
        "entity_identifier": "EOAT-TEST",
        "title": "Contract boundary",
        "file_name": "boundary.txt",
        "content_base64": "A" * (write_routes.MAX_BROWSER_UPLOAD_BASE64_CHARACTERS + 1),
    }

    with pytest.raises(ValidationError) as error:
        write_routes.BrowserMediaUpload.model_validate(payload)

    assert error.value.errors()[0]["type"] == "string_too_long"


def test_browser_upload_decoded_limit_remains_a_defense_in_depth(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(write_routes, "MAX_BROWSER_UPLOAD_BYTES", 3)

    accepted = write_routes._persist_browser_upload("accepted.txt", b64encode(b"abc").decode("ascii"), tmp_path)
    assert accepted.read_bytes() == b"abc"

    with pytest.raises(APIError) as error:
        write_routes._persist_browser_upload("rejected.txt", b64encode(b"abcd").decode("ascii"), tmp_path)

    assert error.value.status_code == 413
    assert error.value.error_code == "WEB_UPLOAD_TOO_LARGE"
    assert not list(tmp_path.glob("*rejected.txt"))
