"""The two readings an open question puts side by side, each with what supports it."""

from __future__ import annotations

from pydantic import Field

from fsi_common.records.base import NonBlank, Part


class Readings(Part):
    """The two ways a question the checks did not settle can be answered, with their evidence.

    Both sides are written by code from the facts, so a reviewer reads what the application and
    the list say for each reading and a person decides which holds. Neither side is the engine's
    choice.
    """

    same_label: NonBlank = Field(description="The first reading, for example 'The same person'")
    same: list[NonBlank] = Field(description="What supports the first reading")
    different_label: NonBlank = Field(
        description="The second reading, for example 'A different person'"
    )
    different: list[NonBlank] = Field(description="What supports the second reading")
