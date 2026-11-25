"""The public files say about the acts' terms what the Publications Office's notice says."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from context.regulations.manifest import REGULATIONS_DIR, load_manifest

ROOT = REGULATIONS_DIR.parents[2]
EDITORIAL = (
    "The editorial content of this website, which is owned by the EU, is licensed under the "
    "Creative Commons Attribution 4.0 International licence. This means that you can reuse it "
    "provided you acknowledge the source and indicate any changes you have made."
)
PUBLICATIONS = (
    "Most of the publications on this website are freely available, many of them under Creative "
    "Commons licences, and can be downloaded and reproduced provided the source is acknowledged."
)
NOTICE = "https://op.europa.eu/en/web/about-us/legal-notices/publications-office-of-the-european-union-copyright"
EURLEX_NOTICE = "https://eur-lex.europa.eu/content/legal-notice/legal-notice.html"
FORBIDDEN = (
    r"CC BY",
    r"Creative Commons Attribution",
    r"under (the|a|their|its) licen[cs]e",
    r"licensed under",
    r"\blicen[cs]e",
)
CODE_DIRS = (REGULATIONS_DIR.parents[1] / "context" / "regulations", Path(__file__).parent)


def squash(text: str) -> str:
    return " ".join(text.split())


def without_the_notice_quotes(text: str) -> str:
    out = squash(text)
    for sentence in (EDITORIAL, PUBLICATIONS):
        out = out.replace(sentence, "")
    return out


def regulation_lines(text: str) -> str:
    """The lines of the README that speak of the regulations."""
    pattern = re.compile(r"DORA|AI Act|Publications Office|regulations/|SS1/23|Prudential|EUR-Lex")
    return "\n".join(line for line in text.splitlines() if pattern.search(line))


def public_files() -> dict[str, str]:
    files = {
        "SOURCES.md": (REGULATIONS_DIR / "SOURCES.md").read_text(encoding="utf-8"),
        "README.md": regulation_lines((ROOT / "README.md").read_text(encoding="utf-8")),
    }
    raw = json.loads((REGULATIONS_DIR / "sources.json").read_text(encoding="utf-8"))
    for row in raw["regulations"]:
        files[f"sources.json {row['key']} keys"] = " ".join(row)
        for key, value in row.items():
            files[f"sources.json {row['key']} {key}"] = (
                " ".join(value) if isinstance(value, list) else str(value)
            )
    for folder in CODE_DIRS:
        for path in sorted(folder.glob("*.py")):
            if path.name != Path(__file__).name:
                files[f"{folder.name}/{path.name}"] = path.read_text(encoding="utf-8")
    return files


@pytest.mark.parametrize("name", sorted(public_files()))
def test_no_public_file_calls_the_acts_cc_by_or_held_under_a_licence(name):
    text = without_the_notice_quotes(public_files()[name])
    found = [p for p in FORBIDDEN if re.search(p, text, re.IGNORECASE)]
    assert found == [], f"{name} says {found} outside a quotation of the notice"


def test_the_manifest_quotes_both_notice_passages_as_a_list_with_a_pointer_for_the_omission():
    for e in load_manifest().regulations:
        if e.text_file:
            assert [squash(p) for p in e.notice_passages] == [
                squash(EDITORIAL),
                squash(PUBLICATIONS),
            ]
            assert e.notice_address == NOTICE
            assert e.notice == "see the notice quoted in SOURCES.md"
            assert "(external link)" in e.notice_omission and "SOURCES.md" in e.notice_omission
            assert "EUR-Lex" not in e.publisher
        else:
            assert e.notice == "" and e.notice_passages == ()


def test_the_attribution_names_the_union_the_official_journal_reference_and_the_address():
    by_key = {e.key: e for e in load_manifest().regulations}
    assert "© European Union" in by_key["DORA"].attribution
    assert "OJ L 333, 27.12.2022" in by_key["DORA"].attribution
    assert "https://publications.europa.eu/resource/celex/32022R2554" in by_key["DORA"].attribution
    assert "OJ L, 2024/1689, 12.7.2024" in by_key["AI-ACT"].attribution
    assert (
        "https://publications.europa.eu/resource/celex/32024R1689" in by_key["AI-ACT"].attribution
    )


def test_sources_note_quotes_the_notice_marks_its_one_omission_and_names_the_check():
    text = squash((REGULATIONS_DIR / "SOURCES.md").read_text(encoding="utf-8"))
    assert EDITORIAL in text and PUBLICATIONS in text
    assert "(external link)" in text  # the omission is named
    assert NOTICE in text
    assert EURLEX_NOTICE in text
    assert "split into units for reading" in text
    assert "test_every_source_paragraph_is_found_word_for_word_in_the_units" in text
    assert "see the notice quoted below" in text


def test_sources_note_gives_both_dates_of_the_statement():
    text = (REGULATIONS_DIR / "SOURCES.md").read_text(encoding="utf-8")
    assert "16 April 2026" in text and "23 April 2026" in text


def test_the_readme_quotes_the_notice_and_gives_the_address_fetched_from_for_each_act():
    readme = squash((ROOT / "README.md").read_text(encoding="utf-8"))
    assert EDITORIAL in readme and PUBLICATIONS in readme
    assert NOTICE in readme
    for address in ("32022R2554", "32024R1689"):
        assert f"https://publications.europa.eu/resource/celex/{address}" in readme
    assert EURLEX_NOTICE in readme
    assert isinstance(ROOT, Path)


def test_the_gate_checks_the_regulations_before_it_runs_the_tests_and_requires_them():
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    gate = next(line for line in makefile.splitlines() if line.startswith("gate:"))
    targets = gate.removeprefix("gate:").split()
    assert targets.index("regulations-check") < targets.index("test")
    assert "export REQUIRE_REGULATIONS = 1" in makefile


def test_the_eurlex_address_is_said_to_come_from_the_publications_office_notice_and_unopened():
    text = squash((REGULATIONS_DIR / "SOURCES.md").read_text(encoding="utf-8"))
    assert "taken from the Publications Office's notice" in text
    assert "was not opened by this reader" in text


def test_the_readme_names_the_check_and_says_what_is_taken_out_of_the_units():
    readme = squash((ROOT / "README.md").read_text(encoding="utf-8"))
    assert "test_every_source_paragraph_is_found_word_for_word_in_the_units" in readme
    assert "footnote references" in readme and "own number" in readme


def test_the_eurlex_address_ends_the_sentence_that_gives_it_in_both_places():
    sources = squash((REGULATIONS_DIR / "SOURCES.md").read_text(encoding="utf-8"))
    readme = squash((ROOT / "README.md").read_text(encoding="utf-8"))
    for text in (sources, readme):
        assert "where a reader checks the terms" in text
        assert "checks the terms for legal documents" not in text


def test_the_readme_names_the_gate_target_that_fetches_the_statement():
    assert "`regulations-check`" in (ROOT / "README.md").read_text(encoding="utf-8")


def test_make_test_depends_on_the_regulations_check():
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    line = next(ln for ln in makefile.splitlines() if ln.startswith("test:"))
    assert "regulations-check" in line
