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


def test_cover_dimensions_custom_trim():
    # 5.5x8.5 at 150pp: spine = 150*0.0025 = 0.375
    w, h = specs.cover_dimensions_in(150, trim_w=5.5, trim_h=8.5)
    assert w == pytest.approx(0.125 + 5.5 + 0.375 + 5.5 + 0.125)  # 11.625
    assert h == pytest.approx(8.5 + 0.25)                          # 8.75


def test_cover_dimensions_defaults_unchanged():
    # default trim still 6x9 for journals
    w, h = specs.cover_dimensions_in(120)
    assert w == pytest.approx(12.55) and h == pytest.approx(9.25)


def test_white_spine_is_thinner_than_cream():
    assert specs.spine_per_page("picture") < specs.spine_per_page("journal")


def test_cover_dimensions_take_per_page():
    cream = specs.cover_dimensions_in(40, 8.5, 8.5, per_page=specs.SPINE_PER_PAGE_IN)
    white = specs.cover_dimensions_in(40, 8.5, 8.5,
                                      per_page=specs.SPINE_PER_PAGE_WHITE_IN)
    assert white[0] < cream[0]  # thinner spine -> narrower wrap


def test_colour_print_costs_more_than_bw():
    assert specs.printing_cost_usd(40, colour=True) > specs.printing_cost_usd(40)
