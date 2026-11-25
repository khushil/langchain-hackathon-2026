"""Only the review route builds a decision or a sign-off, however the code names the builders."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

TOPIC = Path(__file__).resolve().parents[2]
RECORDS = ("Decision", "SignOff")
READS = {"model_validate"}  # reading a stored record back builds nothing a person decided


def builder_calls(source: str) -> set[str]:
    """Return every call that could build a decision or a sign-off, however it is named.

    A call counts when its function is a name or an attribute that resolves to ``Decision`` or
    ``SignOff``: directly, through an import alias, through a module path, or through a name that
    was assigned from one of them. ``Decision.model_validate`` is a read and does not count.
    """
    tree = ast.parse(source)
    bound: dict[str, str] = {name: name for name in RECORDS}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for item in node.names:
                if item.name in RECORDS:
                    bound[item.asname or item.name] = item.name

    def resolve(node: ast.AST) -> str | None:
        if isinstance(node, ast.Name):
            return bound.get(node.id)
        if isinstance(node, ast.Attribute):
            return node.attr if node.attr in RECORDS else resolve(node.value)
        return None

    changed = True
    while changed:
        changed = False
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and (found := resolve(node.value)):
                for target in node.targets:
                    if isinstance(target, ast.Name) and bound.get(target.id) != found:
                        bound[target.id] = found
                        changed = True
    found: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        function = node.func
        if isinstance(function, ast.Attribute) and function.attr in READS:
            continue
        if isinstance(function, ast.Name) and function.id == "getattr" and node.args:
            record = resolve(node.args[0])
            if record:
                found.add(f"getattr({record})")
            continue
        record = resolve(function)
        if record:
            found.add(
                f"{record}.{function.attr}" if isinstance(function, ast.Attribute) else record
            )
    return found


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("Decision.on(x, outcome='accept')", {"Decision.on"}),
        ("SignOff.build(brief_id=b)", {"SignOff.build"}),
        ("Decision(**fields)", {"Decision"}),
        ("SignOff(**fields)", {"SignOff"}),
        ("from fsi_common.records import Decision as Made\nMade.on(x)", {"Decision.on"}),
        ("from fsi_common import records\nrecords.Decision.on(x)", {"Decision.on"}),
        ("import fsi_common.records as r\nr.SignOff.build()", {"SignOff.build"}),
        ("from a import Decision\nmake = Decision.on\nmake(x)", {"Decision"}),
        ("from a import Decision\ngetattr(Decision, 'on')(x)", {"getattr(Decision)"}),
        ("Decision.model_validate(raw)\nSignOff.model_validate(raw)", set()),
        ("Assumption(question_id=q, words=w)\nPerson(name=n, role=r)", set()),
    ],
)
def test_the_scan_finds_a_builder_however_it_is_named_and_lets_a_read_pass(source, expected):
    assert builder_calls(source) == expected


def _application_files():
    root = TOPIC.parent / "fsi_common" / "fsi_common" / "app"
    return [*(TOPIC / "review_app").glob("*.py"), *root.glob("*.py")]


def test_only_the_review_route_builds_a_decision_or_a_sign_off():
    files = _application_files()
    assert {p.name for p in files} >= {"review_route.py", "routes_review.py", "app.py", "seed.py"}
    builders = {}
    for path in files:
        hits = builder_calls(path.read_text())
        if hits:
            builders[path.name] = sorted(hits)
    assert builders == {"review_route.py": ["Decision.on", "SignOff.build"]}


def test_a_builder_planted_in_a_page_module_turns_the_scan_red():
    source = (TOPIC / "review_app" / "routes_review.py").read_text()
    plant = (
        "\nfrom fsi_common.records import Decision\n"
        "smuggled = Decision.on(fact, outcome='accept')\n"
    )
    assert builder_calls(source) == set()
    assert builder_calls(source + plant) == {"Decision.on"}


def test_the_prefix_is_one_path_segment_because_the_shell_routes_by_the_first_segment():
    import re

    from review_app.context import PREFIX

    assert re.fullmatch(r"/[A-Za-z0-9_-]+", PREFIX)
