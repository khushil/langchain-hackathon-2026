"""The compliance brief topic's plug-in for the reviewer's application."""

from __future__ import annotations

from pathlib import Path

from starlette.routing import Mount, Route

from fsi_common.app import TopicPlugin
from review_app import routes_facts, routes_policies, routes_review, routes_start
from review_app.context import PREFIX, Services
from review_app.drafts import DraftStore
from review_app.naming import Naming
from review_app.seed import SEED_NAME, seed_compliance_brief
from review_app.service import BriefRuns, EngineMissingError
from review_app.source_view import (
    check_label,
    decision_by,
    decision_line,
    difference_label,
    sentence_end,
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


def keep_state_in(services: Services, folder: Path) -> None:
    """Make the run service and the drafts of a set of services keep their state in a folder.

    Args:
        services: The services of the topic being served; they are changed in place.
        folder: The folder that keeps the runs, their checkpoints, the decisions and the drafts.

    Raises:
        EngineMissingError: If the engine's run service is not part of this build.
        StateFolderError: If the folder cannot be made or a file in it cannot be read.
        DraftFileError: If the file that keeps the drafts cannot be read.
    """
    if BriefRuns is None:
        raise EngineMissingError(
            "The engine that writes briefs is not part of this build, so it has no state to keep."
        )
    runs = BriefRuns(state_dir=folder)
    services.runs = lambda: runs
    services.drafts = DraftStore(folder / "drafts.sqlite")
    services.state_dir = folder


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
    naming = Naming.of(loaded)
    routes: list[Route | Mount] = [
        *routes_start.routes(services),
        *routes_review.routes(services),
        *routes_facts.routes(services),
        *routes_policies.routes(services),
    ]
    return TopicPlugin(
        name=SEED_NAME,
        title="Compliance brief",
        summary=(
            "Read a regulatory document into cited facts and review the brief written from them."
        ),
        prefix=PREFIX,
        routes=routes,
        templates_dir=HERE / "templates",
        static_dir=HERE / "static",
        about=(*ABOUT, *routes_policies.about_lines(services)),
        template_globals={
            "policy_pages": routes_policies.pages_link(services),
            "attribute_rows": naming.attribute_rows,
            "check_label": check_label,
            "decision_by": decision_by,
            "decision_line": decision_line,
            "place_of": naming.place_of,
            "sentence_end": sentence_end,
            "anchor_label_of": naming.place,
        },
        template_filters={"difference_label": difference_label},
        waiting=lambda: count_waiting(services),
        waiting_noun="brief",
        seed=lambda: seed_compliance_brief(services),
        use_state_dir=lambda folder: keep_state_in(services, folder),
    )


PLUGIN = build_plugin()
