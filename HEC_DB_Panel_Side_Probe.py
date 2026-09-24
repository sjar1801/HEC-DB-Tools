# HEC DB Panel Side Probe
# ─────────────────────────────────────────────────────────────
# Diagnostic — run from an assembly 3D-ortho view.
# Reports each panel's position relative to the assembly origin,
# facing direction, and which "side" it falls on.
# This helps determine the correct A vs B section assignment.
# ─────────────────────────────────────────────────────────────

import clr
clr.AddReference("RevitAPI")
clr.AddReference("RevitServices")

from Autodesk.Revit.DB import *
from RevitServices.Persistence import DocumentManager

import math

doc = DocumentManager.Instance.CurrentDBDocument
active_view = doc.ActiveView

TARGET_FAMILIES = [
    "HEC_EF-DB_SIDE_PANEL",
    "HEC_EF-DB_ASPVSF",
    "HEC_NESTED_EF-DB_ASP",
    "HEC_NESTED_EF-DB90_ASP",
]

def safe_family_name(elem):
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

results = []

if not hasattr(active_view, "AssociatedAssemblyInstanceId"):
    results.append("ERROR: Not in an assembly view.")
    OUT = "\n".join(results)
else:
    assembly_id = active_view.AssociatedAssemblyInstanceId
    if assembly_id == ElementId.InvalidElementId:
        results.append("ERROR: No assembly.")
        OUT = "\n".join(results)
    else:
        asm = doc.GetElement(assembly_id)
        asm_t = asm.GetTransform()
        asm_origin = asm_t.Origin
        asm_x = asm_t.BasisX
        asm_y = asm_t.BasisY
        asm_z = asm_t.BasisZ

        results.append("Assembly: " + asm.Name)
        results.append("  Origin: ({:.3f}, {:.3f}, {:.3f})".format(
            asm_origin.X, asm_origin.Y, asm_origin.Z))
        results.append("  BasisX: ({:.3f}, {:.3f}, {:.3f})".format(
            asm_x.X, asm_x.Y, asm_x.Z))
        results.append("  BasisY: ({:.3f}, {:.3f}, {:.3f})".format(
            asm_y.X, asm_y.Y, asm_y.Z))
        results.append("  BasisZ: ({:.3f}, {:.3f}, {:.3f})".format(
            asm_z.X, asm_z.Y, asm_z.Z))
        results.append("")

        member_ids = asm.GetMemberIds()
        panels = []
        for mid in member_ids:
            elem = doc.GetElement(mid)
            if elem is None:
                continue
            fname = safe_family_name(elem)
            if fname not in TARGET_FAMILIES:
                continue
            cp = elem.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
            if cp and cp.HasValue and cp.AsString():
                panels.append(elem)

        def tag_sort_key(e):
            p = e.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
            return p.AsString() if (p and p.HasValue) else ""
        panels.sort(key=tag_sort_key)

        results.append("── Panel Analysis ──")
        results.append("")

        for panel in panels:
            tag = panel.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS).AsString()
            fname = safe_family_name(panel)

            # Get panel location
            loc = panel.Location
            loc_pt = None
            rotation = None
            if hasattr(loc, "Point"):
                loc_pt = loc.Point
            if hasattr(loc, "Rotation"):
                rotation = loc.Rotation

            # Get facing orientation
            facing = None
            try:
                facing = panel.FacingOrientation
            except Exception:
                pass

            # Get hand orientation
            hand = None
            try:
                hand = panel.HandOrientation
            except Exception:
                pass

            results.append(tag + " | " + str(fname))

            if loc_pt:
                results.append("  Location: ({:.3f}, {:.3f}, {:.3f})".format(
                    loc_pt.X, loc_pt.Y, loc_pt.Z))

                # Vector from assembly origin to panel
                dx = loc_pt.X - asm_origin.X
                dy = loc_pt.Y - asm_origin.Y
                dz = loc_pt.Z - asm_origin.Z

                # Project onto assembly local axes
                local_x = dx * asm_x.X + dy * asm_x.Y + dz * asm_x.Z
                local_y = dx * asm_y.X + dy * asm_y.Y + dz * asm_y.Z
                local_z = dx * asm_z.X + dy * asm_z.Y + dz * asm_z.Z
                results.append("  Local offset: X={:.3f}  Y={:.3f}  Z={:.3f}".format(
                    local_x, local_y, local_z))

                # Side determination
                if local_y >= 0:
                    results.append("  Side: +Y (positive)")
                else:
                    results.append("  Side: -Y (negative)")
            else:
                results.append("  Location: N/A")

            if rotation is not None:
                results.append("  Rotation: {:.1f} deg ({:.4f} rad)".format(
                    math.degrees(rotation), rotation))

            if facing:
                results.append("  FacingOrientation: ({:.3f}, {:.3f}, {:.3f})".format(
                    facing.X, facing.Y, facing.Z))

                # Dot with assembly axes (SIGNED, not abs)
                dot_x = facing.X * asm_x.X + facing.Y * asm_x.Y + facing.Z * asm_x.Z
                dot_y = facing.X * asm_y.X + facing.Y * asm_y.Y + facing.Z * asm_y.Z
                results.append("  Facing dot asm_X: {:.3f}  dot asm_Y: {:.3f}".format(
                    dot_x, dot_y))
                results.append("  |dot_X|={:.3f}  |dot_Y|={:.3f}  -> aligned with: {}".format(
                    abs(dot_x), abs(dot_y),
                    "asm_X" if abs(dot_x) >= abs(dot_y) else "asm_Y"))
            else:
                results.append("  FacingOrientation: N/A")

            if hand:
                results.append("  HandOrientation: ({:.3f}, {:.3f}, {:.3f})".format(
                    hand.X, hand.Y, hand.Z))

            results.append("")

        # Report what v7 currently assigns
        results.append("── v7 Assignment (current logic) ──")
        for panel in panels:
            tag = panel.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS).AsString()
            facing = None
            try:
                facing = panel.FacingOrientation
            except Exception:
                pass
            if facing is None:
                try:
                    loc2 = panel.Location
                    if hasattr(loc2, "Rotation"):
                        angle = loc2.Rotation
                        facing = XYZ(math.cos(angle), math.sin(angle), 0)
                except Exception:
                    pass

            if facing is None:
                results.append("  " + tag + " -> A(default) — no facing data")
                continue

            dot_x = abs(facing.X * asm_x.X + facing.Y * asm_x.Y + facing.Z * asm_x.Z)
            dot_y = abs(facing.X * asm_y.X + facing.Y * asm_y.Y + facing.Z * asm_y.Z)

            if dot_x >= dot_y:
                results.append("  " + tag + " -> B (|dot_x|={:.3f} >= |dot_y|={:.3f})".format(dot_x, dot_y))
            else:
                results.append("  " + tag + " -> A (|dot_y|={:.3f} > |dot_x|={:.3f})".format(dot_y, dot_x))

        results.append("")
        results.append("═══ DONE ═══")
        OUT = "\n".join(results)
