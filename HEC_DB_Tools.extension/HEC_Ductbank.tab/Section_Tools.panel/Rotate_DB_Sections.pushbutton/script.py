#! python3
"""HEC Ductbank Rotate Sections — PyRevit Button  (Tool 3 of 4)

Prerequisites:
  - "Assign Panel IDs"   (Tool 1) — Comments must be populated
  - "Create DB Sections" (Tool 2) — section views must exist, named Panel-XXX

What this tool does:
  - For every section view named "Panel-XXX" in this assembly:
      1. Reads the panel's FacingOrientation as the target view direction (n)
      2. Finds the OST_Viewers marker element for that section
         (coworker's technique — rotate the MARKER, not the View object)
      3. Rotates the marker about a vertical axis so the section faces
         the panel correctly — works for ANY angle, not just 90° increments
      4. Moves the marker in XY so the cut plane is centred on the panel's
         location point — fixes blank/clipped views in non-uniform ductbanks
         (L-shapes, offsets) where the assembly centre ≠ panel position
      5. Verifies the resulting ViewDirection matches target n and reports

What this tool does NOT do:
  - Crop/resize sections  (filters isolate each panel — no tight crop needed)
  - Place views on sheets → Tool 4 (Place On Sheets)

Technique credit: coworker's PyRevit script (Sept 2026) — find the OST_Viewers
marker and RotateElement/MoveElement on it, not on the View object itself.

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
    ElementTransformUtils,
    FilteredElementCollector,
    FamilyInstance,
    Line,
    Transaction,
    TransactionGroup,
    View,
    XYZ,
)

# ── PyRevit doc access ──────────────────────────────────────────────────────
uidoc       = __revit__.ActiveUIDocument          # noqa: F821
doc         = uidoc.Document
active_view = doc.ActiveView
# ───────────────────────────────────────────────────────────────────────────

# ── CONFIG ──────────────────────────────────────────────────────────────────
TARGET_FAMILIES = [
    "HEC_EF-DB_SIDE_PANEL",
    "HEC_EF-DB_ASPVSF",
    "HEC_NESTED_EF-DB_ASP",
    "HEC_NESTED_EF-DB90_ASP",
]

AIM_TOLERANCE   = 0.01   # radians — ~0.6°, forgiving of Revit rounding
MOVE_THRESHOLD  = 0.1    # ft — skip move if cut plane already close enough
ANGLED_THRESHOLD = 0.9   # |dot| below this on both axes → flag as angled panel
# ───────────────────────────────────────────────────────────────────────────


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


def get_facing(panel):
    """Return panel FacingOrientation, or fallback from LocationPoint rotation."""
    try:
        f = panel.FacingOrientation
        if f is not None:
            return f
    except Exception:
        pass
    try:
        loc = panel.Location
        if hasattr(loc, "Rotation"):
            a = loc.Rotation
            return XYZ(math.cos(a), math.sin(a), 0.0)
    except Exception:
        pass
    return None


def is_angled(n):
    """True if the facing vector is not strongly aligned to X or Y axis."""
    dot_x = abs(n.X)
    dot_y = abs(n.Y)
    return max(dot_x, dot_y) < ANGLED_THRESHOLD


def find_marker(view):
    """Find the OST_Viewers marker element whose name matches the view.
    
    This is the coworker's core technique:
    The marker element has a DIFFERENT ElementId than the View object itself.
    RotateElement/MoveElement on the View object is silently ignored in Revit.
    RotateElement/MoveElement on the MARKER actually works.
    
    Match by Name AND exclude View instances (the view itself is also named
    the same — we want the non-View element in OST_Viewers).
    """
    target_name = view.Name
    collector = (FilteredElementCollector(doc)
                 .OfCategory(BuiltInCategory.OST_Viewers)
                 .WhereElementIsNotElementType()
                 .ToElements())
    for e in collector:
        if e.Name == target_name and not isinstance(e, View):
            return e
    return None


def dot(a, b):
    """Scalar dot product of two XYZ vectors."""
    return a.X * b.X + a.Y * b.Y + a.Z * b.Z


def cross_z(a, b):
    """Z component of cross product a × b (the only component we need for plan rotation)."""
    return a.X * b.Y - a.Y * b.X


def signed_plan_angle(vd, n):
    """Signed angle (radians) to rotate vd onto n about the Z axis.
    
    Uses atan2 like the coworker — correct for ANY angle, not just 90° increments.
    Positive = counterclockwise when viewed from above.
    """
    return math.atan2(cross_z(vd, n), dot(vd, n))


def aimed(view, n):
    """True if the view is already looking in direction n (within AIM_TOLERANCE)."""
    vd = view.ViewDirection
    # angle between the two unit vectors
    d = max(-1.0, min(1.0, dot(vd, n)))   # clamp for acos safety
    return abs(math.acos(d)) < AIM_TOLERANCE


# ── VALIDATE ASSEMBLY CONTEXT ───────────────────────────────────────────────
print("── HEC Rotate DB Sections ──")
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
        print("Assembly: {}".format(assembly_elem.Name))

        # ── Build panel lookup: Comments value → (panel element, FacingOrientation) ──
        member_ids = assembly_elem.GetMemberIds()
        panel_map  = {}   # "Panel-001" → (elem, facing XYZ, loc XYZ)

        for mid in member_ids:
            elem = doc.GetElement(mid)
            if elem is None:
                continue
            if safe_family_name(elem) not in TARGET_FAMILIES:
                continue
            cp = elem.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
            if not (cp and cp.HasValue and cp.AsString()):
                continue
            tag = cp.AsString()

            facing = get_facing(elem)
            if facing is None:
                print("  WARNING: No facing for {} — will skip".format(tag))
                continue

            # FacingOrientation points AWAY from the viewer (the direction the panel
            # face pushes outward). A section must look in the OPPOSITE direction to
            # see the face from the front — so we negate it here.
            n = XYZ(-facing.X, -facing.Y, -facing.Z)

            # Panel location point (for move step)
            try:
                loc_pt = elem.Location.Point
            except Exception:
                loc_pt = None

            panel_map[tag] = (elem, n, loc_pt)

        print("Panels with facing data: {}".format(len(panel_map)))

        if not panel_map:
            print("ERROR: No panels with Comments IDs and facing data found.")
            print("Run Tool 1 (Assign Panel IDs) then Tool 2 (Create Sections) first.")
        else:
            # ── Collect section views named "Panel-XXX" in this assembly ──
            all_views = FilteredElementCollector(doc).OfClass(View).ToElements()
            section_views = []
            for v in all_views:
                if v.IsTemplate:
                    continue
                if v.Name in panel_map:
                    section_views.append(v)

            if not section_views:
                print("ERROR: No section views found matching panel names.")
                print("Run Tool 2 (Create Sections) first.")
            else:
                section_views.sort(key=lambda v: v.Name)
                print("Section views to rotate: {}".format(len(section_views)))
                print("")
                print("── Rotating sections ──")

                results = []  # (tag, aimed_ok, how, angle_deg, notes)

                tg = TransactionGroup(doc, "HEC Rotate DB Sections")
                tg.Start()

                for view in section_views:
                    tag = view.Name
                    _elem, n, loc_pt = panel_map[tag]

                    t = Transaction(doc, "Rotate {}".format(tag))
                    t.Start()
                    notes = []
                    how   = "no rotation needed"

                    try:
                        # ── Step 1: Find the OST_Viewers marker ──────────────
                        marker = find_marker(view)
                        if marker is None:
                            notes.append("marker not found — fell back to view element")
                        target = marker if marker is not None else view

                        # ── Step 2: Read current state ────────────────────────
                        vd     = view.ViewDirection
                        cb_o   = view.CropBox.Transform.Origin

                        # ── Step 3: Rotate ────────────────────────────────────
                        angle = signed_plan_angle(vd, n)
                        angle_deg = math.degrees(angle)

                        if abs(angle) > 1e-6:
                            # Vertical axis through the cut plane origin.
                            # IMPORTANT: use explicit XYZ constructor — o + XYZ.BasisZ
                            # fails in CPython/PythonNet (no __add__ on XYZ).
                            axis_pt1 = cb_o
                            axis_pt2 = XYZ(cb_o.X, cb_o.Y, cb_o.Z + 1.0)
                            axis     = Line.CreateBound(axis_pt1, axis_pt2)

                            ElementTransformUtils.RotateElement(
                                doc, target.Id, axis, angle)
                            doc.Regenerate()
                            how = "rotated {:.2f}°".format(angle_deg)
                        else:
                            how = "already aimed — no rotation"
                            angle_deg = 0.0

                        # ── Step 4: Move cut plane to panel location (XY only) ─
                        # Re-read origin AFTER rotation (it may have shifted slightly)
                        cb_o_after = view.CropBox.Transform.Origin

                        if loc_pt is not None:
                            delta = XYZ(
                                loc_pt.X - cb_o_after.X,
                                loc_pt.Y - cb_o_after.Y,
                                0.0   # Z unchanged — assembly sets vertical extents
                            )
                            dist = math.sqrt(delta.X ** 2 + delta.Y ** 2)

                            if dist > MOVE_THRESHOLD:
                                ElementTransformUtils.MoveElement(
                                    doc, target.Id, delta)
                                doc.Regenerate()
                                how += " | moved {:.2f}ft to panel centre".format(dist)
                            else:
                                how += " | already centred (delta {:.3f}ft)".format(dist)
                        else:
                            notes.append("no location point — skipped move")

                        # ── Step 5: Verify ────────────────────────────────────
                        aimed_ok = aimed(view, n)
                        t.Commit()

                    except Exception as ex:
                        t.RollBack()
                        aimed_ok  = False
                        how       = "EXCEPTION"
                        angle_deg = 0.0
                        notes.append(str(ex))

                    # Flag angled panels
                    is_ang = is_angled(n)
                    if is_ang:
                        notes.append("⚠ ANGLED PANEL — verify manually")

                    results.append((tag, aimed_ok, how, angle_deg, notes))

                tg.Assimilate()

                # ── Print results table ───────────────────────────────────────
                print("")
                print("{:<14} {:<8} {:<10} {}".format(
                    "View", "Aimed?", "Angle", "Notes / How"))
                print("─" * 72)

                ok_count     = 0
                failed_count = 0
                angled_count = 0

                for tag, aimed_ok, how, angle_deg, notes in results:
                    status = "YES ✓" if aimed_ok else "NO ✗"
                    note_str = " | ".join(notes) if notes else ""
                    print("{:<14} {:<8} {:>+8.2f}°  {}".format(
                        tag, status, angle_deg, how))
                    if note_str:
                        print("{:<14} {:<8} {:>9}  {}".format(
                            "", "", "", note_str))

                    if aimed_ok:
                        ok_count += 1
                    else:
                        failed_count += 1
                    if any("ANGLED" in n for n in notes):
                        angled_count += 1

                print("")
                print("═══ DONE ═══")
                print("Aimed correctly: {}/{}".format(ok_count, len(results)))
                if failed_count:
                    print("⚠ Failed: {} — check output above".format(failed_count))
                if angled_count:
                    print("⚠ Angled panels (spot-check): {}".format(angled_count))
                print("")
                print("Next: Run 'Place On Sheets' (Tool 4) to create and populate the sheet.")
