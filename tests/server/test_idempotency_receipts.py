from datetime import datetime, timezone

from server.eoat_api.security import ActorContext
from server.eoat_api.write_services import idempotent


class ReceiptSession:
    def __init__(self):
        self.receipt = None
        self.flushed = False

    def scalar(self, _statement):
        return None

    def add(self, record):
        self.receipt = record

    def flush(self):
        self.flushed = True


def test_idempotency_receipt_serializes_nested_datetimes_before_commit():
    session = ReceiptSession()
    actor = ActorContext(
        1,
        "test.admin",
        "Test Administrator",
        "ADMINISTRATOR",
        "request-1",
        None,
        None,
    )
    result = idempotent(
        session,
        actor,
        "admin.users.access.assign",
        "receipt-with-datetime",
        {"user_id": "user-1"},
        lambda: {"user": {"last_sign_in": datetime(2026, 8, 20, tzinfo=timezone.utc)}},
    )

    assert result["user"]["last_sign_in"] == "2026-08-20T00:00:00+00:00"
    assert session.receipt.response_json == result
    assert session.flushed is True
