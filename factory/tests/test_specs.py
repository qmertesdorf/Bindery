import pytest
from factory import specs


def test_spine_width_cream():
    assert specs.spine_width_in(120) == pytest.approx(0.30)


def test_cover_dimensions():
    w, h = specs.cover_dimensions_in(120)
    assert w == pytest.approx(0.125 + 6 + 0.30 + 6 + 0.125)  # 12.55
    assert h == pytest.approx(9.25)


def test_printing_cost():
    # 0.85 fixed + 120 * 0.012 = 2.29
    assert specs.printing_cost_usd(120) == pytest.approx(2.29)


def test_royalty():
    # 9.99 * 0.60 - 2.29 = 3.704, rounded to cents = 3.70
    assert specs.royalty_usd(9.99, 120) == pytest.approx(3.70)


def test_trim_constants():
    assert specs.TRIM_W_IN == 6
    assert specs.TRIM_H_IN == 9
    assert specs.BLEED_IN == 0.125
