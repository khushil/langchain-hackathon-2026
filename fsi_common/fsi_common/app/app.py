"""The Starlette application: layout, sign-in, About, and each topic mounted at its address."""

from __future__ import annotations

from collections.abc import Sequence
from urllib.parse import urlencode

from starlette.applications import Starlette
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import RedirectResponse, Response
from starlette.routing import BaseRoute, Mount, Route
from starlette.staticfiles import StaticFiles

from fsi_common.app.config import AppConfig
from fsi_common.app.home import summarise_home
from fsi_common.app.pages import Answer
from fsi_common.app.rendering import TEMPLATES_DIR, make_environment, render
from fsi_common.app.session import (
    SessionCodec,
    SignInError,
    current_person,
    make_person,
    safe_next,
)
from fsi_common.app.topics import SeedError, TopicPlugin, check_distinct, load_topics

STATIC_DIR = TEMPLATES_DIR.parent / "static"


async def home(request: Request) -> Response:
    """Say what waits for a reviewer across the workflows, and let each be opened."""
    summary = summarise_home(request.app.state.topics)
    return render(request, "home.html", {"answer": summary.answer(), "page_title": "Home"})


async def about(request: Request) -> Response:
    """Say what the data is and how a brief is built."""
    answer = Answer(
        sentence="This is a demonstration on fictional data from the hackathon starter."
    )
    return render(
        request,
        "about.html",
        {"answer": answer, "page_title": "About"},
    )


async def sign_in_form(request: Request) -> Response:
    """Show the sign-in form."""
    target = safe_next(request.query_params.get("next"))
    return render(request, "signin.html", _sign_in_context(target))


async def sign_in(request: Request) -> Response:
    """Sign a person in from their typed name and role."""
    form = await request.form()
    target = safe_next(str(form.get("next", "")))
    name, role = str(form.get("name", "")), str(form.get("role", ""))
    try:
        person = make_person(name, role)
    except SignInError as exc:
        context = _sign_in_context(target) | {"problem": str(exc), "name": name, "role": role}
        return render(request, "signin.html", context, status=422)
    response = RedirectResponse(target, status_code=303)
    response.set_cookie(
        request.app.state.cookie_name,
        request.app.state.sessions.encode(person),
        httponly=True,
        samesite="lax",
        path="/",
    )
    return response


async def sign_out(request: Request) -> Response:
    """Sign the person out."""
    response = RedirectResponse("/", status_code=303)
    response.delete_cookie(request.app.state.cookie_name, path="/")
    return response


def _sign_in_context(target: str) -> dict:
    answer = Answer(sentence="Sign in with your name and role to decide on a brief.")
    return {"answer": answer, "page_title": "Sign in", "next": target}


async def http_error(request: Request, exc: HTTPException) -> Response:
    """Say in words what stopped the page: nothing at the address, or the reason a page gives."""
    if exc.status_code == 404 and exc.detail in {"", "Not Found"}:
        answer, title = Answer(sentence="There is nothing at this address."), "Not found"
    elif exc.status_code == 404:
        answer, title = Answer(sentence=exc.detail), "Not found"
    else:
        answer, title = Answer(sentence=exc.detail), "Not available"
    return render(
        request, "message.html", {"answer": answer, "page_title": title}, status=exc.status_code
    )


def sign_in_address(request: Request) -> str:
    """Return the sign-in address that leads back to the page asked for.

    Args:
        request: The request.

    Returns:
        ``/signin`` with the current path and query as ``next``.
    """
    here = request.url.path + (f"?{request.url.query}" if request.url.query else "")
    return "/signin?" + urlencode({"next": here})


def create_app(
    config: AppConfig | None = None,
    *,
    topics: Sequence[TopicPlugin] | None = None,
    extra_routes: Sequence[BaseRoute] = (),
) -> Starlette:
    """Build the application, with every topic served in this process.

    Topics whose folders share package names (each has a ``utils``) belong in separate processes,
    which is what ``fsi_common.app.shell`` arranges; this builds one process's application.

    Args:
        config: The settings; the environment's when absent.
        topics: The topics to serve; those of the configured folders when absent.
        extra_routes: Routes added after the shell's own, which a topic's process uses for the
            answer its shell asks for.

    Returns:
        The application.

    Raises:
        NoTopicsError: If there is no topic to serve.
        TopicLoadError: If a configured topic cannot be loaded.
    """
    config = config or AppConfig.from_env()
    plugins = list(topics) if topics is not None else load_topics(config.topic_folders)
    check_distinct(plugins)
    routes: list = [
        Route("/", home),
        Route("/about", about),
        Route("/signin", sign_in_form, methods=["GET"]),
        Route("/signin", sign_in, methods=["POST"]),
        Route("/signout", sign_out, methods=["POST"]),
        Mount("/static", StaticFiles(directory=STATIC_DIR), name="static"),
        *extra_routes,
    ]
    for plugin in plugins:
        mounted = list(plugin.routes)
        if plugin.static_dir is not None:
            mounted.append(Mount("/static", StaticFiles(directory=plugin.static_dir)))
        routes.append(Mount(plugin.prefix, routes=mounted, name=plugin.name))
    app = Starlette(routes=routes, exception_handlers={HTTPException: http_error})
    app.state.config = config
    app.state.topics = plugins
    app.state.sessions = SessionCodec(config.secret)
    app.state.cookie_name = config.cookie_name
    app.state.templates = make_environment(plugins)
    if config.state_dir is not None:
        for plugin in plugins:
            if plugin.use_state_dir is not None:
                plugin.use_state_dir(config.state_dir)
    if config.seed:
        make_starting_work(plugins, config.seed)
    return app


def make_starting_work(plugins: Sequence[TopicPlugin], name: str) -> None:
    """Make the starting work of the topic ``APP_SEED`` names.

    Args:
        plugins: The topics served.
        name: The topic's name.

    Raises:
        SeedError: If no served topic has that name, the topic has no starting work, or the
            topic cannot make it.
    """
    chosen = next((p for p in plugins if p.name == name), None)
    if chosen is None:
        served = ", ".join(p.name for p in plugins)
        raise SeedError(
            f"APP_SEED is '{name}', which is not a topic served here; topics served: {served}."
        )
    if chosen.seed is None:
        raise SeedError(
            f"The topic '{name}' has no starting work to make, so APP_SEED cannot name it."
        )
    chosen.seed()


__all__ = ["create_app", "current_person", "make_starting_work", "sign_in_address"]
