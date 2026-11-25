"""The README's figures for this topic are the lines the notebook printed, and its list of the
starter's files is true of the folder."""

from __future__ import annotations

import hashlib
import re

import nbformat

from utils import PROJECT_ROOT

REPO = PROJECT_ROOT.parent
README = (REPO / "README.md").read_text(encoding="utf-8")
NOTEBOOK = PROJECT_ROOT / "modules" / "01_kyc_agent.ipynb"
STARTER_CELLS = 35
SECTION = "## KYC onboarding"

SINGLE = {
    "Settled by the checks": "settled_by_checks",
    "Sent to a person": "sent_to_person",
    "Settled proposals that agree with their label": "settled_agree",
    "Edge cases sent to a person": "edge_cases_sent",
    "Applications accounted for": "applications_accounted",
    "Screenings accounted for": "screenings_accounted",
}
PAIRED = {
    "Risk level agrees with the label": ("risk_agrees", "starter_risk_agrees"),
    "Decision agrees with the label": ("decision_agrees", "starter_decision_agrees"),
}

BYTE_FOR_BYTE = {
    "agent.py": "822f3b956ebac1aedffdad5599715a82018112f43491e5a348d0995856925b59",
    "tools/__init__.py": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "tools/applications.py": "6ff2e0251df226575850e16cae9062c20b22b64a2c6f5465560595db2115f1b4",
    "tools/screening.py": "a2a1e7da16c1ee8cd67d5eab2d29abfab139e7370ae67234b5026c6c4b0fe7a2",
    "utils/__init__.py": "f241e31e3428873e08ae07e8d35d74adb600fffb8365afa9720566a012dcbe30",
    "utils/db.py": "ca08ae26654e25741213fb1f0e55ffb6d0dc28385230c216d7fa4f3d2c372e44",
    "utils/state.py": "12a046cd798586aee888290bbaf720812cd04620bb6861a38c16018ea53ba037",
    "scripts/__init__.py": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "data/applications.jsonl": "6bea2ada2224240c45f1e097e14c92ea0f13a27daf9df171171743b789af2f98",
    "data/sanctions_list.jsonl": "08de333511cc217d01e9d464b829ecabdae341628dbedc31b1aeffe04a8e4bf0",
    "data/pep_list.jsonl": "4f74bb476beff2975b6ea89a275e40431c44c5a8328abd82b9cb63113a53baa9",
}
ADAPTED = (
    "utils/nodes.py",
    "utils/models.py",
    "langgraph.json",
    "pyproject.toml",
    "scripts/run_experiments.py",
    "modules/01_kyc_agent.ipynb",
)


def printed() -> str:
    """Return the text every code cell after the starter's printed, as the notebook holds it."""
    notebook = nbformat.read(NOTEBOOK, as_version=4)
    out = []
    for cell in notebook.cells[STARTER_CELLS:]:
        if cell.cell_type == "code":
            for output in cell.outputs:
                out.append(output.get("text") or output.get("data", {}).get("text/plain", ""))
    return "\n".join(out)


def section(text: str, heading: str) -> str:
    start = text.index(heading)
    rest = text[start + len(heading) :]
    end = re.search(r"^## ", rest, re.M)
    return rest[: end.start()] if end else rest


def notebook_figure(key: str) -> str:
    found = re.search(rf"^{key}: (\d+ of \d+)", printed(), re.M)
    assert found, f"the notebook printed no line for {key}"
    return found.group(1)


def readme_rows(text: str = README) -> dict[str, list[str]]:
    rows = {}
    for line in section(text, SECTION).splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if line.startswith("|") and cells[0] not in {"Measure", ""} and not set(cells[0]) <= {"-"}:
            rows[cells[0]] = cells[1:]
    return rows


def mismatches(text: str = README) -> list[str]:
    """Name each row of the README's table that is not the line the notebook printed."""
    rows = readme_rows(text)
    found = [f"{label} is missing" for label in [*SINGLE, *PAIRED] if label not in rows]
    for label, key in SINGLE.items():
        if label in rows and not rows[label][0].startswith(notebook_figure(key)):
            found.append(label)
    for label, (engine, starter) in PAIRED.items():
        if label in rows and not rows[label][0].startswith(notebook_figure(engine)):
            found.append(label)
        if label in rows and not rows[label][1].startswith(notebook_figure(starter)):
            found.append(f"{label} (starter's rule)")
    found += [f"{label} is not a measure" for label in rows if label not in {*SINGLE, *PAIRED}]
    return found


def test_the_readme_has_a_section_for_this_topic():
    assert SECTION in README


def test_each_figure_of_the_readme_table_is_the_line_the_notebook_printed():
    assert mismatches() == []


def test_a_figure_changed_in_the_readme_is_found():
    for old, new in (
        (notebook_figure("settled_by_checks"), "14 of 25"),
        (notebook_figure("starter_risk_agrees"), "25 of 25"),
    ):
        changed = README.replace(f"| {old} applications", f"| {new} applications", 1)
        assert changed != README
        assert mismatches(changed), old
    assert mismatches(README.replace("| Sent to a person |", "| Sent on |")) == [
        "Sent to a person is missing",
        "Sent on is not a measure",
    ]


def test_the_counts_the_prose_gives_are_the_notebooks():
    text = printed()
    facts = re.search(r"Facts cited: (\d+)", text).group(1)
    questions = re.search(r"Open questions for the reviewer: (\d+)", text).group(1)
    with_facts, without = re.search(
        r"screenings: 350 of 350 units accounted for, (\d+) with facts and (\d+) with none", text
    ).groups()
    prose = section(README, SECTION)
    for sentence in (
        f"{facts} facts",
        f"{questions} open questions",
        f"{with_facts} of them are screening facts",
        f"{without} pairings",
    ):
        assert sentence in prose, sentence


def test_the_files_the_readme_calls_the_starters_are_so_byte_for_byte():
    for path, digest in BYTE_FOR_BYTE.items():
        held = hashlib.sha256((PROJECT_ROOT / path).read_bytes()).hexdigest()
        assert held == digest, f"{path} is not the starter's"
        assert f"`01_kyc_agent/{path}`" in README, f"the README does not list {path}"


def test_the_files_the_readme_calls_adapted_exist_and_are_listed():
    for path in ADAPTED:
        assert (PROJECT_ROOT / path).is_file(), path
        assert f"`01_kyc_agent/{path}`" in README, f"the README does not list {path}"


def test_the_readme_says_the_labels_are_the_starters():
    prose = " ".join(section(README, SECTION).split())
    assert "labels are the starter's" in prose
    assert "hand-labelled" not in README.replace("hand-labelled by", "")


def test_the_recordings_count_the_readme_gives_is_the_count_on_disk():
    on_disk = len(list((PROJECT_ROOT / "recordings").glob("*.json")))
    stated = {int(n) for n in re.findall(r"(\d+) recorded model calls", README)}
    assert stated == {on_disk}, f"the README gives {stated}; the folder holds {on_disk}"
    reasons = {
        m: len(
            [
                1
                for f in (PROJECT_ROOT / "recordings").glob("*.json")
                if f'"model": "{m}"' in f.read_text(encoding="utf-8")
            ]
        )
        for m in ("claude-sonnet-5-5", "claude-opus-5-5")
    }
    assert f"{reasons['claude-sonnet-5-5']} on Sonnet" in README
    assert f"{reasons['claude-opus-5-5']} on Opus" in README


STARTER_DEPENDENCIES = {
    "langgraph",
    "langchain-openai",
    "python-dotenv",
    "langgraph-cli",
    "langgraph-api",
    "notebook",
    "langchain",
    "langchain-anthropic",
}
TOPIC_README = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")


def added_dependencies() -> set[str]:
    """Return the dependencies the topic's pyproject.toml lists beyond the starter's."""
    import tomllib

    held = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    names = {re.split(r"[\[<>=!~ ]", d, maxsplit=1)[0] for d in held["project"]["dependencies"]}
    return names - STARTER_DEPENDENCIES


def listed_as_added(text: str, marker: str) -> set[str]:
    """Return the package names the one line holding the marker lists as added."""
    lines = [line for line in text.splitlines() if marker in line]
    assert len(lines) == 1, f"{len(lines)} lines hold {marker}"
    names = re.findall(r"`([^`]+)`", lines[0])
    return {n for n in names if re.fullmatch(r"[a-z][a-z0-9-]+", n)}


def test_the_starters_dependencies_are_all_still_in_the_topics_pyproject():
    import tomllib

    held = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    names = {re.split(r"[\[<>=!~ ]", d, maxsplit=1)[0] for d in held["project"]["dependencies"]}
    assert STARTER_DEPENDENCIES <= names


def test_the_readmes_list_of_added_dependencies_is_the_pyproject_s():
    assert added_dependencies() == {"fsi-common", "pydantic", "langgraph-checkpoint-sqlite"}
    assert listed_as_added(README, "`01_kyc_agent/pyproject.toml` keeps") == added_dependencies()
    assert listed_as_added(TOPIC_README, "| `pyproject.toml` |") == added_dependencies()


def test_a_dependency_dropped_from_a_readme_or_added_to_the_pyproject_is_found():
    marker = "`01_kyc_agent/pyproject.toml` keeps"
    for text, where in ((README, marker), (TOPIC_README, "| `pyproject.toml` |")):
        dropped = text.replace("`pydantic`, ", "").replace("`pydantic` ", "")
        assert dropped != text
        assert listed_as_added(dropped, where) != added_dependencies()
    assert listed_as_added(README, marker) | {"httpx"} != added_dependencies()
