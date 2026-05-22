"""
Thesis plot style — shared module.
Import into any plotting script and call apply() after setting the backend.

Usage:
    import plot_style
    plot_style.apply()
"""
import matplotlib
from matplotlib.colors import LinearSegmentedColormap

# ── Palette ────────────────────────────────────────────────────────────────
PRIMARY    = '#3B6FA0'   # thesis blue  — main lines, bars, primary data series
ACCENT     = '#C56B3A'   # burnt orange — use sparingly (second series, annotations)
NEUTRAL    = '#7A7A7A'   # mid-grey     — reference lines, secondary text
DARK_BLUE  = '#1F4060'   # deep navy    — emphasis, titles if ever needed
LIGHT_BLUE = '#7A9DC1'   # pale blue    — fills, confidence bands

# Consistent multi-series order
PALETTE = [PRIMARY, ACCENT, LIGHT_BLUE, DARK_BLUE, NEUTRAL]

# ── Custom colourmaps ───────────────────────────────────────────────────────
thesis_cmap = LinearSegmentedColormap.from_list('thesis_blue', ['white', PRIMARY], N=256)

# ── rcParams dict ───────────────────────────────────────────────────────────
_RC = {
    # Typography
    'font.family':          'serif',
    'font.serif':           ['Latin Modern Roman', 'DejaVu Serif', 'Georgia', 'serif'],
    'axes.labelsize':       11,
    'xtick.labelsize':      9,
    'ytick.labelsize':      9,
    'legend.fontsize':      9,
    'legend.frameon':       False,

    # Spines — keep only left + bottom
    'axes.spines.top':      False,
    'axes.spines.right':    False,
    'axes.edgecolor':       '#555555',
    'axes.linewidth':       0.8,

    # Ticks — outward, short
    'xtick.direction':      'out',
    'ytick.direction':      'out',
    'xtick.major.size':     4,
    'ytick.major.size':     4,
    'xtick.major.width':    0.6,
    'ytick.major.width':    0.6,
    'xtick.minor.visible':  False,
    'ytick.minor.visible':  False,

    # Grid — horizontal only, very light
    'axes.grid':            True,
    'axes.grid.axis':       'y',
    'grid.color':           '#E5E5E5',
    'grid.linewidth':       0.6,
    'grid.linestyle':       '-',

    # Backgrounds
    'figure.facecolor':     'white',
    'axes.facecolor':       'white',

    # Lines + markers
    'lines.linewidth':      1.8,
    'lines.markersize':     6,
    'scatter.marker':       'o',

    # Export defaults
    'savefig.dpi':          300,
    'savefig.bbox':         'tight',
    'savefig.facecolor':    'white',

    # No titles (captions live in LaTeX)
    # (titles are set to '' in each script — rcParams cannot enforce this globally)
}


def apply():
    """Apply thesis rcParams to the current matplotlib session."""
    matplotlib.rcParams.update(_RC)


def threshold_line_kwargs():
    """Keyword args for dashed reference/threshold lines."""
    return dict(color=NEUTRAL, linestyle='--', linewidth=1.2)


def bar_kwargs(color=PRIMARY):
    """Keyword args for bar charts."""
    return dict(color=color, alpha=0.8, edgecolor='none')
