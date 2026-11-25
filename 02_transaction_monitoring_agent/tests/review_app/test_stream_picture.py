"""The picture of the stream: transactions by customer over time, each mark showing its state."""

import pytest

from review_app.stream_picture import (
    COLUMN_MAX,
    COLUMN_MIN,
    MARK_RADIUS,
    STATE_WORDS,
    MarkInput,
    StreamPictureError,
    build_picture,
)

PRIYA = ("USR-001", "Priya Shah")
TOMAS = ("USR-002", "Tomás Ferreira")


def mark(tx, when, state="needs", user="USR-001", score=45, merchant="Shop"):
    return MarkInput(
        tx_id=tx,
        user_id=user,
        timestamp=when,
        merchant=merchant,
        amount="380.0 GBP",
        state=state,
        score=score,
        href=f"/transaction-monitoring/runs/r/review?tx={tx}",
    )


def test_every_mark_given_is_placed_and_the_count_line_says_so():
    marks = [
        mark("TX-1001", "2026-10-08T08:12"),
        mark("TX-1002", "2026-10-08T18:45"),
        mark("TX-1003", "2026-10-09T21:03"),
    ]
    picture = build_picture(marks, lanes=[PRIYA])
    assert [m.tx_id for m in picture.marks] == ["TX-1001", "TX-1002", "TX-1003"]
    assert picture.count_line == "3 of 3 transactions marked"
    assert [d.label for d in picture.days if not d.is_break] == ["8 Oct", "9 Oct"]


def test_time_runs_left_to_right_by_day_and_top_to_bottom_by_the_hour():
    marks = [
        mark("TX-1", "2026-10-08T06:00"),
        mark("TX-2", "2026-10-08T18:00"),
        mark("TX-3", "2026-10-09T06:00"),
    ]
    placed = {m.tx_id: m for m in build_picture(marks, lanes=[PRIYA]).marks}
    assert placed["TX-1"].y < placed["TX-2"].y
    assert placed["TX-3"].x > placed["TX-1"].x
    assert placed["TX-3"].y == placed["TX-1"].y


def test_two_transactions_minutes_apart_on_one_day_are_drawn_side_by_side():
    marks = [mark("TX-1005", "2026-10-11T02:14"), mark("TX-1006", "2026-10-11T02:21")]
    placed = build_picture(marks, lanes=[PRIYA]).marks
    gap = ((placed[0].x - placed[1].x) ** 2 + (placed[0].y - placed[1].y) ** 2) ** 0.5
    assert gap >= 2 * MARK_RADIUS


def test_a_run_of_empty_days_becomes_one_break_that_says_how_many_days_it_stands_for():
    marks = [mark("TX-1", "2026-10-11T02:14"), mark("TX-2", "2026-10-19T07:55")]
    picture = build_picture(marks, lanes=[PRIYA])
    breaks = [d for d in picture.days if d.is_break]
    assert [b.label for b in breaks] == ["7 days"]
    assert [d.label for d in picture.days if not d.is_break] == ["11 Oct", "19 Oct"]
    placed = {m.tx_id: m for m in picture.marks}
    assert placed["TX-2"].x - placed["TX-1"].x < 7 * COLUMN_MIN


def test_one_or_two_empty_days_stay_as_days():
    marks = [mark("TX-1", "2026-10-08T08:00"), mark("TX-2", "2026-10-11T08:00")]
    picture = build_picture(marks, lanes=[PRIYA])
    assert [d.label for d in picture.days] == ["8 Oct", "9 Oct", "10 Oct", "11 Oct"]


def test_each_customer_has_a_lane_of_their_own_and_a_mark_sits_in_its_customers_lane():
    marks = [
        mark("TX-1001", "2026-10-08T08:12"),
        mark("TX-2001", "2026-10-08T09:00", user="USR-002"),
    ]
    picture = build_picture(marks, lanes=[PRIYA, TOMAS])
    lanes = {lane.user_id: lane for lane in picture.lanes}
    placed = {m.tx_id: m for m in picture.marks}
    assert lanes["USR-002"].top > lanes["USR-001"].top
    assert (
        lanes["USR-001"].top
        <= placed["TX-1001"].y
        <= lanes["USR-001"].top + lanes["USR-001"].height
    )
    assert (
        lanes["USR-002"].top
        <= placed["TX-2001"].y
        <= lanes["USR-002"].top + lanes["USR-002"].height
    )


def test_a_mark_names_the_transaction_what_it_was_and_the_state_in_words_for_a_screen_reader():
    placed = build_picture(
        [mark("TX-1003", "2026-10-09T21:03", merchant="Hotel Miramar Lisboa")], lanes=[PRIYA]
    ).marks[0]
    assert "TX-1003" in placed.title and "Hotel Miramar Lisboa" in placed.title
    assert "380.0 GBP" in placed.title and STATE_WORDS["needs"] in placed.title
    assert placed.href.endswith("?tx=TX-1003")


def test_the_key_lists_each_state_drawn_and_no_other():
    marks = [
        mark("TX-1", "2026-10-08T08:00", state="needs"),
        mark("TX-2", "2026-10-08T09:00", state="decided"),
    ]
    picture = build_picture(marks, lanes=[PRIYA])
    assert [state for state, _ in picture.key] == ["needs", "decided"]
    assert [word for _, word in picture.key] == [STATE_WORDS["needs"], STATE_WORDS["decided"]]


def test_a_transaction_given_twice_or_with_an_unknown_state_or_customer_is_refused_by_name():
    with pytest.raises(StreamPictureError, match="TX-1"):
        build_picture(
            [mark("TX-1", "2026-10-08T08:00"), mark("TX-1", "2026-10-08T09:00")], lanes=[PRIYA]
        )
    with pytest.raises(StreamPictureError, match="pending"):
        build_picture([mark("TX-1", "2026-10-08T08:00", state="pending")], lanes=[PRIYA])
    with pytest.raises(StreamPictureError, match="USR-002"):
        build_picture([mark("TX-1", "2026-10-08T08:00", user="USR-002")], lanes=[PRIYA])


def test_no_transaction_at_all_is_refused_so_a_picture_is_never_empty():
    with pytest.raises(StreamPictureError, match="no transaction"):
        build_picture([], lanes=[PRIYA])


def test_the_picture_is_as_wide_as_its_columns_and_as_tall_as_its_lanes():
    marks = [mark("TX-1", "2026-10-08T08:00"), mark("TX-2", "2026-10-09T08:00")]
    picture = build_picture(marks, lanes=[PRIYA])
    assert picture.width >= max(d.x + d.width for d in picture.days)
    assert picture.height >= max(lane.top + lane.height for lane in picture.lanes)


def test_the_minutes_count_in_a_marks_height_not_only_the_hour():
    marks = [mark("TX-1", "2026-10-08T06:00"), mark("TX-2", "2026-10-08T06:30")]
    placed = {m.tx_id: m for m in build_picture(marks, lanes=[PRIYA]).marks}
    assert placed["TX-2"].y > placed["TX-1"].y


def test_a_few_days_are_drawn_wide_to_use_the_page_and_many_days_no_narrower_than_a_mark_needs():
    few = build_picture(
        [mark("TX-1", "2026-10-08T08:00"), mark("TX-2", "2026-10-09T08:00")], lanes=[PRIYA]
    )
    assert {d.width for d in few.days} == {COLUMN_MAX}
    many_marks = [mark(f"TX-{n}", f"2026-10-{n:02d}T08:00") for n in range(1, 25)]
    many = build_picture(many_marks, lanes=[PRIYA])
    assert {d.width for d in many.days} == {COLUMN_MIN}
