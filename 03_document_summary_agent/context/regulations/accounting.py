"""Close the units a reader gives against the units pinned for the same fetched bytes.

The pin holds each unit's anchor, kind and the digest of its text, never the text, so it can be
committed where the text cannot. A unit missing, a unit that is not in the pin, a unit whose text
differs, or a unit pinned twice each stops the build with the units named.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from context.regulations.errors import DigestMismatchError, RegulationAccountingError
from context.regulations.manifest import REGULATIONS_DIR
from context.regulations.model import RegulationRead
from fsi_common.ids import digest_text

EXPECTED_DIR = REGULATIONS_DIR / "expected"
"""The folder of pinned unit records, one file per regulation."""


@dataclass(frozen=True)
class RegulationAccounting:
    """The outcome of closing a regulation's units against its pin.

    Attributes:
        units_read: The units the reader gave.
        units_pinned: The units the pin holds.
        by_kind: The count of units of each kind.
        line: The line that states the counts in words.
    """

    units_read: int
    units_pinned: int
    by_kind: dict[str, int]
    line: str


def pin_record(read: RegulationRead) -> dict[str, Any]:
    """Make the pin of a reading: what a later reading of the same bytes must equal.

    Args:
        read: The regulation read.

    Returns:
        A JSON-ready record with the source digest, counts, and each unit's anchor, kind and
        text digest.
    """
    return {
        "key": read.source.key,
        "source_digest": read.source.digest,
        "structure": read.structure_counts(),
        "units_by_kind": read.unit_counts(),
        "units": [[u.anchor, u.kind, digest_text(u.text)] for u in read.items],
    }


def write_pin(read: RegulationRead, path: Path) -> None:
    """Write a pin, one unit to a line, so a change shows plainly in a diff.

    Args:
        read: The regulation read.
        path: The file to write.
    """
    pin = pin_record(read)
    lines = ["{", f'  "key": {json.dumps(pin["key"])},']
    lines.append(f'  "source_digest": {json.dumps(pin["source_digest"])},')
    lines.append(f'  "structure": {json.dumps(pin["structure"], sort_keys=True)},')
    lines.append(f'  "units_by_kind": {json.dumps(pin["units_by_kind"], sort_keys=True)},')
    lines.append('  "units": [')
    rows = [f"    {json.dumps(row, ensure_ascii=False)}" for row in pin["units"]]
    lines.append(",\n".join(rows))
    lines.extend(["  ]", "}", ""])
    path.write_text("\n".join(lines), encoding="utf-8")


def load_pin(key: str, *, directory: Path = EXPECTED_DIR) -> dict[str, Any]:
    """Load the pin of a regulation.

    Args:
        key: The regulation key.
        directory: The folder of pins.

    Returns:
        The pin record.

    Raises:
        RegulationAccountingError: If the pin file is missing or unreadable.
    """
    path = directory / f"{key.lower()}.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RegulationAccountingError(f"The pin {path} cannot be read: {exc}.") from exc


def account_for_regulation(read: RegulationRead, pin: dict[str, Any]) -> RegulationAccounting:
    """Close a reading against its pin, naming every unit that does not match.

    Args:
        read: The regulation read.
        pin: The pin of the same bytes.

    Returns:
        The accounting, whose line states "N of N units read and accounted for".

    Raises:
        DigestMismatchError: If the pin is for other bytes than were read.
        RegulationAccountingError: If a unit is missing, extra, changed or pinned twice.
    """
    key = read.source.key
    if pin["source_digest"] != read.source.digest:
        raise DigestMismatchError(
            f"The pin of {key} is for {pin['source_digest']} and the bytes read are "
            f"{read.source.digest}; the pin must be remade from the bytes the manifest records."
        )
    pinned_rows = pin["units"]
    pinned_anchors = [row[0] for row in pinned_rows]
    repeated = sorted(a for a, n in Counter(pinned_anchors).items() if n > 1)
    if repeated:
        raise RegulationAccountingError(
            f"The pin of {key} lists a unit twice: {', '.join(repeated)}.", repeated=repeated
        )
    read_anchors = [u.anchor for u in read.items]
    read_twice = sorted(a for a, n in Counter(read_anchors).items() if n > 1)
    if read_twice:
        raise RegulationAccountingError(
            f"The reading of {key} holds a unit twice: {', '.join(read_twice)}.",
            repeated=read_twice,
        )
    pinned = {row[0]: row[2] for row in pinned_rows}
    read_digest = {u.anchor: digest_text(u.text) for u in read.items}
    missing = [a for a in pinned_anchors if a not in read_digest]
    unexpected = [a for a in read_digest if a not in pinned]
    changed = [a for a in read_digest if a in pinned and read_digest[a] != pinned[a]]
    if missing or unexpected or changed:
        parts = []
        if missing:
            parts.append(f"{len(missing)} not read: {', '.join(missing)}")
        if unexpected:
            parts.append(f"{len(unexpected)} read and not pinned: {', '.join(unexpected)}")
        if changed:
            parts.append(f"{len(changed)} changed in text: {', '.join(changed)}")
        raise RegulationAccountingError(
            f"The units of {key} do not close: {len(read_digest) - len(unexpected)} of "
            f"{len(pinned_anchors)} pinned units are read; " + "; ".join(parts) + ".",
            missing=missing,
            unexpected=unexpected,
            changed=changed,
        )
    return RegulationAccounting(
        units_read=len(read_digest),
        units_pinned=len(pinned_anchors),
        by_kind=read.unit_counts(),
        line=f"{key}: {len(read_digest)} of {len(pinned_anchors)} units read and accounted for",
    )
