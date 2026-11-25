"""The one place a model is chosen: ``get_model(role)`` gives each agent and step its chat model.

Each role has a fixed model and effort, chosen here and nowhere else. ``MODEL_BACKEND`` in the
.env in the repository root says where the calls go:

- ``claude-code``: live calls through headless Claude Code on the signed-in account;
- ``record``: live calls as above, each saved to the recordings folder;
- ``replay`` (the default): answers from the recordings folder only, so nothing calls a model;
- ``langchain``: the starter's route, ``init_chat_model(MODEL_NAME)`` with a provider key.

The first three build the model lazily, on its first call, so importing an agent never starts
a model call and never needs the adapter until a call is made.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from langchain_core.language_models import BaseChatModel
from langchain_core.outputs import ChatResult
from pydantic import ConfigDict, PrivateAttr

from fsi_common.tracing import model_labels
from utils import PROJECT_ROOT

REPO_ROOT = PROJECT_ROOT.parent
load_dotenv(REPO_ROOT / ".env")

model = os.environ.get("MODEL_NAME", "openai:gpt-6-luna")
"""The starter's ``provider:model`` name, kept so the starter's notebook cells still run."""

DEFAULT_BACKEND = "replay"
BACKEND_MODES = {"claude-code": "live", "record": "record", "replay": "replay"}
BACKENDS = (*BACKEND_MODES, "langchain")
MAX_CONCURRENCY = 4
TOPIC = "brief"
"""This topic's key in ``fsi_common.tracing``, which names it on every traced run."""
DEFAULT_RECORDINGS_DIR = PROJECT_ROOT / "recordings"


@dataclass(frozen=True)
class RoleModel:
    """The model and effort a role runs on, and why."""

    model: str
    effort: str | None
    reason: str


ROLE_MODELS: dict[str, RoleModel] = {
    "orchestrator": RoleModel(
        "claude-opus-5-5",
        "medium",
        "In the starter's deep agent the orchestrator writes the brief from the section summaries, "
        "which is judgement; it makes few calls a run, and most of its turns route tool calls.",
    ),
    "section": RoleModel(
        "claude-sonnet-5-5",
        "medium",
        "Reads one section into obligations with quotes, which plain code then checks; "
        "ten run at once.",
    ),
    "reconcile": RoleModel(
        "claude-opus-5-5",
        "high",
        "Compares facts across sections and against the firm's profile, where no plain-code "
        "check stands behind it.",
    ),
    "brief": RoleModel(
        "claude-opus-5-5",
        "high",
        "Writes the statements a named person signs, each citing the facts it rests on.",
    ),
    "assess": RoleModel(
        "claude-sonnet-5-5",
        "medium",
        "Reads the clauses code found for one provision and states what they say against it, one "
        "call per applicable obligation; plain code checks every quote word for word afterwards.",
    ),
}
"""Every role's model: the section sub-agents on Sonnet, reconciliation and the brief on Opus."""


class ModelConfigError(Exception):
    """The model settings name a role or a backend that does not exist."""


class TracingKeyMissingError(ModelConfigError):
    """Tracing is on but the LangSmith key is empty, so every trace would be lost."""


class ModelAdapterMissingError(ModelConfigError):
    """The headless Claude Code adapter, ``fsi_common.model``, is not installed."""


def tracing_enabled(env: Mapping[str, str]) -> bool:
    """Return whether LangSmith tracing is switched on, as LangSmith reads it.

    Args:
        env: The environment.

    Returns:
        True when ``LANGSMITH_TRACING`` or ``LANGCHAIN_TRACING_V2`` is ``true`` in any case.
    """
    return any(
        env.get(name, "").strip().lower() == "true"
        for name in ("LANGSMITH_TRACING", "LANGCHAIN_TRACING_V2")
    )


def check_tracing_key(env: Mapping[str, str]) -> None:
    """Refuse to run when tracing is on and the LangSmith key is empty.

    Args:
        env: The environment.

    Raises:
        TracingKeyMissingError: If tracing is on and neither ``LANGSMITH_API_KEY`` nor
            ``LANGCHAIN_API_KEY`` holds a value.
    """
    has_key = any(env.get(name, "").strip() for name in ("LANGSMITH_API_KEY", "LANGCHAIN_API_KEY"))
    if tracing_enabled(env) and not has_key:
        raise TracingKeyMissingError(
            "LANGSMITH_TRACING is true but LANGSMITH_API_KEY is empty, so every trace would be "
            "lost. Either export LANGSMITH_KEY in your shell before you start (the .env passes "
            "it on as LANGSMITH_API_KEY), or set LANGSMITH_TRACING=false in the .env in the "
            "repository root to run without tracing."
        )


def recordings_dir(env: Mapping[str, str]) -> Path:
    """Return the folder that ``record`` writes to and ``replay`` reads from.

    Args:
        env: The environment.

    Returns:
        ``MODEL_RECORDINGS_DIR``, taken from the repository root when relative, or the topic's
        ``recordings`` folder when unset.
    """
    value = env.get("MODEL_RECORDINGS_DIR", "").strip()
    if not value:
        return DEFAULT_RECORDINGS_DIR
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


class DeferredChatModel(BaseChatModel):
    """A chat model that builds the headless Claude Code model on its first call.

    Every call, ``bind_tools`` and ``with_structured_output`` go to the model that
    ``fsi_common.model.make_chat_model`` builds, so the deferral changes nothing but the moment
    the adapter is imported.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    role: str
    model: str
    effort: str | None
    mode: str
    recordings_dir: Path
    max_concurrency: int = MAX_CONCURRENCY

    _resolved: BaseChatModel | None = PrivateAttr(default=None)
    _lock: threading.Lock = PrivateAttr(default_factory=threading.Lock)

    @property
    def _llm_type(self) -> str:
        return "claude-code-deferred"

    @property
    def _identifying_params(self) -> dict[str, Any]:
        return {"role": self.role, "model": self.model, "effort": self.effort, "mode": self.mode}

    def resolve(self) -> BaseChatModel:
        """Return the adapter's model, building it on the first call.

        Returns:
            The chat model from ``fsi_common.model.make_chat_model``.

        Raises:
            ModelAdapterMissingError: If ``fsi_common.model`` cannot be imported.
        """
        with self._lock:
            if self._resolved is None:
                try:
                    from fsi_common.model import make_chat_model
                except ImportError as exc:
                    raise ModelAdapterMissingError(
                        f"MODEL_BACKEND needs fsi_common.model for role '{self.role}', and it "
                        "cannot be imported. Run `uv sync --all-packages` in the repository root, "
                        "or set MODEL_BACKEND=langchain to use the starter's route."
                    ) from exc
                self._resolved = make_chat_model(
                    model=self.model,
                    effort=self.effort,
                    mode=self.mode,
                    recordings_dir=self.recordings_dir,
                    max_concurrency=self.max_concurrency,
                )
                # ``bind_tools`` and ``with_structured_output`` run the adapter's own model, so
                # the labels this one carries must be on that one as well.
                self._resolved = self._resolved.model_copy(
                    update={"metadata": self.metadata, "tags": self.tags}
                )
            return self._resolved

    def _generate(
        self, messages: Any, stop: Any = None, run_manager: Any = None, **kwargs: Any
    ) -> ChatResult:
        return self.resolve()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)

    async def _agenerate(
        self, messages: Any, stop: Any = None, run_manager: Any = None, **kwargs: Any
    ) -> ChatResult:
        return await self.resolve()._agenerate(
            messages, stop=stop, run_manager=run_manager, **kwargs
        )

    def bind_tools(self, tools: Any, **kwargs: Any) -> Any:
        """Bind tools on the adapter's model.

        Args:
            tools: The tools, as LangChain accepts them.
            **kwargs: Passed on, for example ``tool_choice``.

        Returns:
            The adapter model's runnable with the tools bound.
        """
        return self.resolve().bind_tools(tools, **kwargs)

    def with_structured_output(self, schema: Any, **kwargs: Any) -> Any:
        """Ask the adapter's model for structured output.

        Args:
            schema: The output schema.
            **kwargs: Passed on.

        Returns:
            The adapter model's structured-output runnable.
        """
        return self.resolve().with_structured_output(schema, **kwargs)


def get_model(role: str) -> BaseChatModel:
    """Return the chat model for one role, on the backend ``MODEL_BACKEND`` names.

    Args:
        role: ``orchestrator``, ``section``, ``reconcile``, ``brief`` or ``assess``.

    Returns:
        A chat model: deferred for ``claude-code``, ``record`` and ``replay``; the starter's
        ``init_chat_model(MODEL_NAME)`` for ``langchain``.

    Raises:
        ModelConfigError: If the role or the backend is unknown.
        TracingKeyMissingError: If tracing is on and the LangSmith key is empty.
    """
    env = os.environ
    if role not in ROLE_MODELS:
        raise ModelConfigError(
            f"There is no model role '{role}'. The roles are: {', '.join(ROLE_MODELS)}."
        )
    backend = env.get("MODEL_BACKEND", "").strip() or DEFAULT_BACKEND
    if backend not in BACKENDS:
        raise ModelConfigError(
            f"MODEL_BACKEND is '{backend}'. Set it to one of: {', '.join(BACKENDS)}."
        )
    check_tracing_key(env)
    if backend == "langchain":
        from langchain.chat_models import init_chat_model

        return init_chat_model(env.get("MODEL_NAME", model))
    chosen = ROLE_MODELS[role]
    labels = model_labels(TOPIC, role, model=chosen.model, effort=chosen.effort)
    return DeferredChatModel(
        role=role,
        model=chosen.model,
        effort=chosen.effort,
        mode=BACKEND_MODES[backend],
        recordings_dir=recordings_dir(env),
        metadata=labels.metadata,
        tags=labels.tags,
    )
