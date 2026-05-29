from src.engine.orchestrator import _numeric_magnitude_ok


def test_numeric_missing_unit_returns_false():
    req = "Minimum 16 GB DDR5 RAM"
    evidence = "This product has a fast processor and integrated graphics"
    assert _numeric_magnitude_ok(req, evidence) is False


def test_numeric_unit_present_and_sufficient():
    req = "Minimum 16 GB DDR5 RAM"
    evidence = "We provide 16 GB DDR5 RAM at 4800 MT/s"
    assert _numeric_magnitude_ok(req, evidence) is True


def test_numeric_unit_present_but_lower_value():
    req = "Minimum 16 GB DDR5 RAM"
    evidence = "We include 8 GB DDR5 memory"
    assert _numeric_magnitude_ok(req, evidence) is False
