"""Build the section and document examples from the reference labels and the policy statement."""

import argparse
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from .labels import (
    LABELS_SHA256,
    LabelFormatError,
    check_labels,
    read_labels,
    reconciliation_problems,
    sha256_of,
)
from .normalise import paragraph_texts

TOPIC = Path(__file__).resolve().parent.parent
DATA_DIR = Path(__file__).resolve().parent / "data"
DEFAULT_LABELS = DATA_DIR / "reference_labels.tsv"
DEFAULT_DOCUMENT = TOPIC / "data" / "documents" / "PS26-4.md"


DOCUMENT_ID = "PS26-4"
FIRM_ID = "FIRM-001"
REQUEST_TEXT = "Write the compliance brief on PS26-4 for Harbour Mutual Bank."
LABELS_MADE_BY = (
    "two independent labelling agents, working to rules fixed before they started; "
    "the coordinating session settled each disagreement and recorded why"
)


@dataclass(frozen=True)
class SectionText:
    """One section of the policy statement as the starter's document tool splits it."""

    number: str
    title: str
    text: str


@dataclass(frozen=True)
class Built:
    """The two files the build produces, and every problem found in the labels."""

    sections: str
    documents: str
    problems: list[str] = field(default_factory=list)
    sections_written: int = 0
    sections_in_document: int = 0
    paragraphs_covered: int = 0
    paragraphs_in_document: int = 0


def read_examples(name: str, *, data_dir: Path = DATA_DIR) -> list[dict]:
    """Read one of the example files, one JSON object per line.

    Args:
        name: The file name, `sections.jsonl` or `documents.jsonl`.
        data_dir: The folder that holds it.

    Returns:
        The examples in file order.
    """
    lines = (data_dir / name).read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines]


def split_sections(document_text: str) -> list[SectionText]:
    """Split a document at its second-level headings, as the starter's document tool does.

    Args:
        document_text: The Markdown of the document.

    Returns:
        The sections in order.
    """
    sections = []
    for block in re.split(r"^## ", document_text, flags=re.MULTILINE)[1:]:
        heading, _, body = block.partition("\n")
        number, _, title = heading.partition(". ")
        sections.append(SectionText(number.strip(), title.strip(), body.strip()))
    return sections


def _text_or_none(value: str) -> str | None:
    return value or None


def _item(row: dict[str, str]) -> dict:
    return {
        "paragraph": row["paragraph"],
        "section": row["section"],
        "item": int(row["item"]),
        "kind": row["kind"],
        "requirement": _text_or_none(row["requirement"]),
        "actor": row["actor"],
        "deadline_as_written": _text_or_none(row["deadline_as_written"]),
        "evidence": row["evidence"],
        "conditions": _text_or_none(row["conditions"]),
        "cross_refs": row["cross_refs"].split(", ") if row["cross_refs"] else [],
        "firms": {
            FIRM_ID: {
                "applies": row["firm_001"],
                "reason": _text_or_none(row["firm_001_reason"]),
            }
        },
    }


def _line(example: dict) -> str:
    return json.dumps(example, ensure_ascii=False) + "\n"


def build(labels_path: Path, document_path: Path) -> Built:
    """Build both example files and check the labels.

    Args:
        labels_path: The labels table.
        document_path: The policy statement.

    Returns:
        The text of both files and every problem found; the files are not written.

    Raises:
        LabelFormatError: If the labels table cannot be read.
    """
    rows = read_labels(labels_path)
    document_text = document_path.read_text(encoding="utf-8")
    paragraphs = paragraph_texts(document_text)
    sections = split_sections(document_text)
    problems = check_labels(rows, paragraphs)
    problems.extend(reconciliation_problems(rows))
    labels_sha = sha256_of(labels_path)
    if labels_sha != LABELS_SHA256:
        problems.append(f"the labels' digest {labels_sha} is not the digest on record")
    metadata = {
        "labels_sha256": "sha256:" + labels_sha,
        "document_sha256": "sha256:" + sha256_of(document_path),
        "labels_made_by": LABELS_MADE_BY,
    }
    items = [_item(row) for row in rows]
    section_lines = []
    for section in sections:
        numbers = [p for p in paragraphs if p.split(".")[0] == section.number]
        section_lines.append(
            _line(
                {
                    "key": f"{DOCUMENT_ID}/section/{section.number}",
                    "inputs": {
                        "document_id": DOCUMENT_ID,
                        "firm_id": FIRM_ID,
                        "section": {
                            "number": section.number,
                            "title": section.title,
                            "text": section.text,
                        },
                    },
                    "reference_outputs": {
                        "paragraphs": numbers,
                        "items": [i for i in items if i["section"] == section.number],
                        "paragraph_texts": {p: paragraphs[p] for p in numbers},
                    },
                    "metadata": metadata,
                }
            )
        )
    document_line = _line(
        {
            "key": f"{DOCUMENT_ID}/{FIRM_ID}",
            "inputs": {
                "request": {
                    "document_id": DOCUMENT_ID,
                    "firm_id": FIRM_ID,
                    "request": REQUEST_TEXT,
                }
            },
            "reference_outputs": {
                "paragraphs": list(paragraphs),
                "items": items,
                "paragraph_texts": paragraphs,
            },
            "metadata": metadata,
        }
    )
    return Built(
        sections="".join(section_lines),
        documents=document_line,
        problems=problems,
        sections_written=len(section_lines),
        sections_in_document=len(sections),
        paragraphs_covered=len({row["paragraph"] for row in rows} & set(paragraphs)),
        paragraphs_in_document=len(paragraphs),
    )


def built_files(built: Built) -> dict[str, str]:
    """The two files of a build, by file name.

    Args:
        built: The result of `build`.

    Returns:
        File name to its text.
    """
    return {"sections.jsonl": built.sections, "documents.jsonl": built.documents}


def disk_problems(built: Built, data_dir: Path) -> list[str]:
    """Compare the files in a folder with what the build produces.

    Args:
        built: The result of `build`.
        data_dir: The folder that should hold the files.

    Returns:
        One sentence per file that is missing or differs.
    """
    problems = []
    for name, content in built_files(built).items():
        path = data_dir / name
        if not path.exists():
            problems.append(f"{name} is missing")
        elif path.read_text(encoding="utf-8") != content:
            problems.append(f"{name} on disk differs from what the build produces")
    return problems


def main(argv: list[str] | None = None) -> int:
    """Build the example files, or with --check compare them with the files on disk.

    Args:
        argv: Command-line arguments; None reads them from the process.

    Returns:
        0 when the labels are sound and (in check mode) the files on disk match, otherwise 1.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="compare with the files on disk")
    parser.add_argument("--labels", type=Path, default=DEFAULT_LABELS)
    parser.add_argument("--document", type=Path, default=DEFAULT_DOCUMENT)
    parser.add_argument("--out-dir", type=Path, default=DATA_DIR)
    args = parser.parse_args(argv)
    try:
        built = build(args.labels, args.document)
    except LabelFormatError as error:
        print(f"FAIL {error}")
        return 1
    problems = list(built.problems)
    files = built_files(built)
    if args.check:
        problems.extend(disk_problems(built, args.out_dir))
    for problem in problems:
        print(f"FAIL {problem}")
    if problems:
        return 1
    if not args.check:
        args.out_dir.mkdir(parents=True, exist_ok=True)
        for name, content in files.items():
            (args.out_dir / name).write_text(content, encoding="utf-8", newline="\n")
    verb = "checked" if args.check else "built"
    print(f"{verb} {built.sections_written} of {built.sections_in_document} sections")
    print(
        f"{verb} {built.paragraphs_covered} of {built.paragraphs_in_document} paragraphs "
        "covered by the labels"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
