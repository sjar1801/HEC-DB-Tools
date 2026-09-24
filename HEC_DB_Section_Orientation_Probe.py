# HEC DB Section Orientation Probe
# PURPOSE: Test whether we can re-orient an assembly detail section
#          after creation and keep it nested under the assembly.
#
# PASTE into Dynamo Python Script node (CPython3), run from assembly view.
# Creates 2 sections, tries a different reorientation method on each.
# DELETE both sections afterward — this is a diagnostic, not production.

import clr
import math

clr.AddReference("RevitAPI")
clr.AddReference("RevitServices")
clr.AddReference("RevitNodes")

from Autodesk.Revit.DB import *
from RevitServices.Persistence import DocumentManager
from RevitServices.Transactions import TransactionManager

doc = DocumentManager.Instance.CurrentDBDocument
active_view = doc.ActiveView
results = []

# ── Validate: must be in an assembly view ──
if not hasattr(active_view, "AssociatedAssemblyInstanceId"):
    results.append("ERROR: Active view has no assembly. Open an assembly view first.")
    OUT = "\n".join(results)
else:
    assembly_id = active_view.AssociatedAssemblyInstanceId
    if assembly_id == ElementId.InvalidElementId:
        results.append("ERROR: No assembly associated with active view.")
        OUT = "\n".join(results)
    else:
        assembly_elem = doc.GetElement(assembly_id)
        results.append("Assembly: " + assembly_elem.Name)
        results.append("Assembly ID: " + str(assembly_id.IntegerValue))

        # ── Find ONE panel to test with ──
        TARGET_FAMILIES = [
            "HEC_EF-DB_SIDE_PANEL",
            "HEC_EF-DB_ASPVSF",
            "HEC_NESTED_EF-DB_ASP",
            "HEC_NESTED_EF-DB90_ASP",
        ]

        member_ids = assembly_elem.GetMemberIds()
        test_panel = None
        for mid in member_ids:
            elem = doc.GetElement(mid)
            if elem is None:
                continue
            try:
                fam_name = elem.Symbol.Family.Name
            except:
                continue
            if fam_name in TARGET_FAMILIES:
                test_panel = elem
                break

        if test_panel is None:
            results.append("ERROR: No target panel found in assembly.")
            OUT = "\n".join(results)
        else:
            try:
                fam_name = test_panel.Symbol.Family.Name
            except:
                fam_name = "Unknown"
            results.append("Test panel: " + fam_name +
                           " (ID " + str(test_panel.Id.IntegerValue) + ")")

            # Get panel facing direction for reference
            try:
                facing = test_panel.FacingOrientation
                results.append("Panel FacingOrientation: (" +
                               str(round(facing.X, 3)) + ", " +
                               str(round(facing.Y, 3)) + ", " +
                               str(round(facing.Z, 3)) + ")")
            except Exception as ex:
                results.append("WARNING: Could not get FacingOrientation: " + str(ex))
                facing = None

            TransactionManager.Instance.EnsureInTransaction(doc)

            # ══════════════════════════════════════════════
            # TEST 1: CropBox Transform Overwrite
            # ══════════════════════════════════════════════
            results.append("")
            results.append("═══ TEST 1: CropBox Transform Overwrite ═══")

            try:
                section1 = AssemblyViewUtils.CreateDetailSection(
                    doc, assembly_id,
                    AssemblyDetailViewOrientation.DetailSectionA)
                doc.Regenerate()
                results.append("Section created: " + section1.Name +
                               " (ID " + str(section1.Id.IntegerValue) + ")")

                # Read original transform
                orig_box = section1.CropBox
                orig_transform = orig_box.Transform
                orig_dir = section1.ViewDirection
                results.append("Original ViewDirection: (" +
                               str(round(orig_dir.X, 3)) + ", " +
                               str(round(orig_dir.Y, 3)) + ", " +
                               str(round(orig_dir.Z, 3)) + ")")

                # Build a new BoundingBoxXYZ rotated 45 degrees around Z
                # (just to see if Revit accepts the change)
                angle = math.pi / 4.0  # 45 degrees
                cos_a = math.cos(angle)
                sin_a = math.sin(angle)

                new_right = XYZ(cos_a * orig_transform.BasisX.X - sin_a * orig_transform.BasisX.Y,
                                sin_a * orig_transform.BasisX.X + cos_a * orig_transform.BasisX.Y,
                                orig_transform.BasisX.Z)
                new_up = XYZ(cos_a * orig_transform.BasisY.X - sin_a * orig_transform.BasisY.Y,
                             sin_a * orig_transform.BasisY.X + cos_a * orig_transform.BasisY.Y,
                             orig_transform.BasisY.Z)
                new_fwd = XYZ(cos_a * orig_transform.BasisZ.X - sin_a * orig_transform.BasisZ.Y,
                              sin_a * orig_transform.BasisZ.X + cos_a * orig_transform.BasisZ.Y,
                              orig_transform.BasisZ.Z)

                new_box = BoundingBoxXYZ()
                new_box.Min = orig_box.Min
                new_box.Max = orig_box.Max
                t = Transform.Identity
                t.BasisX = new_right
                t.BasisY = new_up
                t.BasisZ = new_fwd
                t.Origin = orig_transform.Origin
                new_box.Transform = t

                section1.CropBox = new_box
                doc.Regenerate()

                # Check if ViewDirection actually changed
                new_dir = section1.ViewDirection
                results.append("New ViewDirection:      (" +
                               str(round(new_dir.X, 3)) + ", " +
                               str(round(new_dir.Y, 3)) + ", " +
                               str(round(new_dir.Z, 3)) + ")")

                dot_change = abs(orig_dir.X * new_dir.X +
                                 orig_dir.Y * new_dir.Y +
                                 orig_dir.Z * new_dir.Z)
                if dot_change < 0.99:
                    results.append("RESULT: ViewDirection CHANGED — CropBox reorientation WORKS")
                else:
                    results.append("RESULT: ViewDirection UNCHANGED — CropBox reorientation IGNORED by Revit")

                # Check if still nested under assembly
                if hasattr(section1, "AssociatedAssemblyInstanceId"):
                    still_nested = section1.AssociatedAssemblyInstanceId
                    if still_nested == assembly_id:
                        results.append("NESTING: Still under assembly ✓")
                    else:
                        results.append("NESTING: LOST — no longer under assembly ✗")
                else:
                    results.append("NESTING: Cannot check (no AssociatedAssemblyInstanceId)")

            except Exception as ex:
                results.append("TEST 1 ERROR: " + str(ex))

            # ══════════════════════════════════════════════
            # TEST 2: RotateElement
            # ══════════════════════════════════════════════
            results.append("")
            results.append("═══ TEST 2: RotateElement ═══")

            try:
                section2 = AssemblyViewUtils.CreateDetailSection(
                    doc, assembly_id,
                    AssemblyDetailViewOrientation.DetailSectionB)
                doc.Regenerate()
                results.append("Section created: " + section2.Name +
                               " (ID " + str(section2.Id.IntegerValue) + ")")

                orig_dir2 = section2.ViewDirection
                results.append("Original ViewDirection: (" +
                               str(round(orig_dir2.X, 3)) + ", " +
                               str(round(orig_dir2.Y, 3)) + ", " +
                               str(round(orig_dir2.Z, 3)) + ")")

                # Rotation axis: vertical (Z) through the section's origin
                crop2 = section2.CropBox
                origin2 = crop2.Transform.Origin
                axis_line = Line.CreateBound(
                    origin2,
                    XYZ(origin2.X, origin2.Y, origin2.Z + 1.0))

                rotate_angle = math.pi / 4.0  # 45 degrees

                rotated = ElementTransformUtils.RotateElement(
                    doc, section2.Id, axis_line, rotate_angle)
                doc.Regenerate()

                new_dir2 = section2.ViewDirection
                results.append("New ViewDirection:      (" +
                               str(round(new_dir2.X, 3)) + ", " +
                               str(round(new_dir2.Y, 3)) + ", " +
                               str(round(new_dir2.Z, 3)) + ")")

                dot_change2 = abs(orig_dir2.X * new_dir2.X +
                                  orig_dir2.Y * new_dir2.Y +
                                  orig_dir2.Z * new_dir2.Z)
                if dot_change2 < 0.99:
                    results.append("RESULT: ViewDirection CHANGED — RotateElement WORKS")
                else:
                    results.append("RESULT: ViewDirection UNCHANGED — RotateElement IGNORED by Revit")

                # Check nesting
                if hasattr(section2, "AssociatedAssemblyInstanceId"):
                    still_nested2 = section2.AssociatedAssemblyInstanceId
                    if still_nested2 == assembly_id:
                        results.append("NESTING: Still under assembly ✓")
                    else:
                        results.append("NESTING: LOST — no longer under assembly ✗")
                else:
                    results.append("NESTING: Cannot check (no AssociatedAssemblyInstanceId)")

            except Exception as ex:
                results.append("TEST 2 ERROR: " + str(ex))

            TransactionManager.Instance.TransactionTaskDone()

            results.append("")
            results.append("═══ SUMMARY ═══")
            results.append("Delete both test sections when done.")
            results.append("Paste results back so we know which path to take.")

            OUT = "\n".join(results)
