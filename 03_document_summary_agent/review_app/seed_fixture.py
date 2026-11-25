"""The reviewer's wording for the seed: the profile decision, each fact's decision and each answer.

Every sentence here is the fictional reviewer's, written for the facts and questions of the
recorded run of PS26/4, and goes into the application only through its review routes.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SeedDecision:
    """One decision of the fictional reviewer on one fact of the document, in her words.

    ``paragraph`` and ``quote`` say which fact ``fact_id`` is, so that a new recording that words
    a fact differently is reported by what changed and not only by an identifier.
    """

    fact_id: str
    paragraph: str
    quote: str
    outcome: str
    reason: str
    amendment: str | None = None


@dataclass(frozen=True)
class SeedQuestion:
    """The reviewer's handling of one open question, found by the paragraph it is about.

    A question is either answered, with the answer and what it rests on, or accepted as an
    assumption in her words.
    """

    paragraph: str
    answer: str | None = None
    reason: str | None = None
    assumption: str | None = None


@dataclass(frozen=True)
class SeedProfile:
    """The reviewer's one decision on the firm profile, with the facts she was shown."""

    fact_ids: tuple[str, ...]
    outcome: str
    reason: str
    amendment: str | None = None


PROFILE = SeedProfile(
    fact_ids=(
        "fact:3ea55dfec196c112",
        "fact:5e3ea5fe0af13cf3",
        "fact:33cda8305e9f57c6",
        "fact:7678bf62b4d40a4b",
        "fact:8960216a3540d0ec",
        "fact:6493bf9915f4c712",
        "fact:0b7489f43a5963d5",
        "fact:98b11a93648d2406",
        "fact:7531942445b6e556",
        "fact:460ab6a8123c6350",
        "fact:a6dd7d8a6886b739",
        "fact:245c5a69de83b610",
    ),
    outcome="accept",
    reason=(
        "I read the profile against the firm table and the provider table. Harbour Mutual Bank, "
        "its type, customers and assets, both providers with their services and contract end "
        "dates, and the firm's own note on NimbusCloud all match the tables. The tables name no "
        "operational resilience senior manager, so the profile is right to say none is "
        "recorded; the firm has to fill that gap."
    ),
)
"""The firm profile as the recorded brief cites it, and the one decision on all of it."""

DECISIONS = (
    SeedDecision(
        "fact:a6e87b0ad0ddcc2a",
        "para:2.4",
        "A firm that becomes a small firm, or stops",
        "accept",
        "Paragraph 2.4 requires notice to the FSOA within 30 days when a firm becomes"
        " or stops being a small firm after 31 December 2026.",
    ),
    SeedDecision(
        "fact:1b2c61021f8314e7",
        "para:4.1",
        "Firms must identify their important business",
        "accept",
        "Paragraph 4.1 sets 31 March 2027 for identifying the important business "
        "services, and the quoted sentence says so in those words.",
    ),
    SeedDecision(
        "fact:72902ea32934ba5d",
        "para:4.2",
        "Firms must set an impact tolerance for each",
        "accept",
        "Paragraph 4.2 asks for an impact tolerance for each important business "
        "service by 31 March 2027, the same date as paragraph 4.1.",
    ),
    SeedDecision(
        "fact:b997e73f8e46b3dd",
        "para:4.2",
        "Impact tolerances must be set at the point at",
        "accept",
        "The second sentence of paragraph 4.2 sets the tolerance where harm becomes "
        "intolerable and rules out using the point of expected recovery. It carries "
        "no date of its own.",
    ),
    SeedDecision(
        "fact:5251e29da0c22974",
        "para:4.3",
        "The board must",
        "accept",
        "Paragraph 4.3 gives the board the decision on the list and its tolerances. "
        "It names no date.",
    ),
    SeedDecision(
        "fact:826c0459dc118dc6",
        "para:4.3",
        "must review both at least once every 12 months,",
        "accept",
        "The board also reviews both at least every 12 months, or sooner after a "
        "material change to the business, as the quote says.",
    ),
    SeedDecision(
        "fact:fb1e0f36fec23341",
        "para:4.5",
        "Firms must keep a record of how they identified",
        "accept",
        "Paragraph 4.5 requires a record of how each service was identified and each "
        "tolerance set. I read it as a standing duty with no date.",
    ),
    SeedDecision(
        "fact:e7eed3afab939275",
        "para:4.5",
        "must provide it to the FSOA on request within",
        "accept",
        "The same paragraph sends that record to the FSOA on request within 10 "
        "business days, and the quote carries both parts.",
    ),
    SeedDecision(
        "fact:57e77ba5d39efd2f",
        "para:5.1",
        "Firms must map the people, processes,",
        "accept",
        "Paragraph 5.1 requires mapping of the people, processes, technology, "
        "facilities and information behind each service, those from third parties "
        "included, by 31 March 2027.",
    ),
    SeedDecision(
        "fact:b43350802e8e6109",
        "para:5.2",
        "Mapping must be detailed enough to identify",
        "accept",
        "Paragraph 5.2 sets the standard for the mapping: detailed enough to show "
        "single points of failure and concentrations of risk.",
    ),
    SeedDecision(
        "fact:e2c99a761a195812",
        "para:5.3",
        "Firms must test their ability to remain within",
        "accept",
        "Paragraph 5.3 requires testing against severe but plausible scenarios. The "
        "dates in the same paragraph are separate facts further down.",
    ),
    SeedDecision(
        "fact:abfe4241e305bf64",
        "para:5.3",
        "The first round of scenario testing must be",
        "accept",
        "The first round of scenario testing is due by 30 September 2027, as quoted.",
    ),
    SeedDecision(
        "fact:117ea1138972447d",
        "para:5.3",
        "testing must be repeated at least once a year",
        "accept",
        "After the first round, testing repeats at least once a year, as the quote says.",
    ),
    SeedDecision(
        "fact:7314cf2cddbd4085",
        "para:5.4",
        "Scenarios must include, at a minimum, the",
        "accept",
        "Paragraph 5.4 names three scenarios the testing has to include: a material "
        "provider failing, a cyber attack and the loss of a key site.",
    ),
    SeedDecision(
        "fact:d41a1005caad65c4",
        "para:5.5",
        "the firm must record the",
        "accept",
        "Paragraph 5.5 applies where testing shows the firm cannot stay within a "
        "tolerance, and the first duty then is to record the vulnerability.",
    ),
    SeedDecision(
        "fact:8b9774deb8168b9d",
        "para:5.5",
        "set out the actions it will take to address",
        "accept",
        "The second duty in paragraph 5.5 is to set out the actions the firm will "
        "take to address the vulnerability.",
    ),
    SeedDecision(
        "fact:b5a15a6e828cac35",
        "para:5.5",
        "report the vulnerability to the board at its",
        "accept",
        "The third duty in paragraph 5.5 is to report the vulnerability to the board "
        "at its next meeting.",
    ),
    SeedDecision(
        "fact:5965843b4c13b28f",
        "para:6.1",
        "Firms must maintain a register of all material",
        "accept",
        "Paragraph 6.1 asks for a register of all material third-party providers by 31 March 2027.",
    ),
    SeedDecision(
        "fact:ff5e79e13df2b944",
        "para:6.1",
        "The register must record, for each provider,",
        "accept",
        "The register holds, for each provider, the services it supports, the data it"
        " holds, its location and its contract expiry date, as quoted.",
    ),
    SeedDecision(
        "fact:3fee39f5c9346e49",
        "para:6.2",
        "Firms must notify the FSOA at least 60 days",
        "accept",
        "Paragraph 6.2 requires notice to the FSOA at least 60 days before a new "
        "arrangement with a material provider, or a material change to an existing "
        "one.",
    ),
    SeedDecision(
        "fact:4d4dd998b30ccfd0",
        "para:6.3",
        "Contracts with material third-party providers",
        "accept",
        "Paragraph 6.3 lists three contract terms, and this is the first: rights of "
        "access and audit for the firm and the FSOA.",
    ),
    SeedDecision(
        "fact:e70573c601ec3cb0",
        "para:6.3",
        "require the provider to report incidents to the",
        "accept",
        "The second contract term in paragraph 6.3 is that the provider reports "
        "incidents to the firm without undue delay.",
    ),
    SeedDecision(
        "fact:0399157e26823787",
        "para:6.3",
        "set out how the service will be transferred or",
        "accept",
        "The third contract term is how the service is transferred or wound down if "
        "the arrangement ends.",
    ),
    SeedDecision(
        "fact:c35be1a6472b8916",
        "para:6.4",
        "Firms must have a documented exit plan for each",
        "accept",
        "Paragraph 6.4 requires a documented exit plan for each material third-party provider.",
    ),
    SeedDecision(
        "fact:825384d261a8c4c2",
        "para:6.4",
        "must test each exit plan at least once every",
        "accept",
        "The same paragraph requires each exit plan to be tested at least once every two years.",
    ),
    SeedDecision(
        "fact:093fb7526a1f202e",
        "para:6.5",
        "it must assess the concentration risk and",
        "accept",
        "Paragraph 6.5 applies when one material provider serves more than one "
        "important business service. The firm assesses the concentration risk and "
        "explains to the board how it would manage that provider's failure, and the "
        "fact lists both duties.",
    ),
    SeedDecision(
        "fact:8b8c4ec5a6525be1",
        "para:6.6",
        "Firms remain fully responsible for meeting",
        "accept",
        "Paragraph 6.6 keeps the firm responsible for its regulatory obligations when"
        " it outsources. My answer to the open question on this paragraph gives my "
        "reading.",
    ),
    SeedDecision(
        "fact:be1caf14c1da80d4",
        "para:7.1",
        "Firms must submit an initial notification to",
        "accept",
        "Paragraph 7.1 gives 4 hours from classifying the incident as major, and I "
        "read the quoted words in the paragraph itself.",
    ),
    SeedDecision(
        "fact:8dcce3936b557550",
        "para:7.1",
        "in any case no later than 24 hours after the",
        "accept",
        "Paragraph 7.1 also sets an outer limit of 24 hours after the incident is "
        "first detected, as quoted.",
    ),
    SeedDecision(
        "fact:98b628305fb9d4a4",
        "para:7.2",
        "Firms must submit an intermediate report within",
        "accept",
        "Paragraph 7.2 gives 72 hours from the initial notification, as quoted.",
    ),
    SeedDecision(
        "fact:80507750f54be85e",
        "para:7.3",
        "Firms must submit a final report within 30",
        "accept",
        "Paragraph 7.3 gives 30 business days from the incident being resolved, as quoted.",
    ),
    SeedDecision(
        "fact:ad8c659e73a33138",
        "para:7.3",
        "The final report must include a root-cause",
        "accept",
        "Paragraph 7.3 also asks for a root-cause analysis and the lessons learned in"
        " the final report.",
    ),
    SeedDecision(
        "fact:5f2e1907bf090f40",
        "para:7.4",
        "the firm remains responsible for reporting",
        "accept",
        "Paragraph 7.4 leaves the reporting with the firm when a third-party provider"
        " causes the incident. I read the whole sentence, not only the quoted words.",
    ),
    SeedDecision(
        "fact:3e191bfed2859ff8",
        "para:8.1",
        "Firms must name a senior manager who is",
        "accept",
        "Paragraph 8.1 requires a named senior manager for operational resilience by "
        "31 January 2027. The firm table names none today, which the profile already "
        "says.",
    ),
    SeedDecision(
        "fact:716a41d53d33a74e",
        "para:8.1",
        "must notify the FSOA of that person's name",
        "accept",
        "The firm tells the FSOA the senior manager's name within 14 days of "
        "appointing them, as quoted from paragraph 8.1.",
    ),
    SeedDecision(
        "fact:269db9e38b9a5767",
        "para:8.2",
        "Firms must complete an annual self-assessment",
        "accept",
        "Paragraph 8.2 requires an annual self-assessment of operational resilience.",
    ),
    SeedDecision(
        "fact:250cf8f18032d057",
        "para:8.2",
        "which must be",
        "accept",
        "Each self-assessment goes to the board for its decision, as the quoted clause of "
        "paragraph 8.2 says.",
    ),
    SeedDecision(
        "fact:0a2b30a4a8c41913",
        "para:8.2",
        "The first self-assessment must be completed and",
        "accept",
        "The first self-assessment has to be completed and passed by the board by "
        "31 March 2028, as quoted.",
    ),
    SeedDecision(
        "fact:99303cab809258b0",
        "para:8.3",
        "The self-assessment must cover the firm's",
        "accept",
        "Paragraph 8.3 lists what the self-assessment covers: services, tolerances, "
        "mapping, test results, vulnerabilities, remediation actions and third-party "
        "management.",
    ),
    SeedDecision(
        "fact:596e5d53ac458e25",
        "para:8.5",
        "Firms must keep each self-assessment for at",
        "accept",
        "Paragraph 8.5 requires each self-assessment to be kept for at least 5 years.",
    ),
    SeedDecision(
        "fact:db47e4baf57503e7",
        "para:8.5",
        "provide it to the FSOA on",
        "accept",
        "Each self-assessment also goes to the FSOA on request, as paragraph 8.5 says.",
    ),
    SeedDecision(
        "fact:cdda2242bc01aed4",
        "para:9.1",
        "Small firms, as defined in paragraph 2.3, may",
        "amend",
        "Paragraph 9.1 gives small firms until 31 March 2028 for four requirements. "
        "The quote says may, and the fact's own wording said must, so I have reworded"
        " the fact to follow the paragraph.",
        "Small firms, as defined in paragraph 2.3, may meet the requirements in "
        "paragraphs 4.1, 4.2, 5.1 and 6.1 by 31 March 2028 instead of 31 March 2027.",
    ),
    SeedDecision(
        "fact:7b29b4853fda5542",
        "para:9.3",
        "contracts with material third-party providers",
        "accept",
        "Paragraph 9.3 gives contracts in place before 1 January 2027 until their "
        "next renewal or 31 December 2028, whichever is earlier, to meet paragraph "
        "6.3. It applies to all firms.",
    ),
    SeedDecision(
        "fact:c0ae524eee27a0fb",
        "para:9.4",
        "The transitional arrangements do not apply to",
        "accept",
        "Paragraph 9.4 takes the incident reporting requirements in section 7 out of "
        "the transitional arrangements, so they apply from 1 January 2027.",
    ),
    SeedDecision(
        "fact:77db137b5f81e697",
        "para:9.4",
        "or to the requirement to name a senior manager",
        "accept",
        "Paragraph 9.4 also takes the senior manager requirement in paragraph 8.1 out"
        " of the transitional arrangements, so it applies to all firms from 1 January"
        " 2027.",
    ),
)
"""The reviewer's decision on each fact of the document the recorded brief cites."""

QUESTIONS = (
    SeedQuestion(
        "para:6.6",
        answer=(
            "Yes. Paragraph 6.6 places an obligation on the firm: it stays responsible for its "
            "regulatory obligations when it outsources a service, and outsourcing does not "
            "transfer that responsibility."
        ),
        reason=(
            "I read paragraph 6.6 with paragraphs 6.3 to 6.5. It has no must, but its second "
            "sentence says outsourcing a service does not transfer the firm's responsibility "
            "for it."
        ),
    ),
    SeedQuestion(
        "para:7.4",
        assumption=(
            "I am treating paragraph 7.4 as an obligation on the firm: when a provider causes a "
            "major incident, the firm still reports it. I have not checked this with the FSOA."
        ),
    ),
    SeedQuestion(
        "para:9.1",
        answer=(
            "No. Paragraph 9.1 places no obligation on the firm. It lets small firms meet four "
            "requirements by 31 March 2028 instead of 31 March 2027."
        ),
        reason=(
            "The paragraph says may and gives a later date. The duties themselves sit in "
            "paragraphs 4.1, 4.2, 5.1 and 6.1."
        ),
    ),
    SeedQuestion(
        "para:9.4",
        answer=(
            "Yes. Paragraph 9.4 places obligations on every firm: the incident reporting "
            "requirements in section 7 and the senior manager requirement in paragraph 8.1 "
            "apply from 1 January 2027, with no transitional relief."
        ),
        reason=(
            "The paragraph says the transitional arrangements do not apply to them and that "
            "they apply to all firms from 1 January 2027. I read the two facts taken from it "
            "as one decision."
        ),
    ),
)
"""The reviewer's answer, or the assumption she accepts, for each open question on the brief."""
