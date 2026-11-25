"""A scripted reader for the 25 applications, standing in for the model in tests.

The name and the date of birth are the application's own words (the names are listed here and
a test confirms each is written in its application); the other details quote the application's
opening words, so every check passes. It reads no label and no list: what the engine makes of a
reading is the engine's own.
"""

from __future__ import annotations

import re
import threading
from typing import Any

from langchain_core.runnables import RunnableLambda

from context.extraction import ApplicantRead, Detail, RelationRead
from utils import db

NAMES = {
    "CUST-001": "Sarah Mitchell",
    "CUST-002": "Viktor Harlan",
    "CUST-003": "Dmitri Volkonsky",
    "CUST-004": "Priya Raman",
    "CUST-005": "Marcus Delacroix",
    "CUST-006": "Omar Haddad",
    "CUST-007": "Chloe Nakamura",
    "CUST-008": "Thomas O'Brien",
    "CUST-009": "Grace Okafor",
    "CUST-010": "Lars Eriksson",
    "CUST-011": "Amara Quillon",
    "CUST-012": "Helga Brandt",
    "CUST-013": "Tomas Verretti",
    "CUST-014": "Oskar Lindqvist",
    "CUST-015": "Marta Harlan",
    "CUST-016": "Rurik Zelenko",
    "CUST-017": "Malik Dovrany",
    "CUST-018": "Ivana Strahov",
    "CUST-019": "Anselm Rygaard",
    "CUST-020": "Nadia Karimova",
    "CUST-021": "Victor Harlan",
    "CUST-022": "Isabelle Fontaine",
    "CUST-023": "Teodore Ilkanen",
    "CUST-024": "Sofia Marchetti",
    "CUST-025": "Lena Brandvold",
}
MONTH_NAMES = (
    "January February March April May June July August September October November December"
)
MONTHS = {m: i for i, m in enumerate(MONTH_NAMES.split(), 1)}
DATE = re.compile(r"(\d{1,2}) ([A-Z][a-z]+) (\d{4})")
RELATIONS = {
    "CUST-015": RelationRead(
        relation="husband",
        quote="my husband is a senior government official in Valdoria",
        related_name=None,
        related_office="senior government official in Valdoria",
    )
}


def application_text(customer_id: str) -> str:
    """Return an application's text from the starter's table."""
    return db.get("applications", customer_id=customer_id)["application"]


def reading_of(customer_id: str, *, name: str | None = None) -> ApplicantRead:
    """Return the scripted reading of one application.

    Args:
        customer_id: The customer.
        name: A name to give instead of the application's own, to plant a misreading.

    Returns:
        The reading, whose name and date of birth are the application's own words.
    """
    text = application_text(customer_id)
    day, month, year = DATE.search(text).groups()
    iso = f"{year}-{MONTHS[month]:02d}-{int(day):02d}"
    written = NAMES[customer_id]
    opening = re.split(r"(?<=[.!?]) ", text)[0].rstrip(".")
    amount = re.findall(r"[$£€][\d,]+(?: a (?:month|year))?", text)[-1]
    return ApplicantRead(
        full_name=Detail(value=name or written, quote=written),
        date_of_birth=Detail(value=iso, quote=f"{day} {month} {year}"),
        nationality=Detail(value="stated", quote=opening),
        occupation=Detail(value="stated", quote=opening),
        source_of_funds=Detail(value="stated", quote=opening),
        funds_amount=Detail(value=amount, quote=amount),
        relation=RELATIONS.get(customer_id),
    )


class ScriptedReader:
    """A ``ModelSource``: asks of the ``extract`` role are answered from ``reading_of``."""

    def __init__(
        self,
        *,
        readings: dict[str, ApplicantRead] | None = None,
        gate: threading.Event | None = None,
        fail_for: tuple[str, ...] = (),
    ) -> None:
        self.readings = readings or {}
        self.gate = gate
        self.fail_for = fail_for
        self.asked: list[str] = []
        self.roles: list[str] = []

    def __call__(self, role: str) -> Any:
        self.roles.append(role)
        reader = self

        class Chat:
            def with_structured_output(self, schema: Any, **kwargs: Any) -> RunnableLambda:
                def read(messages: Any) -> ApplicantRead:
                    text = "\n".join(str(getattr(m, "content", m)) for m in messages)
                    for row in db.table("applications"):
                        if row["application"] in text:
                            if reader.gate is not None:
                                reader.gate.wait(10)
                            if row["customer_id"] in reader.fail_for:
                                raise RuntimeError(
                                    f"the model call for {row['customer_id']} failed"
                                )
                            reader.asked.append(row["customer_id"])
                            return reader.readings.get(
                                row["customer_id"], reading_of(row["customer_id"])
                            )
                    raise AssertionError("the reader was given no application of the table")

                return RunnableLambda(read)

        return Chat()
