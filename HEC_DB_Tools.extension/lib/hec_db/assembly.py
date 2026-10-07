"""hec_db.assembly — assembly-level lookups shared by Tools 4 & 5.

PyRevit v6 + CPython 3123  |  Revit 2025
Hunt Electric — MONARCH Job
"""

import clr
clr.AddReference("RevitAPI")
from Autodesk.Revit.DB import (
    FilteredElementCollector,
    FamilyInstance,
    AssemblyInstance,
    ElementId,
    ViewSection,
)

from hec_db.ui import select_from_list
from hec_db.utils import comments_of, safe_family_name, safe_type_name
from hec_db.constants import (
    CUSTOM_PANEL_FAMILIES,
    STANDARD_HOST_FAMILIES,
    NESTED_PANEL_FAMILIES,
)


# ═══════════════════════════════════════════════════════════════════════════
# PANEL COLLECTION — single entry point for custom AND standard ductbanks
# ═══════════════════════════════════════════════════════════════════════════

def _sub_elements(doc, elem):
    """Return the direct sub-component elements of a FamilyInstance (or [])."""
    out = []
    try:
        for sid in elem.GetSubComponentIds():
            se = doc.GetElement(sid)
            if se is not None:
                out.append(se)
    except Exception:
        pass
    return out


def is_nested_panel(doc, elem):
    """True if elem is one of the nested panel families/types that live
    inside a standard host. Checks BOTH the family name and the type name
    because the nested panel may be exposed either way in the model."""
    fname = safe_family_name(doc, elem) or ""
    if fname in NESTED_PANEL_FAMILIES:
        return True
    tname = safe_type_name(elem) or ""
    return tname in NESTED_PANEL_FAMILIES


def is_panel(doc, elem):
    """True if *elem* is a real panel (a leaf we should tag/document).

    A panel is recognised by:
      * family name in CUSTOM_PANEL_FAMILIES  (custom builds — the element IS
        the panel), OR
      * family OR type name in NESTED_PANEL_FAMILIES  (standard builds — the
        nested DB_PANEL_* leaf; note some host families such as
        HEC_NESTED_EF-DB_FSP expose the panel via their *type* name
        DB_PANEL_FIXED, so we must check both).

    Wrappers (outer HEC_EF-DUCTBANK_STANDARD_* containers, _1020F straight
    segments, and pure host frames that only contain a separate nested panel)
    are NOT panels — the recursive collector descends through them.
    """
    fname = safe_family_name(doc, elem) or ""
    if fname in CUSTOM_PANEL_FAMILIES:
        return True
    if fname in NESTED_PANEL_FAMILIES:
        return True
    tname = safe_type_name(elem) or ""
    if tname in NESTED_PANEL_FAMILIES:
        return True
    return False


def has_geometry(elem, tol=0.001):
    """True if the element has a real (non-degenerate) model bounding box.

    Standard host families always carry their maximum panel count (e.g. 4
    slots on a straight DB) and hide the unused ones with a family visibility
    parameter. GetSubComponentIds() still returns those hidden slots, but
    their bounding box is None or zero-size — so this is the signal we use
    to skip them (Bug: 20ft DB picking up 4 panels instead of 2).
    """
    try:
        bb = elem.get_BoundingBox(None)
    except Exception:
        return False
    if bb is None:
        return False
    try:
        dx = abs(bb.Max.X - bb.Min.X)
        dy = abs(bb.Max.Y - bb.Min.Y)
        dz = abs(bb.Max.Z - bb.Min.Z)
    except Exception:
        return False
    # Degenerate if it has no extent in at least two axes
    return sum(1 for d in (dx, dy, dz) if d > tol) >= 2


def _find_panels_recursive(doc, elem, found, visited, verbose=True, depth=0):
    """Recursively descend through sub-components looking for real panels.

    At each node:
      * If it IS a recognised panel (is_panel) AND has geometry → collect it.
      * Otherwise recurse into its sub-components.
      * If a node has children but none are panels (e.g. pure host with only
        bars/angles) → fall back to treating the node itself as the panel
        (preserves pre-nesting behaviour).

    Inactive nested panel slots (no geometry) are skipped — see has_geometry().
    `visited` prevents infinite loops / duplicate processing.
    """
    key = elem.Id.IntegerValue
    if key in visited:
        return
    visited.add(key)

    # Check if this element itself is a recognised panel
    if is_panel(doc, elem):
        if has_geometry(elem):
            found.append(elem)
            if verbose and depth > 0:
                indent = "  " * depth
                print("{}panel {} [{}:{}]".format(
                    indent, elem.Id,
                    safe_family_name(doc, elem) or "?",
                    safe_type_name(elem) or "?"))
            return
        else:
            if verbose and depth > 0:
                indent = "  " * depth
                print("{}panel {} inactive (no geometry) — skipped".format(
                    indent, elem.Id))
            return

    # Not a panel — recurse into sub-components
    subs = _sub_elements(doc, elem)
    if not subs:
        return

    before = len(found)
    for se in subs:
        if isinstance(se, FamilyInstance):
            _find_panels_recursive(doc, se, found, visited, verbose, depth + 1)

    # If we recursed but found nothing, treat the element itself as a panel
    # (handles hosts that only contain bars/angles with no nested panel family)
    if len(found) == before and has_geometry(elem):
        fname = safe_family_name(doc, elem) or ""
        if fname in STANDARD_HOST_FAMILIES:
            found.append(elem)
            if verbose:
                indent = "  " * depth
                print("{}host {} [{}] has no nested panel — treating as panel".format(
                    indent, elem.Id, fname))


def collect_panels(doc, elements_or_ids, from_assembly=False, verbose=True):
    """Return a flat list of panel FamilyInstances from a mixed element list.

    Uses recursive descent to handle any nesting depth:
      * Custom panels (CUSTOM_PANEL_FAMILIES) → collected directly
      * Standard builds → recurse through containers, segments, hosts until
        a NESTED_PANEL_FAMILIES leaf is found
      * Works for 90° builds (3 levels), stapled straights (4 levels), and
        any future nesting depth

    `elements_or_ids` may contain Elements or ElementIds. Duplicates (same
    panel reached twice) are removed, order of first appearance is kept.
    `from_assembly` is informational only (affects log wording).
    """
    panels = []
    seen = set()
    visited = set()

    def _add(p):
        try:
            key = p.Id.IntegerValue
        except Exception:
            key = id(p)
        if key in seen:
            return
        seen.add(key)
        panels.append(p)

    for item in elements_or_ids:
        elem = item
        if isinstance(item, ElementId):
            elem = doc.GetElement(item)
        if elem is None or not isinstance(elem, FamilyInstance):
            continue

        # Recurse into this element to find all panels within it
        found_here = []
        _find_panels_recursive(doc, elem, found_here, visited, verbose)
        for p in found_here:
            _add(p)

    if verbose:
        print("collect_panels{}: {} panel(s) from {} input element(s)".format(
            " (assembly members)" if from_assembly else "",
            len(panels), len(list(elements_or_ids))))
    return panels


def pick_assembly(uidoc, doc,
                  title="Select the ductbank assembly to document",
                  button_text="Use this assembly"):
    """Return the AssemblyInstance to document.

    Order of preference:
      1. Exactly one AssemblyInstance in the current selection → use it.
      2. Active view belongs to an assembly → use that.
      3. Otherwise prompt the user to pick from all assemblies in the model.
    Returns the AssemblyInstance element, "NONE_IN_MODEL", or None.
    """
    # 1. Current selection
    sel_ids = uidoc.Selection.GetElementIds()
    sel_assemblies = []
    for sid in sel_ids:
        el = doc.GetElement(sid)
        if isinstance(el, AssemblyInstance):
            sel_assemblies.append(el)
    if len(sel_assemblies) == 1:
        return sel_assemblies[0]

    # 2. Active view's assembly
    try:
        av = doc.ActiveView
        if hasattr(av, "AssociatedAssemblyInstanceId"):
            aid = av.AssociatedAssemblyInstanceId
            if aid and aid != ElementId.InvalidElementId:
                el = doc.GetElement(aid)
                if isinstance(el, AssemblyInstance):
                    return el
    except Exception:
        pass

    # 3. Prompt from all assemblies
    all_assemblies = list(
        FilteredElementCollector(doc)
        .OfClass(AssemblyInstance)
    )
    if not all_assemblies:
        return "NONE_IN_MODEL"
    if len(all_assemblies) == 1:
        return all_assemblies[0]

    option_map = {}
    for a in all_assemblies:
        try:
            nm = a.Name
        except Exception:
            nm = "Assembly {}".format(a.Id.IntegerValue)
        label = "{}  (id {})".format(nm, a.Id.IntegerValue)
        option_map[label] = a

    chosen = select_from_list(
        sorted(option_map.keys()),
        title=title,
        button_text=button_text,
    )
    if not chosen:
        return None
    return option_map[chosen]


def collect_section_views(doc, assembly_id):
    """Return every non-template section view that belongs to this assembly.

    Scoped by AssociatedAssemblyInstanceId — same pattern as Tools 2 & 3 —
    so DB-2 never picks up DB-1's views. Sorted by Name (= panel ID order).
    ViewSection only → excludes the assembly 3D view, Plan Detail,
    schedules, and (critically) the sheets themselves on re-runs.
    """
    views = []
    for v in FilteredElementCollector(doc).OfClass(ViewSection).ToElements():
        if v.IsTemplate:
            continue
        try:
            if v.AssociatedAssemblyInstanceId != assembly_id:
                continue
        except Exception:
            continue
        views.append(v)
    views.sort(key=lambda x: x.Name)
    return views


def find_panel_in_view(doc, view):
    """Return the real panel FamilyInstance shown in this section view.

    Uses the recursive collector to find all panels visible in the view,
    then picks the one whose Comments matches the view name (i.e. the
    Panel-XXX tag set by Tool 1). Falls back to the first panel found.

    This handles any nesting depth (custom, 90° 3-level, straight 4-level).
    """
    collector = (FilteredElementCollector(doc, view.Id)
                 .OfClass(FamilyInstance)
                 .WhereElementIsNotElementType())
    all_fi = list(collector.ToElements())

    # Use the recursive collector to find real panels at any depth
    panels = collect_panels(doc, all_fi, verbose=False)

    if not panels:
        # Fallback: pick the element with the most sub-components
        best = None
        best_n = 0
        for fi in all_fi:
            try:
                n = len(list(fi.GetSubComponentIds()))
            except Exception:
                n = 0
            if n > best_n:
                best_n = n
                best = fi
        if best:
            print("  find_panel_in_view: no recognised panel — fallback to {} [{}]".format(
                best.Id, safe_family_name(doc, best) or "?"))
        return best

    # Prefer the panel whose Comments matches the view name
    by_name = [p for p in panels if comments_of(p) == view.Name]
    if by_name:
        chosen = by_name[0]
        print("  find_panel_in_view: {} [{}:{}] (Comments match)".format(
            chosen.Id,
            safe_family_name(doc, chosen) or "?",
            safe_type_name(chosen) or "?"))
        return chosen

    chosen = panels[0]
    print("  find_panel_in_view: {} [{}:{}] (first of {} panels, no Comments match)".format(
        chosen.Id,
        safe_family_name(doc, chosen) or "?",
        safe_type_name(chosen) or "?",
        len(panels)))
    return chosen
