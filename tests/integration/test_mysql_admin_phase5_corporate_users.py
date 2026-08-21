from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from uuid import uuid4

import pytest
from sqlalchemy import select

from server.eoat_api.admin import mutation_service
from server.eoat_api.corporate_users import (
    access_state,
    change_explicit_access,
    corporate_user_for_user,
    register_successful_login,
)
from server.eoat_api.database import models as db
from server.eoat_api.database.session import create_session_factory
from server.eoat_api.errors import APIError
from server.eoat_api.security import ActorContext

pytestmark = pytest.mark.skipif(
    os.getenv("EOAT_DB_NAME") != "eoat_atlas_test",
    reason="Phase 5 corporate-user integration requires EOAT_DB_NAME=eoat_atlas_test",
)


def test_real_mysql_corporate_registry_precedence_fallback_and_session_revocation():
    """Exercise the registry on the protected test schema without committing data."""

    factory = create_session_factory(migration=True)
    now = datetime.now(timezone.utc)
    suffix = uuid4().hex[:12]
    group = f"CN=EOAT Phase5 Test {suffix},OU=Test,DC=example,DC=invalid"
    with factory() as session:
        user = db.User(
            external_identity=f"phase5.{suffix}@example.invalid",
            username=f"phase5.{suffix}",
            display_name="Phase 5 MySQL Test User",
            authentication_provider="kerberos_form",
            last_login_at=now,
            source_system="integration_test",
            created_at=now,
            updated_at=now,
        )
        session.add(user)
        session.flush()
        registry = register_successful_login(
            session,
            user,
            provider="kerberos_form",
            canonical_identity=user.external_identity,
            display_name=user.display_name,
        )
        session.add(
            db.ExternalGroupRoleMapping(
                provider="kerberos_form",
                external_group_identifier=group,
                role_code="ADMINISTRATOR",
                created_at=now,
                updated_at=now,
            )
        )
        session.add(
            db.CorporateAuthenticationSession(
                session_reference=str(uuid4()),
                token_hash=sha256(f"token-{suffix}".encode()).hexdigest(),
                csrf_token_hash=sha256(f"csrf-{suffix}".encode()).hexdigest(),
                user_id=user.id,
                provider="kerberos_form",
                roles_json=["ADMINISTRATOR"],
                authorization_groups_json=[group],
                authenticated_at=now,
                issued_at=now,
                expires_at=now + timedelta(minutes=10),
                last_seen_at=now,
            )
        )
        session.flush()

        assert corporate_user_for_user(session, user.id) is registry
        assert access_state(session, registry, groups=(group,))["effective_role"] == "ADMINISTRATOR"
        before, after, revoked = change_explicit_access(
            session,
            registry,
            action="assign",
            role_code="ADMIN_ACCESS_MANAGER",
            reason="Phase 5 real-MySQL qualification",
            actor_user_id=user.id,
            expected_row_version=registry.row_version,
        )
        assert before["access_source"] == "corporate_group"
        assert after["access_source"] == "explicit_user_assignment"
        assert revoked == 1
        _before, fallback, _revoked = change_explicit_access(
            session,
            registry,
            action="remove",
            role_code=None,
            reason="Phase 5 fallback qualification",
            actor_user_id=user.id,
            expected_row_version=registry.row_version,
        )
        assert fallback["effective_role"] == "ADMINISTRATOR"
        assert fallback["access_source"] == "corporate_group"
        _before, denied, _revoked = change_explicit_access(
            session,
            registry,
            action="revoke",
            role_code=None,
            reason="Phase 5 deny qualification",
            actor_user_id=user.id,
            expected_row_version=registry.row_version,
        )
        assert denied["access_source"] == "explicit_deny"
        session.rollback()


def test_real_mysql_group_policy_editor_persists_audits_and_rejects_invalid_or_duplicate_mappings():
    """Exercise the governed group-policy service against the sanctioned MySQL schema."""

    factory = create_session_factory(migration=True)
    now = datetime.now(timezone.utc)
    suffix = uuid4().hex[:12]
    actor = ActorContext(
        user_id=0,
        identity=f"group-policy.{suffix}@example.invalid",
        display_name="Group Policy Integration Administrator",
        role="ADMINISTRATOR",
        request_id=f"group-policy-{suffix}",
        application_instance_id=None,
        client_version="integration-test",
    )
    with factory() as session:
        actor_user = db.User(
            external_identity=actor.identity,
            username=f"group-policy.{suffix}",
            display_name=actor.display_name,
            authentication_provider="kerberos_form",
            last_login_at=now,
            source_system="integration_test",
            created_at=now,
            updated_at=now,
        )
        session.add(actor_user)
        session.flush()
        actor = ActorContext(
            user_id=actor_user.id,
            identity=actor.identity,
            display_name=actor.display_name,
            role="ADMINISTRATOR",
            request_id=actor.request_id,
            application_instance_id=None,
            client_version="integration-test",
        )
        group = f"CN=EOAT Group Policy {suffix},OU=Test,DC=example,DC=invalid"
        created = mutation_service.create_group_policy_governed(
            session, actor, group, "VIEWER", "Real-MySQL group policy creation"
        )
        policy = created["policy"]
        assert policy["corporate_group"] == group
        assert policy["row_version"] == 1
        assert created["audit_event_id"]
        assert (
            session.scalar(select(db.AuditEvent).where(db.AuditEvent.event_id == created["audit_event_id"])) is not None
        )

        with pytest.raises(APIError) as duplicate:
            mutation_service.create_group_policy_governed(session, actor, group, "VIEWER", "Duplicate policy must fail")
        assert duplicate.value.error_code == "GROUP_POLICY_DUPLICATE"
        with pytest.raises(APIError) as invalid:
            mutation_service.create_group_policy_governed(
                session,
                actor,
                f"CN=EOAT Invalid {suffix},OU=Test,DC=example,DC=invalid",
                "NOT_A_ROLE",
                "Invalid role must fail",
            )
        assert invalid.value.error_code == "INVALID_ROLE"

        changed = mutation_service.update_group_policy_governed(
            session, actor, policy["id"], "ENGINEER", None, 1, "Real-MySQL role correction"
        )
        assert changed["policy"]["role_code"] == "ENGINEER"
        assert changed["policy"]["row_version"] == 2
        archived = mutation_service.deactivate_group_policy_governed(
            session, actor, policy["id"], 2, "Real-MySQL policy deactivation"
        )
        assert archived["policy"]["status"] == "inactive"
        assert archived["revoked_session_count"] >= 0
        with pytest.raises(APIError) as stale:
            mutation_service.update_group_policy_governed(
                session, actor, policy["id"], None, True, 1, "Stale version must fail"
            )
        assert stale.value.error_code == "STALE_RECORD_VERSION"
        session.rollback()
