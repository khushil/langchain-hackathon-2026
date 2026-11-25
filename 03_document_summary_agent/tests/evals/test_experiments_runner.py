"""Tests of the experiment runner on a fake LangSmith: no live call, no write to LangSmith."""

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from evals import experiments
from evals.build_dataset import read_examples
from evals.evaluators import MEASURE_KEYS
from evals.experiment_results import ExperimentEntry, read_entries
from evals.reference_summary import document_summary, section_summary
from evals.upload import DOCUMENT_NAME, SECTIONS_NAME

SECTIONS = read_examples("sections.jsonl")
DOCUMENTS = read_examples("documents.jsonl")
LIVE = {"MODEL_BACKEND": "claude-code", "LANGSMITH_API_KEY": "a-key-from-the-test"}
FIXED_NOW = datetime(2026, 11, 25, 10, 30, tzinfo=UTC)


def perfect(agent, dataset):
    """A target that returns the summary built from the labels, so every measure is in full."""
    if dataset == "sections":
        by_number = {e["inputs"]["section"]["number"]: section_summary(e) for e in SECTIONS}
        return lambda inputs: by_number[inputs["section"]["number"]]
    return lambda inputs: document_summary(SECTIONS)


def dropping_first(agent, dataset):
    """A target that leaves out the first obligation of every section it reads."""
    whole = perfect(agent, dataset)

    def cut(summary):
        return {**summary, "obligations": summary["obligations"][1:]}

    if dataset == "sections":
        return lambda inputs: cut(whole(inputs))
    return lambda inputs: {"sections": [cut(s) for s in whole(inputs)["sections"]]}


class FakeEvaluate:
    """Stands in for ``langsmith.evaluate``: runs the target on the dataset's examples."""

    def __init__(self, *, fail_at=None, interrupt_at=None, failing_example=None):
        self.calls, self.fail_at, self.interrupt_at = [], fail_at, interrupt_at
        self.failing_example = failing_example

    def __call__(self, target, /, *, data, evaluators, experiment_prefix, **options):
        self.calls.append(
            {"data": data, "evaluators": evaluators, "prefix": experiment_prefix, **options}
        )
        if self.fail_at == len(self.calls):
            raise RuntimeError("LangSmith refused the experiment")
        if self.interrupt_at == len(self.calls):
            raise KeyboardInterrupt
        examples = read_examples("sections.jsonl" if data == SECTIONS_NAME else "documents.jsonl")
        rows = []
        for example in examples:
            fails = example["key"] == self.failing_example
            output = None if fails else target(example["inputs"])
            rows.append(
                {
                    "run": SimpleNamespace(outputs=output),
                    "example": SimpleNamespace(
                        outputs=example["reference_outputs"], metadata={"key": example["key"]}
                    ),
                }
            )
        return _Results(f"{experiment_prefix}-{uuid.uuid4().hex[:8]}", uuid.uuid4(), rows)


class _Results:
    def __init__(self, name, identifier, rows):
        self.experiment_name, self.experiment_id, self._rows = name, identifier, rows

    def __iter__(self):
        return iter(self._rows)


def run(tmp_path, *argv, evaluate=None, targets=perfect, env=LIVE, client=object()):
    path = tmp_path / "experiments.json"
    evaluate = evaluate or FakeEvaluate()
    code = experiments.main(
        ["--results", str(path), *argv],
        client=client,
        evaluate_fn=evaluate,
        targets=targets,
        env=env,
        now=lambda: FIXED_NOW,
    )
    return code, evaluate, path


def test_the_default_run_makes_three_experiments_on_sections_and_one_on_the_document_for_each_agent(
    tmp_path,
):
    code, evaluate, path = run(tmp_path)
    assert code == 0
    assert [(c["prefix"], c["data"]) for c in evaluate.calls] == [
        ("starter-sections-r1", SECTIONS_NAME),
        ("starter-sections-r2", SECTIONS_NAME),
        ("starter-sections-r3", SECTIONS_NAME),
        ("starter-document-r1", DOCUMENT_NAME),
        ("engine-sections-r1", SECTIONS_NAME),
        ("engine-sections-r2", SECTIONS_NAME),
        ("engine-sections-r3", SECTIONS_NAME),
        ("engine-document-r1", DOCUMENT_NAME),
    ]
    assert len(read_entries(path)) == 8


def test_the_evaluators_are_the_seven_measures_and_each_experiment_is_one_repetition(tmp_path):
    _, evaluate, _ = run(tmp_path, "--agents", "engine", "--datasets", "sections")
    for call in evaluate.calls:
        assert [e.__name__ for e in call["evaluators"]] == list(MEASURE_KEYS)
        assert call["num_repetitions"] == 1
        assert call["disable_evaluator_tracing"] is True
    assert [c["metadata"]["repetition"] for c in evaluate.calls] == [1, 2, 3]
    assert {c["metadata"]["agent"] for c in evaluate.calls} == {"engine"}


def test_an_entry_names_the_experiment_its_agent_dataset_repetition_and_each_measure_as_counts(
    tmp_path,
):
    _, evaluate, path = run(
        tmp_path, "--agents", "starter", "--datasets", "sections", "--repetitions", "1"
    )
    (entry,) = read_entries(path)
    assert entry.name.startswith("starter-sections-r1-")
    assert (entry.agent, entry.dataset, entry.repetition) == ("starter", "sections", 1)
    assert entry.ran_at == "2026-11-25T10:30:00+00:00"
    assert entry.examples == 10 and entry.failed_examples == ()
    assert {k: f.text for k, f in entry.measures.items()} == {
        "obligations_found": "39 of 39",
        "invented_obligations": "0 of 39",
        "quotes_word_for_word": "39 of 39",
        "deadlines_as_written": "16 of 16",
        "deadlines_matched": "16 of 16",
        "paragraph_recall": "23 of 23",
        "paragraph_precision": "23 of 23",
    }
    assert isinstance(entry, ExperimentEntry)


def test_the_counts_are_those_of_what_the_agent_returned(tmp_path):
    _, _, path = run(
        tmp_path, "--agents", "engine", "--datasets", "document", targets=dropping_first
    )
    (entry,) = read_entries(path)
    found = entry.measures["obligations_found"]
    missed = 39 - found.numerator
    assert 0 < missed < 39 and found.denominator == 39
    assert entry.dataset == "document" and entry.examples == 1


def test_repetitions_and_agents_and_datasets_can_be_chosen(tmp_path):
    _, evaluate, path = run(
        tmp_path, "--agents", "engine", "--datasets", "sections", "--repetitions", "2"
    )
    assert [c["prefix"] for c in evaluate.calls] == ["engine-sections-r1", "engine-sections-r2"]
    assert len(read_entries(path)) == 2


def test_the_document_dataset_is_read_once_whatever_the_repetitions(tmp_path):
    _, evaluate, _ = run(tmp_path, "--datasets", "document", "--repetitions", "5")
    assert [c["prefix"] for c in evaluate.calls] == ["starter-document-r1", "engine-document-r1"]


@pytest.mark.parametrize("backend", ["replay", "record", "langchain", ""])
def test_a_run_on_any_backend_but_live_claude_code_is_refused_before_anything_is_made(
    tmp_path, capsys, backend
):
    env = {**LIVE, "MODEL_BACKEND": backend}
    code, evaluate, path = run(tmp_path, env=env)
    assert code == 1
    assert evaluate.calls == [] and not path.exists()
    out = capsys.readouterr().out
    assert "FAIL" in out and "MODEL_BACKEND=claude-code" in out


def test_an_unset_backend_is_refused_because_the_default_is_replay(tmp_path):
    env = {k: v for k, v in LIVE.items() if k != "MODEL_BACKEND"}
    code, evaluate, _ = run(tmp_path, env=env)
    assert code == 1 and evaluate.calls == []


def test_a_run_with_no_langsmith_key_and_no_client_stops_in_words(tmp_path, capsys):
    path = tmp_path / "experiments.json"
    code = experiments.main(
        ["--results", str(path)],
        evaluate_fn=FakeEvaluate(),
        targets=perfect,
        env={"MODEL_BACKEND": "claude-code"},
    )
    assert code == 1
    assert "no LangSmith key" in capsys.readouterr().out


def test_a_run_that_stops_keeps_the_experiments_it_finished(tmp_path, capsys):
    code, evaluate, path = run(tmp_path, evaluate=FakeEvaluate(fail_at=3))
    assert code == 1
    assert len(evaluate.calls) == 3
    assert [e.name.rsplit("-", 1)[0] for e in read_entries(path)] == [
        "starter-sections-r1",
        "starter-sections-r2",
    ]
    out = capsys.readouterr().out
    assert "FAIL starter-sections-r3" in out and "LangSmith refused the experiment" in out


def test_an_interrupted_run_keeps_the_experiments_it_finished(tmp_path):
    with pytest.raises(KeyboardInterrupt):
        run(tmp_path, evaluate=FakeEvaluate(interrupt_at=2))
    assert len(read_entries(tmp_path / "experiments.json")) == 1


def test_a_second_run_skips_the_experiments_the_file_holds_and_makes_the_rest(tmp_path, capsys):
    run(tmp_path, evaluate=FakeEvaluate(fail_at=3))
    capsys.readouterr()
    code, evaluate, path = run(tmp_path)
    assert code == 0
    assert [c["prefix"] for c in evaluate.calls][0] == "starter-sections-r3"
    assert len(evaluate.calls) == 6
    assert len(read_entries(path)) == 8
    assert capsys.readouterr().out.count("already in the file") == 2


def test_an_example_the_agent_could_not_answer_scores_as_nothing_found_and_is_named(tmp_path):
    _, _, path = run(
        tmp_path,
        "--agents",
        "starter",
        "--datasets",
        "sections",
        "--repetitions",
        "1",
        evaluate=FakeEvaluate(failing_example="PS26-4/section/7"),
    )
    (entry,) = read_entries(path)
    assert entry.failed_examples == ("PS26-4/section/7",)
    assert entry.measures["obligations_found"].denominator == 39
    assert entry.measures["obligations_found"].numerator == 35


def test_an_experiment_with_fewer_results_than_examples_is_not_recorded(tmp_path, capsys):
    class Short(FakeEvaluate):
        def __call__(self, target, /, **kw):
            results = super().__call__(target, **kw)
            results._rows = results._rows[:-1]
            return results

    code, _, path = run(tmp_path, "--agents", "engine", "--datasets", "sections", evaluate=Short())
    assert code == 1 and not path.exists()
    assert "9 of 10" in capsys.readouterr().out


def test_concurrency_is_passed_on_and_more_than_four_is_refused(tmp_path):
    _, evaluate, _ = run(
        tmp_path, "--agents", "engine", "--datasets", "document", "--concurrency", "3"
    )
    assert evaluate.calls[0]["max_concurrency"] == 3
    with pytest.raises(SystemExit):
        run(tmp_path, "--concurrency", "5")


def test_an_agent_or_dataset_that_does_not_exist_is_refused(tmp_path):
    with pytest.raises(SystemExit):
        run(tmp_path, "--agents", "other")
    with pytest.raises(SystemExit):
        run(tmp_path, "--datasets", "elsewhere")
    with pytest.raises(SystemExit):
        run(tmp_path, "--repetitions", "0")


def test_the_file_the_run_writes_holds_nothing_about_the_account(tmp_path):
    _, _, path = run(tmp_path, "--agents", "engine", "--datasets", "document")
    text = path.read_text()
    for word in ("cost", "usage", "token", "limit", "utilisation", "key"):
        assert f'"{word}' not in text
    assert "a-key-from-the-test" not in text


def test_an_entry_and_the_experiments_metadata_name_the_model_effort_and_prompt_version(tmp_path):
    from utils.models import ROLE_MODELS
    from workflow.sections import SECTION_PROMPT_VERSION

    _, evaluate, path = run(tmp_path, "--agents", "engine", "--datasets", "document")
    (entry,) = read_entries(path)
    section = ROLE_MODELS["section"]
    assert (entry.model, entry.effort) == (section.model, section.effort)
    assert entry.prompt_version == SECTION_PROMPT_VERSION
    meta = evaluate.calls[0]["metadata"]
    assert (meta["model"], meta["effort"]) == (section.model, section.effort)
    assert meta["prompt_version"] == SECTION_PROMPT_VERSION


class Altered(FakeEvaluate):
    """An evaluate whose rows are changed by a function before the runner reads them."""

    def __init__(self, change):
        super().__init__()
        self.change = change

    def __call__(self, target, /, **kw):
        results = super().__call__(target, **kw)
        results._rows = self.change(list(results._rows))
        return results


def test_a_row_standing_in_for_another_example_is_not_recorded(tmp_path, capsys):
    def tenth_is_a_copy_of_the_first(rows):
        return [*rows[:9], rows[0]]

    code, _, path = run(
        tmp_path,
        "--agents", "engine", "--datasets", "sections",
        evaluate=Altered(tenth_is_a_copy_of_the_first),
    )  # fmt: skip
    assert code == 1 and not path.exists()
    out = capsys.readouterr().out
    assert "missing PS26-4/section/10; extra or repeated PS26-4/section/1." in out


def test_an_example_whose_labels_are_not_the_datasets_is_not_recorded(tmp_path, capsys):
    def seventh_has_the_first_sections_labels(rows):
        other = rows[0]["example"].outputs  # section 1 holds no labelled obligation
        rows[6]["example"] = SimpleNamespace(outputs=other, metadata=rows[6]["example"].metadata)
        return rows

    code, _, path = run(
        tmp_path,
        "--agents", "engine", "--datasets", "sections",
        evaluate=Altered(seventh_has_the_first_sections_labels),
    )  # fmt: skip
    assert code == 1 and not path.exists()
    out = capsys.readouterr().out
    assert "obligations_found 35 where the labels give 39" in out


def test_totals_that_match_the_labels_denominators_are_recorded(tmp_path):
    _, _, path = run(tmp_path, "--agents", "engine")
    for entry in read_entries(path):
        assert entry.measures["obligations_found"].denominator == 39
        assert entry.measures["deadlines_matched"].denominator <= 16
        assert entry.measures["paragraph_recall"].denominator == 23
