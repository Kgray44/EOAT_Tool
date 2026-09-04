# ruff: noqa: B008
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .database.session import get_runtime_session, get_write_session
from .onboarding_contracts import (
    OnboardingDraftCreate,
    OnboardingDraftDiscard,
    OnboardingDraftPatch,
    OnboardingFinalize,
    OnboardingMediaArchive,
    OnboardingMediaCreate,
)
from .onboarding_services import (
    create_draft,
    discard_draft,
    finalize_draft,
    list_drafts,
    remove_staged_media,
    require_onboarding_enabled,
    stage_media,
    update_draft,
)
from .security import ActorContext, require

router = APIRouter(prefix="/api/v1/onboarding", tags=["eoat-onboarding"])


@router.get("/status")
def status():
    from .onboarding_services import onboarding_enabled

    return {"enabled": onboarding_enabled()}


@router.get("/drafts")
def drafts(
    session: Session = Depends(get_runtime_session), actor: ActorContext = Depends(require("onboarding.draft.view"))
):
    require_onboarding_enabled()
    return list_drafts(session, actor)


@router.post("/drafts")
def create(
    payload: OnboardingDraftCreate,
    session: Session = Depends(get_write_session),
    actor: ActorContext = Depends(require("onboarding.draft.create")),
):
    require_onboarding_enabled()
    return create_draft(session, actor, payload.model_dump())


@router.get("/drafts/{draft_uuid}")
def get_draft(
    draft_uuid: str,
    session: Session = Depends(get_runtime_session),
    actor: ActorContext = Depends(require("onboarding.draft.view")),
):
    require_onboarding_enabled()
    from .onboarding_services import _draft, _draft_summary

    draft = _draft(session, draft_uuid)
    if draft.created_by_user_id != actor.user_id and not actor.permits("onboarding.draft.review"):
        from .errors import APIError

        raise APIError(403, "PERMISSION_DENIED", "The authenticated identity cannot view this onboarding draft.")
    return _draft_summary(draft)


@router.patch("/drafts/{draft_uuid}")
def update(
    draft_uuid: str,
    payload: OnboardingDraftPatch,
    session: Session = Depends(get_write_session),
    actor: ActorContext = Depends(require("onboarding.draft.edit")),
):
    require_onboarding_enabled()
    return update_draft(session, actor, draft_uuid, payload.model_dump())


@router.post("/drafts/{draft_uuid}/discard")
def discard(
    draft_uuid: str,
    payload: OnboardingDraftDiscard,
    session: Session = Depends(get_write_session),
    actor: ActorContext = Depends(require("onboarding.draft.discard")),
):
    require_onboarding_enabled()
    return discard_draft(session, actor, draft_uuid, payload.expected_row_version, payload.reason)


@router.post("/drafts/{draft_uuid}/media")
def media(
    draft_uuid: str,
    payload: OnboardingMediaCreate,
    expected_row_version: int,
    session: Session = Depends(get_write_session),
    actor: ActorContext = Depends(require("onboarding.draft.edit")),
):
    require_onboarding_enabled()
    return stage_media(
        session, actor, draft_uuid, {**payload.model_dump(), "expected_row_version": expected_row_version}
    )


@router.post("/drafts/{draft_uuid}/media/{media_id}/remove")
def remove_media(
    draft_uuid: str,
    media_id: int,
    payload: OnboardingMediaArchive,
    session: Session = Depends(get_write_session),
    actor: ActorContext = Depends(require("onboarding.draft.edit")),
):
    require_onboarding_enabled()
    return remove_staged_media(session, actor, draft_uuid, media_id, payload.expected_row_version)


@router.post("/drafts/{draft_uuid}/finalize")
def finalize(
    draft_uuid: str,
    payload: OnboardingFinalize,
    session: Session = Depends(get_write_session),
    actor: ActorContext = Depends(require("onboarding.draft.finalize")),
):
    require_onboarding_enabled()
    return finalize_draft(session, actor, draft_uuid, payload.expected_row_version)
