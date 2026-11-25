"""Structural tests: only the review route builds a decision, and every route is tested."""

import ast
from pathlib import Path

import pytest

from review_app import plugin
from utils import PROJECT_ROOT

APP = PROJECT_ROOT / "review_app"
BUILDERS = {"Decision", "SignOff", "Assumption"}
ALLOWED = {"review_route.py"}
FACT_READERS = {"drafts.py", "seed.py"}


def sources() -> list[Path]:
    return sorted(APP.glob("*.py"))


READERS = {
    "context.py",
    "drafts.py",
    "reviewing.py",
    "routes_start.py",
    "routes_tables.py",
    "review_model.py",
    "wording.py",
}
"""The modules that read a decision or a sign-off the review route made, to show or keep it."""
BUILD_CALLS = {"on", "build"}


def violations(source: str, name: str = "module.py") -> list[str]:
    """Say what in a module could build a decision, a sign-off or an assumption.

    The review route may import and build them. A reading module may import them to read what
    was stored (``model_validate``) and never to build. Every other module may not import them
    at all, under any name.
    """
    tree = ast.parse(source)
    aliases: dict[str, str] = {}
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith(
            "fsi_common.records"
        ):
            for imported in node.names:
                if imported.name in BUILDERS:
                    aliases[imported.asname or imported.name] = imported.name
                    if name not in ALLOWED | READERS or (
                        imported.name == "Assumption" and name not in ALLOWED
                    ):
                        found.append(f"{name}:{node.lineno} imports {imported.name}")
        elif isinstance(node, ast.Import):
            found += [
                f"{name}:{node.lineno} imports {a.name}"
                for a in node.names
                if a.name == "fsi_common.records.decisions"
            ]
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id in aliases
            and node.attr in BUILD_CALLS
            and name not in ALLOWED
        ):
            found.append(f"{name}:{node.lineno} builds with {aliases[node.value.id]}.{node.attr}")
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr.startswith("model_validate")
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id in aliases
            and node.args
            and (
                isinstance(node.args[0], ast.Dict)
                or (
                    isinstance(node.args[0], ast.Call)
                    and isinstance(node.args[0].func, ast.Name)
                    and node.args[0].func.id == "dict"
                )
            )
            and name not in ALLOWED
        ):
            found.append(
                f"{name}:{node.lineno} builds with {aliases[node.func.value.id]} from a literal"
            )
        if (
            isinstance(node, ast.Attribute)
            and node.attr in BUILDERS
            and name not in ALLOWED | READERS
        ):
            found.append(f"{name}:{node.lineno} names {node.attr}")
        if (
            isinstance(node, ast.Attribute)
            and node.attr in BUILD_CALLS
            and isinstance(node.value, ast.Attribute)
            and node.value.attr in BUILDERS
            and name not in ALLOWED
        ):
            found.append(f"{name}:{node.lineno} builds with {node.value.attr}.{node.attr}")
    return found


@pytest.mark.parametrize("path", sources(), ids=lambda p: p.name)
def test_no_module_but_the_review_route_builds_a_decision_or_a_sign_off(path):
    found = violations(path.read_text(encoding="utf-8"), path.name)
    assert found == []
    if path.name in ALLOWED:
        assert "Decision.on" in path.read_text(encoding="utf-8")


PLANTS = {
    "an aliased import": "from fsi_common.records import Decision as _D\n_D.on(x)\n",
    "model_validate of a literal in a page module": (
        "from fsi_common.records import Decision\nDecision.model_validate({'outcome': 'accept'})\n"
    ),
    "model_validate of a built dict": (
        "from fsi_common.records import SignOff\nSignOff.model_validate(dict(outcome='signed'))\n"
    ),
    "a sign-off built": "from fsi_common.records import SignOff\nSignOff.build(a=1)\n",
    "an assumption imported": "from fsi_common.records import Assumption\n",
    "the decisions module": "import fsi_common.records.decisions\n",
    "the module reached through the package": "import fsi_common.records as r\nr.Decision.on(x)\n",
}


@pytest.mark.parametrize("plant", sorted(PLANTS))
def test_the_scan_finds_each_planted_way_to_build_outside_the_route(plant):
    assert violations(PLANTS[plant], "routes_tables.py")


def test_a_reader_may_read_a_stored_decision_and_may_not_build_one():
    read = "from fsi_common.records import Decision\nDecision.model_validate(x)\n"
    assert violations(read, "drafts.py") == []
    assert violations("from fsi_common.records import Decision as D\nD.on(x)\n", "drafts.py")
    literal = "from fsi_common.records import Decision\nDecision.model_validate({'a': 1})\n"
    assert violations(literal, "routes_tables.py")
    assert violations("from fsi_common.records import SignOff\nSignOff.build(x)\n", "reviewing.py")


def test_the_scan_leaves_a_module_with_no_builder_alone():
    assert violations("x = 1\n", "routes_tables.py") == []
    assert violations("SignOff.model_validate(x)\n", "routes_tables.py") == []


def test_the_recording_routes_all_need_the_review_route_and_a_person():
    source = (APP / "routes_record.py").read_text(encoding="utf-8")
    for action in (
        "decide_proposal",
        "answer_question",
        "check_assumption",
        "build_response",
    ):
        assert f"review_route.{action}" in source
    assert "current_person(request)" in source and "SIGN_IN_FIRST" in source


def test_no_template_names_a_machine_deciding():
    text = " ".join(p.read_text() for p in (APP / "templates" / "kyc").glob("*.html")).lower()
    for word in ("auto-approve", "approved by the machine", "approve all", "claude"):
        assert word not in text, word


ROUTES = {
    "/": "pages: start page",
    "/runs": "pages: starting a batch",
    "/runs.csv": "pages: csv",
    "/runs/{thread}": "pages: a batch waiting leads to its review",
    "/runs/{thread}/review": "pages: the batch page",
    "/runs/{thread}/signoff": "pages: the sign-off page",
    "/runs/{thread}/applications/{customer}": "pages: the application page",
    "/runs/{thread}/decide": "flow: a decision",
    "/runs/{thread}/answer": "flow: an answer",
    "/runs/{thread}/assume": "flow: an assumption",
    "/runs/{thread}/sign": "flow: signing",
    "/runs/{thread}/screenings": "pages: the screenings tab",
    "/runs/{thread}/screenings.csv": "pages: the screenings csv",
    "/runs/{thread}/applications.csv": "pages: the applications csv",
    "/runs/{thread}/decisions.csv": "flow: the decisions csv",
    "/runs/{thread}/signed": "flow: the signed page",
    "/static": "browser: every page loads review.css",
}


def test_every_route_of_the_plug_in_is_named_with_the_test_that_covers_it():
    built = plugin.build_plugin()
    found = {r.path for r in built.routes}
    assert found == set(ROUTES) - {"/static"}
    assert built.static_dir is not None


@pytest.mark.parametrize(
    "plant",
    [
        "\nfrom fsi_common.records import Decision as _D\n_D.on(None)\n",
        "\nfrom fsi_common.records import SignOff\nSignOff.model_validate({'outcome': 'signed'})\n",
    ],
)
def test_a_decision_built_in_a_real_page_module_turns_the_scan_red(plant):
    path = APP / "routes_tables.py"
    source = path.read_text(encoding="utf-8")
    assert violations(source, path.name) == []
    assert violations(source + plant, path.name)
