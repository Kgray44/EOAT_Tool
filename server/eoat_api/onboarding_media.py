"""Client for the narrow, root-owned onboarding media promotion broker.

The API never receives write permission to the published media tree.  It asks
the local broker to copy an already-validated staging file into that canonical
tree, create a photo derivative when required, and atomically update the
private manifest.  The broker is deliberately a fixed local socket protocol;
there is no caller-supplied executable, destination root, or shell command.
"""

from __future__ import annotations

import json
import os
import socket
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

from .errors import APIError

_MAX_MESSAGE_BYTES = 1024 * 1024


class MediaPromotionUnavailable(APIError):
    def __init__(self, message: str = "Canonical media promotion is unavailable.") -> None:
        super().__init__(503, "CANONICAL_MEDIA_PROMOTION_UNAVAILABLE", message, retryable=True)


class MediaPromotionRejected(APIError):
    def __init__(self, message: str = "Canonical media promotion could not be completed.") -> None:
        super().__init__(422, "CANONICAL_MEDIA_PROMOTION_REJECTED", message)


@dataclass(frozen=True)
class PromotionItem:
    media_id: int
    document_uuid: str
    source_path: str
    file_name: str
    is_photo: bool

    def as_dict(self) -> dict[str, object]:
        UUID(self.document_uuid)
        return {
            "media_id": self.media_id,
            "document_uuid": self.document_uuid,
            "source_path": self.source_path,
            "file_name": self.file_name,
            "is_photo": self.is_photo,
        }


@dataclass(frozen=True)
class PromotedMedia:
    media_id: int
    document_uuid: str
    storage_path: str
    checksum_sha256: str
    file_size_bytes: int


def _socket_path() -> Path:
    configured = os.getenv("EOAT_ONBOARDING_MEDIA_SOCKET", "").strip()
    if not configured:
        raise MediaPromotionUnavailable("Canonical media promotion is not configured.")
    path = Path(configured)
    if not path.is_absolute() or ".." in path.parts:
        raise MediaPromotionUnavailable("Canonical media promotion is not safely configured.")
    return path


def _request(payload: dict[str, object]) -> dict[str, Any]:
    encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8") + b"\n"
    if len(encoded) > _MAX_MESSAGE_BYTES:
        raise MediaPromotionRejected("The media promotion request is too large.")
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(30)
            client.connect(str(_socket_path()))
            client.sendall(encoded)
            response = bytearray()
            while not response.endswith(b"\n"):
                chunk = client.recv(min(65536, _MAX_MESSAGE_BYTES - len(response)))
                if not chunk:
                    break
                response.extend(chunk)
                if len(response) > _MAX_MESSAGE_BYTES:
                    raise MediaPromotionUnavailable("Canonical media promotion returned an oversized response.")
    except (OSError, TimeoutError) as exc:
        raise MediaPromotionUnavailable() from exc
    try:
        decoded = json.loads(response.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MediaPromotionUnavailable("Canonical media promotion returned an invalid response.") from exc
    if not isinstance(decoded, dict) or not isinstance(decoded.get("ok"), bool):
        raise MediaPromotionUnavailable("Canonical media promotion returned an invalid response.")
    if not decoded["ok"]:
        # The broker deliberately returns a safe reason code only; it never
        # returns filesystem paths or source bytes to the web process.
        raise MediaPromotionRejected(str(decoded.get("message") or "Canonical media promotion was rejected."))
    return decoded


def promote(items: list[PromotionItem], *, eoat_identifier: str) -> tuple[str, dict[int, PromotedMedia]]:
    if not items:
        return "", {}
    response = _request(
        {
            "operation": "promote",
            "eoat_identifier": eoat_identifier,
            "items": [item.as_dict() for item in items],
        }
    )
    promotion_id = response.get("promotion_id")
    raw_items = response.get("items")
    if not isinstance(promotion_id, str) or not isinstance(raw_items, list):
        raise MediaPromotionUnavailable("Canonical media promotion returned incomplete data.")
    promoted: dict[int, PromotedMedia] = {}
    for raw in raw_items:
        if not isinstance(raw, dict):
            raise MediaPromotionUnavailable("Canonical media promotion returned invalid item data.")
        try:
            item = PromotedMedia(
                media_id=int(raw["media_id"]),
                document_uuid=str(UUID(str(raw["document_uuid"]))),
                storage_path=str(raw["storage_path"]),
                checksum_sha256=str(raw["checksum_sha256"]),
                file_size_bytes=int(raw["file_size_bytes"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise MediaPromotionUnavailable("Canonical media promotion returned invalid item data.") from exc
        if len(item.checksum_sha256) != 64 or item.file_size_bytes < 0:
            raise MediaPromotionUnavailable("Canonical media promotion returned invalid item data.")
        if item.media_id in promoted:
            raise MediaPromotionUnavailable("Canonical media promotion returned duplicate item data.")
        promoted[item.media_id] = item
    if set(promoted) != {item.media_id for item in items}:
        raise MediaPromotionUnavailable("Canonical media promotion did not return every requested item.")
    return promotion_id, promoted


def confirm(promotion_id: str) -> None:
    if promotion_id:
        _request({"operation": "confirm", "promotion_id": promotion_id})


def compensate(promotion_id: str) -> None:
    if promotion_id:
        _request({"operation": "compensate", "promotion_id": promotion_id})
