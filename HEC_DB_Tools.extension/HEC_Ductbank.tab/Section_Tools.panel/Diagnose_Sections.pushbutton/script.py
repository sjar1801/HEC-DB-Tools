#! python3
"""HEC Ductbank Diagnose Sections — PyRevit Button  (Diagnostic / Read-Only)

READ-ONLY — this tool never modifies the model.

For every panel in the current assembly, prints:
  - Raw FacingOrientation (X, Y, Z)
  - Negated target direction n (what the section should look at)
  - Panel location point (X, Y, Z) — shows elevation differences
  - Matching section view's current ViewDirection
  - Whether facing has a Z-tilt (non-horizontal panel face)
  - Whether the section is currently aimed correctly
  - CropBox origin vs panel location delta (shows if move landed)

Use this after running Tools 2+3 to diagnose panels where rotation
failed or views came out empty — especially on complex builds with
chimneys, risers, or elevation changes.

PyRevit v6 + CPython 3123  |  Revit 2025
Hunt Electric — MONARCH Job
"""

import math

import clr
clr.AddReference("RevitAPI")
from Autodesk.Revit.DB import (
    BuiltInCategory,
    BuiltInParameter,
    ElementId,
    FilteredElementCollector,
    View,
    XYZ,
)

# ── MARKER LOOKUP (mirrors Rotate tool exactly) ──────────────────────────────

def find_marker_with_method(view):
    """Return (marker_elem_or_None, method_str) for diagnostics.

    Mirrors find_marker() in Rotate tool exactly so we can confirm which
    lookup path fires — dependency graph (ideal) or proximity (fallback).
    """
    viewers_cat_id = ElementId(BuiltInCategory.OST_Viewers)

    # PRIMARY: dependency graph
    try:
        dep_ids = view.GetDependentElements(None)
        for dep_id in dep_ids:
            elem = __revit__.ActiveUIDocument.Document.GetElement(dep_id)  # noqa: F821
            if elem is None:
                continue
            if isinstance(elem, View):
                continue
            try:
                if (elem.Category is not None
                        and elem.Category.Id == viewers_cat_id):
                    return elem, "dependency-graph ✓"
            except Exception:
                continue
    except Exception:
        pass

    # FALLBACK: proximity to CropBox origin
    target_name = view.Name
    try:
        view_origin = view.CropBox.Transform.Origin
    except Exception:
        view_origin = None

    collector = (FilteredElementCollector(__revit__.ActiveUIDocument.Document)  # noqa: F821
                 .OfCategory(BuiltInCategory.OST_Viewers)
                 .WhereElementIsNotElementType()
                 .ToElements())

    candidates = []
    for e in collector:
        if isinstance(e, View):
            continue
        if e.Name != target_name:
            continue
        if view_origin is not None:
            marker_pt = None
            try:
                loc = e.Location
                if hasattr(loc, "Point"):
                    marker_pt = loc.Point
                elif hasattr(loc, "Curve"):
                    marker_pt = loc.Curve.Evaluate(0.5, True)
            except Exception:
                pass
            if marker_pt is not None:
                dx = marker_pt.X - view_origin.X
                dy = marker_pt.Y - view_origin.Y
                candidates.append((math.sqrt(dx * dx + dy * dy), e))
            else:
                candidates.append((1e12, e))
        else:
            return e, "proximity-fallback (no origin)"

    if candidates:
        candidates.sort(key=lambda x: x[0])
        return candidates[0][1], "proximity-fallback ({:.2f}ft)".format(candidates[0][0])

    return None, "NOT FOUND"

# ── PyRevit doc access ──────────────────────────────────────────────────────
uidoc       = __revit__.ActiveUIDocument          # noqa: F821
doc         = uidoc.Document
active_view = doc.ActiveView
# ───────────────────────────────────────────────────────────────────────────

TARGET_FAMILIES = [
    "HEC_EF-DB_SIDE_PANEL",
    "HEC_EF-DB_ASPVSF",
    "HEC_NESTED_EF-DB_ASP",
    "HEC_NESTED_EF-DB90_ASP",
]

AIM_TOLERANCE = 0.01   # radians — same as Rotate tool
Z_TILT_THRESHOLD = 0.05  # |Z| above this → flag as tilted


# ── HELPERS ─────────────────────────────────────────────────────────────────

def safe_family_name(elem):
    """Return family name — handles CPython/PythonNet quirks."""
    try:
        return elem.Symbol.Family.Name
    except Exception:
        pass
    try:
        tid = elem.GetTypeId()
        if tid != ElementId.InvalidElementId:
            etype = doc.GetElement(tid)
            if etype is not None:
                fp = etype.get_Parameter(BuiltInParameter.ALL_MODEL_FAMILY_NAME)
                if fp and fp.HasValue:
                    return fp.AsString()
    except Exception:
        pass
    return None


def dot(a, b):
    return a.X * b.X + a.Y * b.Y + a.Z * b.Z


def vec_str(v):
    """Format an XYZ as a compact string."""
    return "X={:+.4f}  Y={:+.4f}  Z={:+.4f}".format(v.X, v.Y, v.Z)


def pt_str(p):
    """Format a point as a compact string (feet)."""
    return "X={:+.2f}  Y={:+.2f}  Z={:+.2f} ft".format(p.X, p.Y, p.Z)


# ── VALIDATE ASSEMBLY CONTEXT ───────────────────────────────────────────────
print("── HEC Diagnose Sections (READ-ONLY) ──")
print("Active view: {} ({})".format(active_view.Name, active_view.ViewType))

if not hasattr(active_view, "AssociatedAssemblyInstanceId"):
    print("ERROR: Active view has no AssociatedAssemblyInstanceId.")
    print("Open a view that belongs to your ductbank Assembly and run again.")
else:
    assembly_id = active_view.AssociatedAssemblyInstanceId
    if assembly_id == ElementId.InvalidElementId:
        print("ERROR: Active view is not associated with an Assembly.")
        print("Open a view that belongs to your ductbank Assembly and run again.")
    else:
        assembly_elem = doc.GetElement(assembly_id)
        asm_transform = assembly_elem.GetTransform()
        asm_origin    = asm_transform.Origin

        print("Assembly: {}".format(assembly_elem.Name))
        print("Assembly origin: {}".format(pt_str(asm_origin)))
        print("")

        # ── Collect panels ──────────────────────────────────────────────────
        member_ids = assembly_elem.GetMemberIds()
        panels = []
        for mid in member_ids:
            elem = doc.GetElement(mid)
            if elem is None:
                continue
            if safe_family_name(elem) not in TARGET_FAMILIES:
                continue
            cp = elem.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
            if not (cp and cp.HasValue and cp.AsString()):
                continue
            panels.append(elem)

        panels.sort(key=lambda e: e.get_Parameter(
            BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS).AsString())

        print("Panels found: {}".format(len(panels)))

        # ── Build view lookup: name → View (scoped to this assembly) ────────
        view_map = {}
        for v in FilteredElementCollector(doc).OfClass(View).ToElements():
            if v.IsTemplate:
                continue
            if not hasattr(v, "AssociatedAssemblyInstanceId"):
                continue
            if v.AssociatedAssemblyInstanceId != assembly_id:
                continue
            view_map[v.Name] = v

        print("Assembly views found: {}".format(len(view_map)))
        print("")

        # ── Diagnose each panel ─────────────────────────────────────────────
        z_tilt_count = 0
        z_elev_min = None
        z_elev_max = None

        for panel in panels:
            tag = panel.get_Parameter(
                BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS).AsString()
            fname = safe_family_name(panel)

            print("─" * 60)
            print("{} ({})".format(tag, fname))

            # Facing
            facing = None
            try:
                facing = panel.FacingOrientation
            except Exception:
                pass

            if facing is not None:
                n = XYZ(-facing.X, -facing.Y, -facing.Z)
                has_z_tilt = abs(facing.Z) > Z_TILT_THRESHOLD
                if has_z_tilt:
                    z_tilt_count += 1

                print("  Facing (raw):    {}".format(vec_str(facing)))
                print("  Target n:        {}".format(vec_str(n)))
                print("  |Z| in facing:   {:.4f}  → {}".format(
                    abs(facing.Z),
                    "⚠ Z-TILT (non-horizontal face)" if has_z_tilt else "flat (OK)"))
            else:
                n = None
                print("  Facing: NONE — could not read FacingOrientation")

            # Location
            loc_pt = None
            try:
                loc_pt = panel.Location.Point
            except Exception:
                pass

            if loc_pt is not None:
                print("  Location:        {}".format(pt_str(loc_pt)))
                if z_elev_min is None or loc_pt.Z < z_elev_min:
                    z_elev_min = loc_pt.Z
                if z_elev_max is None or loc_pt.Z > z_elev_max:
                    z_elev_max = loc_pt.Z
            else:
                print("  Location: NONE")

            # Matching section view
            view = view_map.get(tag)
            if view is not None:
                vd = view.ViewDirection
                print("  View dir now:    {}".format(vec_str(vd)))

                # Marker lookup — confirm which path fires
                marker, marker_method = find_marker_with_method(view)
                print("  Marker lookup:   {}{}".format(
                    marker_method,
                    " (ID {})".format(marker.Id.IntegerValue) if marker else ""))

                # CropBox origin (where the cut plane sits)
                try:
                    cb_o = view.CropBox.Transform.Origin
                    print("  CropBox origin:  {}".format(pt_str(cb_o)))

                    # Delta from crop box to panel location
                    if loc_pt is not None:
                        dx = loc_pt.X - cb_o.X
                        dy = loc_pt.Y - cb_o.Y
                        dz = loc_pt.Z - cb_o.Z
                        dist_xy = math.sqrt(dx * dx + dy * dy)
                        print("  Delta to panel:  dXY={:.2f}ft  dZ={:.2f}ft".format(
                            dist_xy, dz))
                        if abs(dz) > 0.5:
                            print("                   ⚠ Z-OFFSET: cut plane {:.2f}ft {} panel".format(
                                abs(dz), "below" if dz > 0 else "above"))
                except Exception:
                    print("  CropBox: could not read")

                # Aimed check
                if n is not None:
                    d_val = max(-1.0, min(1.0, dot(vd, n)))
                    angle_off = math.degrees(math.acos(d_val))
                    aimed_ok = abs(math.acos(d_val)) < AIM_TOLERANCE
                    print("  Aimed?           {} (off by {:.2f}°)".format(
                        "YES ✓" if aimed_ok else "NO ✗", angle_off))

                    # Break down the mismatch
                    if not aimed_ok:
                        xy_dot = vd.X * n.X + vd.Y * n.Y
                        xy_mag_vd = math.sqrt(vd.X ** 2 + vd.Y ** 2)
                        xy_mag_n  = math.sqrt(n.X ** 2 + n.Y ** 2)
                        if xy_mag_vd > 1e-6 and xy_mag_n > 1e-6:
                            xy_cos = max(-1.0, min(1.0, xy_dot / (xy_mag_vd * xy_mag_n)))
                            xy_angle = math.degrees(math.acos(xy_cos))
                        else:
                            xy_angle = 0.0
                        z_diff = abs(vd.Z - n.Z)
                        print("  Mismatch detail: XY-angle off={:.2f}°  Z-diff={:.4f}".format(
                            xy_angle, z_diff))
                        if z_diff > 0.01:
                            print("                   ⚠ Z-component mismatch is the culprit")
            else:
                print("  Section view:    NOT FOUND in this assembly")

            print("")

        # ── Summary ─────────────────────────────────────────────────────────
        print("═" * 60)
        print("SUMMARY")
        print("  Panels diagnosed:     {}".format(len(panels)))
        print("  Panels with Z-tilt:   {}".format(z_tilt_count))
        if z_elev_min is not None and z_elev_max is not None:
            z_spread = z_elev_max - z_elev_min
            print("  Elevation range:      {:.2f}ft (min={:.2f} max={:.2f})".format(
                z_spread, z_elev_min, z_elev_max))
            if z_spread > 1.0:
                print("  ⚠ Panels span {:.1f}ft vertically — Z-move may be needed".format(
                    z_spread))
        print("")
        print("If Z-TILT or Z-OFFSET panels appear, the Rotate tool needs")
        print("a 3D rotation fix (not just vertical-axis spin) for those panels.")
        print("")
        print("This tool is READ-ONLY — nothing in the model was changed.")
