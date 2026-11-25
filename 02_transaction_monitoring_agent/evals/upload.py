"""Upload the evaluation dataset to LangSmith, once, from the example file on disk."""

import argparse
import os
import sys
from pathlib import Path
from typing import Any

from fsi_common.evals.upload import DEFAULT_ENDPOINT, UploadError, upload_dataset

from .build_dataset import DATA_DIR, build, disk_problems, read_examples

DATASET_NAME = "transaction-monitoring-reference"
DESCRIPTION = (
    "Two fictional customers' card transactions from the FSI hackathon starter: the analysts' "
    "labels for the eleven transactions before 19 October, and the four simulated reviews of the "
    "week after, as labels by the starter's own rule."
)


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
    """Check the example file against the starter's files, then upload the dataset.

    Args:
        argv: Command-line arguments; None reads them from the process.
        client: A LangSmith client or a fake of one; None makes a real one from the environment.

    Returns:
        0 when the dataset is present with the right content, otherwise 1.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    args = parser.parse_args(argv)
    built = build()
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
    try:
        result = upload_dataset(
            DATASET_NAME,
            read_examples(args.data_dir),
            client=client,
            description=DESCRIPTION,
        )
    except UploadError as error:
        print(f"FAIL {error}")
        return 1
    added = f"added={result.added}" if result.added else "nothing added"
    print(f"{result.name} id={result.dataset_id} examples={result.present} {added}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
