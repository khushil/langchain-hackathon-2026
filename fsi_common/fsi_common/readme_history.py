"""Build the README's sentence on the history from git, and check or refresh it.

The sentence under "How it was built" names a commit and says when the build began and ended up to
it, how many commits it took and of which kinds. ``--check`` fails, naming the README line, when
the sentence differs from what git gives for the commit it names. With ``--strict`` it also fails
when the history has moved on by more than commits of the README itself, which the gate of a tag
uses. ``--write`` rewrites the sentence for the current commit. The README is committed after it is
written, so that commit, and any other that changes only the README, is not counted.

A folder without git history, such as an export of the repository, or a shallow clone cannot be
checked; the check then prints a line starting ``SKIPPED`` with the reason and exits 0.

Run from the repository root: ``python -m fsi_common.readme_history --check README.md``.
"""

from __future__ import annotations

import argparse
import re
import subprocess
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path

SECTION_HEADING = "## How it was built"
SENTENCE_START = "The build up to commit `"
SENTENCE_PATTERN = re.compile(r"^The build up to commit `([0-9a-f]{7,40})` ran .*?\)\.")
KIND_PATTERN = re.compile(r"^(\w+)(\([^)]*\))?!?:")


class HistoryError(RuntimeError):
    """Git could not give the history that the sentence is built from, or the README has no line."""


class CheckStatus(Enum):
    """How a check of the README ended."""

    OK = "ok"
    SKIPPED = "skipped"
    MISMATCH = "mismatch"
    STALE = "stale"
    MISSING_COMMIT = "missing commit"


@dataclass(frozen=True)
class CheckResult:
    """The end of a check and the lines that say why."""

    status: CheckStatus
    message: str


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, check=False
    )


def _plural(count: int, word: str) -> str:
    return f"{count} {word}" if count == 1 else f"{count} {word}s"


def build_sentence(root: Path, end: str) -> str:
    """Return the sentence that opens the section, built from the commits up to ``end``.

    Args:
        root: The repository's folder.
        end: A revision; it and every commit before it count.

    Returns:
        The sentence, with the commit's short hash, the first and last commit times in UTC, the
        length of the build and the commits by kind, most common first.

    Raises:
        HistoryError: If git cannot list the commits, or there are none.
    """
    listing = _git(root, "log", end, "--format=%at%x09%s")
    short = _git(root, "rev-parse", "--short=7", f"{end}^{{commit}}")
    if listing.returncode or short.returncode:
        raise HistoryError(f"git could not list the commits up to {end}: {listing.stderr.strip()}")
    rows = [line.split("\t", 1) for line in listing.stdout.splitlines() if line]
    if not rows:
        raise HistoryError(f"no commits up to {end}")
    times = [datetime.fromtimestamp(int(stamp), UTC) for stamp, _ in rows]
    kinds = Counter(
        (match.group(1) if (match := KIND_PATTERN.match(subject)) else "other")
        for _, subject in rows
    )
    first, last = min(times), max(times)
    hours, minutes = divmod(int((last - first).total_seconds() // 60), 60)

    def day(moment: datetime) -> str:
        return f"{moment.day} {moment:%B %Y}"

    if first.date() == last.date():
        span = f"from {first:%H:%M} to {last:%H:%M} UTC on {day(first)}"
    else:
        span = f"from {first:%H:%M} UTC on {day(first)} to {last:%H:%M} UTC on {day(last)}"
    ordered = sorted(kinds.items(), key=lambda item: (-item[1], item[0]))
    by_kind = ", ".join(f"{count} {kind}" for kind, count in ordered)
    return (
        f"The build up to commit `{short.stdout.strip()}` ran {span}, "
        f"{_plural(hours, 'hour')} {_plural(minutes, 'minute')}, "
        f"in {_plural(len(rows), 'commit')} ({by_kind})."
    )


def _cannot_check(root: Path) -> str | None:
    """Return why ``root`` holds no history to check against, or ``None`` when it does."""
    if not (root / ".git").exists():
        return f"no .git in {root}, so the commits cannot be read here"
    if _git(root, "rev-parse", "--is-shallow-repository").stdout.strip() == "true":
        return "this is a shallow clone, so the commits are not all here"
    return None


def _find_line(readme: Path) -> tuple[list[str], int]:
    """Return the README's lines and the index of the section's sentence line."""
    lines = readme.read_text(encoding="utf-8").splitlines()
    try:
        start = lines.index(SECTION_HEADING)
    except ValueError as exc:
        raise HistoryError(f"{readme.name} has no '{SECTION_HEADING}' section") from exc
    for index in range(start + 1, len(lines)):
        if lines[index].startswith("## "):
            break
        if lines[index].startswith(SENTENCE_START):
            return lines, index
    raise HistoryError(f"{readme.name}: no line of the section starts '{SENTENCE_START}'")


def _commits_after(root: Path, named: str, readme_path: str) -> int:
    """Count the commits after ``named`` that changed anything but the README (or nothing)."""
    log = _git(root, "log", f"{named}..HEAD", "--format=@%H", "--name-only").stdout
    others = 0
    for block in log.split("@")[1:]:
        files = {line for line in block.splitlines()[1:] if line}
        if files != {readme_path}:
            others += 1
    return others


def check_readme(readme: Path, root: Path, *, strict: bool = False) -> CheckResult:
    """Check that the README's sentence is what git gives for the commit it names.

    Args:
        readme: The README file.
        root: The repository's folder.
        strict: Also fail when later commits changed more than the README.

    Returns:
        The result. ``MISMATCH`` names the README line and shows both sentences; ``STALE`` says how
        many commits since the named one changed more than the README.
    """
    reason = _cannot_check(root)
    if reason:
        return CheckResult(CheckStatus.SKIPPED, reason)
    try:
        lines, index = _find_line(readme)
    except HistoryError as exc:
        return CheckResult(CheckStatus.MISMATCH, str(exc))
    number = index + 1
    found = SENTENCE_PATTERN.match(lines[index])
    if not found:
        return CheckResult(
            CheckStatus.MISMATCH, f"{readme.name}:{number} does not hold the sentence in its form"
        )
    named = found.group(1)
    if _git(root, "cat-file", "-e", f"{named}^{{commit}}").returncode:
        return CheckResult(
            CheckStatus.MISSING_COMMIT,
            f"{readme.name}:{number} names commit {named}, which is not in {root}",
        )
    expected = build_sentence(root, named)
    if found.group(0) != expected:
        return CheckResult(
            CheckStatus.MISMATCH,
            f"{readme.name}:{number} differs from git\n  expected: {expected}\n"
            f"  found:    {found.group(0)}",
        )
    others = 0
    if strict:
        try:
            readme_path = readme.resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            readme_path = readme.name
        others = _commits_after(root, named, readme_path)
    if others:
        return CheckResult(
            CheckStatus.STALE,
            f"{readme.name}:{number} is stale: {_plural(others, 'commit')} since `{named}` changed "
            "more than the README; run `make readme-history` and commit the README",
        )
    return CheckResult(CheckStatus.OK, f"{readme.name}:{number} matches git")


def refresh_readme(readme: Path, root: Path) -> str:
    """Rewrite the README's sentence for the current commit, keeping the rest of its line.

    Args:
        readme: The README file.
        root: The repository's folder.

    Returns:
        The new sentence.

    Raises:
        HistoryError: If the section or its sentence is not in the README, or git gives no history.
    """
    lines, index = _find_line(readme)
    found = SENTENCE_PATTERN.match(lines[index])
    if not found:
        raise HistoryError(f"{readme.name}:{index + 1} does not hold the sentence in its form")
    sentence = build_sentence(root, "HEAD")
    lines[index] = sentence + lines[index][found.end() :]
    readme.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return sentence


def main(argv: list[str] | None = None) -> int:
    """Check or refresh the README's sentence and print what happened.

    Args:
        argv: The arguments; the process's own when absent.

    Returns:
        0 when the README matches, was rewritten or cannot be checked here (printed as
        ``SKIPPED``), else 1.
    """
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--check", type=Path, help="the README to check")
    parser.add_argument("--write", type=Path, help="the README to rewrite for the current commit")
    parser.add_argument(
        "--strict", action="store_true", help="with --check, also fail when the sentence is stale"
    )
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="the repository folder")
    args = parser.parse_args(argv)
    if bool(args.check) == bool(args.write):
        parser.error("give --check or --write, one of them")
    if args.write:
        try:
            print(f"readme-history: wrote {refresh_readme(args.write, args.root)}")
        except HistoryError as exc:
            print(f"readme-history: {exc}")
            return 1
        return 0
    result = check_readme(args.check, args.root, strict=args.strict)
    label = "SKIPPED" if result.status is CheckStatus.SKIPPED else "readme-history"
    print(f"{label}: {result.message}")
    return 0 if result.status in (CheckStatus.OK, CheckStatus.SKIPPED) else 1


if __name__ == "__main__":
    raise SystemExit(main())
