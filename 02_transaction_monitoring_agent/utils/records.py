"""This topic's fact kinds and the words its sources and facts use.

A transaction of the stream is a source unit with the anchor ``tx:TX-1003``, and a customer's
profile row is a unit with the anchor ``customer:USR-001``. The starter's agent records an
assessment for each transaction (risk score, confidence, decision and reason); plain code turns
that record into a cited fact whose quote is the transaction's own field values.
"""

from __future__ import annotations

from fsi_common.records import fact_topic_context

FACT_KINDS = ("transaction_assessment", "customer_attribute")
"""The closed list of fact kinds for this topic: what the assessor recorded about a transaction,
and what the customer's profile row says about the customer."""

COPIED_ATTRIBUTES = (
    "user_id",
    "timestamp",
    "merchant",
    "category",
    "amount",
    "currency",
    "country",
    "channel",
)
"""The attributes this topic copies word for word from a transaction's row.

With the kind, the transaction and the quote they make an assessment's id, so the same transaction
read again is the same fact. The score, the decision and the reason are the assessor's own, so they
stay out of the id: a rerun that scores a transaction differently is the same fact with changed
content, and a decision made on it asks again."""

FACT_CONTEXT = fact_topic_context(kinds=FACT_KINDS, copied_attributes=COPIED_ATTRIBUTES)
"""The validation context that holds the topic's declaration, which each of its facts needs."""

TRANSACTION_SCHEME = "tx"
CUSTOMER_SCHEME = "customer"


def transaction_anchor(transaction_id: str) -> str:
    """Return the anchor of a transaction.

    Args:
        transaction_id: The transaction's own id, for example ``TX-1003``.

    Returns:
        ``tx:TX-1003``.
    """
    return f"{TRANSACTION_SCHEME}:{transaction_id}"


def customer_anchor(user_id: str) -> str:
    """Return the anchor of a customer's profile row.

    Args:
        user_id: The customer's own id, for example ``USR-001``.

    Returns:
        ``customer:USR-001``.
    """
    return f"{CUSTOMER_SCHEME}:{user_id}"
