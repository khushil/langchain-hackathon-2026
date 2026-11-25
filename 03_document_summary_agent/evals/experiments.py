"""Run the starter's agent and this engine as LangSmith experiments on the two datasets.

Each experiment is one repetition of one agent on one dataset, scored by the seven measures, and
its counts are written to ``data/experiments.json`` as soon as it finishes. The runs call the model
live through headless Claude Code; they are never recorded and never replayed, so an experiment
can never be taken for the recorded run the application replays.

From the topic folder, with the shared member on the path and the LangSmith key in the process::

    MODEL_BACKEND=claude-code python -m evals.experiments --repetitions 3
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fsi_common.evals.runner import run_evaluators

from .build_dataset import read_examples
from .evaluators import evaluate_pair, langsmith_evaluators
from .experiment_results import (
    RESULTS_FILE,
    ExperimentEntry,
    Figure,
    append_entry,
    read_entries,
)
from .reference_summary import document_summary, section_summary
from .upload import DEFAULT_ENDPOINT, DOCUMENT_NAME, SECTIONS_NAME

LOG = logging.getLogger("evals.experiments")
AGENTS = ("starter", "engine")
DATASETS = {
    "sections": (SECTIONS_NAME, "sections.jsonl"),
    "document": (DOCUMENT_NAME, "documents.jsonl"),
}
DEFAULT_REPETITIONS = 3
MAX_CONCURRENCY = 4
SCOPE_KEYS = ("obligations_found", "paragraph_recall")
"""The measures whose denominators the labels fix: what is in scope does not depend on the agent."""
LABELLED_DEADLINES = "deadlines_matched"
"""Its denominator counts the matched obligations that have a labelled deadline, so it can fall
below the labels' count with the agent but never rise above it."""
LIVE_BACKEND = "claude-code"
Targets = Callable[[str, str], Callable[[Mapping[str, Any]], dict[str, Any]]]
"""Gives the agent to run for an agent name and a dataset name."""


class BackendRefusedError(Exception):
    """The model backend is not the live one, so an experiment could be taken for a replay."""


class ExperimentIncompleteError(Exception):
    """An experiment returned fewer results than the dataset has examples."""


@dataclass(frozen=True)
class Planned:
    """One experiment to make: an agent on a dataset, one repetition."""

    agent: str
    dataset: str
    repetition: int

    @property
    def prefix(self) -> str:
        """The experiment's name before LangSmith adds its own suffix."""
        return f"{self.agent}-{self.dataset}-r{self.repetition}"


def check_backend(env: Mapping[str, str]) -> None:
    """Refuse any model backend but the live one.

    Args:
        env: The environment.

    Raises:
        BackendRefusedError: If ``MODEL_BACKEND`` is anything but ``claude-code``, which includes
            unset (the default is replay), ``replay`` and ``record``.
    """
    backend = env.get("MODEL_BACKEND", "").strip()
    if backend != LIVE_BACKEND:
        shown = backend or "unset, which means replay"
        raise BackendRefusedError(
            f"MODEL_BACKEND is {shown}. An experiment calls the model live and is never recorded "
            f"or replayed; start it with MODEL_BACKEND={LIVE_BACKEND}."
        )


def plan(agents: Sequence[str], datasets: Sequence[str], repetitions: int) -> list[Planned]:
    """List the experiments in the order they run.

    Args:
        agents: The agents, each with all its datasets before the next agent.
        datasets: The datasets; the sections are repeated, the document is read once.
        repetitions: How many times each agent reads the sections.

    Returns:
        The experiments.
    """
    return [
        Planned(agent, dataset, number)
        for agent in agents
        for dataset in datasets
        for number in range(1, (repetitions if dataset == "sections" else 1) + 1)
    ]


def make_client(key: str, env: Mapping[str, str]) -> Any:
    """Make the LangSmith client for the workspace the environment names."""
    from langsmith import Client

    return Client(api_key=key, api_url=env.get("LANGSMITH_ENDPOINT", DEFAULT_ENDPOINT))


def default_targets(agent: str, dataset: str) -> Callable[[Mapping[str, Any]], dict[str, Any]]:
    """Build the starter's agent or the engine for a dataset, on the live model.

    Args:
        agent: ``starter`` or ``engine``.
        dataset: ``sections`` or ``document``.

    Returns:
        The function LangSmith runs on each example.
    """
    from .experiment_targets import document_target, engine_section_target, starter_section_target

    if agent == "starter":
        section = starter_section_target()
    else:
        from utils.models import get_model

        section = engine_section_target(get_model)
    return section if dataset == "sections" else document_target(section)


def section_setup() -> tuple[str, str | None, str]:
    """Name the model, effort and prompt version both agents read a section with.

    Returns:
        The section role's model and effort, and the version of the starter's sub-agent prompt.
    """
    from utils.models import ROLE_MODELS
    from workflow.sections import SECTION_PROMPT_VERSION

    section = ROLE_MODELS["section"]
    return section.model, section.effort, SECTION_PROMPT_VERSION


def reference_denominators(dataset: str) -> dict[str, int]:
    """Count what a dataset's labels put in scope, by scoring the summary built from them.

    Args:
        dataset: ``sections`` or ``document``.

    Returns:
        The denominators of obligations found, deadlines matched and paragraph recall.
    """
    if dataset == "sections":
        examples = read_examples("sections.jsonl")
        pairs = [(e, section_summary(e)) for e in examples]
    else:
        pairs = [
            (e, document_summary(read_examples("sections.jsonl")))
            for e in read_examples("documents.jsonl")
        ]
    report = run_evaluators(pairs, [evaluate_pair])
    return {
        m.key: m.denominator for m in report.totals if m.key in (*SCOPE_KEYS, LABELLED_DEADLINES)
    }


def entry_from(item: Planned, results: Any, *, now: datetime) -> ExperimentEntry:
    """Total one finished experiment's counts into the entry the file keeps.

    An example the agent returned nothing for scores as nothing found and is named in the entry.

    Args:
        item: The experiment.
        results: LangSmith's results: the name, the id and one row for each example.
        now: When it finished.

    Returns:
        The entry.

    Raises:
        ExperimentIncompleteError: If the rows are not the dataset's examples, or a total fails.
    """
    wanted = [e["key"] for e in read_examples(DATASETS[item.dataset][1])]
    expected = len(wanted)
    rows = list(results)
    if len(rows) != expected:
        raise ExperimentIncompleteError(
            f"{item.prefix} returned {len(rows)} of {expected} examples, so nothing was recorded."
        )
    got = [row["example"].metadata["key"] for row in rows]
    if sorted(got) != sorted(wanted):
        missing = sorted(set(wanted) - set(got))
        repeated = sorted({k for k in got if got.count(k) > 1 or k not in wanted})
        raise ExperimentIncompleteError(
            f"{item.prefix} did not return the dataset's examples: "
            f"missing {', '.join(missing) or 'none'}; "
            f"extra or repeated {', '.join(repeated) or 'none'}. Nothing was recorded."
        )
    empty = {"sections": []} if item.dataset == "document" else {"obligations": []}
    pairs, failed = [], []
    for row in rows:
        key = row["example"].metadata["key"]
        output = row["run"].outputs
        if not output:
            failed.append(key)
            output = empty
        pairs.append(({"key": key, "reference_outputs": row["example"].outputs}, output))
    report = run_evaluators(pairs, [evaluate_pair])
    if report.failures:
        raise ExperimentIncompleteError(f"{item.prefix}: {'; '.join(report.failures)}")
    held = {m.key: m.denominator for m in report.totals}
    labels = reference_denominators(item.dataset)
    wrong = [k for k in SCOPE_KEYS if held.get(k) != labels[k]]
    if held.get(LABELLED_DEADLINES, 0) > labels[LABELLED_DEADLINES]:
        wrong.append(LABELLED_DEADLINES)
    if wrong:
        said = ", ".join(f"{k} {held.get(k)} where the labels give {labels[k]}" for k in wrong)
        raise ExperimentIncompleteError(f"{item.prefix} counts {said}, so nothing was recorded.")
    model, effort, prompt_version = section_setup()
    return ExperimentEntry(
        name=results.experiment_name,
        experiment_id=str(results.experiment_id),
        agent=item.agent,
        dataset=item.dataset,
        repetition=item.repetition,
        ran_at=now.isoformat(timespec="seconds"),
        examples=expected,
        failed_examples=tuple(failed),
        model=model,
        effort=effort,
        prompt_version=prompt_version,
        measures={m.key: Figure(m.numerator, m.denominator, m.population) for m in report.totals},
    )


def _arguments(argv: Sequence[str] | None) -> argparse.Namespace:
    def chosen(allowed: Sequence[str]) -> Callable[[str], list[str]]:
        def parse(text: str) -> list[str]:
            names = [n.strip() for n in text.split(",") if n.strip()]
            bad = [n for n in names if n not in allowed]
            if bad or not names:
                raise argparse.ArgumentTypeError(f"choose from {', '.join(allowed)}")
            return list(dict.fromkeys(names))

        return parse

    def count(low: int, high: int | None = None) -> Callable[[str], int]:
        def parse(text: str) -> int:
            number = int(text)
            if number < low or (high is not None and number > high):
                limit = f"at least {low}" if high is None else f"from {low} to {high}"
                raise argparse.ArgumentTypeError(f"must be {limit}")
            return number

        return parse

    parser = argparse.ArgumentParser(prog="python -m evals.experiments", description=__doc__)
    parser.add_argument("--agents", type=chosen(AGENTS), default=list(AGENTS))
    parser.add_argument("--datasets", type=chosen(tuple(DATASETS)), default=list(DATASETS))
    parser.add_argument("--repetitions", type=count(1), default=DEFAULT_REPETITIONS)
    parser.add_argument("--concurrency", type=count(1, MAX_CONCURRENCY), default=2)
    parser.add_argument("--results", type=Path, default=RESULTS_FILE)
    return parser.parse_args(argv)


def main(
    argv: Sequence[str] | None = None,
    *,
    client: Any = None,
    evaluate_fn: Callable[..., Any] | None = None,
    targets: Targets = default_targets,
    env: Mapping[str, str] | None = None,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> int:
    """Make the experiments that the file does not hold yet, writing each one as it finishes.

    Args:
        argv: Command-line arguments; None reads them from the process.
        client: A LangSmith client or a fake of one; None makes a real one from the environment.
        evaluate_fn: ``langsmith.evaluate``, or a fake of it.
        targets: Gives the agent to run for an agent name and a dataset name.
        env: The environment; the process's when omitted.
        now: The clock.

    Returns:
        0 when every experiment asked for is in the file, otherwise 1.
    """
    args = _arguments(argv)
    env = os.environ if env is None else env
    try:
        check_backend(env)
    except BackendRefusedError as error:
        print(f"FAIL {error}")
        return 1
    if client is None:
        key = env.get("LANGSMITH_API_KEY") or env.get("LANGSMITH_KEY")
        if not key:
            print("FAIL no LangSmith key in the environment (LANGSMITH_API_KEY or LANGSMITH_KEY)")
            return 1
        client = make_client(key, env)
    if evaluate_fn is None:
        from langsmith import evaluate as evaluate_fn
    held = {e.kind for e in read_entries(args.results)}
    for item in plan(args.agents, args.datasets, args.repetitions):
        if (item.agent, item.dataset, item.repetition) in held:
            print(f"{item.prefix} is already in the file; not run again")
            continue
        try:
            results = evaluate_fn(
                targets(item.agent, item.dataset),
                data=DATASETS[item.dataset][0],
                evaluators=langsmith_evaluators(),
                experiment_prefix=item.prefix,
                description=f"The {item.agent} agent on {item.dataset}, run {item.repetition}.",
                metadata={
                    "agent": item.agent,
                    "dataset": item.dataset,
                    "repetition": item.repetition,
                    **dict(
                        zip(("model", "effort", "prompt_version"), section_setup(), strict=True)
                    ),
                },
                max_concurrency=args.concurrency,
                num_repetitions=1,
                client=client,
                disable_evaluator_tracing=True,
            )
            entry = entry_from(item, results, now=now())
            append_entry(args.results, entry)
        except Exception as error:  # the run stops here, and what it kept is already in the file
            LOG.exception("The experiment %s did not finish", item.prefix)
            print(f"FAIL {item.prefix}: {type(error).__name__}: {error}")
            return 1
        print(f"{entry.name}: " + "; ".join(f"{k} {f.text}" for k, f in entry.measures.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
