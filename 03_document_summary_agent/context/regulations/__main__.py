"""Command line: fetch the regulations, read them, close their units, and remake the pins.

``python -m context.regulations fetch``  makes every regulation available, checking digests: an open
                                          text is read from the repository, a closed one is fetched
                                          and cached.
``python -m context.regulations verify`` fetches every regulation from its publisher now and
                                          compares it with the manifest's digest.
``python -m context.regulations check``  fetches if needed, reads and closes every regulation
                                          against its pin; exit 1 on any difference.
``python -m context.regulations pin``    remakes the pins from the cached bytes; use it only after
                                          the manifest's digests were remade on purpose.
"""

from __future__ import annotations

import sys

from context.regulations.accounting import EXPECTED_DIR, write_pin
from context.regulations.errors import RegulationError
from context.regulations.fetch import ensure_regulation, verify_live
from context.regulations.manifest import load_manifest
from context.regulations.readers import read_and_account, read_entry


def main(argv: list[str]) -> int:
    """Run one command.

    Args:
        argv: The arguments after the program name.

    Returns:
        The exit code: 0 when every regulation closes, 1 on an error that names what failed.
    """
    command = argv[0] if argv else ""
    manifest = load_manifest()
    try:
        if command == "fetch":
            for entry in manifest.regulations:
                data = ensure_regulation(entry)
                print(f"{entry.key}: {len(data)} bytes, digest {entry.digest} matches")
        elif command == "verify":
            for entry in manifest.regulations:
                print(
                    f"{entry.key}: {verify_live(entry)} bytes at {entry.address} match the digest"
                )
        elif command == "check":
            for entry in manifest.regulations:
                read, accounting = read_and_account(entry.key)
                print(accounting.line)
                print(f"  {read.closure.line}")
        elif command == "pin":
            EXPECTED_DIR.mkdir(parents=True, exist_ok=True)
            for entry in manifest.regulations:
                read = read_entry(entry, ensure_regulation(entry))
                write_pin(read, EXPECTED_DIR / f"{entry.key.lower()}.json")
                print(f"{entry.key}: pinned {len(read.items)} units")
        else:
            print(__doc__, file=sys.stderr)
            return 2
    except RegulationError as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
