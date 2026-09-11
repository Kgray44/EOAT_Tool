from __future__ import annotations

from types import SimpleNamespace

from server.eoat_api import onboarding_services as onboarding


class _Rows:
    def __init__(self, values):
        self.values = values

    def all(self):
        return self.values


class _Session:
    def __init__(self):
        self.values = iter(
            [
                ["P4-EOAT-0001", "P4-EOAT-0002"],
                ["P4-EOAT-0003"],
                [],
            ]
        )

    def scalars(self, _statement):
        return _Rows(next(self.values))


def test_generated_identifier_uses_observed_plant_sequence_and_reserves_it(monkeypatch):
    draft = SimpleNamespace(
        id=91,
        plant_code="p4",
        payload_json={"identity": {"eoat_type": "Vacuum"}},
        proposed_identifier=None,
        completion_state="INCOMPLETE",
        row_version=1,
        updated_by_user_id=None,
        __tablename__="eoat_onboarding_drafts",
    )
    reserved: list[str] = []
    actor = SimpleNamespace(user_id=7, permits=lambda _permission: True)
    monkeypatch.setattr(onboarding, "_draft", lambda *_args, **_kwargs: draft)
    monkeypatch.setattr(onboarding, "_check_draft_version", lambda *_args: None)
    monkeypatch.setattr(onboarding, "_assert_draft_editor", lambda *_args: None)
    monkeypatch.setattr(onboarding, "_reserve_identifier", lambda _s, _a, _d, value: reserved.append(value))
    monkeypatch.setattr(onboarding, "audit_change", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(onboarding, "record_dict", lambda value: {"row_version": value.row_version})
    monkeypatch.setattr(onboarding, "_draft_summary", lambda _s, value: {"identifier": value.proposed_identifier})

    result = onboarding.generate_identifier(_Session(), actor, "draft-uuid", 1)

    assert reserved == ["P4-EOAT-0004"]
    assert draft.payload_json["identity"]["business_identifier"] == "P4-EOAT-0004"
    assert draft.row_version == 2
    assert result == {"identifier": "P4-EOAT-0004"}
