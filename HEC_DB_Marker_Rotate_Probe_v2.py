# HEC_DB_Marker_Rotate_Probe_v2.py
# Fixed: XYZ + XYZ arithmetic replaced with explicit XYZ(x,y,z) constructor
# Also: smarter marker matching — uses the view's assembly to narrow candidates
#
# How to run:
#   1. Open any assembly view (so the script can find the assembly)
#   2. Paste into a Dynamo Python Script node and Run
#   3. Check OUT for results
#   4. Ctrl+Z in Revit to undo the test rotation

import clr
import math

clr.AddReference('RevitAPI')
clr.AddReference('RevitServices')

from Autodesk.Revit.DB import *
from RevitServices.Persistence import DocumentManager

doc = DocumentManager.Instance.CurrentDBDocument

lines = []
lines.append("=" * 65)
lines.append("HEC Marker Rotation Probe v2")
lines.append("=" * 65)

# ── find assembly from active view ────────────────────────────────
active_view = doc.ActiveView
assem_id = None
assem = None

if hasattr(active_view, 'AssociatedAssemblyInstanceId'):
    aid = active_view.AssociatedAssemblyInstanceId
    if aid != ElementId.InvalidElementId:
        assem_id = aid
        assem = doc.GetElement(aid)

if assem is None:
    lines.append("ERROR: No assembly found — open an assembly view first.")
    OUT = "\n".join(lines)
else:
    lines.append("Assembly: {}  id={}".format(
        assem.AssemblyTypeName if hasattr(assem, 'AssemblyTypeName') else "?",
        assem_id.IntegerValue if hasattr(assem_id, 'IntegerValue') else assem_id))

    # ── find a section view in this assembly ──────────────────────
    all_views = FilteredElementCollector(doc).OfClass(View).ToElements()
    test_view = None
    for v in all_views:
        if v.IsTemplate:
            continue
        try:
            if v.AssociatedAssemblyInstanceId == assem_id:
                if int(v.ViewType) == 118:   # 118 = Detail
                    test_view = v
                    break
        except:
            pass

    if test_view is None:
        lines.append("ERROR: No detail section views found in assembly.")
        OUT = "\n".join(lines)
    else:
        vd_before = test_view.ViewDirection
        bx, by, bz = vd_before.X, vd_before.Y, vd_before.Z

        lines.append("Test view : '{}'  id={}".format(test_view.Name, test_view.Id.IntegerValue))
        lines.append("ViewDirection BEFORE : ({:.4f}, {:.4f}, {:.4f})".format(bx, by, bz))

        # ── find the marker with smarter matching ─────────────────
        # Strategy: among all OST_Viewers non-View elements named the same,
        # pick the one whose id is closest to (but greater than) the view id.
        # Assembly view markers are created just after the view element, so
        # their ids are typically just above the view's id.
        lines.append("\n--- Finding marker for view id={} name='{}' ---".format(
            test_view.Id.IntegerValue, test_view.Name))

        viewers = FilteredElementCollector(doc)\
            .OfCategory(BuiltInCategory.OST_Viewers)\
            .WhereElementIsNotElementType()\
            .ToElements()

        candidates = []
        for e in viewers:
            if isinstance(e, View):
                continue
            try:
                ename = e.Name
            except:
                continue
            if ename == test_view.Name:
                candidates.append(e)

        lines.append("Candidates with matching name: {}".format(len(candidates)))
        for c in candidates:
            lines.append("  candidate id={}".format(c.Id.IntegerValue))

        marker = None
        if candidates:
            # Pick the candidate closest to and greater than view id
            view_int = test_view.Id.IntegerValue
            above = [c for c in candidates if c.Id.IntegerValue > view_int]
            if above:
                marker = min(above, key=lambda c: c.Id.IntegerValue)
                lines.append("Picked marker id={} (first above view id {})".format(
                    marker.Id.IntegerValue, view_int))
            else:
                # All below — take the closest one
                marker = max(candidates, key=lambda c: c.Id.IntegerValue)
                lines.append("All candidates below view id — picked closest: id={}".format(
                    marker.Id.IntegerValue))

        if marker is None:
            lines.append("No marker found — rotation test skipped.")
            OUT = "\n".join(lines)
        else:
            same = (marker.Id.IntegerValue == test_view.Id.IntegerValue)
            lines.append("Marker id={}  View id={}  Same={}".format(
                marker.Id.IntegerValue, test_view.Id.IntegerValue, same))

            # ── rotation test ─────────────────────────────────────
            lines.append("\n--- Rotation Test (90° CCW around Z) ---")
            try:
                cb = test_view.CropBox
                cb_origin = cb.Transform.Origin
                lines.append("CropBox origin : ({:.4f}, {:.4f}, {:.4f})".format(
                    cb_origin.X, cb_origin.Y, cb_origin.Z))

                # FIX: CPython XYZ doesn't support + operator — use explicit constructor
                axis_pt1 = cb_origin
                axis_pt2 = XYZ(cb_origin.X, cb_origin.Y, cb_origin.Z + 1.0)
                axis = Line.CreateBound(axis_pt1, axis_pt2)

                angle_rad = math.radians(90.0)

                # Expected result after 90° CCW rotation around Z:
                # (x,y) -> (-y, x)
                exp_x = -by
                exp_y = bx
                lines.append("ViewDirection BEFORE  : ({:.4f}, {:.4f}, {:.4f})".format(bx, by, bz))
                lines.append("Expected after 90 CCW : ({:.4f}, {:.4f}, {:.4f})".format(exp_x, exp_y, bz))

                t = Transaction(doc, "Probe v2: rotate section marker 90 deg CCW")
                t.Start()

                result = ElementTransformUtils.RotateElement(
                    doc, marker.Id, axis, angle_rad)
                doc.Regenerate()

                vd_after = test_view.ViewDirection
                ax, ay, az = vd_after.X, vd_after.Y, vd_after.Z
                t.Commit()

                lines.append("RotateElement returned  : {}".format(result))
                lines.append("ViewDirection AFTER     : ({:.4f}, {:.4f}, {:.4f})".format(ax, ay, az))

                changed = (abs(ax - bx) > 0.01 or abs(ay - by) > 0.01)
                matched = (abs(ax - exp_x) < 0.01 and abs(ay - exp_y) < 0.01)

                lines.append("")
                if changed and matched:
                    lines.append(">>> SUCCESS: ViewDirection changed and matches expected rotation.")
                    lines.append(">>> Marker rotation WORKS in Dynamo CPython!")
                    lines.append(">>> Ctrl+Z in Revit to undo the test rotation.")
                elif changed:
                    lines.append(">>> PARTIAL: ViewDirection changed but doesn't match expected math.")
                    lines.append(">>> Before: ({:.3f},{:.3f})  After: ({:.3f},{:.3f})  Expected: ({:.3f},{:.3f})".format(
                        bx, by, ax, ay, exp_x, exp_y))
                    lines.append(">>> Ctrl+Z in Revit to undo.")
                else:
                    lines.append(">>> FAIL: ViewDirection did not change.")
                    lines.append(">>> RotateElement on this marker has no effect on assembly sections.")

                # ── also check: what is the CropBox origin now? ───
                lines.append("\nPost-rotation CropBox origin: ({:.4f}, {:.4f}, {:.4f})".format(
                    test_view.CropBox.Transform.Origin.X,
                    test_view.CropBox.Transform.Origin.Y,
                    test_view.CropBox.Transform.Origin.Z))

            except Exception as ex:
                try:
                    t.RollBack()
                except:
                    pass
                lines.append("ERROR: {}".format(str(ex)))
                import traceback
                lines.append(traceback.format_exc())

        OUT = "\n".join(lines)
