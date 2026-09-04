# ruff: noqa: B008
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .database.session import get_runtime_session, get_write_session
from .onboarding_contracts import (
    EOATEngineeringPatch,
    OnboardingDraftCreate,
    OnboardingDraftDiscard,
    OnboardingDraftPatch,
    OnboardingFinalize,
    OnboardingIdentifierGenerate,
    OnboardingMediaArchive,
    OnboardingMediaCreate,
    OnboardingMediaUpload,
)
from .onboarding_services import (
    create_draft,
    discard_draft,
    engineering_profile,
    finalize_draft,
    generate_identifier,
    list_drafts,
    remove_staged_media,
    require_onboarding_enabled,
    review_draft,
    stage_media,
    stage_uploaded_media,
    update_draft,
    update_engineering_profile,
)
from .security import ActorContext, require, require_any

router = APIRouter(prefix="/api/v1/onboarding", tags=["eoat-onboarding"])


@router.get("/status")
def status():
    from .onboarding_services import onboarding_enabled

    return {"enabled": onboarding_enabled()}


@router.get("/eoats/{identifier}/engineering")
def get_engineering(identifier: str, session: Session = Depends(get_runtime_session)):
    """Follow the established normal-profile read access model.

    Existing EOAT profile reads are not permission-gated by a synthetic
    ``eoat.view`` permission, so this extension must not be stricter than the
    record it describes. Editing remains guarded by ``eoat.edit``.
    """
    require_onboarding_enabled()
    return engineering_profile(session, identifier)


@router.patch("/eoats/{identifier}/engineering")
def patch_engineering(
    identifier: str,
    payload: EOATEngineeringPatch,
    session: Session = Depends(get_write_session),
    actor: ActorContext = Depends(require("eoat.edit")),
):
    require_onboarding_enabled()
    return update_engineering_profile(session, actor, identifier, payload.model_dump(exclude_unset=True))


@router.get("/drafts")
def drafts(
    session: Session = Depends(get_runtime_session),
    actor: ActorContext = Depends(
        require_any("onboarding.draft.view", "onboarding.draft.review", "onboarding.draft.finalize")
    ),
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
    actor: ActorContext = Depends(
        require_any("onboarding.draft.view", "onboarding.draft.review", "onboarding.draft.finalize")
    ),
):
    require_onboarding_enabled()
    from .onboarding_services import _draft, _draft_summary

    draft = _draft(session, draft_uuid)
    from .onboarding_services import _assert_draft_viewer

    _assert_draft_viewer(actor, draft)
    return _draft_summary(session, draft)


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


@router.post("/drafts/{draft_uuid}/identifier/generate")
def generate_draft_identifier(
    draft_uuid: str,
    payload: OnboardingIdentifierGenerate,
    session: Session = Depends(get_write_session),
    actor: ActorContext = Depends(require("onboarding.draft.edit")),
):
    require_onboarding_enabled()
    return generate_identifier(session, actor, draft_uuid, payload.expected_row_version)


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


@router.post("/drafts/{draft_uuid}/media/upload")
def upload_media(
    draft_uuid: str,
    payload: OnboardingMediaUpload,
    expected_row_version: int,
    session: Session = Depends(get_write_session),
    actor: ActorContext = Depends(require("onboarding.draft.edit")),
):
    require_onboarding_enabled()
    return stage_uploaded_media(
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


@router.get("/drafts/{draft_uuid}/review")
def review(
    draft_uuid: str,
    session: Session = Depends(get_runtime_session),
    actor: ActorContext = Depends(
        require_any("onboarding.draft.view", "onboarding.draft.review", "onboarding.draft.finalize")
    ),
):
    require_onboarding_enabled()
    return review_draft(session, actor, draft_uuid)
