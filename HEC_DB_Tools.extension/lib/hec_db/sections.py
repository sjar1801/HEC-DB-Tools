"""hec_db.sections — Tool 2 (Create DB Sections) and Tool 3 (Rotate DB Sections).

create_sections(doc, active_view):
  - Reads panel Comments IDs (Panel-001, Panel-002 …)
  - Creates one AssemblyDetailSection per panel named to match its ID
  - Adds a NOT-EQUALS filter per section to isolate only that panel
  - Applies view template SECTION_TEMPLATE_NAME to every section
  - Creates one HorizontalDetail (Plan Detail) with PLAN_TEMPLATE_NAME

rotate_sections(doc, active_view):
  - For every section view named "Panel-XXX" in this assembly, finds the
    OST_Viewers marker, rotates it to face the panel (any angle), moves the
    cut plane onto the panel's location point, and verifies the result.
  Technique credit: coworker's PyRevit script (Sept 2026) — rotate the
  MARKER, not the View object.

PyRevit v6 + CPython 3123  |  Revit 2025
Hunt Electric — MONARCH Job
"""

import math

import clr
clr.AddReference("RevitAPI")
from Autodesk.Revit.DB import (
    FilteredElementCollector,
    BuiltInParameter,
    BuiltInCategory,
    Transaction,
    TransactionGroup,
    ElementId,
    ElementTransformUtils,
    AssemblyViewUtils,
    AssemblyDetailViewOrientation,
    ParameterFilterElement,
    ParameterFilterRuleFactory,
    ElementParameterFilter,
    Line,
    View,
    XYZ,
)

from System.Collections.Generic import List

from hec_db.constants import (
    TARGET_FAMILIES, SECTION_TEMPLATE_NAME, PLAN_TEMPLATE_NAME,
    AIM_TOLERANCE, MOVE_THRESHOLD, ANGLED_THRESHOLD,
)
from hec_db.utils import safe_family_name, find_view_template


# ═══════════════════════════════════════════════════════════════════════════
# TOOL 2 — CREATE DB SECTIONS
# ═══════════════════════════════════════════════════════════════════════════

def get_panel_facing_direction(panel):
    """Get the panel facing direction from FacingOrientation or location rotation."""
    try:
        facing = panel.FacingOrientation
        if facing is not None:
            return facing
    except Exception:
        pass
    try:
        loc = panel.Location
        if hasattr(loc, "Rotation"):
            angle = loc.Rotation
            return XYZ(math.cos(angle), math.sin(angle), 0)
    except Exception:
        pass
    return None


def choose_section_orientation(panel, asm_transform):
    """Return (AssemblyDetailViewOrientation, label, is_angled).

    Logic (mirrors Dynamo v7):
      Panel faces along assembly Y → SectionA (cuts perpendicular to Y)
      Panel faces along assembly X → SectionB (cuts perpendicular to X)
    Panels facing ±Y both get SectionA (same cut plane, transparency handles it).
    """
    facing = get_panel_facing_direction(panel)
    if facing is None:
        return AssemblyDetailViewOrientation.DetailSectionA, "A(default)", False

    asm_x = asm_transform.BasisX
    asm_y = asm_transform.BasisY

    dot_x = abs(facing.X * asm_x.X + facing.Y * asm_x.Y + facing.Z * asm_x.Z)
    dot_y = abs(facing.X * asm_y.X + facing.Y * asm_y.Y + facing.Z * asm_y.Z)

    max_dot = max(dot_x, dot_y)
    is_angled = max_dot < 0.9
    label = "|dX|={:.2f} |dY|={:.2f}".format(dot_x, dot_y)

    if dot_y >= dot_x:
        return AssemblyDetailViewOrientation.DetailSectionA, "A({})".format(label), is_angled
    else:
        return AssemblyDetailViewOrientation.DetailSectionB, "B({})".format(label), is_angled


def section_exists(doc, name, assembly_id):
    """Return True if a view with this name already exists IN THIS ASSEMBLY.

    Scoped to the assembly so running on DB-2 never matches DB-1's views
    (both start from Panel-001, Panel-002 … but belong to different assemblies).
    """
    for v in FilteredElementCollector(doc).OfClass(View):
        if v.IsTemplate:
            continue
        if v.Name != name:
            continue
        if not hasattr(v, "AssociatedAssemblyInstanceId"):
            continue
        if v.AssociatedAssemblyInstanceId == assembly_id:
            return True
    return False


def get_or_create_filter(doc, filter_name, category_id, param_id, value):
    """Create a NOT-EQUALS ParameterFilterElement for the given string value.
    Returns the filter ElementId, or None on failure.
    Revit 2025: CreateNotEqualsRule(ElementId, String) — 2-arg form (3-arg is obsolete).
    """
    # Reuse if already exists
    for f in FilteredElementCollector(doc).OfClass(ParameterFilterElement):
        if f.Name == filter_name:
            return f.Id

    cats = List[ElementId]()
    cats.Add(category_id)

    try:
        # Revit 2025 2-arg form — no case sensitivity boolean
        rule = ParameterFilterRuleFactory.CreateNotEqualsRule(param_id, value)
        elem_filter = ElementParameterFilter(rule)
        pfe = ParameterFilterElement.Create(doc, filter_name, cats, elem_filter)
        return pfe.Id
    except Exception as ex:
        print("  Filter creation failed for {}: {}".format(filter_name, ex))
        return None


def create_sections(doc, active_view):
    """Tool 2 orchestrator. Creates one detail section per tagged panel plus a
    Plan Detail for the assembly that *active_view* belongs to.

    Manages its own Transaction. Prints progress. Returns a stats dict:
      {"status": "ok"|"error", "sections": n, "a_count": n, "b_count": n,
       "plan_detail": bool}
    """
    stats = {"status": "error", "sections": 0, "a_count": 0, "b_count": 0,
             "plan_detail": False}

    # ── VALIDATE ASSEMBLY CONTEXT ──────────────────────────────────────────
    print("── HEC Create DB Sections ──")
    print("Active view: {} ({})".format(active_view.Name, active_view.ViewType))

    if not hasattr(active_view, "AssociatedAssemblyInstanceId"):
        print("ERROR: Active view has no AssociatedAssemblyInstanceId.")
        print("Open a view that belongs to your ductbank Assembly and run again.")
        return stats

    assembly_id = active_view.AssociatedAssemblyInstanceId
    if assembly_id == ElementId.InvalidElementId:
        print("ERROR: Active view is not associated with an Assembly.")
        print("Open a view that belongs to your ductbank Assembly and run again.")
        return stats

    assembly_elem = doc.GetElement(assembly_id)
    asm_transform = assembly_elem.GetTransform()
    print("Assembly: {}".format(assembly_elem.Name))

    # ── Collect panels with Comments assigned ──────────────────────────────
    member_ids = assembly_elem.GetMemberIds()
    panels = []
    for mid in member_ids:
        elem = doc.GetElement(mid)
        if elem is None:
            continue
        fname = safe_family_name(doc, elem)
        if fname not in TARGET_FAMILIES:
            continue
        cp = elem.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
        if cp and cp.HasValue and cp.AsString():
            panels.append(elem)

    if not panels:
        print("ERROR: No panels with Comments IDs found in this assembly.")
        print("Run 'Assign Panel IDs' (Tool 1) first, then come back.")
        return stats

    # Sort by Comments value so sections are created in order
    def tag_key(e):
        p = e.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
        return p.AsString() if (p and p.HasValue) else ""
    panels.sort(key=tag_key)
    print("Panels found: {}".format(len(panels)))

    # Look up templates
    section_template = find_view_template(doc, SECTION_TEMPLATE_NAME)
    plan_template    = find_view_template(doc, PLAN_TEMPLATE_NAME)
    print("Section template: {}".format(
        SECTION_TEMPLATE_NAME if section_template else "NOT FOUND — will skip"))
    print("Plan template:    {}".format(
        PLAN_TEMPLATE_NAME if plan_template else "NOT FOUND — will skip"))

    # Filter params
    comments_param_id  = ElementId(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
    elec_fix_cat_id    = ElementId(BuiltInCategory.OST_ElectricalFixtures)

    print("")
    print("── Creating detail sections ──")

    section_views = []
    a_count = 0
    b_count = 0

    t = Transaction(doc, "HEC Create DB Sections")
    t.Start()

    for panel in panels:
        tag   = panel.get_Parameter(
            BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS).AsString()
        fname = safe_family_name(doc, panel)

        # Skip if section with this name already exists IN THIS ASSEMBLY
        if section_exists(doc, tag, assembly_id):
            print("  SKIP: View '{}' already exists in this assembly".format(tag))
            continue

        try:
            # Choose orientation based on panel facing vs assembly axes
            orientation, orient_label, is_angled = choose_section_orientation(
                panel, asm_transform)
            if orient_label.startswith("A"):
                a_count += 1
            else:
                b_count += 1

            # Create the assembly detail section
            section_view = AssemblyViewUtils.CreateDetailSection(
                doc, assembly_id, orientation)
            doc.Regenerate()

            # Name the view to match the panel ID
            try:
                section_view.Name = tag
            except Exception as name_ex:
                print("  WARNING: Could not rename view to '{}': {}".format(
                    tag, name_ex))

            # Add NOT-EQUALS filter (hides all panels EXCEPT this one)
            filter_name = "HideExcept_{}".format(tag)
            filter_id = get_or_create_filter(
                doc, filter_name, elec_fix_cat_id, comments_param_id, tag)

            filter_applied = False
            if filter_id is not None:
                try:
                    section_view.AddFilter(filter_id)
                    section_view.SetFilterVisibility(filter_id, False)
                    filter_applied = True
                except Exception as fex:
                    print("  WARNING: Filter apply failed for {}: {}".format(
                        tag, fex))

            # Apply section view template
            # Note: template may lock filter settings — that's expected
            if section_template is not None:
                try:
                    section_view.ViewTemplateId = section_template.Id
                    doc.Regenerate()
                except Exception as tex:
                    print("  WARNING: Template apply failed for {}: {}".format(
                        tag, tex))

            section_views.append(section_view)

            status = "  OK: {} | {} | Orient:{} | Filter:{}".format(
                tag, fname, orient_label,
                "yes" if filter_applied else "NO")
            if is_angled:
                status += " | ⚠ ANGLED"
            print(status)

        except Exception as ex:
            print("  ERROR on {}: {}".format(tag, ex))

    # ── Create Plan Detail (HorizontalDetail) ──────────────────────────────
    print("")
    print("── Creating Plan Detail ──")
    plan_detail = None
    plan_name   = "Plan Detail"

    if section_exists(doc, plan_name, assembly_id):
        print("  SKIP: '{}' already exists in this assembly".format(plan_name))
    else:
        try:
            plan_detail = AssemblyViewUtils.CreateDetailSection(
                doc, assembly_id,
                AssemblyDetailViewOrientation.HorizontalDetail)
            doc.Regenerate()

            try:
                plan_detail.Name = plan_name
            except Exception:
                pass

            if plan_template is not None:
                try:
                    plan_detail.ViewTemplateId = plan_template.Id
                    doc.Regenerate()
                except Exception as ptex:
                    print("  WARNING: Plan template apply failed: {}".format(ptex))

            print("  OK: Plan Detail created (ID {})".format(
                plan_detail.Id.IntegerValue))

        except Exception as pex:
            print("  ERROR creating Plan Detail: {}".format(pex))

    t.Commit()

    # ── Summary ────────────────────────────────────────────────────────────
    print("")
    print("═══ DONE ═══")
    print("Sections created: {} (A:{} B:{})".format(
        len(section_views), a_count, b_count))
    print("Plan Detail: {}".format("created" if plan_detail else "skipped/failed"))
    print("")
    print("Next: Run 'Rotate Sections' (Tool 3) to align each section")
    print("      to its panel's facing direction.")

    stats.update({"status": "ok", "sections": len(section_views),
                  "a_count": a_count, "b_count": b_count,
                  "plan_detail": plan_detail is not None})
    return stats


# ═══════════════════════════════════════════════════════════════════════════
# TOOL 3 — ROTATE DB SECTIONS
# ═══════════════════════════════════════════════════════════════════════════

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


def find_marker(doc, view):
    """Find the OST_Viewers marker element for THIS specific section view.

    Coworker's core technique: the marker element (not the View object) is
    what RotateElement/MoveElement actually operates on in Revit.

    PRIMARY — dependency graph (GetDependentElements):
      Revit tracks the section marker as a dependent of its View object.
      This lookup is exact: no name matching, no distance guessing.
      Completely immune to cross-assembly collisions even when adjacent
      ductbanks are physically close in the model (proximity fails there).

    FALLBACK — proximity to CropBox origin:
      Used only if GetDependentElements doesn't surface an OST_Viewers element
      (e.g. older Revit builds or unusual assembly view types).
      Picks the name-matched marker closest to the view's cut-plane origin.
    """
    viewers_cat_id = ElementId(BuiltInCategory.OST_Viewers)

    # ── PRIMARY: dependency graph ─────────────────────────────────────────
    try:
        dep_ids = view.GetDependentElements(None)
        for dep_id in dep_ids:
            elem = doc.GetElement(dep_id)
            if elem is None:
                continue
            if isinstance(elem, View):
                continue
            try:
                if (elem.Category is not None
                        and elem.Category.Id == viewers_cat_id):
                    return elem
            except Exception:
                continue
    except Exception:
        pass

    # ── FALLBACK: proximity to CropBox origin ─────────────────────────────
    target_name = view.Name
    try:
        view_origin = view.CropBox.Transform.Origin
    except Exception:
        view_origin = None

    collector = (FilteredElementCollector(doc)
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
            return e   # no origin to compare — first name match

    if not candidates:
        return None

    candidates.sort(key=lambda x: x[0])
    return candidates[0][1]


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


def rotate_sections(doc, active_view):
    """Tool 3 orchestrator. Rotates/moves every Panel-XXX section marker in
    the assembly that *active_view* belongs to.

    Manages its own TransactionGroup (one Transaction per view). Prints a
    results table. Returns a stats dict:
      {"status": "ok"|"error", "total": n, "ok": n, "failed": n,
       "angled": n, "results": [(tag, aimed_ok, how, angle_deg, notes), ...]}
    """
    stats = {"status": "error", "total": 0, "ok": 0, "failed": 0,
             "angled": 0, "results": []}

    # ── VALIDATE ASSEMBLY CONTEXT ──────────────────────────────────────────
    print("── HEC Rotate DB Sections ──")
    print("Active view: {} ({})".format(active_view.Name, active_view.ViewType))

    if not hasattr(active_view, "AssociatedAssemblyInstanceId"):
        print("ERROR: Active view has no AssociatedAssemblyInstanceId.")
        print("Open a view that belongs to your ductbank Assembly and run again.")
        return stats

    assembly_id = active_view.AssociatedAssemblyInstanceId
    if assembly_id == ElementId.InvalidElementId:
        print("ERROR: Active view is not associated with an Assembly.")
        print("Open a view that belongs to your ductbank Assembly and run again.")
        return stats

    assembly_elem = doc.GetElement(assembly_id)
    print("Assembly: {}".format(assembly_elem.Name))

    # ── Build panel lookup: Comments value → (panel element, FacingOrientation) ──
    member_ids = assembly_elem.GetMemberIds()
    panel_map  = {}   # "Panel-001" → (elem, facing XYZ, loc XYZ)

    for mid in member_ids:
        elem = doc.GetElement(mid)
        if elem is None:
            continue
        if safe_family_name(doc, elem) not in TARGET_FAMILIES:
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
        return stats

    # ── Collect section views named "Panel-XXX" in THIS assembly ──
    # Scoped by AssociatedAssemblyInstanceId so DB-2 never picks up
    # DB-1's views (both assemblies use the same Panel-001 … names).
    all_views = FilteredElementCollector(doc).OfClass(View).ToElements()
    section_views = []
    for v in all_views:
        if v.IsTemplate:
            continue
        if not hasattr(v, "AssociatedAssemblyInstanceId"):
            continue
        if v.AssociatedAssemblyInstanceId != assembly_id:
            continue
        if v.Name in panel_map:
            section_views.append(v)

    if not section_views:
        print("ERROR: No section views found matching panel names.")
        print("Run Tool 2 (Create Sections) first.")
        return stats

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
            marker = find_marker(doc, view)
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

    stats.update({"status": "ok", "total": len(results), "ok": ok_count,
                  "failed": failed_count, "angled": angled_count,
                  "results": results})
    return stats
