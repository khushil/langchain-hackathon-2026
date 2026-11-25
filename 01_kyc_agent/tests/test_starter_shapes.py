"""The starter's shapes stay as the starter has them, and the engine reads into them."""

from context.extraction import ApplicantRead
from context.screening import MATCH_THRESHOLD
from tools import screening
from utils.nodes import CustomerProfile
from utils.state import MyAgentState


def test_the_starters_profile_has_its_five_fields_and_the_engines_reading_covers_each():
    fields = set(CustomerProfile.model_fields)
    assert fields == {"full_name", "date_of_birth", "nationality", "occupation", "source_of_funds"}
    assert fields <= set(ApplicantRead.model_fields)


def test_the_starters_descriptions_of_the_fields_are_unchanged():
    fields = CustomerProfile.model_fields
    assert fields["full_name"].description == "The customer's full name, exactly as written"
    assert fields["date_of_birth"].description == "Date of birth in YYYY-MM-DD format"


def test_the_engines_screening_uses_the_starters_measure_and_threshold():
    assert MATCH_THRESHOLD is screening.MATCH_THRESHOLD
    assert screening.MATCH_THRESHOLD == 0.85
    assert round(screening.name_similarity("Dmitri Volkonsky", "Dmitry Volkonskiy"), 2) == 0.91


def test_the_starters_hits_have_the_starters_shape():
    sanctions = screening.check_sanctions("Dmitri Volkonsky", "1975-09-11")
    assert sanctions == [
        {
            "list": "sanctions",
            "matched_name": "Dmitry Volkonskiy",
            "score": 0.91,
            "date_of_birth_matches": True,
            "details": "Karvonia arms embargo",
        }
    ]
    assert (
        screening.check_pep("Viktor Harlan")[0]["details"] == "Deputy Minister of Finance, Valdoria"
    )


def test_the_starters_state_keeps_its_keys():
    assert set(MyAgentState.__annotations__) >= {
        "customer_id",
        "application",
        "profile",
        "screening_hits",
        "risk_level",
        "risk_reasons",
        "decision",
        "reviewer",
        "reviewer_notes",
        "decision_memo",
    }
