"""The dataset builder: its reads, its checks and its determinism, over the starter's own files."""

import json
import shutil
from pathlib import Path

import pytest

from evals import build_dataset as bd

TOPIC = Path(__file__).resolve().parents[2]
DATA = TOPIC / "data"


@pytest.fixture(scope="module")
def built():
    return bd.build(DATA)


def test_the_starters_files_pass_every_check(built):
    assert built.problems == []


def test_there_are_three_examples_one_for_each_stream_and_the_later_week(built):
    assert [e["key"] for e in built.examples] == [
        "USR-001/before-19-october",
        "USR-002/before-19-october",
        "USR-001/from-19-october",
    ]


def test_the_first_two_examples_hold_the_analysts_eleven_labels_and_the_two_scripted_replies(built):
    first, second, _ = built.examples
    labels = {**first["reference_outputs"]["labels"], **second["reference_outputs"]["labels"]}
    assert len(labels) == 11
    assert labels["TX-1005"] == {
        "transaction_id": "TX-1005",
        "decision": "block",
        "risk_score": 90,
        "ambiguous": False,
    }
    replies = {**first["inputs"]["reviewer_answers"], **second["inputs"]["reviewer_answers"]}
    assert sorted(replies) == ["TX-1003", "TX-2005"]
    assert [len(e["inputs"]["transactions"]) for e in built.examples] == [6, 5, 4]


def test_the_later_week_is_labelled_from_the_four_reviews_by_the_starters_own_rule(built):
    labels = built.examples[2]["reference_outputs"]["labels"]
    assert sorted(labels) == ["TX-1007", "TX-1008", "TX-1009", "TX-1010"]
    assert labels["TX-1009"] == {
        "decision": "block",
        "risk_score": 75,
        "ambiguous": False,
        "comment": (
            "Late-night luxury purchase online, far above the usual spend. Customer later "
            "reported it as fraud."
        ),
    }
    assert labels["TX-1008"]["decision"] == "approve" and labels["TX-1008"]["ambiguous"] is False
    assert built.examples[2]["inputs"]["reviewer_answers"] == {}


def test_every_transaction_of_the_data_is_in_exactly_one_example(built):
    ids = [t["transaction_id"] for e in built.examples for t in e["inputs"]["transactions"]]
    on_disk = [
        json.loads(line)["transaction_id"]
        for line in (DATA / "transactions.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert sorted(ids) == sorted(on_disk) and len(ids) == 15


def test_the_counts_the_builder_states_close(built):
    assert built.counts == {
        "labels": "11 of 11 analyst labels used",
        "reviews": "4 of 4 simulated reviews used",
        "replies": "2 of 2 scripted reviewer replies used",
        "transactions": "15 of 15 transactions in an example",
    }


def test_the_file_on_disk_is_what_the_build_gives(built):
    assert (bd.DATA_DIR / bd.EXAMPLES_FILE).read_text(encoding="utf-8") == built.text
    assert bd.read_examples() == built.examples
    assert bd.main(["--check"]) == 0


def test_the_build_is_the_same_twice(built):
    assert bd.build(DATA).text == built.text


def copied(tmp_path) -> Path:
    shutil.copytree(DATA, tmp_path / "data")
    return tmp_path / "data"


def test_a_label_for_a_transaction_the_data_lacks_is_a_problem_naming_it(tmp_path):
    data = copied(tmp_path)
    with (data / "analyst_labels.jsonl").open("a", encoding="utf-8") as file:
        file.write(
            '{"transaction_id": "TX-9999", "decision": "approve", "risk_score": 5, '
            '"ambiguous": false}\n'
        )
    assert any("TX-9999" in p and "no such transaction" in p for p in bd.build(data).problems)


def test_a_label_that_breaks_the_starters_rule_is_a_problem_naming_it(tmp_path):
    data = copied(tmp_path)
    text = (data / "analyst_labels.jsonl").read_text(encoding="utf-8")
    text = text.replace('"TX-1005", "decision": "block"', '"TX-1005", "decision": "approve"')
    (data / "analyst_labels.jsonl").write_text(text, encoding="utf-8")
    assert any("TX-1005" in p and "block from 70" in p for p in bd.build(data).problems)


def test_a_transaction_without_a_label_or_a_review_is_a_problem_naming_it(tmp_path):
    data = copied(tmp_path)
    kept = [
        line
        for line in (data / "analyst_labels.jsonl").read_text(encoding="utf-8").splitlines()
        if "TX-2003" not in line
    ]
    (data / "analyst_labels.jsonl").write_text("\n".join(kept) + "\n", encoding="utf-8")
    assert any("TX-2003" in p and "no label" in p for p in bd.build(data).problems)


def test_a_reply_for_a_transaction_the_analysts_did_not_call_ambiguous_is_a_problem(tmp_path):
    data = copied(tmp_path)
    with (data / "reviewer_answers.jsonl").open("a", encoding="utf-8") as file:
        file.write('{"transaction_id": "TX-1001", "decision": "approve", "note": "x"}\n')
    assert any("TX-1001" in p and "not ambiguous" in p for p in bd.build(data).problems)


def test_the_check_fails_when_the_file_on_disk_is_out_of_date(tmp_path, capsys):
    stale = tmp_path / "stale"
    stale.mkdir()
    (stale / bd.EXAMPLES_FILE).write_text("{}\n", encoding="utf-8")
    assert bd.main(["--check", "--out-dir", str(stale)]) == 1
    assert "differs" in capsys.readouterr().out
    assert bd.main(["--check", "--out-dir", str(tmp_path / "missing")]) == 1


def test_writing_makes_the_file_the_check_then_accepts(tmp_path, capsys):
    assert bd.main(["--out-dir", str(tmp_path)]) == 0
    assert bd.main(["--check", "--out-dir", str(tmp_path)]) == 0
    assert capsys.readouterr().out.count("3 examples") >= 2
