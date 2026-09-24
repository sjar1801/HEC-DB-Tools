# HEC DB Section Creator  v7
# ─────────────────────────────────────────────────────────────
# Dynamo CPython3 script — paste into a Python Script node.
# Run from an assembly 3D-ortho view.
#
# Workflow:
#   1. Propagate Comments tag to all sub-components (recursive)
#   2. Pick section orientation per panel (A vs B based on facing)
#   3. Create one DetailSection per panel (nested under assembly)
#   4. Add NOT-equals filter per section (isolate one panel)
#   5. Apply view template (Filters UNCHECKED so script filters survive)
#   6. Create one HorizontalDetail (Plan Detail) — shows section markers
#   7. Create assembly sheet, place Plan Detail top-left, sections in grid
#
# v7 changes:
#   - Orientation detection: panels aligned with assembly X → SectionA,
#     panels aligned with assembly Y → SectionB (separates lines on bends)
#   - Removed crop tightening — filters already isolate the panel,
#     uniform crop makes sections equal size & easier to move
#   - Removed failed MoveElement / CropBox offset attempts
# ─────────────────────────────────────────────────────────────

import clr
clr.AddReference("RevitAPI")
clr.AddReference("RevitServices")
clr.AddReference("RevitNodes")

from Autodesk.Revit.DB import *
from RevitServices.Persistence import DocumentManager
from RevitServices.Transactions import TransactionManager

from System.Collections.Generic import List
import math

doc   = DocumentManager.Instance.CurrentDBDocument
active_view = doc.ActiveView

# ── CONFIG ──────────────────────────────────────────────────
TARGET_FAMILIES = [
    "HEC_EF-DB_SIDE_PANEL",
    "HEC_EF-DB_ASPVSF",
    "HEC_NESTED_EF-DB_ASP",
    "HEC_NESTED_EF-DB90_ASP",
]

SECTION_TEMPLATE_NAME = "6 Spool_DB_DETAIL SECTION"
PLAN_TEMPLATE_NAME    = "7 Spool_DB_PLAN DETAIL"
TB_NAME               = "HEC_TB - 30X42 - Spooling - DB"

# Sheet layout — sections grid (below the plan detail)
GRID_COLS    = 4
GRID_SPACE_X = 0.9      # ft between viewport centres
GRID_SPACE_Y = 0.9
GRID_START_X = 0.5      # ft from sheet left edge
GRID_START_Y = 2.0      # ft from sheet bottom

# Plan detail placement (top-left)
PLAN_DETAIL_X = 0.8     # ft from sheet left edge
PLAN_DETAIL_Y = 2.6     # ft from sheet bottom

MAX_SUBCOMPONENT_DEPTH = 6
# ────────────────────────────────────────────────────────────


# ── HELPERS ─────────────────────────────────────────────────

def safe_family_name(elem):
    """Return the family name, handling CPython3/PythonNet quirks."""
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


def find_title_block_id(doc, target_name):
    """Find a title block FamilySymbol by family name. Load if needed."""
    collector = FilteredElementCollector(doc).OfClass(FamilySymbol)\
                .OfCategory(BuiltInCategory.OST_TitleBlocks)
    for fs in collector:
        try:
            if fs.Family.Name == target_name:
                if not fs.IsActive:
                    fs.Activate()
                    doc.Regenerate()
                return fs.Id
        except Exception:
            continue
    # Try loading from known path
    import os
    rfa_path = os.path.join(
        os.environ.get("USERPROFILE", "C:\\"),
        "Documents", target_name + ".rfa")
    if os.path.exists(rfa_path):
        from Autodesk.Revit.DB import FamilyLoadOptions
        class _FLO(IFamilyLoadOptions):
            def OnFamilyFound(self, familyInUse, overwriteParameterValues):
                overwriteParameterValues = True
                return True
            def OnSharedFamilyFound(self, sharedFamily, familyInUse,
                                    source, overwriteParameterValues):
                overwriteParameterValues = True
                return True
        ok, family = doc.LoadFamily(rfa_path, _FLO())
        if ok and family is not None:
            for sid in family.GetFamilySymbolIds():
                fs = doc.GetElement(sid)
                if not fs.IsActive:
                    fs.Activate()
                    doc.Regenerate()
                return fs.Id
    return None


def find_view_template(doc, template_name):
    """Return a View used as a template, by name."""
    collector = FilteredElementCollector(doc).OfClass(View)
    for v in collector:
        if v.IsTemplate and v.Name == template_name:
            return v
    return None


def propagate_comments_to_subcomponents(elem, value, doc, depth=0):
    """Recursively write `value` into Comments on every sub-component."""
    if depth > MAX_SUBCOMPONENT_DEPTH:
        return 0
    count = 0
    try:
        sub_ids = elem.GetSubComponentIds()
    except Exception:
        return 0
    if sub_ids is None:
        return 0
    try:
        n = sub_ids.Count
    except AttributeError:
        n = len(sub_ids)
    if n == 0:
        return 0
    for sid in sub_ids:
        sub_elem = doc.GetElement(sid)
        if sub_elem is None:
            continue
        try:
            p = sub_elem.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
            if p and not p.IsReadOnly:
                p.Set(value)
                count += 1
        except Exception:
            pass
        count += propagate_comments_to_subcomponents(sub_elem, value, doc, depth + 1)
    return count


def get_panel_facing_direction(panel):
    """Get the panel's facing direction from FacingOrientation or rotation."""
    # Method 1: FacingOrientation (works for most family instances)
    try:
        facing = panel.FacingOrientation
        if facing is not None:
            return facing
    except Exception:
        pass
    # Method 2: Derive from LocationPoint rotation
    try:
        loc = panel.Location
        if hasattr(loc, "Rotation"):
            angle = loc.Rotation  # radians from global X
            return XYZ(math.cos(angle), math.sin(angle), 0)
    except Exception:
        pass
    return None


def choose_section_orientation(panel, assembly_transform):
    """Pick DetailSectionA or DetailSectionB based on panel facing vs assembly axes.

    If the panel faces roughly along the assembly's local X-axis -> SectionA
    (which cuts perpendicular to X, i.e. along Y).
    If the panel faces roughly along the assembly's local Y-axis -> SectionB
    (which cuts perpendicular to Y, i.e. along X).

    On bends/Ls this separates the section lines in Plan Detail.
    On straight runs all panels face the same way — all get the same
    orientation, which is fine (designer sets transparency).
    """
    facing = get_panel_facing_direction(panel)
    if facing is None:
        return AssemblyDetailViewOrientation.DetailSectionA, "A(default)", False

    asm_x = assembly_transform.BasisX
    asm_y = assembly_transform.BasisY

    # Absolute dot products — we only care WHICH axis, not which direction
    dot_x = abs(facing.X * asm_x.X + facing.Y * asm_x.Y + facing.Z * asm_x.Z)
    dot_y = abs(facing.X * asm_y.X + facing.Y * asm_y.Y + facing.Z * asm_y.Z)

    # SectionA cuts perpendicular to assembly X -> views along Y axis
    # SectionB cuts perpendicular to assembly Y -> views along X axis
    #
    # A and B are PERPENDICULAR AXES, not opposite directions!
    # Panel faces along Y (high dot_y) -> need view along Y -> SectionA
    # Panel faces along X (high dot_x) -> need view along X -> SectionB
    #
    # Panels facing +Y and -Y BOTH need SectionA (same cut plane).
    # Transparency handles seeing through to back-facing panels.

    # Flag panels significantly angled — neither A nor B is face-on
    max_dot = max(dot_x, dot_y)
    angled = max_dot < 0.9

    label = "|dX|={:.2f} |dY|={:.2f}".format(dot_x, dot_y)

    if dot_y >= dot_x:
        # Panel faces along Y -> SectionA (views along Y)
        return AssemblyDetailViewOrientation.DetailSectionA, "A(" + label + ")", angled
    else:
        # Panel faces along X -> SectionB (views along X)
        return AssemblyDetailViewOrientation.DetailSectionB, "B(" + label + ")", angled


def get_or_create_filter(doc, filter_name, category_id, param_id, value):
    """Create a ParameterFilterElement with a NOT-EQUALS rule.
    Returns the filter ElementId, or None on failure."""
    # Check if filter already exists
    existing = FilteredElementCollector(doc).OfClass(ParameterFilterElement)
    for f in existing:
        if f.Name == filter_name:
            return f.Id

    cats = List[ElementId]()
    cats.Add(category_id)

    try:
        rule = ParameterFilterRuleFactory.CreateNotEqualsRule(param_id, value, True)
        elem_filter = ElementParameterFilter(rule)
        pfe = ParameterFilterElement.Create(doc, filter_name, cats, elem_filter)
        return pfe.Id
    except Exception:
        return None


# ── MAIN ────────────────────────────────────────────────────
results = []

# Validate assembly context
if not hasattr(active_view, "AssociatedAssemblyInstanceId"):
    results.append("ERROR: Active view has no assembly.")
    OUT = "\n".join(results)
else:
    assembly_id = active_view.AssociatedAssemblyInstanceId
    if assembly_id == ElementId.InvalidElementId:
        results.append("ERROR: No assembly associated with active view.")
        OUT = "\n".join(results)
    else:
        assembly_elem = doc.GetElement(assembly_id)
        results.append("Assembly: " + assembly_elem.Name)

        # Get assembly transform for orientation detection
        assembly_transform = assembly_elem.GetTransform()

        # Collect tagged panels (those with Comments set)
        member_ids = assembly_elem.GetMemberIds()
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

        if not panels:
            results.append("ERROR: No panels with Comments tags found. Run Panel ID Assigner first.")
            OUT = "\n".join(results)
        else:
            # Sort by tag
            def tag_sort_key(e):
                p = e.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
                return p.AsString() if (p and p.HasValue) else ""
            panels.sort(key=tag_sort_key)
            results.append("Panels found: " + str(len(panels)))

            # Find templates and title block
            section_template = find_view_template(doc, SECTION_TEMPLATE_NAME)
            if section_template is None:
                results.append("WARNING: Section template '" + SECTION_TEMPLATE_NAME + "' not found.")
            else:
                results.append("Section template: " + SECTION_TEMPLATE_NAME)

            plan_template = find_view_template(doc, PLAN_TEMPLATE_NAME)
            if plan_template is None:
                results.append("WARNING: Plan template '" + PLAN_TEMPLATE_NAME + "' not found.")
            else:
                results.append("Plan template: " + PLAN_TEMPLATE_NAME)

            tb_id = None
            TransactionManager.Instance.EnsureInTransaction(doc)
            tb_id = find_title_block_id(doc, TB_NAME)
            if tb_id is None:
                results.append("WARNING: Title block '" + TB_NAME + "' not found. Sheet will have no title block.")
            else:
                results.append("Title block: " + TB_NAME)

            # Get Comments parameter ID and category for filter
            comments_param_id = ElementId(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
            elec_fix_cat_id = ElementId(BuiltInCategory.OST_ElectricalFixtures)

            # ── Step 1: Propagate Comments to sub-components ──
            results.append("")
            results.append("── Propagating Comments to sub-components ──")
            total_propagated = 0
            for panel in panels:
                tag = panel.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS).AsString()
                total_propagated += propagate_comments_to_subcomponents(panel, tag, doc)
            results.append("Sub-components tagged: " + str(total_propagated))

            # ── Step 2-4: Create sections with orientation, filters, template ──
            results.append("")
            results.append("── Creating detail sections ──")
            section_views = []
            a_count = 0
            b_count = 0

            for i, panel in enumerate(panels):
                tag = panel.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS).AsString()
                fname = safe_family_name(panel)

                try:
                    # Step 2: Choose orientation and create section
                    orientation, orient_label, is_angled = choose_section_orientation(
                        panel, assembly_transform)
                    if orient_label.startswith("A"):
                        a_count += 1
                    else:
                        b_count += 1

                    section_view = AssemblyViewUtils.CreateDetailSection(
                        doc, assembly_id, orientation)
                    doc.Regenerate()

                    # Rename section to match panel tag
                    try:
                        section_view.Name = tag
                    except Exception:
                        pass  # name collision — keep default name

                    # Step 3: Add NOT-equals filter
                    filter_name = "HideExcept_" + tag
                    filter_id = get_or_create_filter(
                        doc, filter_name, elec_fix_cat_id,
                        comments_param_id, tag)

                    filter_applied = False
                    if filter_id is not None:
                        try:
                            section_view.AddFilter(filter_id)
                            section_view.SetFilterVisibility(filter_id, False)
                            filter_applied = True
                        except Exception as fex:
                            results.append("  Filter add failed for " + tag + ": " + str(fex))

                    # Step 4: Apply section view template
                    if section_template is not None:
                        try:
                            section_view.ViewTemplateId = section_template.Id
                            doc.Regenerate()
                        except Exception as tex:
                            results.append("  Template failed for " + tag + ": " + str(tex))

                    section_views.append(section_view)

                    status = tag + " | " + str(fname)
                    status += " | Section:" + orient_label
                    status += " | Filter:" + ("yes" if filter_applied else "NO")
                    if is_angled:
                        status += " | ⚠ ANGLED — may need manual reorientation"
                    results.append("  " + status)

                except Exception as ex:
                    results.append("  ERROR creating section for " + tag + ": " + str(ex))

            results.append("Sections created: " + str(len(section_views)) +
                           " (A:" + str(a_count) + " B:" + str(b_count) + ")")

            # ── Step 5: Create HorizontalDetail (Plan Detail) ──
            results.append("")
            results.append("── Creating Plan Detail (HorizontalDetail) ──")
            plan_detail = None
            try:
                plan_detail = AssemblyViewUtils.CreateDetailSection(
                    doc, assembly_id,
                    AssemblyDetailViewOrientation.HorizontalDetail)
                doc.Regenerate()
                results.append("Plan Detail created: " + plan_detail.Name +
                               " (ID " + str(plan_detail.Id.IntegerValue) + ")")

                # Apply plan template to plan detail
                if plan_template is not None:
                    try:
                        plan_detail.ViewTemplateId = plan_template.Id
                        doc.Regenerate()
                    except Exception:
                        pass

            except Exception as ex:
                results.append("ERROR creating Plan Detail: " + str(ex))

            # ── Step 6: Create sheet and place views ──
            results.append("")
            results.append("── Creating assembly sheet ──")

            try:
                if tb_id is not None:
                    sheet = AssemblyViewUtils.CreateSheet(doc, assembly_id, tb_id)
                else:
                    sheet = AssemblyViewUtils.CreateSheet(
                        doc, assembly_id, ElementId.InvalidElementId)
                doc.Regenerate()
                results.append("Sheet created: " + sheet.SheetNumber + " - " + sheet.Name)

                # Place Plan Detail top-left
                if plan_detail is not None:
                    try:
                        if Viewport.CanAddViewToSheet(doc, sheet.Id, plan_detail.Id):
                            vp_plan = Viewport.Create(doc, sheet.Id, plan_detail.Id,
                                                       XYZ(PLAN_DETAIL_X, PLAN_DETAIL_Y, 0))
                            results.append("Plan Detail placed at top-left")
                        else:
                            results.append("WARNING: Could not add Plan Detail to sheet")
                    except Exception as pex:
                        results.append("WARNING: Plan Detail placement failed: " + str(pex))

                # Place sections in grid (below plan detail)
                placed = 0
                for i, sv in enumerate(section_views):
                    col = i % GRID_COLS
                    row = i // GRID_COLS
                    x = GRID_START_X + col * GRID_SPACE_X
                    y = GRID_START_Y - row * GRID_SPACE_Y
                    try:
                        if Viewport.CanAddViewToSheet(doc, sheet.Id, sv.Id):
                            vp = Viewport.Create(doc, sheet.Id, sv.Id,
                                                  XYZ(x, y, 0))
                            placed += 1
                        else:
                            tag = panels[i].get_Parameter(
                                BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS).AsString()
                            results.append("WARNING: Cannot place " + tag + " on sheet")
                    except Exception as vex:
                        results.append("WARNING: Viewport failed: " + str(vex))

                results.append("Sections placed on sheet: " + str(placed) + "/" + str(len(section_views)))

            except Exception as sex:
                results.append("ERROR creating sheet: " + str(sex))

            TransactionManager.Instance.TransactionTaskDone()

            results.append("")
            results.append("═══ DONE ═══")
            OUT = "\n".join(results)
