"""This topic's fact kinds, the attributes it copies from the source, and its anchors.

The starter's profile (name, date of birth, nationality, occupation, source of funds) becomes one
fact for each detail, each quoting the application; a screening of one application against one
list entry becomes a fact when the names are alike; and the proposal for an application is a fact
too, so that a person's decision on it is carried to a later run by the same rule as any other.
"""

from __future__ import annotations

from fsi_common.records import fact_topic_context

APPLICANT_KINDS = (
    "applicant_name",
    "birth_date",
    "nationality",
    "occupation",
    "source_of_funds",
    "funds_amount",
    "relation",
)
"""The kinds of fact read from an application: one for each detail the application states."""

FACT_KINDS = (*APPLICANT_KINDS, "screening", "proposal")
"""The closed list of fact kinds for this topic."""

COPIED_ATTRIBUTES = ("amount",)
"""The attributes this topic copies word for word from the application: the amount as written.

With the kind, the unit and the quote they make a fact's id. Everything else a fact holds is the
model's wording (a nationality, an occupation) or code's result (a score), and stays out of the id,
so a rerun that words a detail differently is the same fact, and a decision on it carries over only
while what the person judged is unchanged."""

FACT_CONTEXT = fact_topic_context(kinds=FACT_KINDS, copied_attributes=COPIED_ATTRIBUTES)
"""The validation context that holds the topic's declaration, which ``Fact.build`` needs."""

APPLICATION_SCHEME = "row"
SCREENING_SCHEME = "pair"


def application_anchor(customer_id: str) -> str:
    """Return the anchor of an application unit.

    Args:
        customer_id: The customer's id, for example ``CUST-003``.

    Returns:
        ``row:CUST-003``.
    """
    return f"{APPLICATION_SCHEME}:{customer_id}"


def customer_of_anchor(anchor: str) -> str:
    """Return the customer an application or screening anchor is about.

    Args:
        anchor: ``row:CUST-003`` or ``pair:CUST-003/sanctions-1``.

    Returns:
        The customer's id, ``CUST-003``.
    """
    return anchor.partition(":")[2].partition("/")[0]
