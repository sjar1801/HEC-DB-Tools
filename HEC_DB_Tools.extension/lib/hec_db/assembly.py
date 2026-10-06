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


def panels_from_host(doc, host, verbose=True):
    """Walk one level into a standard host family and return its nested
    panels. If the host contains no recognised nested panel, the host itself
    is returned as the panel (preserves pre-nesting behaviour for hosts that
    only contain bars/angles).

    Nested panel slots that are hidden/inactive in the family (no geometry)
    are skipped — see has_geometry()."""
    host_name = safe_family_name(doc, host) or "?"
    found = []
    skipped = 0
    for se in _sub_elements(doc, host):
        if isinstance(se, FamilyInstance) and is_nested_panel(doc, se):
            if not has_geometry(se):
                skipped += 1
                if verbose:
                    print("  host {} [{}] -> nested panel {} is inactive (no geometry) — skipped".format(
                        host.Id, host_name, se.Id))
                continue
            found.append(se)
    if found:
        if verbose:
            print("  host {} [{}] -> {} nested panel(s){}".format(
                host.Id, host_name, len(found),
                " ({} inactive skipped)".format(skipped) if skipped else ""))
        return found
    if verbose:
        print("  host {} [{}] has no nested panel — treating host as panel".format(
            host.Id, host_name))
    return [host]


def collect_panels(doc, elements_or_ids, from_assembly=False, verbose=True):
    """Return a flat list of panel FamilyInstances from a mixed element list.

    Handles both ductbank build kinds transparently:
      * CUSTOM_PANEL_FAMILIES  → the element IS the panel
      * STANDARD_HOST_FAMILIES → walk GetSubComponentIds() one level to the
                                 nested panels (NESTED_PANEL_FAMILIES)
      * anything else whose sub-components include a standard host (i.e. the
        outer HEC_EF-DUCTBANK_STANDARD_* container) → walk into those hosts.
        This covers the case where assembly members only list the container.

    `elements_or_ids` may contain Elements or ElementIds. Duplicates (same
    panel reached twice) are removed, order of first appearance is kept.
    `from_assembly` is informational only (affects log wording).
    """
    panels = []
    seen = set()
    custom_n = host_n = container_n = 0

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

        fname = safe_family_name(doc, elem) or ""

        if fname in CUSTOM_PANEL_FAMILIES:
            custom_n += 1
            _add(elem)

        elif fname in STANDARD_HOST_FAMILIES:
            host_n += 1
            for p in panels_from_host(doc, elem, verbose):
                _add(p)

        else:
            # Possible outer container — look one level down for hosts
            hosts = [se for se in _sub_elements(doc, elem)
                     if isinstance(se, FamilyInstance)
                     and (safe_family_name(doc, se) or "") in STANDARD_HOST_FAMILIES]
            if hosts:
                container_n += 1
                if verbose:
                    print("  container {} [{}] -> {} host(s)".format(
                        elem.Id, fname, len(hosts)))
                for h in hosts:
                    for p in panels_from_host(doc, h, verbose):
                        _add(p)

    if verbose:
        print("collect_panels{}: custom={} hosts={} containers={} -> {} panel(s)".format(
            " (assembly members)" if from_assembly else "",
            custom_n, host_n, container_n, len(panels)))
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
    """Return the host panel FamilyInstance shown in this section view.

    The host panel is the instance with the MOST sub-components. If several
    hosts are visible, prefer the one whose Comments equals the view name.

    Standard ductbanks: the winner by sub-component count is usually the
    HOST family (HEC_NESTED_EF-DB_*), not the real panel. In that case we walk
    one level into the host and return the nested panel whose Comments matches
    the view name (falling back to the first recognised nested panel).
    """
    collector = (FilteredElementCollector(doc, view.Id)
                 .OfClass(FamilyInstance)
                 .WhereElementIsNotElementType())
    hosts = []
    for fi in collector:
        try:
            n = len(list(fi.GetSubComponentIds()))
        except Exception:
            n = 0
        if n > 0:
            hosts.append((n, fi))
    if not hosts:
        return None

    named = [h for h in hosts if comments_of(h[1]) == view.Name]
    if named:
        hosts = named
    hosts.sort(key=lambda h: h[0], reverse=True)
    winner = hosts[0][1]

    # ── Standard DB: winner is a host family → descend to the nested panel ──
    wname = safe_family_name(doc, winner) or ""
    if wname in STANDARD_HOST_FAMILIES:
        nested = [se for se in _sub_elements(doc, winner)
                  if isinstance(se, FamilyInstance) and is_nested_panel(doc, se)]
        if nested:
            by_name = [p for p in nested if comments_of(p) == view.Name]
            chosen = by_name[0] if by_name else nested[0]
            print("  find_panel_in_view: host {} [{}] -> nested panel {} [{}]{}".format(
                winner.Id, wname, chosen.Id,
                safe_family_name(doc, chosen) or safe_type_name(chosen),
                "" if by_name else " (no Comments match — first nested)"))
            return chosen
        print("  find_panel_in_view: host {} [{}] has no nested panel — using host".format(
            winner.Id, wname))

    return winner
