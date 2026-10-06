#! python3
"""HEC Ductbank Dimension Panels — PyRevit Button  (Tool 5)

Prerequisites:
  - "Assign Panel IDs"   (Tool 1) — Comments populated
  - "Create DB Sections" (Tool 2) — section views exist, named Panel-XXX
  - "Rotate DB Sections" (Tool 3) — sections aimed square at their panels

What this tool does:
  - Finds the ductbank assembly (current selection → active view → prompt)
  - Lets you tick which dimensions to place (all on by default):
      * Row String        — segmented string through every rebar spacer
      * Overall Height    — single dim, panel Top → Bottom
      * Overall Width     — single dim, panel Left → Right
  - Optionally "Replace existing" — deletes all dims in each view before
    placing, so re-runs produce a clean slate
  - AUTO-DETECTS spacer bar orientation:
      * Bars spread horizontally (same Z)  → row string placed BELOW panel
      * Bars spread vertically (different Z)→ row string placed to the RIGHT
  - Spacer bars identified by REFERENCE FINGERPRINT (has BOTH CenterLeftRight
    AND CenterFrontBack refs), not by family name. Fallback: name ends '_R'.
  - Uses dimension style "ASSEMBLIES - CONTINUOUS - 3/32" - HEC - BLACK"
    (falls back to the first Linear dimension type if it's not loaded)
  - Everything runs inside ONE transaction

What this tool does NOT do:
  - Create / rotate / sheet the sections → Tools 2, 3, 4

All logic lives in lib/hec_db/dimensions.py — this button is a thin wrapper.

PyRevit v6 + CPython 3123  |  Revit 2025
Hunt Electric — MONARCH Job
"""

from hec_db.dimensions import dimension_panels

uidoc = __revit__.ActiveUIDocument          # noqa: F821
doc   = uidoc.Document

dimension_panels(doc, uidoc)
