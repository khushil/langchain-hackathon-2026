"""Transaction monitoring's part of the offline edition: what to start and where the file opens."""

from __future__ import annotations

from collections.abc import Callable

from langchain_core.language_models import BaseChatModel
from starlette.applications import Starlette
from starlette.testclient import TestClient

from fsi_common.app import AppConfig, create_app
from fsi_common.app.offline import OfflineExportError, OfflineTopic, replay_only
from review_app.context import Services, run_url
from review_app.plugin import build_plugin
from review_app.seed import seed_transaction_monitoring
from workflow.runs import MonitorRuns

SECRET = b"offline-export"


def build_app(models: Callable[[str], BaseChatModel] | None = None) -> Starlette:
    """Build the application over a run service of its own, on replayed model calls.

    Args:
        models: Gives the chat model for a role; the replayed recordings when absent.

    Returns:
        The application, serving the transaction monitoring topic, with its services kept in
        ``app.state.services`` for the seed.
    """
    with replay_only():
        runs = MonitorRuns(models=models)
    services = Services(runs=lambda: runs)
    config = AppConfig(secret=SECRET, topic_folders=())
    app = create_app(config, topics=[build_plugin(services)])
    app.state.services = services
    return app


def seed(client: TestClient) -> str:
    """Make the starting work through the application's own routes and name the page to open.

    The starting work is a run signed by the fictional reviewer and a run waiting for a reviewer
    that arrives with the first run's decisions carried; the file opens on the waiting run.

    Args:
        client: A client of the application ``build_app`` made.

    Returns:
        The address of the waiting run's review page.

    Raises:
        ReplayMissError: If a model call has no recording; its message names the request's hash.
        OfflineExportError: If the starting work leaves no run waiting for a reviewer.
    """
    services: Services = client.app.state.services
    seed_transaction_monitoring(services, build_plugin)
    runs = services.runs()
    waiting = [t for t in runs.list_runs() if runs.status(t) == "awaiting_review"]
    if not waiting:
        raise OfflineExportError("The starting work left no run waiting for a reviewer.")
    return run_url(waiting[0], "review")


HOOK = OfflineTopic(name="transaction-monitoring", build_app=build_app, seed=seed)
