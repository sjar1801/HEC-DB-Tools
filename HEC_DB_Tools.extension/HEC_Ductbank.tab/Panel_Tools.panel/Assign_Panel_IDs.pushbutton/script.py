#! python3
"""HEC Ductbank Panel ID Assigner — PyRevit Button
Assigns Panel-001, Panel-002, etc. to the Comments parameter
on target panel families visible in the ACTIVE VIEW only.
Cascades the same ID down to nested/sub-components.

PyRevit v6 + CPython 3123
Hunt Electric — MONARCH Job
"""

import clr
clr.AddReference('RevitAPI')
from Autodesk.Revit.DB import (
    FilteredElementCollector,
    FamilyInstance,
    BuiltInParameter,
    Transaction,
)

# ─── CONFIG — edit these if family names change ───────────────
TARGET_FAMILIES = [
    "HEC_EF-DB_SIDE_PANEL",
    "HEC_EF-DB_ASPVSF",
    "HEC_NESTED_EF-DB_ASP",
    "HEC_NESTED_EF-DB90_ASP",
]
PREFIX = "Panel-"
PARAM_NAME = "Comments"
# ──────────────────────────────────────────────────────────────

# ─── Revit document access (PyRevit style) ────────────────────
uidoc = __revit__.ActiveUIDocument          # noqa: F821
doc   = uidoc.Document
active_view = doc.ActiveView
# ──────────────────────────────────────────────────────────────


def safe_family_name(elem):
    """Get family name, avoiding PythonNet Symbol.Name bug."""
    try:
        return elem.Symbol.Family.Name
    except Exception:
        pass
    try:
        p = elem.get_Parameter(BuiltInParameter.ELEM_FAMILY_PARAM)
        if p is not None:
            return p.AsValueString()
    except Exception:
        pass
    return ""


def safe_type_name(elem):
    """Get type name, avoiding PythonNet Symbol.Name bug."""
    try:
        return elem.Name
    except Exception:
        pass
    try:
        p = elem.get_Parameter(BuiltInParameter.ALL_MODEL_TYPE_NAME)
        if p is not None:
            return p.AsString()
    except Exception:
        pass
    return ""


# ─── Collect panels in active view ────────────────────────────
collector = FilteredElementCollector(doc, active_view.Id)
collector.OfClass(FamilyInstance)
all_instances = list(collector.ToElements())

panels = [e for e in all_instances if safe_family_name(e) in TARGET_FAMILIES]

print("View: {} ({})".format(active_view.Name, active_view.ViewType))
print("FamilyInstances in view: {}".format(len(all_instances)))
print("Panels matched: {}".format(len(panels)))
print("---")

if len(panels) == 0:
    print("ERROR: No panels found matching target families.")
    print("Target families: {}".format(TARGET_FAMILIES))
    seen = set()
    for elem in all_instances[:50]:
        fn = safe_family_name(elem)
        if fn and fn not in seen:
            seen.add(fn)
            if len(seen) <= 15:
                print("  Found family: {}".format(fn))
else:
    tagged = 0
    nested_tagged = 0
    errors = []

    def write_comment(elem, value, label=""):
        """Write value to Comments param on a single element.
        Returns True on success."""
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

    # Manual transaction (PyRevit CPython — no TransactionManager)
    t = Transaction(doc, "HEC Assign Panel IDs")
    t.Start()

    for i, panel in enumerate(panels):
        panel_id = PREFIX + str(i + 1).zfill(3)
        fname = safe_family_name(panel)
        tname = safe_type_name(panel)

        # Write to parent panel
        if write_comment(panel, panel_id, "parent"):
            tagged += 1
            print("OK: {} -> {} [{}:{}]".format(panel_id, panel.Id, fname, tname))

        # Cascade to nested/sub-components
        sub_ids = panel.GetSubComponentIds()
        if sub_ids:
            for sub_id in sub_ids:
                sub_elem = doc.GetElement(sub_id)
                if sub_elem is not None:
                    if write_comment(sub_elem, panel_id, "nested"):
                        nested_tagged += 1
                        sub_fname = safe_family_name(sub_elem)
                        print("  └─ nested: {} -> {} [{}]".format(
                            panel_id, sub_elem.Id, sub_fname))

    t.Commit()

    print("---")
    print("Panels found: {} | Tagged: {} | Nested tagged: {} | Errors: {}".format(
        len(panels), tagged, nested_tagged, len(errors)))
    for e in errors:
        print(e)
