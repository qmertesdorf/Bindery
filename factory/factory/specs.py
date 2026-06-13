"""KDP layout and economics math. Pure functions, no I/O."""

TRIM_W_IN = 6.0
TRIM_H_IN = 9.0
BLEED_IN = 0.125
SPINE_PER_PAGE_IN = 0.0025          # cream paper
SPINE_PER_PAGE_WHITE_IN = 0.002252  # white / colour stock (thinner)
ROYALTY_RATE = 0.60                 # 60% for >= $9.99 paperback
PRINT_FIXED_USD = 0.85              # US B&W fixed charge (KDP US, 110+ pages)
PRINT_PER_PAGE_USD = 0.012          # US B&W per-page
# Rough colour-print estimate (verify per-book in KDP's calculator):
PRINT_COLOUR_FIXED_USD = 1.00
PRINT_COLOUR_PER_PAGE_USD = 0.07

# Interior margins (no-bleed interior). Inside (gutter) larger for binding.
MARGIN_INSIDE_IN = 0.5
MARGIN_OUTSIDE_IN = 0.375
MARGIN_TOPBOTTOM_IN = 0.5


def spine_per_page(book_type: str = "journal") -> float:
    """Per-page spine caliper: colour picture books print on white/colour stock,
    which is thinner per sheet than the cream stock journals/standard use."""
    return SPINE_PER_PAGE_WHITE_IN if book_type == "picture" else SPINE_PER_PAGE_IN


def spine_width_in(pages: int, per_page: float = SPINE_PER_PAGE_IN) -> float:
    return round(pages * per_page, 4)


def cover_dimensions_in(pages: int, trim_w: float = TRIM_W_IN,
                        trim_h: float = TRIM_H_IN,
                        per_page: float = SPINE_PER_PAGE_IN) -> tuple[float, float]:
    spine = spine_width_in(pages, per_page)
    width = BLEED_IN + trim_w + spine + trim_w + BLEED_IN
    height = trim_h + 2 * BLEED_IN
    return (round(width, 4), round(height, 4))


def printing_cost_usd(pages: int, colour: bool = False) -> float:
    if colour:
        return round(PRINT_COLOUR_FIXED_USD + pages * PRINT_COLOUR_PER_PAGE_USD, 2)
    return round(PRINT_FIXED_USD + pages * PRINT_PER_PAGE_USD, 2)


def royalty_usd(price_usd: float, pages: int, colour: bool = False) -> float:
    return round(price_usd * ROYALTY_RATE - printing_cost_usd(pages, colour), 2)
