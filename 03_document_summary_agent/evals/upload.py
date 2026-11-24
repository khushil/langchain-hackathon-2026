"""Upload the section and document datasets to LangSmith, once, from the example files on disk."""

import argparse
import os
import sys
from pathlib import Path
from typing import Any

from fsi_common.evals.upload import UploadError, upload_dataset

from .build_dataset import (
    DATA_DIR,
    DEFAULT_DOCUMENT,
    DEFAULT_LABELS,
    LabelFormatError,
    build,
    disk_problems,
    read_examples,
)

SECTIONS_NAME = "compliance-brief-ps26-4-sections"
DOCUMENT_NAME = "compliance-brief-ps26-4-document"
DEFAULT_ENDPOINT = "https://eu.api.smith.langchain.com"
DESCRIPTIONS = {
    SECTIONS_NAME: "One example per section of the fictional policy statement PS26-4: the "
    "section's text and its labelled items, made by two independent labelling agents under "
    "rules fixed beforehand.",
    DOCUMENT_NAME: "The fictional policy statement PS26-4 for one firm: every labelled item.",
}


def read_key() -> str | None:
    """Read the LangSmith key from the environment, under either of its two names.

    Returns:
        The key, or None when neither name is set. The key is never printed by this module.
    """
    return os.environ.get("LANGSMITH_API_KEY") or os.environ.get("LANGSMITH_KEY") or None


def _make_client(key: str) -> Any:
    from langsmith import Client

    return Client(api_key=key, api_url=os.environ.get("LANGSMITH_ENDPOINT", DEFAULT_ENDPOINT))


def main(argv: list[str] | None = None, *, client: Any = None) -> int:
    """Check the example files against the labels, then upload both datasets.

    Args:
        argv: Command-line arguments; None reads them from the process.
        client: A LangSmith client or a fake of one; None makes a real one from the environment.

    Returns:
        0 when both datasets are present with the right content, otherwise 1.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    args = parser.parse_args(argv)
    try:
        built = build(DEFAULT_LABELS, DEFAULT_DOCUMENT)
    except LabelFormatError as error:
        print(f"FAIL {error}")
        return 1
    found = built.problems + disk_problems(built, args.data_dir)
    for problem in found:
        print(f"FAIL {problem}")
    if found:
        return 1
    if client is None:
        key = read_key()
        if key is None:
            print("FAIL no LangSmith key in the environment (LANGSMITH_API_KEY or LANGSMITH_KEY)")
            return 1
        client = _make_client(key)
    for name, file in ((SECTIONS_NAME, "sections.jsonl"), (DOCUMENT_NAME, "documents.jsonl")):
        examples = read_examples(file, data_dir=args.data_dir)
        try:
            result = upload_dataset(name, examples, client=client, description=DESCRIPTIONS[name])
        except UploadError as error:
            print(f"FAIL {error}")
            return 1
        added = f"added={result.added}" if result.added else "nothing added"
        print(f"{result.name} id={result.dataset_id} examples={result.present} {added}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
