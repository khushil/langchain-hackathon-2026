"""The KYC topic's part of the offline edition: what to start and where the file opens."""

from __future__ import annotations

from starlette.applications import Starlette
from starlette.testclient import TestClient

from fsi_common.app import AppConfig, create_app
from fsi_common.app.offline import OfflineExportError, OfflineTopic, replay_only
from review_app.context import Services, runs_of
from review_app.plugin import NAME, build_plugin
from review_app.seed import seed_kyc_onboarding
from review_app.service import make_runs

SECRET = b"offline-export"
_services: list[Services] = []
"""The services of the application built last, which the seed fills."""


def build_app() -> Starlette:
    """Build the application over a run service of its own, on replayed model calls.

    Returns:
        The application, serving the KYC onboarding topic.
    """
    with replay_only():
        runs = make_runs()
    services = Services(runs=lambda: runs)
    _services[:] = [services]
    return create_app(AppConfig(secret=SECRET, topic_folders=()), topics=[build_plugin(services)])


def seed(client: TestClient) -> str:
    """Make the topic's starting work and say where the file opens: the batch waiting.

    The batches are made through the application's own routes by the fictional reviewer, and the
    pages are read once both stand at their review or signed.

    Args:
        client: A client signed in as the reviewer, that does not follow redirects.

    Returns:
        The address of the waiting batch's review page.

    Raises:
        OfflineExportError: If the starting work cannot be made, or no batch waits afterwards.
    """
    if not _services:
        raise OfflineExportError("The application was not built by this hook, so it has no state.")
    services = _services[0]
    with replay_only():
        seed_kyc_onboarding(services)
    runs = runs_of(services)
    waiting = [t for t in runs.list_runs() if runs.status(t) == "awaiting_review"]
    if not waiting:
        raise OfflineExportError("No batch waits for a reviewer after the starting work.")
    return client.get(f"/kyc/runs/{waiting[0]}").headers["location"]


HOOK = OfflineTopic(name=NAME, build_app=build_app, seed=seed)
