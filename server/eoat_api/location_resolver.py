"""Canonical EOAT physical-location resolver.

Compatibility is intentionally absent.  Lifecycle events win only when their
real event time is provably later than the latest authoritative observation.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from .contracts import CurrentEOATLocation
from .database import models as db


def _day(value: datetime | date | None) -> date | None:
    return value.date() if isinstance(value, datetime) else value


def _observation_key(row: db.EOATLocationObservation) -> tuple[date, datetime, int]:
    day = row.observed_on or _day(row.observed_at) or date.min
    exact = row.observed_at or datetime.min
    return day, exact, row.id


def _observed_contract(row: db.EOATLocationObservation, machine: str | None, storage: str | None) -> CurrentEOATLocation:
    return CurrentEOATLocation(
        state=row.state,
        source="OBSERVATION",
        machine_number=machine,
        storage_location=storage,
        observed_at=row.observed_at,
        observed_on=row.observed_on,
        observation_precision=row.observation_precision,
        confidence=row.confidence,
        resolution_status=row.resolution_status,
        evidence=row.original_source_wording,
        observation_uuid=row.observation_uuid,
        conflict_group_uuid=row.conflict_group_uuid,
    )


def resolve_eoat_locations(session: Session, eoat_ids: Iterable[int]) -> dict[int, CurrentEOATLocation]:
    ids = sorted(set(eoat_ids))
    if not ids:
        return {}
    observations: dict[int, list[tuple[db.EOATLocationObservation, str | None, str | None]]] = defaultdict(list)
    for row, machine, storage in session.execute(
        select(db.EOATLocationObservation, db.Machine.machine_number, db.StorageLocation.location_name)
        .outerjoin(db.Machine, db.Machine.id == db.EOATLocationObservation.machine_id)
        .outerjoin(db.StorageLocation, db.StorageLocation.id == db.EOATLocationObservation.storage_location_id)
        .where(
            db.EOATLocationObservation.eoat_id.in_(ids),
            db.EOATLocationObservation.is_authoritative.is_(True),
            db.EOATLocationObservation.superseded_by_observation_id.is_(None),
        )
    ):
        observations[row.eoat_id].append((row, machine, storage))

    installs = {row.eoat_id: (row, number) for row, number in session.execute(
        select(db.EOATInstallation, db.Machine.machine_number)
        .join(db.Machine, db.Machine.id == db.EOATInstallation.machine_id)
        .where(db.EOATInstallation.eoat_id.in_(ids), db.EOATInstallation.removed_at.is_(None))
    )}
    stored = {row.eoat_id: (row, name) for row, name in session.execute(
        select(db.EOATStorageAssignment, db.StorageLocation.location_name)
        .join(db.StorageLocation, db.StorageLocation.id == db.EOATStorageAssignment.storage_location_id)
        .where(db.EOATStorageAssignment.eoat_id.in_(ids), db.EOATStorageAssignment.removed_from_storage_at.is_(None))
    )}

    results: dict[int, CurrentEOATLocation] = {}
    for eoat_id in ids:
        obs_tuple = max(observations.get(eoat_id, []), key=lambda value: _observation_key(value[0]), default=None)
        install = installs.get(eoat_id)
        storage = stored.get(eoat_id)
        if install and storage:
            results[eoat_id] = CurrentEOATLocation(
                state="CONFLICTING", source="LIFECYCLE_EVENT", confidence="REVIEW_REQUIRED",
                resolution_status="REVIEW_REQUIRED", evidence="Active installation and active storage lifecycle records both exist.",
            )
            continue
        event_state, event_time, machine_number, storage_name = None, None, None, None
        if install:
            event_state, event_time, machine_number = "INSTALLED", install[0].installed_at, install[1]
        elif storage:
            event_state, event_time, storage_name = "STORED", storage[0].stored_at, storage[1]
        if event_state and obs_tuple:
            observation = obs_tuple[0]
            observation_day = observation.observed_on or _day(observation.observed_at)
            if observation.observation_precision == "DATE" and _day(event_time) == observation_day:
                results[eoat_id] = CurrentEOATLocation(
                    state="CONFLICTING", source="RESOLVER", confidence="REVIEW_REQUIRED",
                    resolution_status="REVIEW_REQUIRED",
                    evidence="A date-only observation and lifecycle event occur on the same day; chronology is unknowable.",
                )
                continue
            if observation_day is not None and (_day(event_time) or date.min) <= observation_day:
                results[eoat_id] = _observed_contract(*obs_tuple)
                continue
        if event_state:
            results[eoat_id] = CurrentEOATLocation(
                state=event_state, source="LIFECYCLE_EVENT", machine_number=machine_number,
                storage_location=storage_name, observed_at=event_time, observation_precision="TIMESTAMP",
                confidence="HIGH", resolution_status="CURRENT",
                evidence="Current lifecycle event is later than all authoritative observations.",
            )
        elif obs_tuple:
            results[eoat_id] = _observed_contract(*obs_tuple)
        else:
            results[eoat_id] = CurrentEOATLocation(
                state="UNKNOWN", source="NONE", confidence="LOW", resolution_status="CURRENT",
                evidence="No active lifecycle event or authoritative location observation exists.",
            )
    return results


def resolve_eoat_location(session: Session, eoat_id: int) -> CurrentEOATLocation:
    return resolve_eoat_locations(session, [eoat_id])[eoat_id]
