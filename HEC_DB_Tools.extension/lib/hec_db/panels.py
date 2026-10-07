"""hec_db.panels — Tool 1: Assign Panel IDs.

Assigns Panel-001, Panel-002, etc. to the Comments parameter on target panel
families visible in the given view.  Cascades the same ID down to
nested/sub-components.  After tagging, a second pass stamps every *other*
assembly member with ``Not A Panel`` so that section-view filters can hide
non-panel clutter (cards, spare angles, stayform, etc.).

PyRevit v6 + CPython 3123  |  Revit 2025
Hunt Electric — MONARCH Job
"""

import clr
clr.AddReference("RevitAPI")
from Autodesk.Revit.DB import (
    AssemblyInstance,
    FilteredElementCollector,
    FamilyInstance,
    BuiltInParameter,
    Transaction,
)

from hec_db.constants import (
    TARGET_FAMILIES, NESTED_PANEL_FAMILIES,
    STANDARD_HOST_FAMILIES, PREFIX, PARAM_NAME,
)
from hec_db.utils import safe_family_name, safe_type_name
from hec_db.assembly import collect_panels

NOT_A_PANEL = "Not A Panel"


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


def _read_comment(elem):
    """Return the current Comments value (str) or ''."""
    p = elem.LookupParameter(PARAM_NAME)
    if p is None:
        p = elem.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
    if p is not None:
        try:
            v = p.AsString()
            return v if v else ""
        except Exception:
            return ""
    return ""


def _collect_all_descendants(doc, elem):
    """Return a set of ElementId.IntegerValue for *elem* and every
    sub-component recursively (the entire nested tree below it)."""
    result = set()
    stack = [elem]
    while stack:
        cur = stack.pop()
        key = cur.Id.IntegerValue
        if key in result:
            continue
        result.add(key)
        try:
            for sid in cur.GetSubComponentIds():
                se = doc.GetElement(sid)
                if se is not None:
                    stack.append(se)
        except Exception:
            pass
    return result


def _stamp_non_panels(doc, active_view, panel_tree_ids, errors):
    """Second pass — stamp ``Not A Panel`` on every FamilyInstance in the
    view that is NOT part of the panel tree (panels + their hosts +
    sub-components) and does not already carry a Panel-XXX tag.

    Returns the number of elements stamped.
    """
    stamped = 0
    collector = (FilteredElementCollector(doc, active_view.Id)
                 .OfClass(FamilyInstance)
                 .WhereElementIsNotElementType())
    for fi in collector:
        key = fi.Id.IntegerValue
        if key in panel_tree_ids:
            continue
        existing = _read_comment(fi)
        if existing.startswith(PREFIX) or existing == NOT_A_PANEL:
            continue
        if write_comment(fi, NOT_A_PANEL, errors, "nap"):
            stamped += 1
    return stamped


def assign_panel_ids(doc, active_view):
    """Tool 1 orchestrator. Tags every target panel visible in *active_view*.

    Two passes inside one Transaction:
      1. Assign Panel-001 … Panel-NNN to every recognised panel and cascade
         the ID to sub-components.
      2. Stamp ``Not A Panel`` on every remaining element in the view that
         is not part of the panel tree.

    Returns a stats dict:
      {"panels": n, "tagged": n, "nested_tagged": n,
       "nap_stamped": n, "errors": [..]}
    """
    stats = {"panels": 0, "tagged": 0, "nested_tagged": 0,
             "nap_stamped": 0, "errors": []}

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

    # Build the "panel tree" — elements that should NOT get "Not A Panel".
    # Strategy: protect each panel + its descendants (rebar/angles inside it),
    # then walk UP via SuperComponent to protect each direct ancestor element
    # (host, segment, container) WITHOUT pulling in their other children.
    # This ensures sibling hosts (card hosts, spare angles) are NOT protected.
    panel_tree_ids = set()

    # Manual transaction (PyRevit CPython — no TransactionManager)
    t = Transaction(doc, "HEC Assign Panel IDs")
    t.Start()
    try:
        # ── Pass 1: assign Panel-XXX IDs ─────────────────────────
        for i, panel in enumerate(panels):
            panel_id = PREFIX + str(i + 1).zfill(3)
            fname = safe_family_name(doc, panel) or ""
            tname = safe_type_name(panel)

            # Protect the panel and everything nested inside it
            panel_tree_ids |= _collect_all_descendants(doc, panel)

            # Walk UP via SuperComponent — protect each ancestor element
            # itself (host → segment → container) but NOT their siblings.
            try:
                ancestor = panel.SuperComponent
                while ancestor is not None:
                    panel_tree_ids.add(ancestor.Id.IntegerValue)
                    try:
                        ancestor = ancestor.SuperComponent
                    except Exception:
                        ancestor = None
            except Exception:
                pass

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

        # ── Pass 2: stamp "Not A Panel" on everything else ───────
        nap_count = _stamp_non_panels(doc, active_view, panel_tree_ids, errors)
        stats["nap_stamped"] = nap_count
        if nap_count:
            print("---")
            print("'Not A Panel' stamped on {} element(s)".format(nap_count))

        t.Commit()
    except Exception as ex:
        # Never leave a transaction open — Revit discards everything and
        # shows "A transaction or sub-transaction was opened but not closed".
        try:
            t.RollBack()
        except Exception:
            pass
        print("")
        print("ERROR — transaction rolled back: {}".format(ex))
        stats["errors"].append("TRANSACTION ROLLED BACK: {}".format(ex))
        return stats

    print("---")
    print("Panels found: {} | Tagged: {} | Nested tagged: {} | NAP: {} | Errors: {}".format(
        len(panels), tagged, nested_tagged, nap_count, len(errors)))
    for e in errors:
        print(e)

    stats["tagged"] = tagged
    stats["nested_tagged"] = nested_tagged
    return stats
