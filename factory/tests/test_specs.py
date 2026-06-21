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


# --- WS4: verified KDP print geometry ---

@pytest.mark.parametrize("pages,gutter", [
    (24, 0.375), (150, 0.375),          # 24–150pp band
    (151, 0.5), (300, 0.5),             # 151–300pp band
    (301, 0.625), (500, 0.625),         # 301–500pp band
    (501, 0.75), (700, 0.75),           # 501–700pp band
    (701, 0.875), (828, 0.875),         # 701–828pp band
])
def test_gutter_by_page_count(pages, gutter):
    assert specs.gutter_in(pages) == pytest.approx(gutter)

def test_gutter_rejects_over_kdp_limit():
    with pytest.raises(ValueError):
        specs.gutter_in(829)

def test_outside_margin_with_and_without_bleed():
    assert specs.outside_margin_in(bleed=True) == pytest.approx(0.375)
    assert specs.outside_margin_in(bleed=False) == pytest.approx(0.25)

def test_interior_bleed_size():
    # +0.125 outside (width), +0.125 top & bottom (height); inside edge no bleed
    assert specs.interior_bleed_size_in(8.5, 8.5) == (8.625, 8.75)
    assert specs.interior_bleed_size_in() == (6.125, 9.25)

def test_min_pixels_for_dpi_targets_trim_plus_bleed():
    # 8.5x8.5 + 0.125 bleed -> 8.625in -> ceil(8.625*300) = 2588px (>2560 current)
    w, h = specs.interior_bleed_size_in(8.5, 8.5)
    assert specs.min_pixels_for_dpi(w) == 2588
    assert specs.DPI == 300

def test_print_art_px_sizes_for_the_larger_trim_plus_bleed_axis():
    # square art fills page+bleed; height (8.75 = trim + top&bottom bleed) is the
    # binding axis on 8.5x8.5 -> 2625px, above the old hardcoded 2560 (~293 DPI)
    assert specs.print_art_px(8.5, 8.5) == 2625
    assert specs.print_art_px(8.5, 8.5) > 2560
    # the larger of the two trim+bleed dims wins (here height) for any trim
    w, h = specs.interior_bleed_size_in(6.0, 9.0)
    assert specs.print_art_px(6.0, 9.0) == specs.min_pixels_for_dpi(max(w, h))

def test_spine_per_page_for_stock_matches_kdp_table():
    assert specs.spine_per_page_for_stock("cream") == pytest.approx(0.0025)
    assert specs.spine_per_page_for_stock("white") == pytest.approx(0.002252)
    assert specs.spine_per_page_for_stock("standard_color") == pytest.approx(0.002252)
    assert specs.spine_per_page_for_stock("premium_color") == pytest.approx(0.002347)

def test_spine_per_page_for_stock_rejects_unknown():
    with pytest.raises(ValueError):
        specs.spine_per_page_for_stock("glossy")

def test_premium_color_spine_thicker_than_standard():
    assert (specs.spine_per_page_for_stock("premium_color")
            > specs.spine_per_page_for_stock("standard_color"))
