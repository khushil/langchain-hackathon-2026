"""``python -m assessment``: plan the calls of a corpus, then run it and write its bundle.

``plan`` counts the calls by code and prints the count; it makes no call. ``run`` prints the
plan first, makes the calls through the ``assess`` role on the backend ``MODEL_BACKEND`` names
(``record`` or ``replay``), writes the bundle to ``<out>/<corpus>/`` and prints the lines the
deck reads.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path

from assessment.bundle import BundleFileError, write_bundle
from assessment.engine import (
    DEFAULT_CONCURRENCY,
    REGULATION_NAMES,
    Prepared,
    RunPlan,
    plan_of,
    prepare,
    run_assessment,
)
from assessment.judge import AsyncJudge, ModelJudge
from assessment.profile import load_profile
from assessment.records import Bundle
from assessment.run_lines import left_out_lines, run_lines
from assessment.texts import TextIndex, load_texts
from context.errors import ContextError
from utils import PROJECT_ROOT
from utils.models import (
    BACKEND_MODES,
    DEFAULT_BACKEND,
    MAX_CONCURRENCY,
    ModelConfigError,
)

_RUN_LABELS = {"record": "record", "replay": "replay"}
_REGULATIONS_HELP = (
    "assess only these regulations, for example DORA,AI-ACT; the others are recorded in the "
    "bundle as not included, with the commands that bring them in; a replay reads "
    "data/assessments/<corpus>/recordings unless MODEL_RECORDINGS_DIR names a folder"
)


class _UsageError(ContextError):
    """The command line asks for something the run cannot do."""


def _concurrency(value: str) -> int:
    number = int(value)
    if not 1 <= number <= MAX_CONCURRENCY:
        raise argparse.ArgumentTypeError(f"must be between 1 and {MAX_CONCURRENCY}")
    return number


def _regulations(value: str) -> list[str]:
    """Read ``--regulations``: names in any case, with a space, slash or underscore for a hyphen."""
    wanted = [re.sub(r"[\s/_]+", "-", part.strip()).upper() for part in value.split(",")]
    wanted = [w for w in wanted if w]
    unknown = [w for w in wanted if w not in REGULATION_NAMES]
    if unknown or not wanted:
        what = (
            f"There is no regulation {', '.join(unknown)}" if unknown else "No regulation is named"
        )
        raise _UsageError(
            f"{what}; --regulations takes {', '.join(REGULATION_NAMES)}, separated by commas."
        )
    return [k for k in REGULATION_NAMES if k in wanted]


def open_recordings(corpus: str) -> Path:
    """Return the folder of the open regulations' recordings that the repository commits.

    Args:
        corpus: The corpus's name.

    Returns:
        ``data/assessments/<corpus>/recordings`` under the topic, which a replay of the open
        regulations reads when no folder is named.
    """
    return PROJECT_ROOT / "data" / "assessments" / corpus / "recordings"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m assessment", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    plan = commands.add_parser("plan", help="count the judgement calls of a corpus; makes none")
    plan.add_argument("corpus")
    plan.add_argument("--concurrency", type=_concurrency, default=DEFAULT_CONCURRENCY)
    plan.add_argument("--regulations", help=_REGULATIONS_HELP)
    run = commands.add_parser("run", help="assess a corpus and write its bundle")
    run.add_argument("corpus")
    run.add_argument("--out", required=True, help="the folder that holds one folder per corpus")
    run.add_argument("--concurrency", type=_concurrency, default=DEFAULT_CONCURRENCY)
    run.add_argument("--regulations", help=_REGULATIONS_HELP)
    run.add_argument(
        "--run", choices=sorted(_RUN_LABELS), help="the bundle's label; from MODEL_BACKEND if unset"
    )
    return parser


def _run_label(chosen: str | None) -> str:
    if chosen:
        return chosen
    backend = os.environ.get("MODEL_BACKEND", "").strip() or DEFAULT_BACKEND
    if backend not in _RUN_LABELS:
        raise _UsageError(
            f"MODEL_BACKEND is '{backend}', and a bundle is labelled record or replay. Set "
            f"MODEL_BACKEND to one of {', '.join(sorted(_RUN_LABELS))} in the environment or the "
            f".env in the repository root; the backends are {', '.join(BACKEND_MODES)}."
        )
    return _RUN_LABELS[backend]


def _plan_lines(plan: RunPlan, texts: TextIndex, *, with_left_out: bool) -> list[str]:
    """Write the plan; the line on regulations left out is the plan's alone, and a run's own
    lines carry it first, so that it is printed once per command."""
    names = ", ".join(f"{REGULATION_NAMES[k]} {n}" for k, n in plan.by_regulation.items())
    return [
        plan.line,
        f"Applicable by regulation: {names}",
        f"Second look: {plan.second_look} obligations had no kept clause on the first look",
        *(left_out_lines(texts) if with_left_out else []),
    ]


@contextmanager
def _default_recordings(corpus: str, label: str, *, partial: bool) -> Iterator[None]:
    """Point a replay of chosen regulations at the committed open recordings, if none is named."""
    named = os.environ.get("MODEL_RECORDINGS_DIR", "").strip()
    if label != "replay" or not partial or named:
        yield
        return
    os.environ["MODEL_RECORDINGS_DIR"] = str(open_recordings(corpus))
    try:
        yield
    finally:
        del os.environ["MODEL_RECORDINGS_DIR"]


def _write_in_place(bundle: Bundle, root: Path) -> Path:
    """Write a bundle beside its folder, then move each file in, so a failed write changes nothing.

    Args:
        bundle: The bundle.
        root: The folder that holds one folder per corpus.

    Returns:
        The bundle's folder, ``<root>/<corpus>``. Files already there that the bundle does not
        replace (a folder of recordings, say) stay where they are.

    Raises:
        OSError: If a file cannot be written; the folder is then as it was.
    """
    root.mkdir(parents=True, exist_ok=True)
    stage = root / f".{bundle.index.corpus}.writing-{os.getpid()}"
    try:
        written = write_bundle(bundle, stage)
        folder = root / bundle.index.corpus
        folder.mkdir(exist_ok=True)
        for part in written.iterdir():
            os.replace(part, folder / part.name)
    finally:
        shutil.rmtree(stage, ignore_errors=True)
    return folder


def main(
    argv: Sequence[str] | None = None,
    *,
    judge_factory: Callable[[], AsyncJudge] = ModelJudge,
    loader: Callable[..., TextIndex] = load_texts,
) -> int:
    """Run the command line.

    Args:
        argv: The arguments; ``sys.argv`` by default.
        judge_factory: Makes the judge once the plan is printed; tests give a fake.
        loader: Reads the regulations and the corpus, given ``regulations=`` when the option is
            used; tests give one that makes no fetch.

    Returns:
        0 on success; 2 when the command cannot be carried out, with the reason on stderr.
    """
    args = _parser().parse_args(argv)
    try:
        label = _run_label(args.run) if args.command == "run" else ""
        keys = None if args.regulations is None else _regulations(args.regulations)
        texts = loader(args.corpus) if keys is None else loader(args.corpus, regulations=keys)
        prepared: Prepared = prepare(texts, load_profile(args.corpus))
        plan = plan_of(prepared, concurrency=args.concurrency)
        for line in _plan_lines(plan, texts, with_left_out=args.command == "plan"):
            print(line, flush=True)
        if args.command == "plan":
            return 0
        with _default_recordings(args.corpus, label, partial=keys is not None):
            bundle = run_assessment(
                args.corpus,
                judge_factory(),
                texts=texts,
                prepared=prepared,
                run=label,
                concurrency=args.concurrency,
            )
        folder = _write_in_place(bundle, Path(args.out))
        for line in run_lines(bundle, texts):
            print(line)
        print(f"Bundle written to {folder}")
    except (ContextError, ModelConfigError, BundleFileError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
