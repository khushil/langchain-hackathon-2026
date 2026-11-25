"""The read step: one model call reads one application into the applicant's details."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import ValidationError

from context.extraction import ApplicantRead, read_applicant
from context.reader import read_applications
from fsi_common.ids import digest_text
from utils import PROJECT_ROOT
from utils.kyc_state import fact_writes
from utils.models import ROLE_MODELS
from workflow.checks import run_check
from workflow.engine_state import ReadTask
from workflow.errors import ReadCallError

ModelSource = Callable[[str], BaseChatModel]
"""Gives the chat model for a role; ``get_model`` in production, a scripted reader in tests."""

INSTRUCTIONS = (PROJECT_ROOT / "workflow" / "extraction_instructions.md").read_text(
    encoding="utf-8"
)
PROMPT_VERSION = f"extract-{digest_text(INSTRUCTIONS)[7:15]}"
"""The prompt's version, taken from the digest of its instructions."""


def read_task(customer_id: str, text: str) -> str:
    """Return the task text an application's model call is given.

    Args:
        customer_id: The customer.
        text: The application's text.

    Returns:
        The customer's id and the application.
    """
    return f"Application {customer_id}:\n\n{text}"


def ask_reader(models: ModelSource, customer_id: str, text: str) -> ApplicantRead:
    """Ask the extract model to read one application.

    Args:
        models: Gives the chat model for a role.
        customer_id: The customer.
        text: The application's text.

    Returns:
        The reading the model returned.

    Raises:
        ReadCallError: If the reply is not a reading of an application.
    """
    chat = models("extract").with_structured_output(ApplicantRead)
    reply = chat.invoke([SystemMessage(INSTRUCTIONS), HumanMessage(read_task(customer_id, text))])
    if isinstance(reply, ApplicantRead):
        return reply
    try:
        return ApplicantRead.model_validate(reply)
    except ValidationError as exc:
        raise ReadCallError(
            f"The model's reply for {customer_id} is not a reading of the application: {exc}"
        ) from exc


def make_read_step(models: ModelSource) -> Callable[[ReadTask], dict[str, Any]]:
    """Build the read step, which reads one application with the model ``models`` gives.

    Args:
        models: Gives the chat model for a role.

    Returns:
        The graph node for one application.
    """

    def read_step(task: ReadTask) -> dict[str, Any]:
        customer_id = task["customer_id"]
        applications = read_applications([customer_id])
        unit = applications.units[0]
        text = applications.unit_text[unit.id]
        reading = ask_reader(models, customer_id, text)
        read = read_applicant(
            reading,
            source=applications.source,
            unit=unit,
            text=text,
            model=ROLE_MODELS["extract"].model,
            prompt_version=PROMPT_VERSION,
        )
        passed = [f for f in read.facts if f.passed_checks]
        checks = run_check(
            "applicant-read.v1",
            customer_id,
            passed=True,
            detail=f"{len(passed)} of {len(read.facts)} facts read from {customer_id} passed "
            f"their checks; {len(read.questions)} detail(s) asked about",
        )
        return {
            "raw_reads": {customer_id: reading.model_dump(mode="json")},
            "applicants": {customer_id: read.applicant.to_json()},
            "facts": fact_writes(read.facts),
            "open_questions": {q.id: q.to_json() for q in read.questions},
            "check_results": checks,
        }

    return read_step
