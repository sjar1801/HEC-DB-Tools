#! python3
"""HEC Ductbank Rotate Sections — PyRevit Button  (Tool 3)

Prerequisites:
  - "Assign Panel IDs"   (Tool 1) — Comments must be populated
  - "Create DB Sections" (Tool 2) — section views must exist, named Panel-XXX

What this tool does:
  - For every section view named "Panel-XXX" in this assembly:
      1. Reads the panel's FacingOrientation as the target view direction (n)
      2. Finds the OST_Viewers marker element for that section
         (coworker's technique — rotate the MARKER, not the View object)
      3. Rotates the marker about a vertical axis so the section faces
         the panel correctly — works for ANY angle, not just 90° increments
      4. Moves the marker in XY so the cut plane is centred on the panel's
         location point — fixes blank/clipped views in non-uniform ductbanks
      5. Verifies the resulting ViewDirection matches target n and reports

What this tool does NOT do:
  - Crop/resize sections  (filters isolate each panel — no tight crop needed)
  - Place views on sheets → Tool 4 (Place On Sheets)
  - Dimension sections    → Tool 5 (Dimension Panels)

All logic lives in lib/hec_db/sections.py — this button is a thin wrapper.

PyRevit v6 + CPython 3123  |  Revit 2025
Hunt Electric — MONARCH Job
"""

from hec_db.sections import rotate_sections

uidoc       = __revit__.ActiveUIDocument          # noqa: F821
doc         = uidoc.Document
active_view = doc.ActiveView

rotate_sections(doc, active_view)
