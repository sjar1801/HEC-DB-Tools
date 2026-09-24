# HEC DB Horizontal Detail Probe
# PURPOSE: Test whether a HorizontalDetail section acts as a plan-like view
#          and whether other detail section markers are visible on it.
#
# PASTE into Dynamo Python Script node (CPython3), run from assembly view.
# Creates 2 views: one HorizontalDetail + one DetailSectionA.
# Check visually: does the horizontal view show a section cut line?
# DELETE both views afterward — this is a diagnostic.

import clr

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

        TransactionManager.Instance.EnsureInTransaction(doc)

        # ══════════════════════════════════════════════
        # STEP 1: Create a DetailSectionA
        # ══════════════════════════════════════════════
        results.append("")
        results.append("═══ STEP 1: Create DetailSectionA ═══")

        section_a = None
        try:
            section_a = AssemblyViewUtils.CreateDetailSection(
                doc, assembly_id,
                AssemblyDetailViewOrientation.DetailSectionA)
            doc.Regenerate()
            results.append("Created: " + section_a.Name +
                           " (ID " + str(section_a.Id.IntegerValue) + ")")
            results.append("ViewDirection: (" +
                           str(round(section_a.ViewDirection.X, 3)) + ", " +
                           str(round(section_a.ViewDirection.Y, 3)) + ", " +
                           str(round(section_a.ViewDirection.Z, 3)) + ")")
        except Exception as ex:
            results.append("ERROR creating DetailSectionA: " + str(ex))

        # ══════════════════════════════════════════════
        # STEP 2: Create a HorizontalDetail
        # ══════════════════════════════════════════════
        results.append("")
        results.append("═══ STEP 2: Create HorizontalDetail ═══")

        horiz_view = None
        try:
            horiz_view = AssemblyViewUtils.CreateDetailSection(
                doc, assembly_id,
                AssemblyDetailViewOrientation.HorizontalDetail)
            doc.Regenerate()
            results.append("Created: " + horiz_view.Name +
                           " (ID " + str(horiz_view.Id.IntegerValue) + ")")
            results.append("ViewDirection: (" +
                           str(round(horiz_view.ViewDirection.X, 3)) + ", " +
                           str(round(horiz_view.ViewDirection.Y, 3)) + ", " +
                           str(round(horiz_view.ViewDirection.Z, 3)) + ")")
            results.append("ViewType: " + str(horiz_view.ViewType))

            # Check if it's nested under assembly
            if hasattr(horiz_view, "AssociatedAssemblyInstanceId"):
                assoc = horiz_view.AssociatedAssemblyInstanceId
                if assoc == assembly_id:
                    results.append("NESTING: Under assembly ✓")
                else:
                    results.append("NESTING: NOT under assembly ✗")

            # Check crop box info
            if horiz_view.CropBoxActive:
                cb = horiz_view.CropBox
                results.append("CropBox Min: (" +
                               str(round(cb.Min.X, 2)) + ", " +
                               str(round(cb.Min.Y, 2)) + ", " +
                               str(round(cb.Min.Z, 2)) + ")")
                results.append("CropBox Max: (" +
                               str(round(cb.Max.X, 2)) + ", " +
                               str(round(cb.Max.Y, 2)) + ", " +
                               str(round(cb.Max.Z, 2)) + ")")
            else:
                results.append("CropBox: Not active")

        except Exception as ex:
            results.append("ERROR creating HorizontalDetail: " + str(ex))

        TransactionManager.Instance.TransactionTaskDone()

        # ══════════════════════════════════════════════
        # INSTRUCTIONS
        # ══════════════════════════════════════════════
        results.append("")
        results.append("═══ WHAT TO CHECK VISUALLY ═══")
        results.append("1. Find the HorizontalDetail view in project browser")
        results.append("   (should be under the assembly)")
        results.append("2. Open it — does it look like a plan/top-down view?")
        results.append("3. Do you see the DetailSectionA cut line on it?")
        results.append("4. Screenshot and paste back here")
        results.append("")
        results.append("Delete both views when done testing.")

        OUT = "\n".join(results)
