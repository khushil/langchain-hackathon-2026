"""The README's policy figures are the lines the measures print for the seed matches file."""

import re
import subprocess
import sys

import pytest

from evals import policy_measures
from evals.policy_dataset import REGULATION_LABELS, populations, read_seeds
from evals.policy_measures import measure_seeds, read_seed_matches, report_lines
from utils import PROJECT_ROOT

REPO = PROJECT_ROOT.parent
README = REPO / "README.md"
MAKEFILE = REPO / "Makefile"
MATCHES = PROJECT_ROOT / "evals" / "data" / "policy_seed_matches.jsonl"
HEADING = "### Measuring the policy assessment"
LINE = re.compile(r"^(?P<measure>[a-z_]+) \[(?P<scope>[^\]]+)\]: (?P<rest>.+)$")


def section(readme: str) -> str:
    """Return the policy part of the README: from its heading to the next heading."""
    return readme.split(HEADING, 1)[1].split("\n## ", 1)[0].split("\n### ", 1)[0]


def figure_lines(readme: str) -> list[str]:
    """Return the lines of the policy part's one fenced block."""
    blocks = re.findall(r"```text\n(.*?)\n```", section(readme), flags=re.S)
    assert len(blocks) == 1, f"the policy part holds {len(blocks)} text blocks, not 1"
    return blocks[0].splitlines()


def population_rows(readme: str) -> dict[str, tuple[int, int, int]]:
    """Return the populations table of the policy part as label to (seeds, gaps, covered)."""
    rows = {}
    for line in section(readme).splitlines():
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) == 4 and cells[1].isdigit():
            rows[cells[0]] = (int(cells[1]), int(cells[2]), int(cells[3]))
    return rows


@pytest.fixture(scope="module")
def readme():
    return README.read_text(encoding="utf-8")


def test_the_readme_figures_are_the_lines_the_measures_print_for_the_matches_file(readme):
    report = measure_seeds(read_seeds(), read_seed_matches(MATCHES))
    assert figure_lines(readme) == report_lines(report)


def test_the_readme_figures_are_the_lines_the_command_prints(readme):
    printed = subprocess.run(
        [sys.executable, "-m", "evals.policy_measures", "--seed-matches", str(MATCHES)],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=True,
        env={"PYTHONPATH": f"{REPO / 'fsi_common'}:{PROJECT_ROOT}", "PATH": "/usr/bin"},
    ).stdout.splitlines()
    assert [line for line in printed if LINE.match(line)] == figure_lines(readme)


def test_a_figure_that_drifts_from_the_file_is_found(readme):
    lines = figure_lines(readme)
    first = lines[0]
    drifted = readme.replace(first, first.replace(" of ", " of 9", 1), 1)
    assert figure_lines(drifted) != lines
    report = measure_seeds(read_seeds(), read_seed_matches(MATCHES))
    assert figure_lines(drifted) != report_lines(report)


def test_the_readme_populations_are_the_ones_the_seeds_file_gives(readme):
    expected = {
        ("All three" if p.regulation == "all" else REGULATION_LABELS[p.regulation]): (
            p.seeds,
            p.gaps,
            p.covered,
        )
        for p in populations(read_seeds())
    }
    assert population_rows(readme) == expected


def test_the_readme_denominators_of_two_measures_are_the_seed_populations(readme):
    rows = population_rows(readme)
    for line in figure_lines(readme):
        found = LINE.match(line)
        assert found
        measure, scope, rest = found["measure"], found["scope"], found["rest"]
        label = "All three" if scope == "all" else scope
        denominator = int(rest.split(" of ")[1].split(" ")[0])
        if measure == "seeded_gaps_found":
            assert denominator == rows[label][1], line
        if measure == "same_state":
            assert denominator == rows[label][0], line
        if measure == "false_gaps":
            assert denominator == rows[label][2], line


def test_every_figure_is_a_line_the_run_prints_for_the_deck(readme):
    shapes = {
        "seeded_gaps_found": re.compile(r"^\d+ of \d+ seeded gaps$"),
        "same_state": re.compile(r"^\d+ of \d+ seeds$"),
        "false_gaps": re.compile(r"^\d+ of \d+ seeds the labels hold as covered$"),
        "wrong_citations": re.compile(
            r"^\d+ of \d+ seeds that name clauses and were found as anything but not covered$"
        ),
    }
    lines = figure_lines(readme)
    assert len(lines) == 16
    for line in lines:
        found = LINE.match(line)
        assert found and found["scope"] in {"DORA", "AI Act", "SS1/23", "all"}, line
        assert shapes[found["measure"]].match(found["rest"]) or found["rest"] == "none in scope"


def test_the_matches_file_holds_no_text_of_a_regulation_or_a_policy():
    allowed = {
        "seed_id",
        "regulation",
        "target",
        "points",
        "obligation_ids",
        "found_state",
        "seeded_state",
        "cited_clauses",
        "seeded_clauses",
    }
    import json

    for number, line in enumerate(MATCHES.read_text(encoding="utf-8").splitlines(), start=1):
        assert set(json.loads(line)) == allowed, f"line {number}"


def test_the_makefile_has_a_policy_measures_target_that_selftests_then_prints():
    text = MAKEFILE.read_text(encoding="utf-8")
    assert re.search(r"^\.PHONY:.*\bpolicy-measures\b", text, flags=re.M)
    body = text.split("\npolicy-measures:", 1)[1].split("\n\n", 1)[0]
    commands = [line.strip() for line in body.splitlines() if line.startswith("\t")]
    assert len(commands) == 2
    assert "-m evals.policy_measures --selftest" in commands[0]
    assert "--seed-matches evals/data/policy_seed_matches.jsonl" in commands[1]
    assert all(
        c.startswith("cd 03_document_summary_agent && PYTHONPATH=../fsi_common") for c in commands
    )


def test_the_commands_of_the_target_succeed_on_the_committed_file(capsys):
    assert policy_measures.main(["--selftest"]) == 0
    assert policy_measures.main(["--seed-matches", str(MATCHES)]) == 0


def test_the_selftest_closing_line_is_the_count_the_readme_states(readme, capsys):
    assert policy_measures.main(["--selftest"]) == 0
    closing = capsys.readouterr().out.splitlines()[-1]
    caught, total = re.fullmatch(r"planted faults caught: (\d+) of (\d+)", closing).groups()
    assert caught == total
    assert f"the command reports {caught} of {total} caught" in section(readme)


def test_a_matches_file_that_is_the_fake_bundles_is_called_that_in_the_readme(readme, tmp_path):
    from assessment.bundle import write_bundle
    from assessment.fake import build_fake_bundle
    from assessment.texts import load_texts

    def no_network(address, headers):
        raise OSError(f"no network call in a test ({address})")

    fake = build_fake_bundle(load_texts("harbour-mutual-bank", opener=no_network))
    written = write_bundle(fake, tmp_path) / "seed_matches.jsonl"
    if written.read_text(encoding="utf-8") != MATCHES.read_text(encoding="utf-8"):
        pytest.skip("the file is no longer the fake bundle's; the README names the recorded run")
    count = len(read_seed_matches(MATCHES))
    words = {8: "eight"}[count]
    text = section(readme)
    assert "fake bundle" in text and f"{words} of the 55 seeds" in text
    row = next(line for line in readme.splitlines() if "policy_seed_matches.jsonl` |" in line)
    assert "fake bundle" in row and "Written by the assessment engine" not in row


def test_the_readme_does_not_say_a_skipped_case_lowers_every_figure(readme):
    text = section(readme)
    assert "lowers its figures" not in text
    assert "must make it worse" in text
