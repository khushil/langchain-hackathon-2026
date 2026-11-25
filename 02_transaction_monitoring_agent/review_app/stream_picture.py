"""The picture of the stream: each customer's transactions by day and hour, a mark for each.

The data holds a time for every transaction, so the picture orders by time and by nothing else:
days run left to right, the hour of the day runs top to bottom, and each customer has a lane of
their own. A run of three or more days with nothing in them is drawn as one break that says how
many days it stands for. Every transaction handed in is drawn once, or the picture refuses.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta

MARK_RADIUS = 11
COLUMN_MIN = 64
COLUMN_MAX = 150
TARGET_WIDTH = 1100
BREAK_WIDTH = 44
LEFT_MARGIN = 52
TOP_MARGIN = 30
LANE_HEIGHT = 160
LANE_PADDING = 18
LANE_GAP = 14
LANE_LABEL_HEIGHT = 20
MIN_BREAK_DAYS = 3
SLOT_STEP = 2 * MARK_RADIUS + 2

STATE_WORDS = {
    "needs": "Needs a decision",
    "decided": "Decided",
    "carried": "Decided earlier, nothing changed",
    "rejected": "Rejected",
    "question": "No usable assessment",
    "answered": "Question answered",
    "idle": "Not assessed yet",
}
"""Every state a mark can show, in words; the picture's key and each mark's title use them."""

STATUS = {"needs": "needs_person", "rejected": "needs_person", "question": "failed"}
"""The alert level of a state; every other state is grey."""


class StreamPictureError(ValueError):
    """The marks cannot be drawn: none, one twice, an unknown state or a customer with no lane."""


@dataclass(frozen=True)
class MarkInput:
    """One transaction as the picture is given it."""

    tx_id: str
    user_id: str
    timestamp: str
    merchant: str
    amount: str
    state: str
    score: int | None
    href: str | None


@dataclass(frozen=True)
class DayColumn:
    """One column of the picture: a day, or a break standing for several empty days."""

    x: int
    width: int
    label: str
    is_break: bool


@dataclass(frozen=True)
class Lane:
    """One customer's lane."""

    user_id: str
    name: str
    top: int
    height: int


@dataclass(frozen=True)
class PlacedMark:
    """A transaction's mark and where it sits."""

    tx_id: str
    x: float
    y: float
    state: str
    status: str
    href: str | None
    title: str
    text: str


@dataclass(frozen=True)
class StreamPicture:
    """Everything the template needs to draw the picture."""

    width: int
    height: int
    days: tuple[DayColumn, ...]
    lanes: tuple[Lane, ...]
    marks: tuple[PlacedMark, ...]
    hours: tuple[tuple[str, float], ...]
    key: tuple[tuple[str, str], ...]
    count_line: str


def _day(timestamp: str) -> date:
    return datetime.fromisoformat(timestamp).date()


def _label(day: date) -> str:
    return f"{day.day} {day.strftime('%b')}"


def _day_width(days: Sequence[date]) -> int:
    """Choose how wide a day is: wide enough to use the page, never narrower than a mark needs."""
    steps = [(later - earlier).days - 1 for earlier, later in zip(days, days[1:], strict=False)]
    breaks = sum(empty >= MIN_BREAK_DAYS for empty in steps)
    count = len(days) + sum(empty for empty in steps if empty < MIN_BREAK_DAYS)
    room = TARGET_WIDTH - LEFT_MARGIN - breaks * BREAK_WIDTH
    return max(COLUMN_MIN, min(COLUMN_MAX, room // count))


def _columns(days: Sequence[date]) -> list[tuple[date | None, DayColumn]]:
    """Make a column for each day with a transaction, and for each short or long gap between."""
    width = _day_width(days)
    columns: list[tuple[date | None, DayColumn]] = []
    x = LEFT_MARGIN
    previous: date | None = None

    def add(day: date | None, width: int, label: str, *, is_break: bool = False) -> None:
        nonlocal x
        columns.append((day, DayColumn(x, width, label, is_break)))
        x += width

    for day in days:
        if previous is not None:
            empty = (day - previous).days - 1
            if empty >= MIN_BREAK_DAYS:
                add(None, BREAK_WIDTH, f"{empty} days", is_break=True)
            else:
                for step in range(1, empty + 1):
                    between = previous + timedelta(days=step)
                    add(between, width, _label(between))
        add(day, width, _label(day))
        previous = day
    return columns


def _check(marks: Sequence[MarkInput], lanes: Sequence[tuple[str, str]]) -> None:
    if not marks:
        raise StreamPictureError("There is no transaction to draw.")
    seen: set[str] = set()
    users = {user for user, _ in lanes}
    for item in marks:
        if item.tx_id in seen:
            raise StreamPictureError(f"{item.tx_id} was given twice, so it would be drawn twice.")
        seen.add(item.tx_id)
        if item.state not in STATE_WORDS:
            raise StreamPictureError(
                f"{item.tx_id} has the state '{item.state}', which has no word."
            )
        if item.user_id not in users:
            raise StreamPictureError(f"{item.tx_id} belongs to {item.user_id}, who has no lane.")


def _title(item: MarkInput) -> str:
    when = datetime.fromisoformat(item.timestamp)
    return (
        f"{item.tx_id}, {item.merchant}, {item.amount}, {when.day} {when.strftime('%B')} at "
        f"{when:%H:%M}: {STATE_WORDS[item.state]}"
    )


def build_picture(marks: Sequence[MarkInput], *, lanes: Sequence[tuple[str, str]]) -> StreamPicture:
    """Place each transaction on a picture of days and hours, one lane for each customer.

    Args:
        marks: The transactions, each with its customer, time, state and where it opens.
        lanes: The customers as (user id, name), top to bottom.

    Returns:
        The picture: its columns, lanes, marks and key, with the line that says how many
        transactions were marked of how many were given.

    Raises:
        StreamPictureError: If there is no transaction, one is given twice, a state has no word,
            or a transaction belongs to a customer with no lane.
    """
    _check(marks, lanes)
    days = sorted({_day(m.timestamp) for m in marks})
    columns = _columns(days)
    column_of = {day: col for day, col in columns if day is not None}
    lane_top = TOP_MARGIN
    placed_lanes = []
    for user_id, name in lanes:
        placed_lanes.append(Lane(user_id, name, lane_top + LANE_LABEL_HEIGHT, LANE_HEIGHT))
        lane_top += LANE_LABEL_HEIGHT + LANE_HEIGHT + LANE_GAP
    by_user = {lane.user_id: lane for lane in placed_lanes}
    inner = LANE_HEIGHT - 2 * LANE_PADDING
    slots: dict[tuple[str, date], list[list[float]]] = {}
    placed = []
    for item in sorted(marks, key=lambda m: (m.user_id, m.timestamp)):
        when = datetime.fromisoformat(item.timestamp)
        lane = by_user[item.user_id]
        y = lane.top + LANE_PADDING + (when.hour * 60 + when.minute) / 1440 * inner
        column = column_of[when.date()]
        taken = slots.setdefault((item.user_id, when.date()), [])
        for index, ys in enumerate(taken + [[]]):
            if all(abs(y - other) >= 2 * MARK_RADIUS + 1 for other in ys):
                break
        if index == len(taken):
            taken.append([])
        taken[index].append(y)
        offset = ((index + 1) // 2) * SLOT_STEP * (1 if index % 2 else -1) if index else 0
        placed.append(
            PlacedMark(
                tx_id=item.tx_id,
                x=column.x + column.width / 2 + offset,
                y=y,
                state=item.state,
                status=STATUS.get(item.state, "normal"),
                href=item.href,
                title=_title(item),
                text="" if item.score is None else str(item.score),
            )
        )
    order = {m.tx_id: i for i, m in enumerate(marks)}
    placed.sort(key=lambda m: order[m.tx_id])
    drawn = [state for state in STATE_WORDS if any(m.state == state for m in placed)]
    last = columns[-1][1]
    count = len(placed)
    return StreamPicture(
        width=last.x + last.width + 8,
        height=lane_top,
        days=tuple(col for _, col in columns),
        lanes=tuple(placed_lanes),
        marks=tuple(placed),
        hours=(("00:00", 0.0), ("12:00", 0.5), ("24:00", 1.0)),
        key=tuple((state, STATE_WORDS[state]) for state in drawn),
        count_line=f"{count} of {len(marks)} transactions marked",
    )
