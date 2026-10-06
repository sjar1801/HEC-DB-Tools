#! python3
"""HEC Ductbank Create Sections — PyRevit Button  (Tool 2)

Prerequisites:
  - Run "Assign Panel IDs" first (Tool 1) — Comments must be populated
  - Active view must belong to an Assembly

What this tool does:
  - Reads panel Comments IDs (Panel-001, Panel-002 …)
  - Creates one AssemblyDetailSection per panel named to match its ID
  - Adds a NOT-EQUALS filter per section to isolate only that panel
  - Applies view template "6 Spool_DB_DETAIL SECTION" to every section
  - Creates one HorizontalDetail (Plan Detail) named "Plan Detail"
  - Applies view template "7 Spool_DB_PLAN DETAIL" to the plan view

What this tool does NOT do:
  - Rotate sections to correct orientation  → Tool 3 (Rotate Sections)
  - Place views on a sheet                 → Tool 4 (Place On Sheets)
  - Dimension the sections                 → Tool 5 (Dimension Panels)

All logic lives in lib/hec_db/sections.py — this button is a thin wrapper.

PyRevit v6 + CPython 3123  |  Revit 2025
Hunt Electric — MONARCH Job
"""

from hec_db.sections import create_sections

uidoc       = __revit__.ActiveUIDocument          # noqa: F821
doc         = uidoc.Document
active_view = doc.ActiveView

create_sections(doc, active_view)
