"""The transaction monitoring topic's plug-in for the reviewer's application."""

from __future__ import annotations

from pathlib import Path

from starlette.routing import Mount, Route

from fsi_common.app import TopicPlugin
from review_app import routes_review, routes_signed, routes_start
from review_app.context import PREFIX, Services
from review_app.drafts import DraftStore
from review_app.seed import SEED_NAME, seed_transaction_monitoring
from review_app.views import (
    check_label,
    decision_by,
    decision_line,
    difference_label,
    outcome_word,
    sentence_end,
)
from workflow.runs import MonitorRuns

HERE = Path(__file__).parent
ABOUT = (
    "Transaction monitoring starts from a customer's card transactions. An agent looks each one "
    "up beside the customer's profile and proposes a risk score, a decision to approve or block, "
    "how sure it is and why. Plain code checks each proposal against the transaction's own line "
    "of the data and the starter's rules, and a transaction with no usable proposal goes to the "
    "reviewer as a question.",
    "The transactions are the starter's fictional card payments for two fictional customers, "
    "Priya Shah in London and Tomás Ferreira in Lisbon. A named person reads each proposal beside "
    "its source, agrees with it, gives their own decision or disagrees, in their own words, and "
    "signs the brief or returns it. Nothing is decided for them, and what reviewers say about a "
    "customer is kept for the next run on that customer.",
)


def count_waiting(services: Services) -> int:
    """Count the runs that wait for a reviewer, as the topic's own page counts them.

    Args:
        services: The run service and held decisions.

    Returns:
        The number of runs stopped at the review.
    """
    runs = services.runs()
    return sum(runs.status(thread) == "awaiting_review" for thread in runs.list_runs())


def keep_state_in(services: Services, folder: Path) -> None:
    """Make the run service and the drafts of a set of services keep their state in a folder.

    Args:
        services: The services of the topic being served; they are changed in place.
        folder: The folder that keeps the runs, their checkpoints, the decisions and the drafts.

    Raises:
        StateFolderError: If the folder cannot be made or a file in it cannot be read.
        DraftFileError: If the file that keeps the drafts cannot be read.
    """
    runs = MonitorRuns(state_dir=folder)
    services.runs = lambda: runs
    services.drafts = DraftStore(folder / "drafts.sqlite")
    services.state_dir = folder


def build_plugin(services: Services | None = None) -> TopicPlugin:
    """Build the plug-in over a set of services.

    Args:
        services: The run service, held decisions and clock; the engine's when absent.

    Returns:
        The topic's plug-in.
    """
    services = services or Services()
    routes: list[Route | Mount] = [
        *routes_start.routes(services),
        *routes_review.routes(services),
        *routes_signed.routes(services),
    ]
    return TopicPlugin(
        name=SEED_NAME,
        title="Transaction monitoring",
        summary=(
            "Review the assessments an agent proposes for a customer's card transactions and "
            "decide each one."
        ),
        prefix=PREFIX,
        routes=routes,
        templates_dir=HERE / "templates",
        static_dir=HERE / "static",
        about=ABOUT,
        template_globals={
            "check_label": check_label,
            "decision_by": decision_by,
            "decision_line": decision_line,
            "outcome_word": outcome_word,
            "sentence_end": sentence_end,
        },
        template_filters={"difference_label": difference_label},
        waiting=lambda: count_waiting(services),
        waiting_noun="customer review",
        seed=lambda: seed_transaction_monitoring(services, build_plugin),
        use_state_dir=lambda folder: keep_state_in(services, folder),
    )


PLUGIN = build_plugin()
__all__ = ["PLUGIN", "build_plugin", "count_waiting", "keep_state_in"]
