"""hec_db.panels — Tool 1: Assign Panel IDs.

Assigns Panel-001, Panel-002, etc. to the Comments parameter on target panel
families visible in the given view. Cascades the same ID down to
nested/sub-components.

PyRevit v6 + CPython 3123  |  Revit 2025
Hunt Electric — MONARCH Job
"""

import clr
clr.AddReference("RevitAPI")
from Autodesk.Revit.DB import (
    FilteredElementCollector,
    FamilyInstance,
    BuiltInParameter,
    Transaction,
)

from hec_db.constants import (
    TARGET_FAMILIES, NESTED_PANEL_FAMILIES, PREFIX, PARAM_NAME,
)
from hec_db.utils import safe_family_name, safe_type_name
from hec_db.assembly import collect_panels


def write_comment(elem, value, errors, label=""):
    """Write value to Comments param on a single element.
    Appends failure messages to *errors*. Returns True on success."""
    param = elem.LookupParameter(PARAM_NAME)
    if param is None:
        param = elem.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
    if param is not None and not param.IsReadOnly:
        try:
            param.Set(value)
            return True
        except Exception as ex:
            errors.append("WRITE ERR {} ({}): {}".format(elem.Id, label, ex))
            return False
    else:
        if param is None:
            errors.append("NO PARAM {} ({}): {} not found".format(
                elem.Id, label, PARAM_NAME))
        else:
            errors.append("READONLY {} ({}): {}".format(
                elem.Id, label, PARAM_NAME))
        return False


def assign_panel_ids(doc, active_view):
    """Tool 1 orchestrator. Tags every target panel visible in *active_view*.

    Manages its own Transaction. Prints progress. Returns a stats dict:
      {"panels": n, "tagged": n, "nested_tagged": n, "errors": [..]}
    """
    stats = {"panels": 0, "tagged": 0, "nested_tagged": 0, "errors": []}

    # ── Collect panels in active view ────────────────────────────
    collector = FilteredElementCollector(doc, active_view.Id)
    collector.OfClass(FamilyInstance)
    all_instances = list(collector.ToElements())

    print("View: {} ({})".format(active_view.Name, active_view.ViewType))
    print("FamilyInstances in view: {}".format(len(all_instances)))

    # Custom panels come back directly; standard hosts are walked one level
    # down to their nested DB_PANEL_* instances (see hec_db.assembly).
    panels = collect_panels(doc, all_instances)
    stats["panels"] = len(panels)

    print("Panels matched: {}".format(len(panels)))
    print("---")

    if len(panels) == 0:
        print("ERROR: No panels found matching target families.")
        print("Target families: {}".format(TARGET_FAMILIES))
        print("Nested panel families: {}".format(NESTED_PANEL_FAMILIES))
        seen = set()
        for elem in all_instances[:50]:
            fn = safe_family_name(doc, elem)
            if fn and fn not in seen:
                seen.add(fn)
                if len(seen) <= 15:
                    print("  Found family: {}".format(fn))
        return stats

    tagged = 0
    nested_tagged = 0
    errors = stats["errors"]

    # Manual transaction (PyRevit CPython — no TransactionManager)
    t = Transaction(doc, "HEC Assign Panel IDs")
    t.Start()

    for i, panel in enumerate(panels):
        panel_id = PREFIX + str(i + 1).zfill(3)
        fname = safe_family_name(doc, panel) or ""
        tname = safe_type_name(panel)

        # Write to parent panel
        if write_comment(panel, panel_id, errors, "parent"):
            tagged += 1
            print("OK: {} -> {} [{}:{}]".format(panel_id, panel.Id, fname, tname))

        # Cascade to nested/sub-components
        sub_ids = panel.GetSubComponentIds()
        if sub_ids:
            for sub_id in sub_ids:
                sub_elem = doc.GetElement(sub_id)
                if sub_elem is not None:
                    if write_comment(sub_elem, panel_id, errors, "nested"):
                        nested_tagged += 1
                        sub_fname = safe_family_name(doc, sub_elem) or ""
                        print("  └─ nested: {} -> {} [{}]".format(
                            panel_id, sub_elem.Id, sub_fname))

    t.Commit()

    print("---")
    print("Panels found: {} | Tagged: {} | Nested tagged: {} | Errors: {}".format(
        len(panels), tagged, nested_tagged, len(errors)))
    for e in errors:
        print(e)

    stats["tagged"] = tagged
    stats["nested_tagged"] = nested_tagged
    return stats
