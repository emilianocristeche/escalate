from app import classifier


def test_severity_p1_on_outage():
    assert classifier.classify_severity("Total outage, all customers down") == "P1"


def test_severity_p2_on_error():
    assert classifier.classify_severity("Login returns a 500 error") == "P2"


def test_severity_p4_on_howto():
    assert classifier.classify_severity("How do I export invoices?") == "P4"


def test_severity_defaults_to_p3():
    assert classifier.classify_severity("The colors look a bit off") == "P3"


def test_category_matches():
    assert classifier.classify_category("refund on my invoice") == "billing"
    assert classifier.classify_category("eSIM no signal") == "connectivity"
    assert classifier.classify_category("webhook endpoint down") == "api"
    assert classifier.classify_category("locked out, password reset") == "account"
    assert classifier.classify_category("just some feedback") == "general"


def test_confidence_true_when_both_axes_match():
    r = classifier.classify_with_confidence("Payments API 500 outage")
    assert r["confident"] is True  # severity (outage) + category (payments) both hit


def test_confidence_false_when_axis_defaults():
    # No severity keyword and no category keyword -> both default -> not confident.
    r = classifier.classify_with_confidence("The thing looks a little odd today")
    assert r["confident"] is False


def test_classify_combined():
    assert classifier.classify("Payments endpoint 500", "all charges fail") == {
        "severity": "P2",  # "500" is a P2 keyword
        "category": "billing",  # "payments"/"charges" -> billing
    }


def test_keywords_match_plurals():
    assert classifier.classify_severity("Multiple outages since this morning") == "P1"
    assert classifier.classify_severity("Two breaches reported") == "P1"
    assert classifier.classify_severity("Seeing timeouts on checkout") == "P2"
    assert classifier.classify_category("Duplicate charges on my card") == "billing"
    assert classifier.classify_category("Our webhooks stopped") == "api"


def test_keywords_respect_word_boundaries():
    # Substring matching used to fire on these ("down" in "download", "sim" in
    # "simple", "api" in "rapid", "500" in "1500").
    assert classifier.classify_severity("How to download the report") == "P4"
    assert classifier.classify_category("A simple rapid question") == "general"
    assert classifier.classify_severity("Imported 1500 contacts fine") == "P3"


def test_listed_inflections_still_match():
    assert classifier.classify_severity("The app crashed again") == "P2"
