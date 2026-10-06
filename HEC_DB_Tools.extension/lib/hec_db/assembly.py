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
from hec_db.utils import comments_of


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
    return hosts[0][1]
