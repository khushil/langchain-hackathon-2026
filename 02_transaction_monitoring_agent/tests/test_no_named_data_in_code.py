"""No rule of the product is tuned to a named transaction or customer.

A check that mentions ``TX-2004`` would pass every test written against the starter's data and
still be wrong for any other data. Product code names no transaction and no customer; only the
seed's decisions and the planted faults, which are about the starter's data on purpose, may.
"""

import ast
import re
from pathlib import Path

TOPIC = Path(__file__).resolve().parents[1]
FOLDERS = ("context", "workflow", "review_app", "evals", "utils", "scripts")
SINGLE = ("agents.py", "agent.py")
ALLOWED = {"review_app/seed_fixture.py", "evals/planted_faults.py"}
NAMED = re.compile(r"\b(?:TX|USR)-\d+")


def named_literals(source: str) -> list[str]:
    """Return every string constant that names a transaction or a customer, docstrings left out."""
    tree = ast.parse(source)
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            first = node.body[0] if node.body else None
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                docstrings.add(id(first.value))
    return [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
        and NAMED.search(node.value)
    ]


def product_files() -> list[Path]:
    files = [TOPIC / name for name in SINGLE]
    for folder in FOLDERS:
        files.extend(sorted((TOPIC / folder).rglob("*.py")))
    return files


def test_product_code_names_no_transaction_and_no_customer_outside_its_two_allowed_files():
    found = {}
    for path in product_files():
        relative = path.relative_to(TOPIC).as_posix()
        if relative in ALLOWED:
            continue
        literals = named_literals(path.read_text(encoding="utf-8"))
        if literals:
            found[relative] = literals
    assert found == {}


def test_the_allowed_files_exist_and_do_name_data_so_the_allowance_is_not_stale():
    for relative in ALLOWED:
        assert named_literals((TOPIC / relative).read_text(encoding="utf-8")), relative


def test_the_scan_finds_a_rule_tuned_to_a_named_transaction_and_ignores_docstrings():
    tuned = "\n".join(
        [
            "def passes(row):",
            '    """Mentions TX-1001 in words."""',
            '    return row["id"] == "TX-2004"',
        ]
    )
    assert named_literals(tuned) == ["TX-2004"]
    assert named_literals('USER = f"USR-{1}"\nOTHER = "USR-002"\n') == ["USR-002"]
    assert named_literals('"""TX-1001 is described here."""\nVALUE = "no id"\n') == []
