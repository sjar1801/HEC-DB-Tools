"""hec_db.detection — spacer-bar detection and orientation logic (Tool 5).

Spacer bars are identified by REFERENCE FINGERPRINT (has BOTH CenterLeftRight
AND CenterFrontBack refs), not by family name, so old family names on other
projects still work. Fallback: family name ends with '_R'.

PyRevit v6 + CPython 3123  |  Revit 2025
Hunt Electric — MONARCH Job
"""

import clr
clr.AddReference("RevitAPI")
from Autodesk.Revit.DB import (
    FamilyInstance,
    FamilyInstanceReferenceType,
)

from hec_db.constants import Z_TOLERANCE
from hec_db.utils import has_ref, loc_point, safe_family_name


def identify_spacer_bars(doc, panel):
    """Return list of (FamilyInstance, locPoint) for all spacer bar sub-comps.

    PRIMARY test: has BOTH CenterLeftRight AND CenterFrontBack references.
    FALLBACK: family name ends with '_R'.
    Returns [] if no sub-components or no bars found.
    """
    try:
        sub_ids = list(panel.GetSubComponentIds())
    except Exception:
        return []
    if not sub_ids:
        return []

    primary = []
    fallback = []

    for sid in sub_ids:
        el = doc.GetElement(sid)
        if not isinstance(el, FamilyInstance):
            continue
        pt = loc_point(el)
        if pt is None:
            continue

        has_clr = has_ref(el, FamilyInstanceReferenceType.CenterLeftRight)
        has_cfb = has_ref(el, FamilyInstanceReferenceType.CenterFrontBack)
        if has_clr and has_cfb:
            primary.append((el, pt))
        else:
            # Name fallback
            fname = safe_family_name(doc, el) or ""
            if fname.endswith("_R"):
                fallback.append((el, pt))

    if primary:
        return primary
    return fallback


def detect_orientation(bars):
    """Determine whether spacer bars run horizontally or vertically.

    Compares the spread of the bars' location-Z values (vertical spread)
    versus their location-X/Y projected spread (horizontal spread).

    Returns "vertical"  if bars stack in Z  (row string goes on the right)
            "horizontal" if bars spread in X/Y (row string goes on the bottom)
            None         if undetermined (0 or 1 bar)
    """
    if len(bars) < 2:
        return None

    zs = [pt.Z for _, pt in bars]
    xs = [pt.X for _, pt in bars]
    ys = [pt.Y for _, pt in bars]

    z_spread = max(zs) - min(zs)
    x_spread = max(xs) - min(xs)
    y_spread = max(ys) - min(ys)
    horiz_spread = max(x_spread, y_spread)

    if z_spread < Z_TOLERANCE and horiz_spread > Z_TOLERANCE:
        return "horizontal"
    if z_spread > Z_TOLERANCE:
        return "vertical"
    return None
