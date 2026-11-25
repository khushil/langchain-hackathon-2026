"""Helpers for tests: one application read, screened and proposed on, as the engine does."""

from __future__ import annotations

from kyc_fakes import reading_of

from context.extraction import ApplicantRead, read_applicant
from context.proposals import ApplicationOutcome, assess_application
from context.reader import entries_of, read_applications, read_screenings, screening_anchor
from context.screening import screen_pair


def outcome_of(customer_id: str, reading: ApplicantRead | None = None) -> ApplicationOutcome:
    """Read, screen and propose on one application with the scripted reader."""
    apps = read_applications([customer_id])
    screenings = read_screenings([customer_id])
    unit = apps.units[0]
    text = apps.unit_text[unit.id]
    read = read_applicant(
        reading or reading_of(customer_id),
        source=apps.source,
        unit=unit,
        text=text,
        model="m",
        prompt_version="p",
    )
    by_anchor = {u.anchor: u for u in screenings.units}
    pairs = []
    for entry in entries_of():
        pair_unit = by_anchor[screening_anchor(customer_id, entry.anchor_part)]
        pairs.append(
            screen_pair(
                read.applicant,
                entry,
                source=screenings.source,
                unit=pair_unit,
                unit_text=screenings.unit_text[pair_unit.id],
            )
        )
    return assess_application(
        read,
        pairs,
        source=apps.source,
        unit=unit,
        text=text,
        entries=entries_of(),
    )
