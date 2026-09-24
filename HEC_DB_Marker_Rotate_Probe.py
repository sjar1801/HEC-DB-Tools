# HEC_DB_Marker_Rotate_Probe.py
# Tests whether rotating the OST_Viewers marker element changes a section's ViewDirection.
# This is the key technique from the PyRevit coworker script — we're testing it in Dynamo.
#
# How to run:
#   1. Open any assembly view (so the script can find the assembly)
#   2. Paste into a Dynamo Python Script node and Run
#   3. Check OUT for results
#   4. Ctrl+Z in Revit to undo the test rotation
#
# What it does:
#   - Finds the first detail section view in the active assembly
#   - Scans OST_Viewers for a marker element with the same name (NOT a View subclass)
#   - Reports both IDs to confirm they differ
#   - Rotates the marker 90° around Z through the CropBox origin
#   - Reads ViewDirection back to see if it changed

import clr
import math

clr.AddReference('RevitAPI')
clr.AddReference('RevitServices')

from Autodesk.Revit.DB import *
from RevitServices.Persistence import DocumentManager

doc = DocumentManager.Instance.CurrentDBDocument

lines = []
lines.append("=" * 65)
lines.append("HEC Marker Rotation Probe")
lines.append("Testing OST_Viewers marker rotate approach in Dynamo")
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
    # ViewType 118 = Detail (what AssemblyViewUtils.CreateDetailSection creates)
    all_views = FilteredElementCollector(doc).OfClass(View).ToElements()
    test_view = None
    for v in all_views:
        if v.IsTemplate:
            continue
        try:
            if v.AssociatedAssemblyInstanceId == assem_id:
                if int(v.ViewType) == 118:
                    test_view = v
                    break
        except:
            pass

    if test_view is None:
        lines.append("ERROR: No detail section views found in assembly.")
        OUT = "\n".join(lines)
    else:
        vd_before = test_view.ViewDirection
        bx = vd_before.X
        by = vd_before.Y
        bz = vd_before.Z

        lines.append("\nTest view : '{}'  id={}".format(test_view.Name, test_view.Id.IntegerValue))
        lines.append("ViewDirection BEFORE : ({:.4f}, {:.4f}, {:.4f})".format(bx, by, bz))

        # ── scan OST_Viewers for the marker element ───────────────
        lines.append("\n--- OST_Viewers scan ---")
        viewers = FilteredElementCollector(doc)\
            .OfCategory(BuiltInCategory.OST_Viewers)\
            .WhereElementIsNotElementType()\
            .ToElements()

        marker = None
        viewer_list = list(viewers)
        lines.append("Total OST_Viewers elements: {}".format(len(viewer_list)))

        for e in viewer_list:
            is_view = isinstance(e, View)
            try:
                ename = e.Name
            except:
                ename = "<no name>"
            lines.append("  id={:8d}  IsView={}  type={:30s}  name='{}'".format(
                e.Id.IntegerValue, str(is_view).ljust(5), type(e).__name__, ename))
            # Match by name, exclude View subclasses
            if ename == test_view.Name and not is_view:
                marker = e

        lines.append("")
        if marker is not None:
            same = (marker.Id.IntegerValue == test_view.Id.IntegerValue)
            lines.append("MARKER FOUND: id={}  (view id={})".format(
                marker.Id.IntegerValue, test_view.Id.IntegerValue))
            lines.append("IDs are {}".format(
                "SAME — unexpected, may not work" if same else "DIFFERENT — good, this is a distinct element"))
        else:
            lines.append("No separate marker element found matching '{}'".format(test_view.Name))
            lines.append("Falling back: will rotate the view element itself (id={})".format(
                test_view.Id.IntegerValue))
            marker = test_view

        # ── attempt 90° rotation around Z through CropBox origin ──
        lines.append("\n--- Rotation Test (90° around Z) ---")
        try:
            cb_origin = test_view.CropBox.Transform.Origin
            lines.append("CropBox origin: ({:.4f}, {:.4f}, {:.4f})".format(
                cb_origin.X, cb_origin.Y, cb_origin.Z))

            axis = Line.CreateBound(cb_origin, cb_origin + XYZ.BasisZ)
            angle_rad = math.radians(90.0)

            # Expected result: rotate the ViewDirection vector 90° CCW around Z
            # e.g. (0,-1,0) rotated 90° CCW -> (1,0,0)
            # e.g. (1,0,0) rotated 90° CCW -> (0,1,0)
            exp_x = bx * math.cos(angle_rad) - by * math.sin(angle_rad)
            exp_y = bx * math.sin(angle_rad) + by * math.cos(angle_rad)
            lines.append("Expected ViewDirection after 90° CCW: ({:.4f}, {:.4f}, {:.4f})".format(
                exp_x, exp_y, bz))

            t = Transaction(doc, "Probe: rotate section marker 90 deg")
            t.Start()

            rotate_result = ElementTransformUtils.RotateElement(
                doc, marker.Id, axis, angle_rad)
            doc.Regenerate()

            vd_after = test_view.ViewDirection
            ax = vd_after.X
            ay = vd_after.Y
            az = vd_after.Z

            t.Commit()

            lines.append("\nElementTransformUtils.RotateElement returned: {}".format(rotate_result))
            lines.append("ViewDirection AFTER  : ({:.4f}, {:.4f}, {:.4f})".format(ax, ay, az))

            changed = (abs(ax - bx) > 0.01 or abs(ay - by) > 0.01 or abs(az - bz) > 0.01)
            matched_expected = (abs(ax - exp_x) < 0.01 and abs(ay - exp_y) < 0.01)

            lines.append("")
            if changed and matched_expected:
                lines.append(">>> RESULT: ViewDirection CHANGED and matches expected.")
                lines.append(">>> Marker rotation WORKS in Dynamo! We can use this.")
                lines.append(">>> Ctrl+Z in Revit to undo the test rotation.")
            elif changed:
                lines.append(">>> RESULT: ViewDirection CHANGED but does not match expected rotation math.")
                lines.append(">>> Partial success — investigate further.")
                lines.append(">>> Ctrl+Z in Revit to undo.")
            else:
                lines.append(">>> RESULT: ViewDirection UNCHANGED — marker rotation does NOT work.")
                lines.append(">>> Need a different approach.")

        except Exception as ex:
            try:
                t.RollBack()
            except:
                pass
            lines.append("ERROR during rotation attempt: {}".format(str(ex)))
            import traceback
            lines.append(traceback.format_exc())

        OUT = "\n".join(lines)
