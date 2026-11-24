"""Tests for the seven measures, on small hand-built cases and on the reference-built summaries."""

import pytest
from evals import evaluators as ev
from evals.build_dataset import read_examples
from evals.reference_summary import document_summary, section_summary

from fsi_common.evals.measures import sum_measures

TEXTS = {
    "1.1": "Firms must submit an initial notification within 4 hours of classifying an incident.",
    "1.2": "We will publish a template before the rules take effect.",
    "1.3": "Firms must keep a record. Firms must keep a copy for 5 years.",
}
REF_ITEMS = [
    {
        "paragraph": "1.1",
        "item": 1,
        "kind": "obligation",
        "deadline_as_written": "within 4 hours of classifying an incident",
        "evidence": (
            "Firms must submit an initial notification within 4 hours of classifying an incident."
        ),
    },
    {
        "paragraph": "1.2",
        "item": 1,
        "kind": "regulator_action",
        "deadline_as_written": None,
        "evidence": "We will publish a template",
    },
    {
        "paragraph": "1.3",
        "item": 1,
        "kind": "obligation",
        "deadline_as_written": None,
        "evidence": "Firms must keep a record.",
    },
    {
        "paragraph": "1.3",
        "item": 2,
        "kind": "obligation",
        "deadline_as_written": "for 5 years",
        "evidence": "Firms must keep a copy for 5 years.",
    },
]
REFERENCE = {"paragraphs": list(TEXTS), "paragraph_texts": TEXTS, "items": REF_ITEMS}


def ob(paragraph, evidence, deadline=None):
    return {"requirement": "r", "paragraph": paragraph, "deadline": deadline, "evidence": evidence}


def good():
    return [
        ob("1.1", REF_ITEMS[0]["evidence"], "within 4 hours of classifying an incident"),
        ob("1.3", "Firms must keep a record."),
        ob("1.3", "Firms must keep a copy for 5 years.", "for 5 years"),
    ]


def summary(*obligations):
    return {"number": "1", "title": "t", "summary": "s", "obligations": list(obligations)}


def measure(key, obligations, reference=REFERENCE):
    found = {m.key: m for m in ev.score_summary(summary(*obligations), reference)}
    return found[key]


def counts(key, obligations, reference=REFERENCE):
    m = measure(key, obligations, reference)
    return (m.numerator, m.denominator)


def test_a_summary_equal_to_the_labels_scores_in_full_on_every_measure():
    scored = ev.score_summary(summary(*good()), REFERENCE)
    assert [m.key for m in scored] == list(ev.MEASURE_KEYS)
    assert all(m.is_full for m in scored)


def test_obligations_found_counts_matched_labelled_obligations():
    assert counts("obligations_found", good()) == (3, 3)
    assert counts("obligations_found", good()[:2]) == (2, 3)
    assert counts("obligations_found", []) == (0, 3)


def test_a_match_needs_the_same_paragraph():
    moved = [ob("1.2", REF_ITEMS[0]["evidence"])] + good()[1:]
    assert counts("obligations_found", moved) == (2, 3)


def test_a_near_paraphrase_still_matches_on_word_overlap():
    tweaked = REF_ITEMS[0]["evidence"].replace("must", "shall")
    assert counts("obligations_found", [ob("1.1", tweaked)] + good()[1:]) == (3, 3)


def test_a_loose_paraphrase_below_half_overlap_does_not_match():
    loose = [ob("1.1", "Report incidents fast")] + good()[1:]
    assert counts("obligations_found", loose) == (2, 3)


def test_containment_matches_even_when_overlap_is_low():
    longer = "x " * 40 + REF_ITEMS[0]["evidence"] + " y" * 40
    assert counts("obligations_found", [ob("1.1", longer)] + good()[1:]) == (3, 3)


def test_empty_evidence_never_matches_and_is_not_word_for_word():
    bad = [ob("1.1", "")] + good()[1:]
    assert counts("obligations_found", bad) == (2, 3)
    assert counts("quotes_word_for_word", bad) == (2, 3)


def test_pairs_are_one_to_one_so_a_repeat_does_not_find_two_labelled_obligations():
    twice = [good()[0], good()[1], good()[1]]
    assert counts("obligations_found", twice) == (2, 3)


def test_identical_evidence_in_two_labelled_items_is_paired_in_item_order():
    same = {
        "paragraphs": ["8.5"],
        "paragraph_texts": {"8.5": "Firms must keep it and give it."},
        "items": [
            {
                "paragraph": "8.5",
                "item": 1,
                "kind": "obligation",
                "deadline_as_written": None,
                "evidence": "Firms must keep it and give it.",
            },
            {
                "paragraph": "8.5",
                "item": 2,
                "kind": "obligation",
                "deadline_as_written": None,
                "evidence": "Firms must keep it and give it.",
            },
        ],
    }
    both = [ob("8.5", "Firms must keep it and give it.")] * 2
    assert counts("obligations_found", both, same) == (2, 2)
    assert counts("obligations_found", both[:1], same) == (1, 2)


def test_an_exact_match_beats_a_containing_one_for_the_same_labelled_item():
    ref = {
        "paragraphs": ["6.3"],
        "paragraph_texts": {"6.3": "give access, report incidents, and set out exit."},
        "items": [
            {
                "paragraph": "6.3",
                "item": 1,
                "kind": "obligation",
                "deadline_as_written": None,
                "evidence": "give access",
            },
            {
                "paragraph": "6.3",
                "item": 2,
                "kind": "obligation",
                "deadline_as_written": None,
                "evidence": "give access, report incidents",
            },
        ],
    }
    predicted = [ob("6.3", "give access, report incidents"), ob("6.3", "give access")]
    assert counts("obligations_found", predicted, ref) == (2, 2)


def test_an_obligation_on_a_paragraph_with_no_labelled_obligation_is_invented():
    extra = good() + [ob("1.2", "We will publish a template")]
    assert counts("invented_obligations", extra) == (1, 4)
    assert counts("invented_obligations", good()) == (0, 3)


def test_an_obligation_citing_a_paragraph_that_does_not_exist_is_invented():
    assert counts("invented_obligations", good() + [ob("9.9", "anything")]) == (1, 4)


def test_an_extra_obligation_on_a_paragraph_that_holds_one_is_not_invented():
    extra = good() + [ob("1.1", "Firms must also do something else entirely and unrelated")]
    assert counts("invented_obligations", extra) == (0, 4)


def test_a_wholly_wrong_obligation_on_a_labelled_paragraph_is_not_invented_but_not_found():
    wrong = [ob("1.1", "Totally different words here")] + good()[1:]
    assert counts("invented_obligations", wrong) == (0, 3)
    assert counts("obligations_found", wrong) == (2, 3)


def test_quotes_are_word_for_word_inside_the_cited_paragraph():
    assert counts("quotes_word_for_word", good()) == (3, 3)
    wrong_paragraph = [ob("1.2", REF_ITEMS[0]["evidence"])] + good()[1:]
    assert counts("quotes_word_for_word", wrong_paragraph) == (2, 3)


def test_quotes_leave_out_obligations_citing_a_missing_paragraph():
    assert counts("quotes_word_for_word", good() + [ob("9.9", "anything")]) == (3, 3)


def test_curly_quotes_and_a_trailing_stop_do_not_break_a_quote():
    ref = {
        "paragraphs": ["1.1"],
        "paragraph_texts": {"1.1": "The firm's duty applies."},
        "items": [
            {
                "paragraph": "1.1",
                "item": 1,
                "kind": "obligation",
                "deadline_as_written": None,
                "evidence": "The firm's duty applies.",
            }
        ],
    }
    assert counts("quotes_word_for_word", [ob("1.1", "The firm’s duty applies")], ref) == (1, 1)


def test_a_changed_capital_is_a_changed_quote():
    changed = [ob("1.3", "firms must keep a record.")] + good()[:1] + good()[2:]
    assert counts("quotes_word_for_word", changed) == (2, 3)


def test_deadlines_as_written_counts_only_predicted_obligations_with_a_deadline():
    assert counts("deadlines_as_written", good()) == (2, 2)
    assert counts("deadlines_as_written", [ob("1.3", "Firms must keep a record.")]) == (0, 0)


def test_a_converted_deadline_is_not_as_written():
    converted = [
        ob("1.1", REF_ITEMS[0]["evidence"], "within four hours of classifying an incident")
    ]
    assert counts("deadlines_as_written", converted + good()[1:]) == (1, 2)


def test_a_deadline_in_the_paragraph_where_the_label_has_none_is_not_counted_against():
    extra = [good()[0], ob("1.3", "Firms must keep a record.", "for 5 years"), good()[2]]
    assert counts("deadlines_as_written", extra) == (3, 3)
    assert counts("deadlines_matched", extra) == (2, 2)


def test_deadlines_matched_looks_only_at_matched_pairs_with_a_labelled_deadline():
    assert counts("deadlines_matched", good()) == (2, 2)
    no_deadline = [ob("1.1", REF_ITEMS[0]["evidence"])] + good()[1:]
    assert counts("deadlines_matched", no_deadline) == (1, 2)
    assert counts("deadlines_matched", []) == (0, 0)


def test_a_deadline_inside_the_labelled_one_or_around_it_matches():
    shorter = [ob("1.1", REF_ITEMS[0]["evidence"], "within 4 hours")] + good()[1:]
    longer = [
        ob("1.1", REF_ITEMS[0]["evidence"], "x within 4 hours of classifying an incident y")
    ] + good()[1:]
    assert counts("deadlines_matched", shorter) == (2, 2)
    assert counts("deadlines_matched", longer) == (2, 2)


def test_a_different_deadline_does_not_match():
    other = [ob("1.1", REF_ITEMS[0]["evidence"], "within 72 hours")] + good()[1:]
    assert counts("deadlines_matched", other) == (1, 2)


def test_a_blank_deadline_never_matches_a_labelled_one():
    blank = [ob("1.1", REF_ITEMS[0]["evidence"], "  ")] + good()[1:]
    assert counts("deadlines_matched", blank) == (1, 2)
    assert counts("deadlines_as_written", blank) == (1, 1)


def test_paragraph_recall_and_precision_count_paragraphs_not_obligations():
    assert counts("paragraph_recall", good()) == (2, 2)
    assert counts("paragraph_precision", good()) == (2, 2)
    assert counts("paragraph_recall", good()[:1]) == (1, 2)
    extra = good() + [ob("1.2", "We will publish a template")]
    assert counts("paragraph_precision", extra) == (2, 3)
    assert counts("paragraph_recall", extra) == (2, 2)


def test_a_cited_paragraph_that_does_not_exist_counts_against_precision():
    assert counts("paragraph_precision", good() + [ob("9.9", "x")]) == (2, 3)


def test_nothing_predicted_leaves_precision_and_the_other_predicted_measures_out_of_scope():
    for key in (
        "invented_obligations",
        "quotes_word_for_word",
        "deadlines_as_written",
        "paragraph_precision",
    ):
        assert counts(key, []) == (0, 0)
    assert not measure("paragraph_precision", []).in_scope


def test_a_reference_with_no_obligation_has_nothing_in_scope_for_the_found_measures():
    ref = {"paragraphs": ["1.2"], "paragraph_texts": {"1.2": TEXTS["1.2"]}, "items": [REF_ITEMS[1]]}
    for key in ("obligations_found", "deadlines_matched", "paragraph_recall"):
        assert counts(key, [], ref) == (0, 0)


def test_the_populations_are_stated():
    scored = {m.key: m for m in ev.score_summary(summary(*good()), REFERENCE)}
    assert (
        scored["obligations_found"].line()
        == "obligations_found: 3 of 3 labelled obligations in scope"
    )
    assert scored["invented_obligations"].lower_is_better
    assert scored["invented_obligations"].line().endswith("predicted obligations")


@pytest.mark.parametrize(
    "bad",
    [
        None,
        [],
        {"obligations": "no"},
        {"obligations": [None]},
        {"obligations": [{"paragraph": "1.1"}]},
        {"obligations": [{"paragraph": 1.1, "evidence": "x"}]},
        {"obligations": [{"paragraph": "1.1", "evidence": "x", "deadline": 4}]},
        {"neither": 1},
    ],
)
def test_a_malformed_summary_is_refused(bad):
    with pytest.raises(ev.MalformedSummaryError):
        ev.score_summary(bad, REFERENCE)


def test_a_summary_with_no_deadline_key_is_read_as_having_none():
    plain = {"obligations": [{"paragraph": "1.3", "evidence": "Firms must keep a record."}]}
    assert ev.score_summary(plain, REFERENCE)[0].numerator == 1


def test_a_reference_with_no_paragraph_texts_is_refused():
    with pytest.raises(ev.MalformedSummaryError, match="reference"):
        ev.score_summary(summary(), {"items": []})


# The reference-built summaries, on the real dataset.


@pytest.fixture(scope="module")
def sections():
    return read_examples("sections.jsonl")


def test_every_section_built_from_the_labels_is_full_wherever_something_is_in_scope(sections):
    assert len(sections) == 10
    for example in sections:
        for m in ev.score_summary(section_summary(example), example["reference_outputs"]):
            assert m.is_full or not m.in_scope, (example["key"], m.line())


def test_the_document_totals_of_the_reference_built_summaries(sections):
    totals = {}
    for key in ev.MEASURE_KEYS:
        totals[key] = sum_measures(
            ev.score_summary(section_summary(e), e["reference_outputs"])[i]
            for e in sections
            for i, k in enumerate(ev.MEASURE_KEYS)
            if k == key
        )
    got = {k: (m.numerator, m.denominator) for k, m in totals.items()}
    assert got == {
        "obligations_found": (39, 39),
        "invented_obligations": (0, 39),
        "quotes_word_for_word": (39, 39),
        "deadlines_as_written": (16, 16),
        "deadlines_matched": (16, 16),
        "paragraph_recall": (23, 23),
        "paragraph_precision": (23, 23),
    }


def test_sections_one_three_and_ten_have_no_obligation_in_scope(sections):
    for example in sections:
        number = example["inputs"]["section"]["number"]
        scored = ev.score_summary(section_summary(example), example["reference_outputs"])
        found = scored[0]
        assert found.in_scope == (number not in {"1", "3", "10"}), number


def test_the_document_example_scores_the_same_as_the_ten_sections_added(sections):
    document = read_examples("documents.jsonl")[0]
    output = document_summary(sections)
    scored = ev.score_summary(output, document["reference_outputs"])
    assert {m.key: (m.numerator, m.denominator) for m in scored}["obligations_found"] == (39, 39)
    assert all(m.is_full for m in scored)


def test_the_runner_adapter_scores_an_example_and_its_output(sections):
    example = sections[6]
    measures = ev.evaluate_pair(example, section_summary(example))
    assert [m.key for m in measures] == list(ev.MEASURE_KEYS)


def test_langsmith_evaluators_return_a_key_a_score_and_the_counts_as_a_comment(sections):
    example = sections[6]
    outputs = section_summary(example)
    functions = ev.langsmith_evaluators()
    assert [f.__name__ for f in functions] == list(ev.MEASURE_KEYS)
    results = {f.__name__: f(outputs, example["reference_outputs"]) for f in functions}
    assert results["obligations_found"] == {
        "key": "obligations_found",
        "score": 1.0,
        "comment": "4 of 4 labelled obligations in scope",
    }
    assert results["invented_obligations"]["score"] == 0.0


def test_a_langsmith_evaluator_with_nothing_in_scope_gives_no_score(sections):
    example = sections[0]
    result = ev.langsmith_evaluators()[0](section_summary(example), example["reference_outputs"])
    assert result["score"] is None
    assert "none in scope" in result["comment"]
