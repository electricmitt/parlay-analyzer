import pytest

from courtside import odds_math as om


def test_american_decimal_roundtrip():
    assert om.american_to_decimal(-110) == pytest.approx(1.909090, rel=1e-5)
    assert om.american_to_decimal(150) == pytest.approx(2.5)
    for a in (-250, -110, 100, 120, 450):
        assert om.decimal_to_american(om.american_to_decimal(a)) == a


def test_invalid_odds():
    with pytest.raises(ValueError):
        om.american_to_decimal(50)
    with pytest.raises(ValueError):
        om.decimal_to_american(1.0)


def test_spec_example_ev_and_fair_odds():
    # 64% at -110 -> EV +22.2% per unit; fair odds -178 (the illustrative example in the brief)
    assert om.expected_value(0.64, -110) == pytest.approx(0.2218, abs=1e-4)
    assert om.prob_to_american(0.64) == -178


def test_no_vig_and_margin():
    o, u = om.no_vig_two_way(-110, -110)
    assert o == pytest.approx(0.5) and u == pytest.approx(0.5)
    assert om.book_margin(-110, -110) == pytest.approx(0.04762, abs=1e-4)
    o, u = om.no_vig_two_way(-150, 130)
    assert o + u == pytest.approx(1.0)
    assert o > 0.5


def test_ev_breakeven_is_zero():
    p = om.implied_prob(-110)
    assert om.expected_value(p, -110) == pytest.approx(0.0, abs=1e-12)


def test_push_ev_and_kelly():
    assert om.expected_value_with_push(0.5, 0.1, 100) == pytest.approx(0.5 - 0.4)
    assert om.kelly_fraction(0.5, -110) == 0.0
    assert om.kelly_fraction(0.6, 100) == pytest.approx(0.2)


def test_profit_units():
    assert om.profit_units("win", -110) == pytest.approx(0.90909, rel=1e-4)
    assert om.profit_units("loss", -110) == -1
    assert om.profit_units("push", -110) == 0
    assert om.profit_units("void", 200) == 0
