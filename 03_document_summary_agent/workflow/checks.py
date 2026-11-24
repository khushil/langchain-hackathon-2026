"""Run-level check results: the counts a run states and reconciles."""

from __future__ import annotations

from utils.state import RunCheck


def run_check(check: str, subject: str, *, passed: bool, detail: str) -> dict[str, RunCheck]:
    """Return one run check as a state write.

    Args:
        check: The check's name and version, for example ``units-accounted.v1``.
        subject: What it was run on, for example a source id or ``section:7``.
        passed: Whether it passed.
        detail: The counts or the finding, in plain words.

    Returns:
        ``{"<check>|<subject>": RunCheck}``, ready for the state's ``check_results``.
    """
    return {
        f"{check}|{subject}": RunCheck(
            check=check, subject_id=subject, outcome="pass" if passed else "fail", detail=detail
        )
    }
