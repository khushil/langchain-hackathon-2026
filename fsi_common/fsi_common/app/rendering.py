"""Templates, shared by the shell and every topic's pages."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from jinja2 import ChoiceLoader, Environment, FileSystemLoader, select_autoescape
from starlette.requests import Request
from starlette.responses import HTMLResponse

from fsi_common.app.pages import STATUS_WORDS
from fsi_common.app.session import current_person
from fsi_common.app.topic_info import PEERS_HEADER, decode_peers
from fsi_common.app.topics import TopicPlugin

TEMPLATES_DIR = Path(__file__).parent / "templates"
PRODUCT_NAME = "Review desk"


def long_date(value: str) -> str:
    """Write an ISO date as "25 November 2026".

    Args:
        value: A date as ``YYYY-MM-DD``.

    Returns:
        The date in words, or the value unchanged if it is not an ISO date.
    """
    try:
        day = date.fromisoformat(value)
    except ValueError:
        return value
    return f"{day.day} {day.strftime('%B %Y')}"


def make_environment(topics: list[TopicPlugin]) -> Environment:
    """Make the template environment over the shell's templates and each topic's.

    Args:
        topics: The topics served.

    Returns:
        The environment, with autoescaping on.
    """
    loaders = [FileSystemLoader(TEMPLATES_DIR)] + [
        FileSystemLoader(topic.templates_dir) for topic in topics
    ]
    env = Environment(
        loader=ChoiceLoader(loaders),
        autoescape=select_autoescape(["html"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["long_date"] = long_date
    env.globals.update(status_words=STATUS_WORDS)
    for topic in topics:
        env.globals.update(topic.template_globals)
        env.filters.update(topic.template_filters)
    return env


def listed_topics(request: Request) -> object:
    """Return the topics the page header lists.

    A topic's own process lists every topic by the header its shell adds to each request; with no
    such header, or when the application is not a topic's process, it lists the topics it holds.

    Args:
        request: The request being answered.

    Returns:
        The topics, each with a title and a prefix.
    """
    state = request.app.state
    if getattr(state, "lists_peers", False):
        return decode_peers(request.headers.get(PEERS_HEADER)) or state.topics
    return state.topics


def render(
    request: Request, template: str, context: dict | None = None, *, status: int = 200
) -> HTMLResponse:
    """Render a page inside the application's layout.

    Args:
        request: The request being answered.
        template: The template's name.
        context: What the page shows.
        status: The response's status code.

    Returns:
        The page.
    """
    app_state = request.app.state
    page = {
        "product_name": PRODUCT_NAME,
        "person": current_person(request),
        "topics": listed_topics(request),
        "path": request.url.path,
        "request": request,
        **(context or {}),
    }
    html = app_state.templates.get_template(template).render(page)
    return HTMLResponse(html, status_code=status)
