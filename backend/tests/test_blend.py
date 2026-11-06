"""Provisional market blend: estimates are anchored to the no-vig market, and the raw model is kept."""
from types import SimpleNamespace

import pytest

from courtside.config import get_settings
from courtside.models import utcnow
from courtside.services.analysis import blend_with_market, evaluate_prop

CTX = {"player_reasons": [], "factors": [], "risks": [], "data_quality": {}}


def snap(over=-110, under=-110):
    return SimpleNamespace(over_price=over, under_price=under, fetched_at=utcnow(), source="test")


@pytest.fixture
def weight(monkeypatch):
    def set_weight(w):
        monkeypatch.setattr(get_settings(), "market_blend_weight", w)
    return set_weight


def test_blend_endpoints_and_midpoint():
    assert blend_with_market(0.7, 0.5, 1.0) == pytest.approx(0.7)
    assert blend_with_market(0.7, 0.5, 0.0) == pytest.approx(0.5)
    assert 0.5 < blend_with_market(0.7, 0.5, 0.3) < 0.6


def test_weight_one_leaves_model_unchanged(weight):
    weight(1.0)
    e = evaluate_prop(snap(), "under", 0.35, 0.65, 0.0, 0.5, CTX)
    assert e.p_win == pytest.approx(0.65)
    assert "market_blend" not in e.data_quality


def test_blend_shrinks_ev_and_records_raw_model(weight):
    weight(1.0)
    raw = evaluate_prop(snap(), "under", 0.35, 0.65, 0.0, 0.5, CTX)
    weight(0.3)
    e = evaluate_prop(snap(), "under", 0.35, 0.65, 0.0, 0.5, CTX)
    assert 0.5 < e.p_win < raw.p_win
    assert e.ev < raw.ev
    assert e.data_quality["market_blend"] == {"weight": 0.3, "raw_model_prob": 0.65, "market_prob": 0.5,
                                              "raw_model_ev": pytest.approx(raw.ev, abs=1e-4)}
    assert any("Provisional blend" in f for f in e.factors)


def test_blend_can_remove_a_pick_the_raw_model_would_make(weight):
    weight(1.0)
    assert evaluate_prop(snap(), "under", 0.42, 0.58, 0.0, 0.5, CTX).eligible
    weight(0.3)
    assert not evaluate_prop(snap(), "under", 0.42, 0.58, 0.0, 0.5, CTX).eligible


def test_gap_guard_still_uses_the_raw_model(weight):
    weight(0.3)
    e = evaluate_prop(snap(), "under", 0.2, 0.8, 0.0, 0.5, CTX)
    assert any("disagrees" in r for r in e.reasons)


def test_one_sided_quote_cannot_be_blended(weight):
    weight(0.3)
    e = evaluate_prop(snap(under=None), "over", 0.65, 0.35, 0.0, None, CTX)
    assert not e.eligible
    assert any("anchor" in r for r in e.reasons)
