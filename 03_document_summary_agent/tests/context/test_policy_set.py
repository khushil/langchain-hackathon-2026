"""Tests that the written Harbour Mutual Bank set is a policy framework of related documents."""

import re

from policy_support import hmb_manifest_documents, hmb_policies, read_policy

CONTROL_KEYS = (
    "Reference",
    "Document type",
    "Version",
    "Status",
    "Owner",
    "Approved by",
    "Approval date",
    "Effective date",
    "Next review",
)
DATE = re.compile(
    r"^\d{1,2} (January|February|March|April|May|June|July|August|September|"
    r"October|November|December) \d{4}$"
)
REFERENCE = re.compile(r"\bHMB-[A-Z]{3}-[A-Z]{2,3}-\d{3}\b")
OUTSIDE_THE_SET = {"HMB-STD-ICT-019"}
"""References the set makes to documents it does not hold; the seed register records each."""


def test_the_set_holds_at_least_six_documents_of_policy_standard_and_procedure():
    policies = hmb_policies()
    assert len(policies) >= 6
    types = {p.control["Document type"] for p in policies.values()}
    assert {"Policy", "Standard", "Procedure"} <= types


def test_every_document_has_its_title_and_control_lines():
    for entry in hmb_manifest_documents():
        policy = hmb_policies()[entry["id"]]
        assert policy.title == entry["title"], entry["id"]
        missing = [key for key in CONTROL_KEYS if key not in policy.control]
        assert not missing, f"{entry['id']} lacks {missing}"
        assert policy.control["Status"] in {"In force", "Superseded"}, entry["id"]
        assert DATE.match(policy.control["Approval date"]), entry["id"]
        assert DATE.match(policy.control["Effective date"]), entry["id"]
        assert re.fullmatch(r"\d+\.\d+", policy.control["Version"]), entry["id"]
        assert entry["id"] == f"{policy.control['Reference']}-v{policy.control['Version']}"


def test_every_document_is_of_real_weight():
    for doc_id, policy in hmb_policies().items():
        assert policy.words >= 1500, f"{doc_id} has {policy.words} words"
        assert len(policy.sections) >= 6, doc_id


def test_sections_and_clauses_are_numbered_in_order():
    for doc_id, policy in hmb_policies().items():
        numbers = [int(number) for number, _ in policy.sections]
        assert numbers == list(range(1, len(numbers) + 1)), doc_id
        for section, _ in policy.sections:
            clauses = [c for c in policy.clauses if c.split(".")[0] == section]
            assert clauses == [f"{section}.{n}" for n in range(1, len(clauses) + 1)], doc_id
            assert clauses, f"{doc_id} section {section} holds no clause"


def test_one_superseded_version_is_kept_beside_its_successor():
    policies = hmb_policies()
    superseded = [d for d, p in policies.items() if p.control["Status"] == "Superseded"]
    assert len(superseded) == 1
    old = policies[superseded[0]]
    successors = [
        (d, p)
        for d, p in policies.items()
        if p.control.get("Supersedes", "").startswith(
            f"{old.control['Reference']} version {old.control['Version']}"
        )
    ]
    assert len(successors) == 1
    _, new = successors[0]
    assert new.control["Status"] == "In force"
    assert new.control["Reference"] == old.control["Reference"]
    assert old.control["Superseded by"].startswith(
        f"{new.control['Reference']} version {new.control['Version']}"
    )


def test_every_document_refers_to_another_and_references_resolve():
    policies = hmb_policies()
    references = {p.control["Reference"] for p in policies.values()}
    unresolved = set()
    for doc_id, policy in policies.items():
        text = "\n".join(policy.clauses.values())
        found = set(REFERENCE.findall(text)) - {policy.control["Reference"]}
        assert found, f"{doc_id} refers to no other document"
        unresolved |= found - references
    assert unresolved == OUTSIDE_THE_SET


def test_owners_are_roles_and_documents_name_no_person():
    for doc_id, policy in hmb_policies().items():
        owner = policy.control["Owner"]
        assert owner[0].isupper() and len(owner.split()) >= 2, doc_id
        assert not re.search(r"\b(Mr|Mrs|Ms|Dr)\.? [A-Z]", "\n".join(policy.clauses.values()))


def test_read_policy_refuses_a_block_outside_the_numbering():
    text = "# T\n\n## Document control\n\nReference: X\n\n## 1. Purpose\n\n1.1 One.\n\nStray.\n"
    try:
        read_policy(text)
    except AssertionError as error:
        assert "Stray" in str(error)
    else:
        raise AssertionError("a stray block was read as a clause")


COMPANIES = {"NimbusCloud", "PayCore Ltd", "Brindlemoor Analytics Ltd"}
"""The only companies the written set names: the starter's two providers and one invented vendor."""


def test_the_set_names_only_its_own_companies():
    text = "\n".join("\n".join(p.clauses.values()) for p in hmb_policies().values())
    named = set(re.findall(r"\b(?:[A-Z][a-z]+ )+(?:Ltd|Limited|Inc|GmbH|AG|SA)\b", text))
    assert named <= COMPANIES, named - COMPANIES
