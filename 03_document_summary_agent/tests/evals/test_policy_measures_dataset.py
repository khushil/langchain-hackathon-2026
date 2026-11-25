"""The policy seeds as the measures' dataset: read from the seeds file, counted by regulation."""

import pytest

from evals.policy_dataset import (
    REGULATION_LABELS,
    SEEDS_FILE,
    SeedFileError,
    examples,
    main,
    populations,
    read_seeds,
)

HEADER = (
    "seed_id\tregulation\tprovision\tprovision_quote\tbinds\tdocuments\tclauses\t"
    "clause_quotes\tstate\twhy\n"
)


def write_seeds(tmp_path, *rows: str, comment: str = "# a comment line\n"):
    path = tmp_path / "seeds.tsv"
    path.write_text(comment + HEADER + "".join(rows), encoding="utf-8")
    return path


def row(
    seed_id="DORA-01",
    regulation="DORA",
    state="covered",
    documents="HMB-POL-ICT-001-v3.0",
    clauses="4.1",
    quotes="The Board approves",
):
    return (
        f"{seed_id}\t{regulation}\tArticle 5(2)\tthe provision words\tthe firm\t{documents}\t"
        f"{clauses}\t{quotes}\t{state}\twhy\n"
    )


def test_the_seeds_file_holds_55_seeds_of_which_25_are_dora_12_ai_act_and_18_ss123():
    seeds = read_seeds()
    by_regulation = {key: [s for s in seeds if s.regulation == key] for key in REGULATION_LABELS}
    assert len(seeds) == 55
    assert {k: len(v) for k, v in by_regulation.items()} == {"DORA": 25, "AI-ACT": 12, "SS1-23": 18}


def test_populations_by_regulation_match_the_contract_and_the_run_lines():
    counts = {p.regulation: p for p in populations(read_seeds())}
    assert {k: (p.gaps, p.covered, p.seeds) for k, p in counts.items()} == {
        "DORA": (12, 13, 25),
        "AI-ACT": (5, 7, 12),
        "SS1-23": (6, 12, 18),
        "all": (23, 32, 55),
    }


def test_populations_count_a_gap_as_any_state_other_than_covered(tmp_path):
    path = write_seeds(
        tmp_path,
        row("DORA-01", state="covered"),
        row("DORA-02", state="partly covered"),
        row("DORA-03", state="in conflict"),
        row("DORA-04", state="not covered", documents="", clauses="", quotes=""),
    )
    dora = populations(read_seeds(path))[0]
    assert (dora.seeds, dora.gaps, dora.covered) == (4, 3, 1)
    assert dora.with_clauses == 3


def test_a_regulation_with_no_seeds_has_zero_counts_and_all_still_adds_up(tmp_path):
    path = write_seeds(tmp_path, row("DORA-01"))
    counts = {p.regulation: p for p in populations(read_seeds(path))}
    assert counts["AI-ACT"].seeds == 0 and counts["SS1-23"].gaps == 0
    assert counts["all"].seeds == 1


def test_a_seed_file_with_no_rows_reads_as_no_seeds(tmp_path):
    assert read_seeds(write_seeds(tmp_path)) == []


def test_clauses_are_read_as_document_and_number_pairs_in_step(tmp_path):
    path = write_seeds(
        tmp_path,
        row(
            documents="HMB-POL-ICT-001-v3.0 | HMB-FRM-GOV-000-v2.0",
            clauses="5.2 | 6.1",
            quotes="first words | second words",
        ),
    )
    (seed,) = read_seeds(path)
    assert seed.clauses == (("HMB-POL-ICT-001-v3.0", "5.2"), ("HMB-FRM-GOV-000-v2.0", "6.1"))
    assert seed.clause_quotes == ("first words", "second words")
    assert seed.state == "covered" and seed.regulation == "DORA"


def test_regulation_names_of_the_file_become_the_manifest_keys(tmp_path):
    path = write_seeds(
        tmp_path,
        row("AIA-01", regulation="AI Act"),
        row("SS123-01", regulation="SS1/23"),
    )
    assert [s.regulation for s in read_seeds(path)] == ["AI-ACT", "SS1-23"]


@pytest.mark.parametrize(
    ("rows", "message"),
    [
        ((row(state="approved"),), "state"),
        ((row(regulation="GDPR"),), "regulation"),
        ((row(documents="A | B", clauses="1.1"),), "not in step"),
        ((row(quotes=""),), "not in step"),
        ((row("DORA-01"), row("DORA-01")), "twice"),
        ((row(seed_id=""),), "seed id"),
    ],
)
def test_a_malformed_seed_file_is_refused_naming_the_seed(tmp_path, rows, message):
    with pytest.raises(SeedFileError, match=message):
        read_seeds(write_seeds(tmp_path, *rows))


def test_a_missing_seed_file_is_refused_naming_the_path(tmp_path):
    with pytest.raises(SeedFileError, match="nothing.tsv"):
        read_seeds(tmp_path / "nothing.tsv")


def test_a_file_without_the_expected_columns_is_refused(tmp_path):
    path = tmp_path / "seeds.tsv"
    path.write_text("seed_id\tstate\nDORA-01\tcovered\n", encoding="utf-8")
    with pytest.raises(SeedFileError, match="column"):
        read_seeds(path)


def test_examples_hold_one_dataset_example_per_seed_with_the_label_as_its_output():
    seeds = read_seeds()
    made = examples(seeds)
    assert len(made) == 55
    first = made[0]
    assert first["inputs"]["seed_id"] == seeds[0].seed_id
    assert first["outputs"]["state"] == seeds[0].state
    assert set(first) == {"inputs", "outputs", "metadata"}
    assert [e["inputs"]["seed_id"] for e in made] == [s.seed_id for s in seeds]


def test_main_check_prints_the_populations_and_exits_zero(capsys):
    assert main(["--check"]) == 0
    out = capsys.readouterr().out
    assert "55 seeds" in out
    assert "DORA: 25 seeds, 12 gaps, 13 covered" in out
    assert "all: 55 seeds, 23 gaps, 32 covered" in out


def test_main_check_exits_non_zero_on_an_unreadable_file(tmp_path, capsys):
    assert main(["--check", "--seeds", str(tmp_path / "nothing.tsv")]) == 2
    assert "nothing.tsv" in capsys.readouterr().err


def test_the_default_seeds_file_is_the_one_the_contract_names():
    assert SEEDS_FILE.name == "policy_seeds.tsv" and SEEDS_FILE.parent.name == "data"


FORBIDDEN_ROOTS = {
    "assessment", "workflow", "context", "utils", "sub_agent", "agent", "agents", "deepagents",
    "langchain", "langchain_core", "langchain_anthropic", "langgraph", "anthropic", "openai",
    "subprocess", "requests", "httpx", "fsi_common",
}  # fmt: skip


ALLOWED_MODULES = {"assessment.provisions"}
"""The one module of the engine's side the scoring code may import: it only places a provision
label on a regulation's anchors, so the measures and the engine agree on where a seed sits."""


@pytest.mark.parametrize("name", ["policy_dataset.py", "policy_measures.py"])
def test_the_scoring_code_imports_nothing_from_the_engine_or_a_model_library(name):
    import ast

    source = (SEEDS_FILE.parent.parent / name).read_text(encoding="utf-8")
    modules = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            modules.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            modules.add(node.module)
    roots = {m.split(".")[0] for m in modules if m not in ALLOWED_MODULES}
    assert roots.isdisjoint(FORBIDDEN_ROOTS), roots & FORBIDDEN_ROOTS
