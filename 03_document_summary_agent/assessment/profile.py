"""Load a firm's stated profile, the input the register decides applicability from."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError

from assessment.records import FirmProfile
from context.errors import ContextError
from fsi_common.ids import digest_json
from utils.db import DATA_DIR

PROFILES_DIR = DATA_DIR / "profiles"
"""One JSON file per corpus, named after it. Kept outside the corpus folder, whose manifest
accounts for every file."""


class ProfileError(ContextError):
    """A firm profile is missing or does not validate."""


def load_profile(corpus: str, *, folder: Path = PROFILES_DIR) -> FirmProfile:
    """Load and validate the profile of a corpus.

    Args:
        corpus: The corpus's name.
        folder: The folder of profiles.

    Returns:
        The profile.

    Raises:
        ProfileError: If the file is missing, is not JSON, or does not validate.
    """
    path = folder / f"{corpus}.json"
    try:
        return FirmProfile.model_validate(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError, ValidationError) as exc:
        raise ProfileError(f"The firm profile {path} cannot be used: {exc}") from exc


def profile_digest(profile: FirmProfile) -> str:
    """Return the digest of a profile's JSON, which the register records.

    Args:
        profile: The profile.

    Returns:
        ``sha256:`` and 64 hex characters.
    """
    return digest_json(profile.model_dump(mode="json"))
