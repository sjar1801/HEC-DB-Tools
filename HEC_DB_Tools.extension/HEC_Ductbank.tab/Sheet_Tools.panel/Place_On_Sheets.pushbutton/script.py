#! python3
"""HEC Ductbank Place On Sheets — PyRevit Button  (Tool 4)

Prerequisites:
  - "Assign Panel IDs"   (Tool 1) — Comments populated
  - "Create DB Sections" (Tool 2) — section views exist, named Panel-XXX
  - "Rotate DB Sections" (Tool 3) — sections aimed at their panels

What this tool does:
  - Lets you PICK the title block to use (any title block loaded in the project)
  - Finds the ductbank assembly (uses your current selection, or prompts)
  - Collects every section view that belongs to that assembly
  - Sorts them by name (= panel ID order)
  - Packs them onto sheets using PLACE-MEASURE-MOVE layout:
      * places each viewport at a temp spot, asks Revit for the REAL rendered
        size (GetBoxOutline + GetLabelOutline), then moves it into position
      * lays viewports left-to-right, wraps to a new row when the row is full
      * starts a new overflow sheet when the current sheet is full
  - Creates sheets with AssemblyViewUtils.CreateSheet() and renames them
      "[AssemblyName] — Panel Builds", "… Panel Builds 2", "… Panel Builds 3" …

What this tool does NOT do:
  - Create or rotate sections → Tools 2 and 3
  - Dimension sections        → Tool 5 (Dimension Panels)

All logic lives in lib/hec_db/sheets.py — this button is a thin wrapper.

PyRevit v6 + CPython 3123  |  Revit 2025
Hunt Electric — MONARCH Job
"""

from hec_db.sheets import place_on_sheets

uidoc = __revit__.ActiveUIDocument          # noqa: F821
doc   = uidoc.Document

place_on_sheets(doc, uidoc)
