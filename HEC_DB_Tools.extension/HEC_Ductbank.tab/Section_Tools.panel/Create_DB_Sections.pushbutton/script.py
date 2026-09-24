#! python3
"""HEC Ductbank Create Sections — PyRevit Button  (Tool 2 of 4)

Prerequisites:
  - Run "Assign Panel IDs" first (Tool 1) — Comments must be populated
  - Active view must belong to an Assembly

What this tool does:
  - Reads panel Comments IDs (Panel-001, Panel-002 …)
  - Creates one AssemblyDetailSection per panel named to match its ID
  - Adds a NOT-EQUALS filter per section to isolate only that panel
    (no crop tightening — filter does the work, exactly like Dynamo v7)
  - Applies view template "6 Spool_DB_DETAIL SECTION" to every section
  - Creates one HorizontalDetail (Plan Detail) named "Plan Detail"
  - Applies view template "7 Spool_DB_PLAN DETAIL" to the plan view

What this tool does NOT do:
  - Rotate sections to correct orientation  → Tool 3 (Rotate Sections)
  - Place views on a sheet                 → Tool 4 (Place On Sheets)

PyRevit v6 + CPython 3123
Hunt Electric — MONARCH Job
"""

import clr
import math

clr.AddReference("RevitAPI")
from Autodesk.Revit.DB import (
    FilteredElementCollector,
    FamilyInstance,
    BuiltInParameter,
    BuiltInCategory,
    Transaction,
    ElementId,
    AssemblyViewUtils,
    AssemblyDetailViewOrientation,
    ParameterFilterElement,
    ParameterFilterRuleFactory,
    ElementParameterFilter,
    View,
    XYZ,
)

from System.Collections.Generic import List

# ── CONFIG ─────────────────────────────────────────────────────────────────
TARGET_FAMILIES = [
    "HEC_EF-DB_SIDE_PANEL",
    "HEC_EF-DB_ASPVSF",
    "HEC_NESTED_EF-DB_ASP",
    "HEC_NESTED_EF-DB90_ASP",
]
SECTION_TEMPLATE_NAME = "6 Spool_DB_DETAIL SECTION"
PLAN_TEMPLATE_NAME    = "7 Spool_DB_PLAN DETAIL"
# ───────────────────────────────────────────────────────────────────────────

# ── PyRevit doc access ──────────────────────────────────────────────────────
uidoc       = __revit__.ActiveUIDocument          # noqa: F821
doc         = uidoc.Document
active_view = doc.ActiveView
# ───────────────────────────────────────────────────────────────────────────


# ── HELPERS ─────────────────────────────────────────────────────────────────

def safe_family_name(elem):
    """Return family name, handling CPython/PythonNet quirks."""
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


def find_view_template(name):
    """Return a View used as a template, matched by name."""
    for v in FilteredElementCollector(doc).OfClass(View):
        if v.IsTemplate and v.Name == name:
            return v
    return None


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


def section_exists(name):
    """Return True if a view with this name already exists in the project."""
    for v in FilteredElementCollector(doc).OfClass(View):
        if not v.IsTemplate and v.Name == name:
            return True
    return False


def get_or_create_filter(filter_name, category_id, param_id, value):
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


# ── VALIDATE ASSEMBLY CONTEXT ───────────────────────────────────────────────
print("── HEC Create DB Sections ──")
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
        print("Assembly: {}".format(assembly_elem.Name))

        # ── Collect panels with Comments assigned ──────────────────────────
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
            print("ERROR: No panels with Comments IDs found in this assembly.")
            print("Run 'Assign Panel IDs' (Tool 1) first, then come back.")
        else:
            # Sort by Comments value so sections are created in order
            def tag_key(e):
                p = e.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
                return p.AsString() if (p and p.HasValue) else ""
            panels.sort(key=tag_key)
            print("Panels found: {}".format(len(panels)))

            # Look up templates
            section_template = find_view_template(SECTION_TEMPLATE_NAME)
            plan_template    = find_view_template(PLAN_TEMPLATE_NAME)
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
                fname = safe_family_name(panel)

                # Skip if section with this name already exists
                if section_exists(tag):
                    print("  SKIP: View '{}' already exists".format(tag))
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
                        filter_name, elec_fix_cat_id, comments_param_id, tag)

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

            # ── Create Plan Detail (HorizontalDetail) ──────────────────────
            print("")
            print("── Creating Plan Detail ──")
            plan_detail = None
            plan_name   = "Plan Detail"

            if section_exists(plan_name):
                print("  SKIP: '{}' already exists".format(plan_name))
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

            # ── Summary ────────────────────────────────────────────────────
            print("")
            print("═══ DONE ═══")
            print("Sections created: {} (A:{} B:{})".format(
                len(section_views), a_count, b_count))
            print("Plan Detail: {}".format("created" if plan_detail else "skipped/failed"))
            print("")
            print("Next: Run 'Rotate Sections' (Tool 3) to align each section")
            print("      to its panel's facing direction.")
