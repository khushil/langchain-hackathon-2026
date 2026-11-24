"""Read the reference labels table and check it against the policy statement and its own rules."""

import hashlib
from pathlib import Path

LABELS_SHA256 = "ad090c551c484cdbe8d44befb40b086e3b160c273498e0b6d0952d058bd646a4"


EXPECTED_ROWS = 77


EXPECTED_OBLIGATIONS = 39


EXPECTED_OBLIGATION_PARAGRAPHS = 23


COLUMNS = (
    "paragraph section item kind requirement actor deadline_as_written evidence "
    "conditions cross_refs firm_001 firm_001_reason"
).split()


KINDS = {
    "obligation",
    "permission",
    "guidance",
    "definition",
    "scope",
    "effective_date",
    "regulator_action",
    "context",
}


ACTORS = {"firm", "board", "senior_manager", "small_firm", "group", "regulator", "none"}


APPLIES = {"applies", "does_not_apply", "depends", "n/a"}


MAX_EVIDENCE_WORDS = 30


class LabelFormatError(Exception):
    """The labels file cannot be read as a table of the expected columns."""


def sha256_of(path: Path) -> str:
    """The hex SHA-256 of a file's bytes.

    Args:
        path: The file to read.

    Returns:
        The digest in lower-case hex.
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_labels(path: Path) -> list[dict[str, str]]:
    """Read the labels table, one dict of strings per row.

    Args:
        path: A tab-separated file with the expected header.

    Returns:
        The rows in file order, each keyed by column name.

    Raises:
        LabelFormatError: If the header differs or a row has the wrong number of columns.
    """
    lines = path.read_text(encoding="utf-8").split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    if not lines or lines[0].split("\t") != COLUMNS:
        raise LabelFormatError(f"{path}: the header is not the expected {len(COLUMNS)} columns")
    rows = []
    for number, line in enumerate(lines[1:], start=2):
        cells = line.split("\t")
        if len(cells) != len(COLUMNS):
            raise LabelFormatError(
                f"{path}: row {number} has {len(cells)} columns, expected {len(COLUMNS)}"
            )
        rows.append(dict(zip(COLUMNS, cells, strict=True)))
    return rows


def _numeric(paragraph: str) -> tuple[int, ...]:
    return tuple(int(part) for part in paragraph.split("."))


def check_labels(rows: list[dict[str, str]], paragraphs: dict[str, str]) -> list[str]:
    """Check the labels against the document and against their own rules.

    Args:
        rows: The label rows.
        paragraphs: Paragraph number to its text, for every paragraph of the document.

    Returns:
        One sentence per problem; empty when the labels are sound.
    """
    problems: list[str] = []
    covered = {row["paragraph"] for row in rows}
    missing = [p for p in paragraphs if p not in covered]
    if missing:
        problems.append(
            f"the labels cover {len(paragraphs) - len(missing)} of {len(paragraphs)} paragraphs; "
            f"none for {', '.join(missing)}"
        )
    unknown = sorted(covered - set(paragraphs), key=_numeric)
    if unknown:
        problems.append(f"the labels name paragraphs the document lacks: {', '.join(unknown)}")
    seen: dict[str, int] = {}
    for row in rows:
        where = f"paragraph {row['paragraph']} item {row['item']}"
        text = paragraphs.get(row["paragraph"])
        seen[row["paragraph"]] = seen.get(row["paragraph"], 0) + 1
        if row["item"] != str(seen[row["paragraph"]]):
            problems.append(f"{where}: items are not numbered 1, 2, 3 in order")
        if text is not None and row["section"] != row["paragraph"].split(".")[0]:
            problems.append(f"{where}: the section column disagrees with the paragraph")
        problems.extend(_row_problems(row, where, text))
    keys = [(_numeric(r["paragraph"]), int(r["item"]) if r["item"].isdigit() else 0) for r in rows]
    if keys != sorted(keys):
        problems.append("the rows are not in paragraph then item order")
    return problems


def _row_problems(row: dict[str, str], where: str, text: str | None) -> list[str]:
    problems = []
    if row["kind"] not in KINDS:
        problems.append(f"{where}: kind '{row['kind']}' is not one of the eight kinds")
    if row["actor"] not in ACTORS:
        problems.append(f"{where}: actor '{row['actor']}' is not one of the seven actors")
    if row["firm_001"] not in APPLIES:
        problems.append(f"{where}: firm_001 '{row['firm_001']}' is not a known value")
    is_obligation = row["kind"] == "obligation"
    if is_obligation and not row["requirement"]:
        problems.append(f"{where}: an obligation has no requirement")
    if is_obligation == (row["firm_001"] == "n/a"):
        problems.append(f"{where}: firm_001 is n/a exactly when the row is not an obligation")
    if not row["evidence"]:
        problems.append(f"{where}: the row has no evidence")
    if len(row["evidence"].split()) > MAX_EVIDENCE_WORDS:
        problems.append(f"{where}: the evidence is over {MAX_EVIDENCE_WORDS} words")
    for column in ("evidence", "deadline_as_written"):
        value = row[column]
        if value and (text is None or value not in text):
            problems.append(f"{where}: {column} is not word for word in the paragraph")
    return problems


def reconciliation_problems(rows: list[dict[str, str]]) -> list[str]:
    obligations = [r for r in rows if r["kind"] == "obligation"]
    found = (len(rows), len(obligations), len({r["paragraph"] for r in obligations}))
    expected = (EXPECTED_ROWS, EXPECTED_OBLIGATIONS, EXPECTED_OBLIGATION_PARAGRAPHS)
    if found == expected:
        return []
    return [
        f"the labels hold {found[0]} rows, {found[1]} obligations in {found[2]} paragraphs; "
        f"expected {expected[0]}, {expected[1]} in {expected[2]}"
    ]
