"""Structural tests: nothing in the engine builds a decision or a sign-off, and a model cannot."""

import ast
from pathlib import Path

import pytest
from engine_fakes import Harness
from kyc_fakes import ScriptedReader, reading_of

from utils import PROJECT_ROOT

BANNED_NAMES = {"Decision", "SignOff"}
BANNED_MODULES = {"fsi_common.records.decisions"}
BANNED_CALLS = {"getattr", "__import__", "import_module", "eval", "exec"}
BANNED_TEXTS = ("signoff.v1", "decision.v1")
ENGINE_PACKAGES = ("workflow", "context")
STORED_DECISION_READER = "workflow/decisions.py"
BRIEF_READER = "workflow/review.py"
"""The two modules that may read a record through the registry: the one stored-decision read,
and the brief the graph itself wrote into its own state."""


def _registry_read_allowed(node: ast.Subscript, parent: ast.AST | None, name: str, tree) -> bool:
    """Whether a registry subscript is one of the two reads the engine is allowed."""
    if not (isinstance(parent, ast.Attribute) and parent.attr == "model_validate"):
        return False
    key = node.slice
    if not isinstance(key, ast.Name):
        return False
    if name == STORED_DECISION_READER and key.id == "DECISION_SCHEMA":
        call = next(
            (c for c in ast.walk(tree) if isinstance(c, ast.Call) and c.func is parent), None
        )
        return (
            call is not None
            and len(call.args) == 1
            and isinstance(call.args[0], ast.Attribute)
            and call.args[0].attr == "value"
            and isinstance(call.args[0].value, ast.Name)
            and call.args[0].value.id == "item"
        )
    return name == BRIEF_READER and key.id == "BRIEF_SCHEMA"


def _is_stored_decision_constant(node: ast.Constant, parent: ast.AST | None, name: str) -> bool:
    return (
        name == STORED_DECISION_READER
        and node.value == "decision.v1"
        and isinstance(parent, ast.Assign)
        and [t.id for t in parent.targets if isinstance(t, ast.Name)] == ["DECISION_SCHEMA"]
    )


def violations(source: str, name: str = "module") -> list[str]:
    """Return what in a module's source could build a decision or a sign-off."""
    tree = ast.parse(source)
    parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
    found = []
    for node in ast.walk(tree):
        line = f"{name}:{getattr(node, 'lineno', 0)}"
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module in BANNED_MODULES or (
                module == "fsi_common.records" and any(a.name == "decisions" for a in node.names)
            ):
                found.append(f"{line} imports the decisions module")
            found += [f"{line} imports {a.name}" for a in node.names if a.name in BANNED_NAMES]
            found += [
                f"{line} renames RECORD_TYPES"
                for a in node.names
                if a.name == "RECORD_TYPES" and a.asname
            ]
        elif isinstance(node, ast.Import):
            found += [f"{line} imports {a.name}" for a in node.names if a.name in BANNED_MODULES]
        elif isinstance(node, ast.Name) and node.id in BANNED_NAMES:
            found.append(f"{line} names {node.id}")
        elif isinstance(node, ast.Attribute) and node.attr in BANNED_NAMES:
            found.append(f"{line} names {node.attr}")
        elif isinstance(node, ast.Constant) and node.value in BANNED_NAMES:
            found.append(f"{line} holds the text {node.value}")
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            for text in BANNED_TEXTS:
                if text in node.value and not _is_stored_decision_constant(
                    node, parents.get(node), name
                ):
                    found.append(f"{line} holds the text {text}")
        elif isinstance(node, ast.Call):
            func = node.func
            called = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
            if called in BANNED_CALLS:
                found.append(f"{line} calls {called}")
        if isinstance(node, ast.Subscript):
            holder = node.value
            if (isinstance(holder, ast.Name) and holder.id == "RECORD_TYPES") or (
                isinstance(holder, ast.Attribute) and holder.attr == "RECORD_TYPES"
            ):
                if not _registry_read_allowed(node, parents.get(node), name, tree):
                    found.append(f"{line} uses RECORD_TYPES other than for its one allowed read")
    return found


def _relative(path: Path) -> str:
    return path.relative_to(PROJECT_ROOT).as_posix()


def engine_sources() -> list[Path]:
    return sorted(
        path for package in ENGINE_PACKAGES for path in (PROJECT_ROOT / package).rglob("*.py")
    )


def test_the_scan_reads_every_module_of_both_packages():
    names = {_relative(p) for p in engine_sources()}
    assert {"workflow/review.py", "workflow/graph.py", "context/proposals.py"} <= names
    assert len(names) >= 20


@pytest.mark.parametrize("path", engine_sources(), ids=_relative)
def test_no_engine_module_imports_or_calls_a_decision_or_sign_off_builder(path):
    assert violations(path.read_text(encoding="utf-8"), _relative(path)) == []


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("from fsi_common.records import Decision\n", "imports Decision"),
        ("from fsi_common.records import SignOff as S\n", "imports SignOff"),
        ("from fsi_common.records.decisions import Assumption\n", "decisions module"),
        ("import fsi_common.records.decisions\n", "imports fsi_common.records.decisions"),
        ("import fsi_common.records as r\nr.Decision.on(x)\n", "names Decision"),
        ("x = RECORD_TYPES['decision.v1'].build(a=1)\n", "other than for its one allowed read"),
        ("getattr(records, 'Dec' + 'ision')\n", "calls getattr"),
        ("name = 'Decision'\n", "holds the text Decision"),
    ],
)
def test_the_scan_finds_each_planted_way_in(source, expected):
    assert any(expected in v for v in violations(source))


def test_a_sign_off_built_from_a_dict_in_a_real_engine_module_turns_the_scan_red():
    path = PROJECT_ROOT / "workflow" / "closing.py"
    source = path.read_text(encoding="utf-8")
    plant = "\nsmuggled = RECORD_TYPES['signoff.v1'].model_validate({'outcome': 'signed'})\n"
    assert violations(source, _relative(path)) == []
    assert violations(source + plant, _relative(path))


def _code_strings(source: str) -> list[str]:
    """Every string constant of a module that is not a docstring."""
    tree = ast.parse(source)
    docstrings = {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
    }
    return [
        n.value
        for n in ast.walk(tree)
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docstrings
    ]


def test_no_rule_of_the_engine_names_a_customer():
    for path in engine_sources():
        named = [s for s in _code_strings(path.read_text(encoding="utf-8")) if "CUST-" in s]
        assert named == [], _relative(path)


def test_the_scan_for_a_named_customer_finds_one_in_code_and_not_in_a_docstring():
    assert _code_strings('"""About CUST-001."""\nx = "CUST-001"\n') == ["CUST-001"]


def test_a_model_output_with_an_approval_changes_nothing_and_the_run_stops_at_the_interrupt():
    approving = {
        **reading_of("CUST-003").model_dump(mode="json"),
        "accepted": True,
        "approved_by": "Dana Whitfield",
        "reviewer": {"name": "Dana Whitfield", "role": "Head of Compliance"},
        "sign_off": {"outcome": "signed"},
        "decisions": [{"outcome": "accept"}],
    }
    harness = Harness(ScriptedReader(readings={"CUST-003": approving}))
    config = harness.start("CUST-003")
    state = harness.graph.get_state(config)
    values = state.values
    assert state.next == ("review",)
    assert not values.get("decisions") and not values.get("sign_off")
    assert harness.store.search(("kyc-onboarding", "decisions"), limit=100) == []
    assert harness.store.search(("kyc-onboarding", "sign-offs"), limit=100) == []
    request = harness.review_request(config)
    assert {c.carry.outcome for s in request.statements for c in s.facts} == {"fresh"}
    assert request.open_questions, "the application is still put to a person"


def _code_text(path: Path) -> str:
    return "\n".join(_code_strings(path.read_text(encoding="utf-8")))


def test_no_rule_of_the_engine_names_a_surname_the_applications_hold():
    from kyc_fakes import NAMES

    surnames = {name.split()[-1] for name in NAMES.values()}
    for path in engine_sources():
        named = sorted(s for s in surnames if s in _code_text(path))
        assert named == [], f"{_relative(path)} names {named}"


def test_a_surname_planted_into_a_rule_is_found_by_the_scan():
    path = PROJECT_ROOT / "context" / "screening.py"
    planted = path.read_text(encoding="utf-8") + '\nBLOCKED = "Strahov"\n'
    assert "Strahov" not in _code_text(path)
    assert "Strahov" in "\n".join(_code_strings(planted))
