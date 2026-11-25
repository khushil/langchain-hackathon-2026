"""The register's starting rule: every unit of every regulation made an obligation or not, by code.

The engine lane owns this file after the contract is committed. It may refine the rule, and
then it raises ``RULE``'s version and states the new counts beside the old ones in its report.
Applicability comes from the firm profile only; where the text turns on something the profile
does not state, the obligation stays on the record as undetermined, for a person to settle.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from assessment.profile import profile_digest
from assessment.records import (
    Addressee,
    FirmProfile,
    Obligation,
    Population,
    Register,
    UnitDisposition,
)
from assessment.texts import TextIndex
from context.regulations.model import RegulationRead, RegUnit

RULE = "register-rule.v1"

NOT_OPERATIVE = {
    "citation": "a citation of the act's legal basis, which binds no one",
    "recital": "a recital, which explains the act and binds no one",
    "footnote": "a footnote, which gives a reference",
    "final_formula": "the closing formula of the act",
    "article_lead": "the lead-in of a list whose points are read as their own units",
    "annex_lead": "the lead-in of an annex, read through the article that refers to it",
    "annex_body": "an annex, read through the article that refers to it",
    "annex_point": "a point of an annex, read through the article that refers to it",
    "principle_overview": "the overview of a principle, assessed through its sub-principles",
    "principle_statement": "a principle's statement, assessed through its sub-principles",
}

_SCOPE_ARTICLES = {"art:1", "art:2", "art:3"}
_FINAL_HEADING = re.compile(
    r"^(Amendments? |Entry into force|Transitional|Repeal|Review|Evaluation|Exercise of the "
    r"delegation|Committee procedure|Delegated acts|Implementing acts)",
    re.IGNORECASE,
)
_MARKER = {
    "DORA": re.compile(r"\bshall\b"),
    "AI-ACT": re.compile(r"\bshall\b"),
    "SS1-23": re.compile(r"\b(should|expects?|expected)\b"),
}
_ADDRESSEES: list[tuple[Addressee, re.Pattern[str]]] = [
    ("deployer_high_risk", re.compile(r"deployers? of (a )?high-risk AI systems?", re.I)),
    ("provider_high_risk", re.compile(r"providers? of (a )?high-risk AI systems?", re.I)),
    ("provider_general_purpose", re.compile(r"providers? of general-purpose AI models?", re.I)),
    ("management_body", re.compile(r"management bod(y|ies)", re.I)),
    ("financial_entity", re.compile(r"financial entit(y|ies)", re.I)),
    ("ict_third_party_provider", re.compile(r"ICT third-party service providers?", re.I)),
    ("deployer", re.compile(r"\bdeployers?\b", re.I)),
    ("provider", re.compile(r"(?<!service )\bproviders?\b", re.I)),
    ("other_operator", re.compile(r"\b(importers?|distributors?|authorised representatives?)\b")),
    ("member_state", re.compile(r"\bMember States?\b")),
    ("commission", re.compile(r"\b(the Commission|AI Office)\b")),
    (
        "authority",
        re.compile(
            r"(competent|market surveillance|notifying|national|supervisory) authorit|notified "
            r"bod|\bthe Board\b|\bESAs?\b|\bEBA\b|\bESMA\b|\bEIOPA\b|Lead Overseer|Joint "
            r"Committee|Oversight Forum|scientific panel",
            re.I,
        ),
    ),
    ("firm", re.compile(r"\b(firms?|the PRA expects|board|senior management|SMFs?)\b", re.I)),
]
_OTHER_FINANCIAL_CLASSES = re.compile(
    r"\b(payment institutions?|electronic money institutions?|investment firms?|crypto-asset "
    r"service providers?|central securities depositor(y|ies)|central counterpart(y|ies)|trading "
    r"venues?|trade repositor(y|ies)|insurance|reinsurance|credit rating agenc(y|ies)|"
    r"crowdfunding|securitisation repositor(y|ies)|institutions for occupational retirement|"
    r"managers of alternative investment funds|management companies|data reporting service)\b",
    re.I,
)
_UNSTATED = re.compile(r"identified in accordance with", re.I)
_NOT_MICRO = re.compile(r"other than microenterprises", re.I)
_MICRO_ONLY = re.compile(r"\bmicroenterprises?\b", re.I)
_DORA_FE_CHAPTERS = ("chapter:II", "chapter:III", "chapter:IV", "section:V.I")
_AI_FEATURES = {
    "interact directly with natural persons": "interacts_with_natural_persons",
    "generating synthetic": "generates_synthetic_content",
}
_AI_DATES = (
    (
        "chapter:I",
        "2025-02-02",
        "Article 113, point (a): Chapters I and II apply from 2 February 2025",
    ),
    (
        "chapter:II",
        "2025-02-02",
        "Article 113, point (a): Chapters I and II apply from 2 February 2025",
    ),
    (
        "section:III.4",
        "2025-08-02",
        "Article 113, point (b): Chapter III, Section 4, applies from 2 August 2025",
    ),
    ("chapter:V", "2025-08-02", "Article 113, point (b): Chapter V applies from 2 August 2025"),
    ("chapter:VII", "2025-08-02", "Article 113, point (b): Chapter VII applies from 2 August 2025"),
    ("chapter:XII", "2025-08-02", "Article 113, point (b): Chapter XII applies from 2 August 2025"),
)
_APPLIES_FROM = {
    "DORA": ("2025-01-17", "Article 64: the Regulation applies from 17 January 2025"),
    "AI-ACT": ("2026-08-02", "Article 113: the Regulation applies from 2 August 2026"),
    "SS1-23": ("2024-05-17", "Paragraph 1.5: the policy comes into effect on 17 May 2024"),
}


@dataclass(frozen=True)
class _Applicability:
    applies: bool | None
    applies_to: list[str]
    reason: str


def _not_an_obligation(key: str, unit: RegUnit) -> str | None:
    if unit.kind in NOT_OPERATIVE:
        return NOT_OPERATIVE[unit.kind]
    article = unit.anchor.split("/")[0]
    if key != "SS1-23" and article in _SCOPE_ARTICLES:
        return "sets the act's subject, scope or definitions, which the register applies"
    if _FINAL_HEADING.match(unit.heading or ""):
        return f"a final provision ({unit.heading}) that binds no firm"
    if not _MARKER[key].search(unit.text):
        return "holds no word of obligation (shall, should, expects)"
    return None


def _subject(key: str, unit: RegUnit) -> str:
    found = _MARKER[key].search(unit.text)
    return unit.text[: found.start()] if found else unit.text


def _addressees(key: str, unit: RegUnit, subject: str) -> list[Addressee]:
    if key == "SS1-23":
        return ["firm"]
    hits = []
    for name, pattern in _ADDRESSEES:
        for match in pattern.finditer(subject):
            hits.append((match.end(), name))
    found: list[Addressee] = []
    for _, name in sorted(hits, reverse=True):
        if name not in found and name != "firm":
            found.append(name)
    if key == "AI-ACT" and any(
        p.startswith("chapter:III") or p.startswith("section:III") for p in unit.parents
    ):
        found = [
            {"deployer": "deployer_high_risk", "provider": "provider_high_risk"}.get(n, n)  # type: ignore[misc]
            for n in found
        ]
    if not found and key == "AI-ACT" and re.search(r"shall be prohibited", unit.text):
        return ["every_operator"]
    if not found and key == "DORA" and any(p in _DORA_FE_CHAPTERS for p in unit.parents):
        return ["financial_entity"]
    return list(dict.fromkeys(found)) or ["unclear"]


def _roles(profile: FirmProfile, key: str) -> dict[str, list[str]]:
    held: dict[str, list[str]] = {}
    for entity in profile.entities:
        for role in entity.roles:
            if role.regulation == key:
                held.setdefault(role.role, []).append(entity.name)
    return held


def _applicability(
    key: str, unit: RegUnit, subject: str, binds: list[Addressee], profile: FirmProfile
) -> _Applicability:
    held = _roles(profile, key)
    if key == "DORA":
        held.setdefault("management_body", held.get("financial_entity", []))
    if key == "AI-ACT":
        held.setdefault("every_operator", sorted({n for v in held.values() for n in v}))
    matched = sorted({name for b in binds for name in held.get(b, [])})
    words = ", ".join(b.replace("_", " ") for b in binds)
    if binds == ["unclear"]:
        return _Applicability(
            False,
            [],
            "names no addressee before its word of obligation, so the rule reads it as binding "
            "none of the firm's roles; a person may reopen it",
        )
    if not matched:
        return _Applicability(False, [], f"binds {words}, a role no entity of the firm holds")
    if (
        key == "DORA"
        and _OTHER_FINANCIAL_CLASSES.search(subject)
        and "credit institution" not in subject
    ):
        return _Applicability(
            False, [], "binds a class of financial entity other than a credit institution"
        )
    if key == "DORA" and _MICRO_ONLY.search(subject) and not _NOT_MICRO.search(subject):
        if not any(e.microenterprise is False for e in profile.entities):
            return _Applicability(
                None, [], "binds microenterprises, and the profile does not state the entity's size"
            )
        return _Applicability(
            False, [], "binds microenterprises, which the profile states the entity is not"
        )
    if (
        key == "DORA"
        and _NOT_MICRO.search(subject)
        and not any(e.microenterprise is False for e in profile.entities)
    ):
        return _Applicability(
            None, [], "excludes microenterprises, and the profile does not state the entity's size"
        )
    if key == "DORA" and _UNSTATED.search(subject):
        return _Applicability(
            None,
            [],
            "turns on the entity's size or on a choice of the competent authority, which the "
            "profile does not state",
        )
    if key == "AI-ACT" and unit.anchor.startswith("art:50/"):
        for phrase, feature in _AI_FEATURES.items():
            if phrase in unit.text:
                values = {getattr(s, feature) for s in profile.ai_systems}
                if True in values:
                    return _Applicability(
                        True, matched, f"names AI systems that {phrase}, and the profile holds one"
                    )
                if None in values:
                    return _Applicability(
                        None, [], f"names AI systems {phrase}, which the profile leaves unsettled"
                    )
        return _Applicability(False, [], "names a kind of AI system the profile holds none of")
    if (
        key == "AI-ACT"
        and "provider" in binds
        and not (unit.anchor in ("art:4",) or unit.anchor.startswith(("art:4/", "art:50/")))
    ):
        return _Applicability(
            False,
            [],
            "binds providers, and the firm provides only the chat assistant, which Article 50 "
            "governs",
        )
    if (
        key == "AI-ACT"
        and re.search(r"that are public authorities|bodies governed by public law", subject)
        and "deployer_high_risk" not in binds
    ):
        return _Applicability(
            False, [], "binds deployers that are public authorities, which the firm is not"
        )
    return _Applicability(
        True, matched, f"binds {words}, a role the profile gives {', '.join(matched)}"
    )


def _applies_from(key: str, unit: RegUnit) -> tuple[str, str]:
    if key == "AI-ACT":
        for parent, day, basis in _AI_DATES:
            if parent in unit.parents:
                return day, basis
    return _APPLIES_FROM[key]


def _obligation(key: str, read: RegulationRead, unit: RegUnit, profile: FirmProfile) -> Obligation:
    subject = _subject(key, unit)
    binds = _addressees(key, unit, subject)
    verdict = _applicability(key, unit, subject, binds, profile)
    day, basis = _applies_from(key, unit)
    return Obligation(
        obligation_id=f"{key} {unit.anchor}",
        regulation=key,  # type: ignore[arg-type]
        anchor=unit.anchor,
        label=unit.label,
        parents=list(unit.parents),
        points=[p.strip("().") for p in unit.points],
        provision_words=unit.text,
        binds=binds,
        binds_words=subject.strip()[-200:] or unit.text[:200],
        applies_from=day,
        applies_from_basis=basis,
        applies=verdict.applies,
        applies_to=verdict.applies_to,
        reason=verdict.reason,
        rule=RULE,
    )


def build_register(texts: TextIndex, profile: FirmProfile) -> Register:
    """Turn every unit of every regulation into an obligation or a recorded non-obligation.

    Args:
        texts: The regulations and the corpus, read whole.
        profile: The firm's stated profile.

    Returns:
        The register, with one disposition per unit and the population of each regulation.
    """
    obligations: list[Obligation] = []
    dispositions: list[UnitDisposition] = []
    populations: list[Population] = []
    for key, read in texts.regulations.items():
        made: list[Obligation] = []
        for unit in read.items:
            reason = _not_an_obligation(key, unit)
            if reason is None:
                made.append(_obligation(key, read, unit, profile))
                reason = "read as an obligation"
            outcome = "obligation" if reason == "read as an obligation" else "not an obligation"
            dispositions.append(
                UnitDisposition(regulation=key, anchor=unit.anchor, outcome=outcome, reason=reason)  # type: ignore[arg-type]
            )
        obligations.extend(made)
        populations.append(
            Population(
                regulation=key,  # type: ignore[arg-type]
                units=len(read.items),
                obligations=len(made),
                not_obligations=len(read.items) - len(made),
                applicable=sum(o.applies is True for o in made),
                not_applicable=sum(o.applies is False for o in made),
                undetermined=sum(o.applies is None for o in made),
            )
        )
    return Register(
        corpus=profile.corpus,
        profile_digest=profile_digest(profile),
        regulation_digests={k: r.source.digest for k, r in texts.regulations.items()},
        rule=RULE,
        obligations=obligations,
        dispositions=dispositions,
        populations=populations,
    )
