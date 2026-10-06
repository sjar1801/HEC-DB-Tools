#! python3
"""HEC Ductbank Assign Panel IDs — PyRevit Button  (Tool 1)

Assigns Panel-001, Panel-002, etc. to the Comments parameter
on target panel families visible in the ACTIVE VIEW only.
Cascades the same ID down to nested/sub-components.

All logic lives in lib/hec_db/panels.py — this button is a thin wrapper.

PyRevit v6 + CPython 3123  |  Revit 2025
Hunt Electric — MONARCH Job
"""

from hec_db.panels import assign_panel_ids

uidoc       = __revit__.ActiveUIDocument          # noqa: F821
doc         = uidoc.Document
active_view = doc.ActiveView

assign_panel_ids(doc, active_view)
