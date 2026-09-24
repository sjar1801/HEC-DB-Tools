# HEC Ductbank Panel ID Assigner v7
# Writes to Comments parameter on panels in the ACTIVE VIEW only
# Does NOT cascade to nested/sub-components
# Target families and config are hardcoded below

import clr
clr.AddReference('RevitAPI')
from Autodesk.Revit.DB import *

clr.AddReference('RevitServices')
from RevitServices.Persistence import DocumentManager
from RevitServices.Transactions import TransactionManager

# CONFIG - edit these if needed
TARGET_FAMILIES = [
    "HEC_EF-DB_SIDE_PANEL",
    "HEC_EF-DB_ASPVSF",
    "HEC_NESTED_EF-DB_ASP",
    "HEC_NESTED_EF-DB90_ASP",
]
PREFIX = "Panel-"
PARAM_NAME = "Comments"

def safe_family_name(elem):
    # Get family name avoiding PythonNet Symbol.Name bug
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
    # Get type name avoiding PythonNet Symbol.Name bug
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

doc = DocumentManager.Instance.CurrentDBDocument
active_view = doc.ActiveView

# Collect FamilyInstances in the active view only
collector = FilteredElementCollector(doc, active_view.Id)
collector.OfClass(FamilyInstance)
all_instances = list(collector.ToElements())

# Filter to target families
panels = []
for elem in all_instances:
    fname = safe_family_name(elem)
    if fname in TARGET_FAMILIES:
        panels.append(elem)

results = []
results.append("View: " + str(active_view.Name) + " (" + str(active_view.ViewType) + ")")
results.append("FamilyInstances in view: " + str(len(all_instances)))
results.append("Panels matched: " + str(len(panels)))
results.append("---")

if len(panels) == 0:
    results.append("ERROR: No panels found matching target families.")
    results.append("Target families: " + str(TARGET_FAMILIES))
    seen = set()
    for elem in all_instances[:50]:
        fn = safe_family_name(elem)
        if fn and fn not in seen:
            seen.add(fn)
            if len(seen) <= 15:
                results.append("  Found family: " + fn)
    OUT = "\n".join(results)
else:
    tagged = 0
    errors = []
    TransactionManager.Instance.EnsureInTransaction(doc)
    for i, panel in enumerate(panels):
        panel_id = PREFIX + str(i + 1).zfill(3)
        fname = safe_family_name(panel)
        tname = safe_type_name(panel)
        # Try LookupParameter first, then BIP fallback
        param = panel.LookupParameter(PARAM_NAME)
        if param is None:
            param = panel.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
        if param is not None and not param.IsReadOnly:
            try:
                param.Set(panel_id)
                tagged += 1
                results.append("OK: " + panel_id + " -> " + str(panel.Id) + " [" + fname + ":" + tname + "]")
            except Exception as ex:
                errors.append("WRITE ERR " + str(panel.Id) + ": " + str(ex))
        else:
            if param is None:
                errors.append("NO PARAM " + str(panel.Id) + ": " + PARAM_NAME + " not found")
            else:
                errors.append("READONLY " + str(panel.Id) + ": " + PARAM_NAME)
    TransactionManager.Instance.TransactionTaskDone()
    results.append("---")
    results.append("Panels found: " + str(len(panels)) + " | Tagged: " + str(tagged) + " | Errors: " + str(len(errors)))
    for e in errors:
        results.append(e)
    OUT = "\n".join(results)
