#! python3
"""HEC Ductbank Dimension Probe — PyRevit Button  (Diagnostic / Read-Only)

READ-ONLY — this tool never modifies the model.

PURPOSE
  Determine whether auto-dimensioning is feasible and, if so, exactly which
  references to target. Run this with a PANEL SECTION VIEW active (e.g. the
  Panel-001 section). It inspects the panel family instance shown in that view
  and reports everything the future "Dimension Panels" tool needs to know:

    1. The panel FamilyInstance found in the view (name, category, id)
    2. Its sub-components via GetSubComponentIds() — are the nested rebar
       families individually addressable? (answers the "Shared?" question)
    3. For the panel AND each nested instance, how many stable references
       each FamilyInstanceReferenceType returns
       (CenterLeftRight, CenterFrontBack, Left, Right, Front, Back, Top,
        Bottom, StrongReference, WeakReference) — these are the planes a
       dimension can attach to
    4. The geometry faces of the panel solids: orientation (horizontal /
       vertical), material name, and whether each face carries a stable
       reference in this view
    5. A plain-English verdict on which strategy will work:
         A) nested reference planes (preferred), or
         B) geometry-face filtering by material (fallback)

HOW TO READ THE OUTPUT
  - If each nested rebar reports 1 CenterLeftRight (or Left/Right) reference,
    strategy A works: we stack those into a ReferenceArray for the row string.
  - If sub-components come back empty, the nested families are NOT shared;
    we fall back to strategy B (faces filtered by the rebar material).

PyRevit v6 + CPython 3123  |  Revit 2025
Hunt Electric — MONARCH Job
"""

import clr
clr.AddReference("RevitAPI")
from Autodesk.Revit.DB import (
    FilteredElementCollector,
    FamilyInstance,
    BuiltInCategory,
    ElementId,
    Options,
    ViewDetailLevel,
    Solid,
    PlanarFace,
    FamilyInstanceReferenceType,
    XYZ,
)

uidoc = __revit__.ActiveUIDocument          # noqa: F821
doc   = uidoc.Document
view  = doc.ActiveView

# Reference types we want to probe on each instance
REF_TYPES = [
    "CenterLeftRight",
    "CenterFrontBack",
    "CenterElevation",
    "Left",
    "Right",
    "Front",
    "Back",
    "Top",
    "Bottom",
    "StrongReference",
    "WeakReference",
]


def mat_name(doc, mat_id):
    """Return a material's name, or '<none>'."""
    try:
        if mat_id is None or mat_id == ElementId.InvalidElementId:
            return "<none>"
        m = doc.GetElement(mat_id)
        if m is not None:
            return m.Name
    except Exception:
        pass
    return "<none>"


def probe_references(inst, label):
    """Print how many references each FamilyInstanceReferenceType returns."""
    print("  references for {}:".format(label))
    any_found = False
    for rt_name in REF_TYPES:
        rt = getattr(FamilyInstanceReferenceType, rt_name, None)
        if rt is None:
            continue
        try:
            refs = inst.GetReferences(rt)
            n = len(list(refs))
        except Exception as ex:
            print("      {:<16} ERROR {}".format(rt_name, ex))
            continue
        if n > 0:
            any_found = True
            print("      {:<16} {} ref(s)".format(rt_name, n))
    if not any_found:
        print("      (no named references of any type)")
    return any_found


def find_panel_in_view(view):
    """Return the largest Electrical-Fixture family instance visible in view.

    Panels and nested rebar are both Electrical Fixtures; the host panel is the
    one that HAS sub-components, so we prefer an instance whose
    GetSubComponentIds() is non-empty, else the first one found.
    """
    collector = (FilteredElementCollector(doc, view.Id)
                 .OfClass(FamilyInstance)
                 .WhereElementIsNotElementType())
    candidates = list(collector)
    hosts = []
    for fi in candidates:
        try:
            subs = fi.GetSubComponentIds()
            if subs and len(list(subs)) > 0:
                hosts.append(fi)
        except Exception:
            pass
    if hosts:
        # pick the host with the most sub-components
        hosts.sort(key=lambda f: len(list(f.GetSubComponentIds())),
                   reverse=True)
        return hosts[0], candidates
    return (candidates[0] if candidates else None), candidates


# ── RUN ──────────────────────────────────────────────────────────────────────
print("══════════════════════════════════════════════════════════")
print(" HEC Dimension Probe  (READ-ONLY)")
print(" Active view: {}  ({})".format(view.Name, view.ViewType))
print("══════════════════════════════════════════════════════════")

panel, all_in_view = find_panel_in_view(view)
print("")
print("Family instances visible in view: {}".format(len(all_in_view)))

if panel is None:
    print("")
    print("⚠ No family instances found in this view.")
    print("  Make a PANEL SECTION VIEW active and run again.")
    raise SystemExit

try:
    pname = panel.Symbol.Family.Name
except Exception:
    pname = "<family>"
try:
    pcat = panel.Category.Name
except Exception:
    pcat = "<cat>"
print("")
print("── HOST PANEL ──────────────────────────────────────────────")
print("  Name:     {}".format(pname))
print("  Category: {}".format(pcat))
print("  Id:       {}".format(panel.Id.IntegerValue))

# Sub-components (answers the "Shared?" question)
try:
    sub_ids = list(panel.GetSubComponentIds())
except Exception:
    sub_ids = []
print("  Sub-components (GetSubComponentIds): {}".format(len(sub_ids)))

# Probe the host panel's own references
probe_references(panel, "HOST PANEL")

# ── Nested instances ──────────────────────────────────────────────────────
print("")
print("── NESTED SUB-COMPONENTS ───────────────────────────────────")
if not sub_ids:
    print("  NONE returned. Nested families are NOT shared, so their")
    print("  reference planes are not individually addressable.")
    print("  → Strategy A (nested ref planes) unavailable; use Strategy B.")
else:
    print("  {} nested instance(s) are individually addressable → shared.".format(
        len(sub_ids)))
    shown = 0
    for sid in sub_ids:
        el = doc.GetElement(sid)
        if el is None:
            continue
        try:
            nm = el.Symbol.Family.Name
        except Exception:
            nm = "<family>"
        try:
            cat = el.Category.Name
        except Exception:
            cat = "<cat>"
        # location Z (to confirm we can sort rows vertically)
        z = "?"
        try:
            loc = el.Location
            if hasattr(loc, "Point"):
                z = "{:.4f}".format(loc.Point.Z)
        except Exception:
            pass
        print("")
        print("  • {}  [{}]  id {}  locZ={}".format(
            nm, cat, el.Id.IntegerValue, z))
        if isinstance(el, FamilyInstance):
            probe_references(el, nm)
        shown += 1
        if shown >= 12:
            print("  … ({} more not shown)".format(len(sub_ids) - shown))
            break

# ── Geometry faces (Strategy B fallback data) ─────────────────────────────
print("")
print("── PANEL GEOMETRY FACES (material + orientation) ───────────")
opt = Options()
opt.ComputeReferences = True
opt.IncludeNonVisibleObjects = False
opt.View = view   # references valid in THIS view
try:
    geom = panel.get_Geometry(opt)
except Exception as ex:
    geom = None
    print("  Could not read geometry: {}".format(ex))

face_count = 0
horiz = 0
vert = 0
mats = {}
if geom is not None:
    def walk(geo):
        global face_count, horiz, vert
        for g in geo:
            if isinstance(g, Solid):
                if g.Faces.Size == 0:
                    continue
                for f in g.Faces:
                    if not isinstance(f, PlanarFace):
                        continue
                    face_count += 1
                    n = f.FaceNormal
                    mn = mat_name(doc, f.MaterialElementId)
                    mats[mn] = mats.get(mn, 0) + 1
                    has_ref = f.Reference is not None
                    if abs(n.Z) > 0.7:
                        horiz += 1
                        orient = "HORIZ (faces up/down)"
                    elif abs(n.Z) < 0.3:
                        vert += 1
                        orient = "VERT"
                    else:
                        orient = "angled"
                    if face_count <= 30:
                        print("    face {:<3} {:<22} mat='{}' ref={}".format(
                            face_count, orient, mn, has_ref))
            else:
                # nested geometry instance
                try:
                    inst_geo = g.GetInstanceGeometry()
                    if inst_geo is not None:
                        walk(inst_geo)
                except Exception:
                    pass
    walk(geom)

print("")
print("  Total planar faces: {}  (horizontal={}, vertical={})".format(
    face_count, horiz, vert))
print("  Materials seen:")
for mn, c in sorted(mats.items(), key=lambda kv: -kv[1]):
    print("    '{}': {} face(s)".format(mn, c))

# ── VERDICT ───────────────────────────────────────────────────────────────
print("")
print("══════════════════ VERDICT ════════════════════════════════")
if sub_ids:
    print(" Strategy A (PREFERRED): nested instances are shared.")
    print("   → Collect each nested rebar's CenterLeftRight (or Left/Right)")
    print("     reference, sort by locZ, build one ReferenceArray for the")
    print("     row string. Add panel top/bottom faces as endpoints.")
else:
    print(" Strategy B: nested families not shared.")
    print("   → Filter panel geometry faces by the rebar material, take one")
    print("     horizontal face per row, sort by Z, build the ReferenceArray.")
print("")
print(" Overall dims: use the extreme left/right faces (width) and")
print(" extreme top/bottom faces (height) reported above.")
print("════════════════════════════════════════════════════════════")
