"""The KYC onboarding topic's plug-in for the reviewer's application."""

from __future__ import annotations

from pathlib import Path

from starlette.routing import Route

from fsi_common.app import TopicPlugin
from review_app import routes_record, routes_review, routes_start, routes_tables
from review_app.context import PREFIX, Services
from review_app.drafts import DraftStore
from review_app.service import EngineMissingError, make_runs
from review_app.wording import decision_by, decision_line, difference_label, sentence_end

HERE = Path(__file__).parent
NAME = "kyc-onboarding"
ABOUT = (
    "A KYC onboarding batch starts from the applications of people who want an account. Each "
    "application is read into its details, each with the words of the application that state "
    "it, and plain code checks every quote. Each application is then set against every entry of "
    "the sanctions list and the list of politically exposed people, and each screening ends as a "
    "fact or as a score below the floor of likeness.",
    "The applications and both lists are the starter's fictional ones. Where the checks settle an "
    "application, a proposal says so; where they do not, a question puts both readings side by "
    "side. A named person accepts, amends or rejects each proposal in their own words, answers or "
    "accepts each question, and signs the batch or returns it. Nothing is decided for them.",
)


def count_waiting(services: Services) -> int | None:
    """Count the batches that wait for a reviewer, as the topic's own page counts them.

    Args:
        services: The run service and the held decisions.

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
        StateFolderError: If the folder cannot be made or a file in it cannot be read.
        DraftFileError: If the file that keeps the drafts cannot be read.
    """
    runs = make_runs(folder)
    services.runs = lambda: runs
    services.drafts = DraftStore(folder / "drafts.sqlite")
    services.state_dir = folder


def build_plugin(services: Services | None = None) -> TopicPlugin:
    """Build the plug-in over a set of services.

    Args:
        services: The run service and held decisions; the engine's when absent.

    Returns:
        The topic's plug-in.
    """
    from review_app.seed import seed_kyc_onboarding  # the seed imports this module to serve

    services = services or Services()
    pages = routes_review.ReviewPages(services)
    routes: list[Route] = [
        *routes_start.routes(services),
        *pages.routes(),
        *routes_record.routes(services, pages),
        *routes_tables.routes(services),
    ]
    return TopicPlugin(
        name=NAME,
        title="KYC onboarding",
        summary="Screen new applications against the sanctions and PEP lists and review proposals.",
        prefix=PREFIX,
        routes=routes,
        templates_dir=HERE / "templates",
        static_dir=HERE / "static",
        about=ABOUT,
        template_globals={
            "decision_by": decision_by,
            "decision_line": decision_line,
            "sentence_end": sentence_end,
        },
        template_filters={
            "difference_label": difference_label,
            "capitalize_first": lambda text: text[:1].upper() + text[1:],
        },
        waiting=lambda: count_waiting(services),
        waiting_noun="batch",
        seed=lambda: seed_kyc_onboarding(services),
        use_state_dir=lambda folder: keep_state_in(services, folder),
    )


PLUGIN = build_plugin()
