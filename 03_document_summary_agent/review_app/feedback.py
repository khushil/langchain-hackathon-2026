"""What the application sends to LangSmith when a brief is signed or returned.

Each decision on the brief goes as feedback on the brief's root run, with the reviewer's outcome,
reason, name and role, and the run joins an annotation queue so a person can look at it there.
Sending is never a condition of the decision: the decision and the sign-off are kept before
anything is sent, and a failure to send is one sentence on the signed page.

The run joins the queue through the queue's items, which the client offers as a coroutine; it is run
to the end here, inside the same time limit as every other call of the send.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import datetime
import logging
import os
import threading
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, Protocol, TypeVar

from langsmith import LangsmithError
from langsmith.utils import LangSmithError

from fsi_common.evals.upload import DEFAULT_ENDPOINT
from utils.models import tracing_enabled
from utils.state import ReviewResponse

LOG = logging.getLogger("review_app.feedback")
_T = TypeVar("_T")
QUEUE_NAME = "compliance-brief-reviews"
QUEUE_DESCRIPTION = "Briefs signed or returned in the reviewer's application, with each decision."
FEEDBACK_KEY = "reviewer_decision"
FAILED_WORDS = (
    "Your decisions are kept here, but some may not have reached the LangSmith review queue; "
    "tell the person who runs this server."
)
CONNECT_MS, READ_MS = 2000, 2000
"""How long the client waits to connect and to read, so one call fails in seconds."""
SEND_ATTEMPTS = 2
"""How many times the client tries a feedback request; its own default is ten, with back-off."""
SEND_BUDGET_SECONDS = 8.0
"""The longest the sign request waits for LangSmith in all; a send still going then is left."""
SEND_ERRORS = (
    LangSmithError,
    LangsmithError,
    OSError,
    ValueError,
    TypeError,
    AttributeError,
    KeyError,
    RuntimeError,
)
"""What a send can raise. The first four are LangSmith's errors, in the two families the client
raises (the older calls raise the first, the queue call the second, with a time-out among them), a
broken connection and a refused request. The rest are what the client or the libraries under it
raise when LangSmith answers in a shape it does not expect (a closed session or a stopped thread
pool raise `RuntimeError`), which can only be told from a fault of ours by the request failing: the
decision is already kept, so the person is told in one sentence and the traceback goes to the
log."""


class FeedbackUnavailableError(Exception):
    """Tracing is on and there is no LangSmith key, so nothing can be sent."""


class Traced(Protocol):
    """Where a brief's root run was traced."""

    run_id: str | None
    project_id: str | None
    started_at: str | None


class FeedbackClient(Protocol):
    """The parts of the LangSmith client the application uses."""

    def create_feedback(self, run_id: str, key: str, **kwargs: Any) -> Any:
        """Add feedback to a run."""

    def list_annotation_queues(self, *, name: str | None = None, **kwargs: Any) -> Any:
        """The annotation queues, optionally those whose names contain a text."""

    def create_annotation_queue(self, *, name: str, **kwargs: Any) -> Any:
        """Make a queue and return it."""

    @property
    def annotation_queues(self) -> Any:
        """The queue resource: its ``items.create`` is a coroutine that adds runs to a queue."""


def new_client(env: Mapping[str, str]) -> FeedbackClient:
    """Make the LangSmith client for the workspace the environment names.

    Args:
        env: The environment, which holds the key and the endpoint.

    Returns:
        The client.

    Raises:
        FeedbackUnavailableError: If neither ``LANGSMITH_API_KEY`` nor ``LANGSMITH_KEY`` is set.
    """
    from langsmith import Client

    key = env.get("LANGSMITH_API_KEY") or env.get("LANGSMITH_KEY")
    if not key:
        raise FeedbackUnavailableError("Tracing is on and no LangSmith key is set.")
    return Client(
        api_key=key,
        api_url=env.get("LANGSMITH_ENDPOINT", DEFAULT_ENDPOINT),
        timeout_ms=(CONNECT_MS, READ_MS),
    )


def default_client() -> FeedbackClient | None:
    """Give the client decisions are sent with, or None when tracing is off.

    Returns:
        The client; None when ``LANGSMITH_TRACING`` and ``LANGCHAIN_TRACING_V2`` are not true.

    Raises:
        FeedbackUnavailableError: If tracing is on and there is no key.
    """
    if not tracing_enabled(os.environ):
        return None
    return new_client(os.environ)


def _decisions(response: ReviewResponse) -> list[tuple[str, str | None, Any, str]]:
    """Each decision, then the sign-off: outcome, reason, reviewer and what it is about."""
    given = [(d.outcome, d.reason, d.reviewer, d.subject_id) for d in response.decisions]
    sign_off = response.sign_off
    if sign_off is not None:
        given.append((sign_off.outcome, sign_off.reason, sign_off.reviewer, sign_off.brief_id))
    return given


def _queue_id(client: FeedbackClient) -> Any:
    """Find the named queue, or make it when it is absent."""
    for queue in client.list_annotation_queues(name=QUEUE_NAME):
        if queue.name == QUEUE_NAME:
            return queue.id
    return client.create_annotation_queue(name=QUEUE_NAME, description=QUEUE_DESCRIPTION).id


def run_to_completion(make: Callable[[], Awaitable[_T]]) -> _T:
    """Run a coroutine to the end from synchronous code, for no longer than the send budget.

    The send runs in a thread of its own that has no event loop, so the coroutine gets one. Where a
    loop is already running in the calling thread, a second cannot be started there, so the
    coroutine runs in a helper thread with a loop of its own and the caller waits for it.

    Args:
        make: Makes the coroutine; called once, in the thread that runs it.

    Returns:
        What the coroutine returned.

    Raises:
        TimeoutError: If the coroutine had not finished when the budget ran out.
        Exception: Whatever the coroutine raised.
    """

    async def bounded() -> _T:
        return await asyncio.wait_for(make(), timeout=SEND_BUDGET_SECONDS)

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(bounded())
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, bounded()).result()


def _queue_resource(client: FeedbackClient) -> Any:
    """The client's queue resource, set to try a request at most ``SEND_ATTEMPTS`` times.

    The client's own retry setting does not reach the queue resource, which keeps the generated
    client's default of three attempts. The generated client is the resource's ``_client``, and it
    copies itself with a lower limit. When the resource does not have one, the default stays and the
    send budget is the only limit.
    """
    resource = client.annotation_queues
    generated = getattr(resource, "_client", None)
    if generated is None or not hasattr(generated, "with_options"):
        LOG.warning("The queue resource has no retry setting; the send budget is its only limit")
        return resource
    return generated.with_options(max_retries=SEND_ATTEMPTS - 1).annotation_queues


def add_run_to_queue(client: FeedbackClient, queue_id: Any, root: Traced) -> None:
    """Put the brief's root run in the queue, as one item that names where the run is.

    Args:
        client: The LangSmith client.
        queue_id: The queue.
        root: Where the brief's root run was traced; its run id, project and start time are known.

    Raises:
        LangsmithError: If LangSmith refuses the item, cannot be reached or does not answer in time.
        TimeoutError: If the whole call outlasts the send budget.
    """
    started = datetime.datetime.fromisoformat(str(root.started_at))
    if started.tzinfo is None:
        started = started.replace(tzinfo=datetime.UTC)  # LangSmith keeps run times in UTC
    item = {
        "item_type": "RUN",
        "run_id": str(root.run_id),
        "project_id": str(root.project_id),
        "start_time": started.isoformat(),
    }
    resource = _queue_resource(client)
    run_to_completion(lambda: resource.items.create(str(queue_id), items=[item]))


def _send(
    client: FeedbackClient, root: Traced, response: ReviewResponse, progress: dict[str, Any]
) -> bool:
    """Send every decision and queue the run, stopping at the first failure; say whether all went.

    A failed request is already tried twice, and one that fails says that LangSmith cannot be
    reached or cannot place the run, so sending the rest would only make the person wait longer.
    """
    run_id = root.run_id
    if root.project_id is None or root.started_at is None:
        raise FeedbackUnavailableError("The run's trace project or start time is not known.")
    started = datetime.datetime.fromisoformat(root.started_at)
    given = _decisions(response)
    progress.update(sent=0, total=len(given), queued=False)
    for outcome, reason, reviewer, subject in given:
        try:
            client.create_feedback(
                run_id,
                FEEDBACK_KEY,
                value=outcome,
                comment=reason,
                source_info={"reviewer": reviewer.name, "role": reviewer.role},
                extra={"subject_id": subject},
                session_id=root.project_id,
                start_time=started,
                stop_after_attempt=SEND_ATTEMPTS,
            )
            progress["sent"] += 1
        except SEND_ERRORS:
            LOG.exception("The decision on %s could not be sent to LangSmith", subject)
            return False
    add_run_to_queue(client, _queue_id(client), root)
    progress["queued"] = True
    return True


def _within_budget(send: Callable[[], bool], progress: dict[str, Any]) -> bool:
    """Run a send, and give it up when it has taken longer than the budget.

    The send runs in a daemon thread of its own, so the sign request is held for the budget at most
    whatever LangSmith does. A send still going then is left to finish by itself, which means some
    decisions may reach LangSmith after the page is shown: how many had gone at the cap, and how
    many had gone when it ended, are logged.

    Args:
        send: The send, which says whether all of it went.
        progress: What the send keeps up to date: ``sent``, ``total`` and ``queued``.

    Returns:
        Whether all of it went; False when it failed or was left going.

    Raises:
        Exception: Whatever the send raised, in the calling thread.
    """
    outcome: list[bool | BaseException] = []
    given_up = threading.Event()

    def work() -> None:
        try:
            outcome.append(send())
        except BaseException as exc:  # carried to the caller, who decides what to say
            outcome.append(exc)
        if given_up.is_set():
            failed = not outcome or outcome[0] is not True
            LOG.log(
                logging.WARNING if failed else logging.INFO,
                "The send to LangSmith finished after the cap: %s",
                _progress_words(progress, failed=failed),
            )

    thread = threading.Thread(target=work, daemon=True, name="queue-feedback")
    thread.start()
    thread.join(SEND_BUDGET_SECONDS)
    if not outcome:
        given_up.set()
        LOG.error(
            "The send to LangSmith was still going after %s seconds: %s of %s sent",
            SEND_BUDGET_SECONDS,
            progress.get("sent", 0),
            progress.get("total", "?"),
        )
        return False
    if isinstance(outcome[0], BaseException):
        raise outcome[0]
    return outcome[0]


def _progress_words(progress: dict[str, Any], *, failed: bool) -> str:
    """Say how much of a send went: the decisions sent and whether the run was queued."""
    queued = "and the run queued" if progress.get("queued") else "and the run not queued"
    ending = "; it failed" if failed else ""
    return (
        f"{progress.get('sent', 0)} of {progress.get('total', '?')} decisions sent {queued}{ending}"
    )


def report_to_queue(
    make_client: Callable[[], FeedbackClient | None],
    root_of: Callable[[], Traced | None],
    response: ReviewResponse,
) -> str | None:
    """Send a signed or returned brief's decisions to LangSmith, and say in words if any failed.

    With tracing off nothing is sent and nothing is said. A failure never reaches the caller: the
    decisions and the sign-off are kept already.

    Args:
        make_client: Gives the LangSmith client, or None when tracing is off.
        root_of: Gives where the brief's root run was traced, or None when the run is not known.
        response: What the reviewer sent: the decisions and the sign-off.

    Returns:
        The sentence for the signed page when something was not sent; None when all of it was,
        or when tracing is off.
    """
    try:
        client = make_client()
        if client is None:
            return None
        root = root_of()
        if root is None or root.run_id is None:
            LOG.error("The run has no run id, so its decisions cannot be sent to LangSmith")
            return FAILED_WORDS
        progress: dict[str, Any] = {}
        sent = _within_budget(lambda: _send(client, root, response, progress), progress)
        return None if sent else FAILED_WORDS
    except (FeedbackUnavailableError, *SEND_ERRORS):
        LOG.exception("The decisions could not be sent to LangSmith")
        return FAILED_WORDS
