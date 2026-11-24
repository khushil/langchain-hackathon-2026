"""The compliance brief topic's plug-in for the reviewer's application."""

from __future__ import annotations

from pathlib import Path

from starlette.routing import Mount, Route

from fsi_common.app import TopicPlugin
from review_app import routes_facts, routes_review, routes_start
from review_app.context import PREFIX, Services
from review_app.seed import seed_compliance_brief
from review_app.service import EngineMissingError
from review_app.source_view import (
    anchor_label,
    attribute_rows,
    check_label,
    decision_by,
    decision_line,
    difference_label,
    place_of,
)

HERE = Path(__file__).parent
ABOUT = (
    "A compliance brief starts from a regulatory document. The document is read into facts, each "
    "quoting one paragraph word for word, and plain code checks every quote and every deadline "
    "against that paragraph. A brief is then written from the facts that passed, each statement "
    "citing the facts it rests on.",
    "The document here is PS26/4, a fictional policy statement from the starter, and the firm is "
    "Harbour Mutual Bank, also fictional, with its providers from the starter's tables. A named "
    "person reads the brief, opens each statement's source paragraph, accepts, amends or rejects "
    "each fact in their own words, and signs the brief or returns it. Nothing is decided for them.",
)


def count_waiting(services: Services) -> int | None:
    """Count the briefs that wait for a reviewer, as the topic's own page counts them.

    Args:
        services: The run service, library, held decisions and clock.

    Returns:
        The number of runs stopped at the review, or None when the engine is not part of this
        build and so cannot say.
    """
    try:
        runs = services.runs()
    except EngineMissingError:
        return None
    return sum(runs.status(thread) == "awaiting_review" for thread in runs.list_runs())


def build_plugin(services: Services | None = None) -> TopicPlugin:
    """Build the plug-in over a set of services.

    Args:
        services: The run service, library, held decisions and clock; the engine's when absent.

    Returns:
        The topic's plug-in.
    """
    services = services or Services()
    loaded = services.library()  # read once, here; the data does not change while the app runs
    services.library = lambda: loaded
    routes: list[Route | Mount] = [
        *routes_start.routes(services),
        *routes_review.routes(services),
        *routes_facts.routes(services),
    ]
    return TopicPlugin(
        name="compliance-brief",
        title="Compliance brief",
        summary=(
            "Read a regulatory document into cited facts and review the brief written from them."
        ),
        prefix=PREFIX,
        routes=routes,
        templates_dir=HERE / "templates",
        static_dir=HERE / "static",
        about=ABOUT,
        template_globals={
            "attribute_rows": attribute_rows,
            "check_label": check_label,
            "decision_by": decision_by,
            "decision_line": decision_line,
            "place_of": place_of,
            "anchor_label_of": anchor_label,
        },
        template_filters={"difference_label": difference_label},
        waiting=lambda: count_waiting(services),
        waiting_noun="brief",
        seed=lambda: seed_compliance_brief(services),
    )


PLUGIN = build_plugin()
