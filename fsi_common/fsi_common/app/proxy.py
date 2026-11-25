"""Passing a request to a topic's process and its answer back, whole."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Iterable, Sequence

import httpx
from starlette.background import BackgroundTask
from starlette.requests import Request
from starlette.responses import StreamingResponse

from fsi_common.app.topic_info import PEERS_HEADER, TopicInfo, encode_peers

log = logging.getLogger(__name__)

CONNECT_SECONDS = 3.0
# A topic's own request may wait on a model for minutes, so the answer is given this long.
READ_SECONDS = 600.0
# The shell's own server adds these two to every answer, so the topic's are dropped.
OWN_HEADERS = frozenset({"date", "server"})
HOP_BY_HOP = frozenset(
    {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailer",
        "transfer-encoding",
        "upgrade",
    }
)


class ChildUnreachableError(RuntimeError):
    """A topic's process did not take the request: it is down, or it did not answer in time."""


class ChildGoneError(ChildUnreachableError):
    """The connection to a topic's process was refused or reset, as one that has ended gives."""


GONE_ERRORS = (httpx.ConnectError, httpx.RemoteProtocolError, httpx.ReadError, httpx.WriteError)


def is_gone(exc: BaseException) -> bool:
    """Say whether a failure of the connection to a topic's process is a refusal or a reset.

    A timeout is not: a frozen process is still alive and must not be started again.

    Args:
        exc: The failure.

    Returns:
        True for a refused or reset connection, or an error caused by one.
    """
    while exc is not None:
        if isinstance(exc, httpx.TimeoutException):
            return False
        if isinstance(exc, GONE_ERRORS):
            return True
        exc = exc.__cause__
    return False


def make_client() -> httpx.AsyncClient:
    """Make the client that talks to topics' processes.

    The environment's proxy settings are ignored, because every address it is used for is on
    this host's loopback.

    Returns:
        The client.
    """
    timeout = httpx.Timeout(CONNECT_SECONDS, read=READ_SECONDS, write=60.0, pool=10.0)
    return httpx.AsyncClient(timeout=timeout, trust_env=False, follow_redirects=False)


def forward_headers(
    raw: Iterable[tuple[bytes, bytes]], topics: Sequence[TopicInfo]
) -> list[tuple[str, str]]:
    """Choose the headers to send to a topic's process.

    Everything the person's browser sent goes on except the headers of the one hop between
    browser and shell and any topic list header of the browser's own; ``Host`` goes on, so an
    absolute address the topic makes names the address the person used. The shell adds the
    topic list its page headers show.

    Args:
        raw: The request's headers as bytes pairs.
        topics: The topics to list in the page header.

    Returns:
        The headers, names in lower case.
    """
    kept = []
    for name, value in raw:
        key = name.decode("latin-1").lower()
        if key in HOP_BY_HOP or key in {"content-length", PEERS_HEADER}:
            continue
        kept.append((key, value.decode("latin-1")))
    kept.append((PEERS_HEADER, encode_peers(topics)))
    return kept


def target_of(request: Request, base_url: str) -> str:
    """Return the address on a topic's process of the path and query the person asked for."""
    path = request.scope.get("raw_path")
    text = path.decode("ascii", "replace") if path else request.url.path
    query = request.scope.get("query_string", b"").decode("latin-1")
    return f"{base_url}{text}" + (f"?{query}" if query else "")


async def pass_request(
    client: httpx.AsyncClient, request: Request, *, base_url: str, topics: Sequence[TopicInfo]
) -> StreamingResponse:
    """Send a request to a topic's process and return its answer as it comes.

    Status, headers (every ``Set-Cookie`` line too), redirects and the body are the topic's own.

    Args:
        client: The client for topics' processes.
        request: The person's request.
        base_url: The topic's process's address.
        topics: The topics to list in the page header.

    Returns:
        The answer, streamed.

    Raises:
        ChildUnreachableError: If the process did not take the request or did not answer.
    """
    body = await request.body()
    sent = client.build_request(
        request.method,
        target_of(request, base_url),
        headers=forward_headers(request.headers.raw, topics),
        content=body or None,
    )
    try:
        answer = await client.send(sent, stream=True)
    except httpx.TransportError as exc:
        error = ChildGoneError if is_gone(exc) else ChildUnreachableError
        raise error(f"{base_url} did not answer: {exc!r}") from exc

    async def chunks() -> AsyncIterator[bytes]:
        try:
            async for chunk in answer.aiter_raw():
                yield chunk
        except httpx.TransportError:
            log.warning("%s ended its answer early.", base_url, exc_info=True)
        finally:
            await answer.aclose()

    response = StreamingResponse(
        chunks(), status_code=answer.status_code, background=BackgroundTask(answer.aclose)
    )
    dropped = HOP_BY_HOP | OWN_HEADERS
    response.raw_headers = [
        (k, v) for k, v in answer.headers.raw if k.decode("latin-1").lower() not in dropped
    ]
    return response
