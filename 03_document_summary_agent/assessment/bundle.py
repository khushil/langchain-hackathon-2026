"""The bundle's file layout: one folder per corpus run, one file per part, read back exactly.

Layout of ``<root>/<corpus>/``:

- ``bundle.json``: the index (corpus, run, scope, sources, counts)
- ``register.json``: the obligation register, every unit's disposition and the populations
- ``candidates.jsonl``: one candidate per line, kept or dropped
- ``judgements.jsonl``: one model call per line, request and answer, keyed by request digest
- ``assessments.jsonl``: one assessment per line
- ``facts.jsonl``: the evidence facts and the graph facts
- ``clause_map.jsonl``: every clause in force, mapped or listed unmapped with its reason
- ``seed_matches.jsonl``: one seed per line, matched by ``provisions.match_seed`` at the end of
  the run; empty for a corpus with no seeds
- ``gap_report.json``: the brief a named person signs
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from assessment.records import COPIED_ATTRIBUTES, FACT_KINDS, Bundle
from context.errors import ContextError
from fsi_common.records import fact_topic_context

FACT_CONTEXT = fact_topic_context(kinds=FACT_KINDS, copied_attributes=COPIED_ATTRIBUTES)
"""The validation context every fact of a bundle is built and read with."""

_LISTS = ("candidates", "judgements", "assessments", "facts", "clause_map", "seed_matches")


class BundleFileError(ContextError):
    """A bundle folder is missing a file, or a file does not read as its record."""


def _dump(value: Any) -> Any:
    return value.model_dump(mode="json", by_alias=True)


def write_bundle(bundle: Bundle, root: Path) -> Path:
    """Write a bundle into ``<root>/<corpus>/``, one file per part.

    Args:
        bundle: The bundle.
        root: The folder that holds one folder per corpus.

    Returns:
        The bundle's folder.
    """
    folder = root / bundle.index.corpus
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "bundle.json").write_text(json.dumps(_dump(bundle.index), indent=1), "utf-8")
    (folder / "register.json").write_text(
        json.dumps(_dump(bundle.obligation_register), indent=1, ensure_ascii=False), "utf-8"
    )
    for name in _LISTS:
        rows = [json.dumps(_dump(r), ensure_ascii=False) for r in getattr(bundle, name)]
        (folder / f"{name}.jsonl").write_text("".join(f"{r}\n" for r in rows), "utf-8")
    (folder / "gap_report.json").write_text(
        json.dumps(_dump(bundle.gap_report), indent=1, ensure_ascii=False), "utf-8"
    )
    return folder


def read_bundle(folder: Path) -> Bundle:
    """Read a bundle folder back into the records it was written from.

    Args:
        folder: The bundle's folder.

    Returns:
        The bundle, every record validated again (ids recomputed).

    Raises:
        BundleFileError: If a file is missing or a record does not validate.
    """
    try:
        data: dict[str, Any] = {
            "index": json.loads((folder / "bundle.json").read_text("utf-8")),
            "obligation_register": json.loads((folder / "register.json").read_text("utf-8")),
            "gap_report": json.loads((folder / "gap_report.json").read_text("utf-8")),
        }
        for name in _LISTS:
            lines = (folder / f"{name}.jsonl").read_text("utf-8").splitlines()
            data[name] = [json.loads(line) for line in lines if line.strip()]
        return Bundle.model_validate(data, context=FACT_CONTEXT)
    except (OSError, ValueError, ValidationError) as exc:
        raise BundleFileError(f"The bundle in {folder} cannot be read: {exc}") from exc
