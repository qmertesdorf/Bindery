import pytest
from factory import specs


def test_spine_width_cream():
    assert specs.spine_width_in(120) == pytest.approx(0.30)


def test_cover_dimensions():
    w, h = specs.cover_dimensions_in(120)
    assert w == pytest.approx(0.125 + 6 + 0.30 + 6 + 0.125)  # 12.55
    assert h == pytest.approx(9.25)


def test_printing_cost():
    assert specs.printing_cost_usd(120) == pytest.approx(2.44)


def test_royalty():
    # 9.99 * 0.60 - 2.44 = 3.554, rounded to cents = 3.55
    assert specs.royalty_usd(9.99, 120) == pytest.approx(3.55)


def test_trim_constants():
    assert specs.TRIM_W_IN == 6
    assert specs.TRIM_H_IN == 9
    assert specs.BLEED_IN == 0.125
