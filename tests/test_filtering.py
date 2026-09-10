import yaml

from smithsonian_image_text.filtering import evaluate_candidate


def rules():
    with open("config/eligibility_rules.yaml", encoding="utf-8") as stream:
        return yaml.safe_load(stream)


def good_candidate(**overrides):
    row = {
        "object_id": "nmah_1",
        "media_id": "media:1",
        "source_url": "https://example.org/object/1",
        "media_url": "https://ids.si.edu/ids/deliveryService?id=X",
        "media_type": "Images",
        "metadata_rights": "CC0",
        "media_rights": "CC0",
        "unit_code": "NMAH",
        "title": "Scientific instrument",
        "description": "A brass instrument used for measurement.",
        "object_type": "Instrument",
        "date": "1890",
        "topics": "Science",
        "creator": None,
        "place": None,
        "culture": None,
        "alt_text": None,
        "media_description": None,
    }
    row.update(overrides)
    return row


def test_good_candidate_is_eligible():
    assert evaluate_candidate(good_candidate(), rules()).status == "eligible"


def test_metadata_cc0_does_not_override_restricted_media():
    decision = evaluate_candidate(
        good_candidate(media_rights="Usage conditions apply"), rules()
    )
    assert decision.status == "rejected"
    assert "NO_CC0_MEDIA" in decision.reasons


def test_sensitive_keyword_goes_to_review_not_auto_release():
    decision = evaluate_candidate(
        good_candidate(description="A funerary object with documented provenance."), rules()
    )
    assert decision.status == "review_required"
    assert decision.reasons == ("SENSITIVE_REVIEW",)


def test_sensitive_keyword_does_not_match_inside_normal_word():
    decision = evaluate_candidate(
        good_candidate(description="An engraved brass plate made in 1890."), rules()
    )
    assert decision.status == "eligible"


def test_nmai_is_review_required_by_unit_guardrail():
    decision = evaluate_candidate(good_candidate(unit_code="NMAI"), rules())
    assert decision.status == "review_required"


def test_unknown_rights_are_rejected():
    decision = evaluate_candidate(good_candidate(media_rights=None), rules())
    assert decision.status == "rejected"
    assert "RIGHTS_UNCLEAR" in decision.reasons


def test_conflicting_context_rights_are_quarantined():
    decision = evaluate_candidate(
        good_candidate(object_rights="Usage conditions apply; permission required"), rules()
    )
    assert decision.status == "review_required"
    assert "RIGHTS_CONTEXT_REVIEW" in decision.reasons


def test_context_cc0_does_not_create_false_rights_review():
    decision = evaluate_candidate(good_candidate(object_rights="CC0"), rules())
    assert decision.status == "eligible"
