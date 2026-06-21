"""KDP layout and economics math. Pure functions, no I/O.

Geometry constants below are encoded verbatim from KDP's verified help pages
(see docs/superpowers/plans/2026-06-21-…  §WS4) so we never re-measure per book:
interior bleed, gutter-by-page-count, outside margins, and per-stock spine
caliper. Print resolution is 300 DPI.
"""
import math

TRIM_W_IN = 6.0
TRIM_H_IN = 9.0
BLEED_IN = 0.125
DPI = 300                           # KDP minimum print resolution

# --- Spine caliper by paper stock (inch/page), KDP-verified ---
SPINE_PER_PAGE_CREAM_IN = 0.0025          # cream B&W (thickest)
SPINE_PER_PAGE_WHITE_IN = 0.002252        # white B&W
SPINE_PER_PAGE_STD_COLOR_IN = 0.002252    # Standard Color
SPINE_PER_PAGE_PREMIUM_COLOR_IN = 0.002347  # Premium Color (vivid; thicker than std)
SPINE_PER_PAGE_IN = SPINE_PER_PAGE_CREAM_IN  # back-compat default name
STOCK_MULTIPLIERS = {
    "cream": SPINE_PER_PAGE_CREAM_IN,
    "white": SPINE_PER_PAGE_WHITE_IN,
    "standard_color": SPINE_PER_PAGE_STD_COLOR_IN,
    "premium_color": SPINE_PER_PAGE_PREMIUM_COLOR_IN,
}

ROYALTY_RATE = 0.60                 # 60% for >= $9.99 paperback
PRINT_FIXED_USD = 0.85              # US B&W fixed charge (KDP US, 110+ pages)
PRINT_PER_PAGE_USD = 0.012          # US B&W per-page
# Rough colour-print estimate (verify per-book in KDP's calculator):
PRINT_COLOUR_FIXED_USD = 1.00
PRINT_COLOUR_PER_PAGE_USD = 0.07

# --- Interior margins (KDP-verified) ---
# Gutter (inside/binding margin) grows with page count; (max_pages, gutter_in).
GUTTER_BANDS = ((150, 0.375), (300, 0.5), (500, 0.625), (700, 0.75), (828, 0.875))
MAX_PAPERBACK_PAGES = 828
MARGIN_OUTSIDE_NO_BLEED_IN = 0.25   # outside margin, no bleed
MARGIN_OUTSIDE_BLEED_IN = 0.375     # outside margin, with bleed
MARGIN_INSIDE_IN = 0.5              # back-compat default gutter (24–300pp band)
MARGIN_OUTSIDE_IN = 0.375           # back-compat default outside margin
MARGIN_TOPBOTTOM_IN = 0.5


def gutter_in(pages: int) -> float:
    """KDP minimum inside (binding) margin for a `pages`-page paperback. Scales by
    page band; raises past KDP's 828-page limit."""
    if pages > MAX_PAPERBACK_PAGES:
        raise ValueError(
            f"{pages} pages exceeds KDP's {MAX_PAPERBACK_PAGES}-page paperback limit")
    for hi, g in GUTTER_BANDS:
        if pages <= hi:
            return g
    return GUTTER_BANDS[-1][1]


def outside_margin_in(bleed: bool = False) -> float:
    """KDP minimum outside margin: 0.375in with bleed, 0.25in without."""
    return MARGIN_OUTSIDE_BLEED_IN if bleed else MARGIN_OUTSIDE_NO_BLEED_IN


def interior_bleed_size_in(trim_w: float = TRIM_W_IN,
                           trim_h: float = TRIM_H_IN) -> tuple[float, float]:
    """Interior page size WITH bleed: +0.125in outside (width) and +0.125in on top
    AND bottom (height); the inside/binding edge gets no bleed (KDP-verified)."""
    return (round(trim_w + BLEED_IN, 4), round(trim_h + 2 * BLEED_IN, 4))


def min_pixels_for_dpi(length_in: float, dpi: int = DPI) -> int:
    """Pixels needed to hit `dpi` across `length_in` inches (ceil). Use with the
    trim+bleed dimension to size art for print."""
    return math.ceil(length_in * dpi)


def print_art_px(trim_w: float = TRIM_W_IN, trim_h: float = TRIM_H_IN,
                 dpi: int = DPI) -> int:
    """Square side (px) a Flux page/cover image needs to print full-bleed at >=
    `dpi` for a `trim_w` x `trim_h` book.

    The art is square and gets scaled to FILL the page-plus-bleed (the cover
    composites it full-bleed and even over-scans it), so size it to the LARGER
    trim+bleed dimension — otherwise one axis prints under `dpi`. For an 8.5x8.5
    book this is 8.75in -> 2625px; the old hardcoded 2560 was only ~293 DPI on
    the full-bleed cover."""
    w, h = interior_bleed_size_in(trim_w, trim_h)
    return min_pixels_for_dpi(max(w, h), dpi)


def spine_per_page(book_type: str = "journal") -> float:
    """Per-page spine caliper: colour picture/concept books print on white/colour
    stock, which is thinner per sheet than the cream stock journals/standard use."""
    return (SPINE_PER_PAGE_WHITE_IN if book_type in ("picture", "concept")
            else SPINE_PER_PAGE_IN)


def spine_per_page_for_stock(stock: str) -> float:
    """Per-page spine caliper for an explicit paper stock (cream / white /
    standard_color / premium_color)."""
    try:
        return STOCK_MULTIPLIERS[stock]
    except KeyError:
        raise ValueError(
            f"unknown stock {stock!r}; choose one of {sorted(STOCK_MULTIPLIERS)}")


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
