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
