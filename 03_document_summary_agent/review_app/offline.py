"""The compliance brief's part of the offline edition: what to start and where the file opens."""

from __future__ import annotations

import dataclasses
import logging
import time

from starlette.applications import Starlette
from starlette.testclient import TestClient

from fsi_common.app import AppConfig, create_app
from fsi_common.app.offline import OfflineExportError, OfflineTopic, replay_only
from fsi_common.app.topics import TopicPlugin
from review_app import routes_policies
from review_app.context import PREFIX, Services
from review_app.plugin import build_plugin
from review_app.seed import SECTIONS
from workflow.runs import BriefRuns

DOCUMENT_ID = "PS26-4"
FIRM_ID = "FIRM-001"
WAIT_SECONDS = 120.0
POLL_SECONDS = 0.1
SECRET = b"offline-export"
POLICY_PICTURE = "/policies/{corpus}"
"""The route path that marks a plug-in as listing the policy pages."""


class _FailureCatcher(logging.Handler):
    """Keeps the exceptions the run service logs when a run fails, for the export to raise."""

    def __init__(self) -> None:
        super().__init__(level=logging.ERROR)
        self.caught: list[BaseException] = []

    def emit(self, record: logging.LogRecord) -> None:
        if record.exc_info and record.exc_info[1] is not None:
            self.caught.append(record.exc_info[1])


def with_policy_pages(plugin: TopicPlugin, services: Services) -> TopicPlugin:
    """Give a plug-in the policy pages when it does not list them already.

    The pages read the bundles in the folder ``POLICY_BUNDLES_DIR`` names, which is where an
    export finds the replayed run of an assessment; they make no model call and no request
    outside the file. When the folder holds no bundle the start page links to no policy page, so
    the file holds none.

    Args:
        plugin: The topic's plug-in.
        services: The services the pages read their state through.

    Returns:
        The plug-in itself when it already lists the policy routes; else a copy that lists them
        and the function the start page asks for the policy pages' address.
    """
    if any(getattr(r, "path", "") == POLICY_PICTURE for r in plugin.routes):
        return plugin
    link = routes_policies.pages_link(services)
    return dataclasses.replace(
        plugin,
        routes=[*plugin.routes, *routes_policies.routes(services)],
        template_globals={**plugin.template_globals, "policy_pages": link},
    )


def build_app() -> Starlette:
    """Build the application over a run service of its own, on replayed model calls.

    Returns:
        The application, serving the compliance brief topic and, where a replayed assessment is
        held, its policy pages.
    """
    with replay_only():
        runs = BriefRuns()
    services = Services(runs=lambda: runs)
    config = AppConfig(secret=SECRET, topic_folders=())
    return create_app(config, topics=[with_policy_pages(build_plugin(services), services)])


def seed(client: TestClient) -> str:
    """Start a brief on every section of PS26-4 for FIRM-001 and wait for its review step.

    The brief is started through the application's own start route, as the signed-in person the
    client carries, and the pages are read once the run waits for a reviewer.

    Args:
        client: A client signed in as the reviewer, that does not follow redirects.

    Returns:
        The address of the brief's review page.

    Raises:
        ReplayMissError: If a model call has no recording; its message names the request's hash.
        OfflineExportError: If the run stops for another reason, does not start, or does not reach
            the review in time.
    """
    catcher = _FailureCatcher()
    log = logging.getLogger("workflow.runs")
    log.addHandler(catcher)
    try:
        with replay_only():
            return _start_and_wait(client, catcher)
    finally:
        log.removeHandler(catcher)


def _start_and_wait(client: TestClient, catcher: _FailureCatcher) -> str:
    form = {"document_id": DOCUMENT_ID, "firm_id": FIRM_ID, "sections": list(SECTIONS)}
    started = client.post(f"{PREFIX}/runs", data=form)
    if started.status_code != 303:
        raise OfflineExportError(
            f"The start route answered {started.status_code} instead of starting a brief."
        )
    run = started.headers["location"]
    deadline = time.monotonic() + WAIT_SECONDS
    while time.monotonic() < deadline:
        page = client.get(run)
        if page.status_code == 303:
            return page.headers["location"]
        if 'data-hook="run-error"' in page.text:
            raise _failure(catcher)
        time.sleep(POLL_SECONDS)
    raise OfflineExportError(f"The brief did not reach its review within {WAIT_SECONDS:g} seconds.")


def _failure(catcher: _FailureCatcher) -> BaseException:
    """Return the error that stopped the run: a missing recording as itself, else a summary."""
    from fsi_common.model import ReplayMissError

    for caught in catcher.caught:
        link: BaseException | None = caught
        while link is not None:
            if isinstance(link, ReplayMissError):
                return link
            link = link.__cause__ or link.__context__
    reason = str(catcher.caught[0]) if catcher.caught else "the engine gave no reason"
    return OfflineExportError(f"The brief stopped before its review: {reason}")


HOOK = OfflineTopic(name="compliance-brief", build_app=build_app, seed=seed)
