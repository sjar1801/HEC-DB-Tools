"""hec_db.constants — all configuration constants for the HEC DB Tools.

Edit these if family names, templates, dimension styles or sheet layout
change. Every tool imports from here so there is ONE place to update.

PyRevit v6 + CPython 3123  |  Revit 2025
Hunt Electric — MONARCH Job
"""

# ── Panel families (Tools 1-4) ──────────────────────────────────────────────
TARGET_FAMILIES = [
    "HEC_EF-DB_SIDE_PANEL",
    "HEC_EF-DB_ASPVSF",
    "HEC_NESTED_EF-DB_ASP",
    "HEC_NESTED_EF-DB90_ASP",
]

# ── Tool 1: Assign Panel IDs ────────────────────────────────────────────────
PREFIX     = "Panel-"
PARAM_NAME = "Comments"

# ── Tool 2: Create DB Sections ──────────────────────────────────────────────
SECTION_TEMPLATE_NAME = "6 Spool_DB_DETAIL SECTION"
PLAN_TEMPLATE_NAME    = "7 Spool_DB_PLAN DETAIL"

# ── Tool 3: Rotate DB Sections ──────────────────────────────────────────────
AIM_TOLERANCE    = 0.01   # radians — ~0.6°, forgiving of Revit rounding
MOVE_THRESHOLD   = 0.1    # ft — skip move if cut plane already close enough
ANGLED_THRESHOLD = 0.9    # |dot| below this on both axes → flag as angled panel

# ── Tool 5: Dimension Panels ────────────────────────────────────────────────
DEFAULT_DIM_TYPE_NAME = 'ASSEMBLIES - CONTINUOUS - 3/32" - HEC - BLACK'

DIM_OFFSET   = 0.5     # ft — gap between panel extent and dimension line
Z_TOLERANCE  = 0.01    # ft — refs closer than this in Z are the same row line
X_TOLERANCE  = 0.01    # ft — refs closer than this in X are the same column
SIDE_MARGIN  = 0.05    # ft — how far past panel centre counts as "that side"

OPT_ROW     = "Row String"
OPT_HEIGHT  = "Overall Height"
OPT_WIDTH   = "Overall Width"
OPT_REPLACE = "Replace existing dimensions"
DIM_OPTIONS = [OPT_ROW, OPT_HEIGHT, OPT_WIDTH, OPT_REPLACE]
# Indices that are checked by default (first 3 on, Replace off)
DEFAULT_CHECKED = [True, True, True, False]

# ── Tool 4: Place On Sheets ─────────────────────────────────────────────────
# All values in FEET (Revit internal units). Tune to match your title block.
# These describe the usable drawing rectangle INSIDE the title block border.
SHEET_W       = 3.5     # 42" nominal sheet width
SHEET_H       = 2.5     # 30" nominal sheet height
MARGIN_LEFT   = 0.125   # ~1.5" from left edge
MARGIN_RIGHT  = 0.625   # ~7.5" from right edge (title block info strip)
MARGIN_TOP    = 0.125   # ~1.5" from top edge
MARGIN_BOTTOM = 0.25    # ~3" from bottom edge (title block info area)
PAD_X         = 0.083   # ~1" horizontal gap between viewports
PAD_Y         = 0.083   # ~1" vertical gap between viewports

SHEET_SUFFIX = "Panel Builds"
