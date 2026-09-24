# HEC_DB_Panel_Side_Probe v2
# Comprehensive diagnostic: panel geometry + existing section CropBox data
# Paste into Dynamo Python Script node (no inputs needed)

import clr
import math

clr.AddReference('RevitAPI')
clr.AddReference('RevitServices')
clr.AddReference('System')

from Autodesk.Revit.DB import *
from RevitServices.Persistence import DocumentManager

doc = DocumentManager.Instance.CurrentDBDocument

# ── helpers ──────────────────────────────────────────────────────────────
def fmt(v):
    return "({:.4f}, {:.4f}, {:.4f})".format(v.X, v.Y, v.Z)

def safe_param(el, name):
    p = el.LookupParameter(name)
    if p and p.HasValue:
        if p.StorageType == StorageType.String:
            return p.AsString()
        elif p.StorageType == StorageType.Double:
            return round(p.AsDouble(), 6)
        elif p.StorageType == StorageType.Integer:
            return p.AsInteger()
        elif p.StorageType == StorageType.ElementId:
            return p.AsElementId().IntegerValue
    return None

target_families = [
    "HEC_EF-DB_SIDE_PANEL",
    "HEC_EF-DB_ASPVSF",
    "HEC_NESTED_EF-DB_ASP",
    "HEC_NESTED_EF-DB90_ASP"
]

lines = []
lines.append("=" * 80)
lines.append("HEC DB Panel Side Probe v2 — Comprehensive Diagnostics")
lines.append("=" * 80)

# ── Find active assembly ─────────────────────────────────────────────────
active_view = doc.ActiveView
assem_id = None
assem = None

if hasattr(active_view, 'AssociatedAssemblyInstanceId'):
    aid = active_view.AssociatedAssemblyInstanceId
    if aid != ElementId.InvalidElementId:
        assem_id = aid
        assem = doc.GetElement(aid)

if assem is None:
    # try selected element
    uidoc = DocumentManager.Instance.CurrentUIApplication.ActiveUIDocument
    sel = uidoc.Selection.GetElementIds()
    for eid in sel:
        el = doc.GetElement(eid)
        if isinstance(el, AssemblyInstance):
            assem = el
            assem_id = eid
            break

if assem is None:
    lines.append("ERROR: No assembly found. Open an assembly view or select one.")
    OUT = "\n".join(lines)
else:
    lines.append("Assembly: {} (id {})".format(
        assem.AssemblyTypeName if hasattr(assem, 'AssemblyTypeName') else assem.Name,
        assem_id.IntegerValue if hasattr(assem_id, 'IntegerValue') else assem_id))

    # Assembly transform
    atx = assem.GetTransform()
    lines.append("\n--- Assembly Transform ---")
    lines.append("  Origin : {}".format(fmt(atx.Origin)))
    lines.append("  BasisX : {}".format(fmt(atx.BasisX)))
    lines.append("  BasisY : {}".format(fmt(atx.BasisY)))
    lines.append("  BasisZ : {}".format(fmt(atx.BasisZ)))

    # ── Collect panels ────────────────────────────────────────────────────
    try:
        sub_ids = assem.GetMemberIds()
    except:
        sub_ids = []

    panels = []
    for mid in sub_ids:
        mel = doc.GetElement(mid)
        if mel is None:
            continue
        fi = None
        if isinstance(mel, FamilyInstance):
            fi = mel
        if fi is None:
            continue
        fam_name = fi.Symbol.Family.Name if fi.Symbol and fi.Symbol.Family else ""
        if fam_name not in target_families:
            continue
        cmt = safe_param(fi, "Comments") or "?"
        panels.append((cmt, fi, fam_name))

    # sort by Comments
    def sort_key(t):
        c = t[0]
        try:
            return int(c.split("-")[-1])
        except:
            return c
    panels.sort(key=sort_key)

    lines.append("\n--- Panel Data ({} panels) ---".format(len(panels)))

    inv = atx.Inverse
    for cmt, fi, fam_name in panels:
        lines.append("\n  {} [{}]  (id {})".format(cmt, fam_name, fi.Id.IntegerValue))

        # Location
        loc = fi.Location
        if hasattr(loc, 'Point'):
            pt = loc.Point
            lines.append("    Location (project) : {}".format(fmt(pt)))
            local_pt = inv.OfPoint(pt)
            lines.append("    Location (assembly) : {}".format(fmt(local_pt)))

        # FacingOrientation and HandOrientation
        facing = fi.FacingOrientation
        hand = fi.HandOrientation
        lines.append("    FacingOrientation : {}".format(fmt(facing)))
        lines.append("    HandOrientation   : {}".format(fmt(hand)))

        # Transform to assembly space
        local_facing = inv.OfVector(facing)
        local_hand = inv.OfVector(hand)
        lines.append("    Facing (assembly) : {}".format(fmt(local_facing)))
        lines.append("    Hand   (assembly) : {}".format(fmt(local_hand)))

        # Dot products (facing in assembly space)
        dot_x = local_facing.X
        dot_y = local_facing.Y
        dot_z = local_facing.Z
        lines.append("    Facing dots: X={:.4f}  Y={:.4f}  Z={:.4f}".format(dot_x, dot_y, dot_z))

        # Hand dot products
        hdot_x = local_hand.X
        hdot_y = local_hand.Y
        hdot_z = local_hand.Z
        lines.append("    Hand   dots: X={:.4f}  Y={:.4f}  Z={:.4f}".format(hdot_x, hdot_y, hdot_z))

        # Rotation angle
        angle_rad = math.atan2(local_facing.Y, local_facing.X)
        angle_deg = math.degrees(angle_rad)
        lines.append("    Rotation angle: {:.1f} deg".format(angle_deg))

        # Bounding box
        bb = fi.get_BoundingBox(None)
        if bb:
            bmin = bb.Min
            bmax = bb.Max
            center = XYZ((bmin.X+bmax.X)/2, (bmin.Y+bmax.Y)/2, (bmin.Z+bmax.Z)/2)
            size = XYZ(bmax.X-bmin.X, bmax.Y-bmin.Y, bmax.Z-bmin.Z)
            lines.append("    BBox center : {}".format(fmt(center)))
            lines.append("    BBox size   : {}".format(fmt(size)))
            # aspect clue: which dimension is smallest = thickness direction
            dims = [("X", abs(size.X)), ("Y", abs(size.Y)), ("Z", abs(size.Z))]
            dims.sort(key=lambda d: d[1])
            lines.append("    BBox thin axis: {} ({:.4f} ft)".format(dims[0][0], dims[0][1]))
        else:
            lines.append("    BBox: None")

        # Version comparison
        abs_dx = abs(dot_x)
        abs_dy = abs(dot_y)
        v7b_pick = "A" if dot_y > 0 else "B"
        v7e_pick = "A" if abs_dy >= abs_dx else "B"
        lines.append("    v7b would pick: {}  |  v7e would pick: {}".format(v7b_pick, v7e_pick))

    # ── Existing assembly views & section CropBox data ────────────────────
    lines.append("\n" + "=" * 80)
    lines.append("--- Existing Assembly Views ---")

    all_views = FilteredElementCollector(doc).OfClass(View).ToElements()
    assem_views = []
    for v in all_views:
        if v.IsTemplate:
            continue
        try:
            if hasattr(v, 'AssociatedAssemblyInstanceId'):
                if v.AssociatedAssemblyInstanceId == assem_id:
                    assem_views.append(v)
        except:
            pass

    lines.append("Found {} assembly views".format(len(assem_views)))

    for v in assem_views:
        vtype = v.ViewType if hasattr(v, 'ViewType') else "?"
        vname = v.Name if hasattr(v, 'Name') else "?"
        lines.append("\n  View: '{}' (type={}, id={})".format(vname, vtype, v.Id.IntegerValue))

        # CropBox info
        try:
            cb = v.CropBox
            lines.append("    CropBox.Min    : {}".format(fmt(cb.Min)))
            lines.append("    CropBox.Max    : {}".format(fmt(cb.Max)))
            cbt = cb.Transform
            lines.append("    CropBox Origin : {}".format(fmt(cbt.Origin)))
            lines.append("    CropBox BasisX : {}".format(fmt(cbt.BasisX)))
            lines.append("    CropBox BasisY : {}".format(fmt(cbt.BasisY)))
            lines.append("    CropBox BasisZ : {}".format(fmt(cbt.BasisZ)))
        except Exception as ex:
            lines.append("    CropBox error: {}".format(str(ex)))

        # ViewDirection and RightDirection
        try:
            vd = v.ViewDirection
            lines.append("    ViewDirection  : {}".format(fmt(vd)))
        except:
            pass
        try:
            rd = v.RightDirection
            lines.append("    RightDirection : {}".format(fmt(rd)))
        except:
            pass
        try:
            ud = v.UpDirection
            lines.append("    UpDirection    : {}".format(fmt(ud)))
        except:
            pass

        # View template
        vt_id = v.ViewTemplateId
        if vt_id != ElementId.InvalidElementId:
            vt = doc.GetElement(vt_id)
            vtname = vt.Name if vt else "?"
            lines.append("    ViewTemplate   : '{}'".format(vtname))

        # Filters on this view
        try:
            fids = v.GetFilters()
            lines.append("    Filters: {} total".format(len(fids)))
            for fid in fids:
                fel = doc.GetElement(fid)
                fname = fel.Name if fel else "?"
                vis = v.GetFilterVisibility(fid)
                lines.append("      - '{}' visible={}".format(fname, vis))
        except:
            pass

    # ── Summary: Decision Matrix ──────────────────────────────────────────
    lines.append("\n" + "=" * 80)
    lines.append("--- Decision Matrix ---")
    lines.append("Panel       | Facing(asm)            | v7b | v7e | v7b_result | v7e_result")
    lines.append("-" * 85)
    for cmt, fi, fam_name in panels:
        facing = fi.FacingOrientation
        lf = inv.OfVector(facing)
        dx, dy = lf.X, lf.Y
        adx, ady = abs(dx), abs(dy)
        v7b = "A" if dy > 0 else "B"
        v7e = "A" if ady >= adx else "B"
        lines.append("{:<12}| ({:+.3f},{:+.3f})          | {}   | {}   |            |".format(
            cmt, dx, dy, v7b, v7e))

    lines.append("\nFill in v7b_result and v7e_result with: OK, narrow, blank, wrong")
    lines.append("This tells us exactly which orientation works for each facing direction.")

    lines.append("\n" + "=" * 80)
    lines.append("END OF PROBE v2")

    OUT = "\n".join(lines)
