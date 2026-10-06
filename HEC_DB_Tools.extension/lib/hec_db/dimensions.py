"""hec_db.dimensions — Tool 5: Dimension Panels.

Places linear dimensions on every assembly section view:
  * Row String      — segmented string through every rebar spacer bar
                      (auto-detects bar orientation: vertical → RIGHT side,
                       horizontal → BOTTOM side)
  * Overall Height  — single dim, panel Top → Bottom  (LEFT side)
  * Overall Width   — single dim, panel Left → Right  (TOP side)
Optionally "Replace existing" deletes all dims in each view first.

PyRevit v6 + CPython 3123  |  Revit 2025
Hunt Electric — MONARCH Job
"""

import clr
clr.AddReference("RevitAPI")
from Autodesk.Revit.DB import (
    FilteredElementCollector,
    FamilyInstanceReferenceType,
    Transaction,
    Dimension,
    DimensionType,
    DimensionStyleType,
    ReferenceArray,
    Line,
    XYZ,
)

from hec_db.constants import (
    DEFAULT_DIM_TYPE_NAME, DIM_OFFSET, Z_TOLERANCE, X_TOLERANCE, SIDE_MARGIN,
    OPT_ROW, OPT_HEIGHT, OPT_WIDTH, OPT_REPLACE, DIM_OPTIONS, DEFAULT_CHECKED,
)
from hec_db.utils import (
    _norm, dim_type_name, vdot, vadd, vscale, bbox_z, get_refs,
)
from hec_db.ui import alert, select_checked
from hec_db.assembly import pick_assembly, collect_section_views, find_panel_in_view
from hec_db.detection import identify_spacer_bars, detect_orientation


# ── DIMENSION TYPE ──────────────────────────────────────────────────────────

def find_dimension_type(doc):
    """Return (DimensionType, used_fallback_bool).

    Looks for DEFAULT_DIM_TYPE_NAME first (whitespace/case-insensitive).
    Falls back to the first Linear dimension type. Returns (None, False) if
    the project has no linear dimension types at all.
    """
    linear = []
    for dt in FilteredElementCollector(doc).OfClass(DimensionType):
        try:
            if dt.StyleType != DimensionStyleType.Linear:
                continue
        except Exception:
            continue
        linear.append(dt)

    if not linear:
        return None, False

    target = _norm(DEFAULT_DIM_TYPE_NAME)
    for dt in linear:
        if _norm(dim_type_name(dt)) == target:
            return dt, False

    linear.sort(key=lambda d: dim_type_name(d))
    return linear[0], True


# ── VIEW-SPACE GEOMETRY (explicit XYZ maths — PythonNet has no XYZ.__add__) ─

def panel_view_extents(panel, view):
    """Project the panel's bounding box into view space.

    Returns dict with r_min/r_max (along view.RightDirection) and
    u_min/u_max (along view.UpDirection), measured from view.Origin,
    or None if the bounding box can't be read.
    """
    try:
        bb = panel.get_BoundingBox(None)
    except Exception:
        bb = None
    if bb is None:
        return None

    right = view.RightDirection
    up    = view.UpDirection
    o     = view.Origin

    corners = []
    for x in (bb.Min.X, bb.Max.X):
        for y in (bb.Min.Y, bb.Max.Y):
            for z in (bb.Min.Z, bb.Max.Z):
                corners.append(XYZ(x - o.X, y - o.Y, z - o.Z))

    rs = [vdot(c, right) for c in corners]
    us = [vdot(c, up) for c in corners]
    return {
        "r_min": min(rs), "r_max": max(rs),
        "u_min": min(us), "u_max": max(us),
    }


def view_point(view, r, u):
    """Model point at view-space coords (r along Right, u along Up).

    Depth (along ViewDirection) is the view origin's — i.e. on the cut plane.
    """
    o = view.Origin
    p = vadd(o, vscale(view.RightDirection, r))
    return vadd(p, vscale(view.UpDirection, u))


def delete_all_dims_in_view(doc, view):
    """Delete every Dimension element in *view*. Returns count deleted."""
    dims = list(FilteredElementCollector(doc, view.Id).OfClass(Dimension))
    n = 0
    for d in dims:
        try:
            doc.Delete(d.Id)
            n += 1
        except Exception:
            pass
    return n


def existing_dim_sides(doc, view, ext):
    """Classify dimensions already in this view relative to the panel.

    Returns a set containing any of "right", "left", "top", "bottom" for each
    side that already carries a dimension of the matching orientation.
    """
    sides = set()
    if ext is None:
        return sides

    right = view.RightDirection
    up    = view.UpDirection
    o     = view.Origin
    r_mid = 0.5 * (ext["r_min"] + ext["r_max"])
    u_mid = 0.5 * (ext["u_min"] + ext["u_max"])

    for d in FilteredElementCollector(doc, view.Id).OfClass(Dimension):
        try:
            crv = d.Curve
            if crv is None:
                continue
            direction = crv.Direction if hasattr(crv, "Direction") else None
            if direction is None:
                p0 = crv.GetEndPoint(0)
                p1 = crv.GetEndPoint(1)
                direction = XYZ(p1.X - p0.X, p1.Y - p0.Y,
                                p1.Z - p0.Z).Normalize()
            mid = crv.Evaluate(0.5, True)
        except Exception:
            continue

        rel = XYZ(mid.X - o.X, mid.Y - o.Y, mid.Z - o.Z)
        r = vdot(rel, right)
        u = vdot(rel, up)

        if abs(vdot(direction, up)) > 0.9:           # vertical string
            if r > r_mid + SIDE_MARGIN:
                sides.add("right")
            elif r < r_mid - SIDE_MARGIN:
                sides.add("left")
        elif abs(vdot(direction, right)) > 0.9:      # horizontal string
            if u > u_mid + SIDE_MARGIN:
                sides.add("top")
            elif u < u_mid - SIDE_MARGIN:
                sides.add("bottom")
    return sides


# ── REFERENCE COLLECTION (Strategy A) ───────────────────────────────────────

def collect_row_refs_vertical(doc, panel, bars):
    """Row string for VERTICAL orientation (bars stacked in Z).

    Uses each bar's CenterFrontBack ref (one point per bar), with the host
    panel's Top/Bottom as outer endpoints.  Returns (refs_sorted_by_z, notes).
    """
    notes = []
    tagged = []   # (z, priority, ref)   priority 0 = panel, 1 = bar

    # Host panel outer endpoints
    p_zmin, p_zmax = bbox_z(panel)
    p_top = get_refs(panel, FamilyInstanceReferenceType.Top)
    p_bot = get_refs(panel, FamilyInstanceReferenceType.Bottom)
    if p_top and p_zmax is not None:
        tagged.append((p_zmax, 0, p_top[0]))
    else:
        notes.append("panel Top ref missing")
    if p_bot and p_zmin is not None:
        tagged.append((p_zmin, 0, p_bot[0]))
    else:
        notes.append("panel Bottom ref missing")

    # Each bar's CenterFrontBack = one horizontal plane per bar
    for el, pt in bars:
        cfb = get_refs(el, FamilyInstanceReferenceType.CenterFrontBack)
        if cfb:
            tagged.append((pt.Z, 1, cfb[0]))
        else:
            notes.append("bar id {} missing CenterFrontBack ref".format(
                el.Id.IntegerValue))

    # Sort by Z, panel refs first on ties, then collapse near-coincident Z
    tagged.sort(key=lambda t: (t[0], t[1]))
    deduped = []
    for z, pri, ref in tagged:
        if deduped and abs(z - deduped[-1][0]) < Z_TOLERANCE:
            # keep the higher-priority (lower number) one
            if pri < deduped[-1][1]:
                deduped[-1] = (z, pri, ref)
            continue
        deduped.append((z, pri, ref))

    return [t[2] for t in deduped], notes


def collect_row_refs_horizontal(doc, panel, bars, view):
    """Row string for HORIZONTAL orientation (bars spread along X/Y).

    Uses each bar's CenterLeftRight ref (one vertical plane per bar), with the
    host panel's Left/Right as outer endpoints. References are sorted by their
    projected position along the VIEW's RightDirection so the ordering matches
    the on-screen left-to-right arrangement regardless of model orientation.
    Returns (refs_sorted_by_view_right, notes).
    """
    notes = []
    tagged = []   # (r_position, priority, ref)

    right_dir = view.RightDirection
    origin    = view.Origin

    def project_r(pt):
        """Dot product of (pt - origin) onto view.RightDirection."""
        return vdot(XYZ(pt.X - origin.X, pt.Y - origin.Y,
                        pt.Z - origin.Z), right_dir)

    # Host panel outer endpoints
    p_left  = get_refs(panel, FamilyInstanceReferenceType.Left)
    p_right = get_refs(panel, FamilyInstanceReferenceType.Right)

    # Get panel extents for Left/Right positions
    try:
        bb = panel.get_BoundingBox(None)
    except Exception:
        bb = None
    if bb is None:
        notes.append("panel bbox unreadable")
        return [], notes

    # Project all 8 bbox corners to find the min/max along view Right
    corners_r = []
    for x in (bb.Min.X, bb.Max.X):
        for y in (bb.Min.Y, bb.Max.Y):
            for z in (bb.Min.Z, bb.Max.Z):
                corners_r.append(project_r(XYZ(x, y, z)))
    r_min = min(corners_r)
    r_max = max(corners_r)

    if p_left:
        tagged.append((r_min, 0, p_left[0]))
    else:
        notes.append("panel Left ref missing")
    if p_right:
        tagged.append((r_max, 0, p_right[0]))
    else:
        notes.append("panel Right ref missing")

    # Each bar's CenterLeftRight = one vertical plane per bar
    for el, pt in bars:
        clr_refs = get_refs(el, FamilyInstanceReferenceType.CenterLeftRight)
        if clr_refs:
            tagged.append((project_r(pt), 1, clr_refs[0]))
        else:
            notes.append("bar id {} missing CenterLeftRight ref".format(
                el.Id.IntegerValue))

    # Sort by projected R position, panel refs first on ties
    tagged.sort(key=lambda t: (t[0], t[1]))
    deduped = []
    for r, pri, ref in tagged:
        if deduped and abs(r - deduped[-1][0]) < X_TOLERANCE:
            if pri < deduped[-1][1]:
                deduped[-1] = (r, pri, ref)
            continue
        deduped.append((r, pri, ref))

    return [t[2] for t in deduped], notes


def make_ref_array(refs):
    ra = ReferenceArray()
    for r in refs:
        ra.Append(r)
    return ra


# ── ORCHESTRATOR ────────────────────────────────────────────────────────────

def dimension_panels(doc, uidoc, assembly=None, picked=None):
    """Tool 5 orchestrator. Places dimensions on every section view of the
    ductbank assembly.

    *assembly* — AssemblyInstance to use. If None, resolved via pick_assembly
                 (selection → active view → prompt).
    *picked*   — list of ticked option labels (from DIM_OPTIONS). If None,
                 the user is prompted with the CheckedListBox dialog.

    Manages its own Transaction. Prints progress. Returns a stats dict:
      {"status": "ok"|"cancelled"|"error", "views": n,
       "placed_row": n, "placed_h": n, "placed_w": n,
       "skipped_row": n, "skipped_h": n, "skipped_w": n,
       "replaced": n, "no_panel": [..], "errors": n}
    """
    stats = {"status": "cancelled", "views": 0,
             "placed_row": 0, "placed_h": 0, "placed_w": 0,
             "skipped_row": 0, "skipped_h": 0, "skipped_w": 0,
             "replaced": 0, "no_panel": [], "errors": 0}

    print("── HEC Dimension Panels ──")

    # 1. Assembly -----------------------------------------------------------
    if assembly is None:
        assembly = pick_assembly(
            uidoc, doc,
            title="Select the ductbank assembly to dimension",
            button_text="Dimension this assembly")
    if isinstance(assembly, str) and assembly == "NONE_IN_MODEL":
        alert("No assemblies exist in this model.\n\n"
              "Create your ductbank assembly first.", title="No Assembly")
        stats["status"] = "error"
        return stats
    if assembly is None:
        alert("Cancelled — no assembly selected.", title="Cancelled")
        return stats

    assembly_id = assembly.Id
    try:
        assembly_name = assembly.Name
    except Exception:
        assembly_name = "Assembly {}".format(assembly_id.IntegerValue)
    print("Assembly: {}".format(assembly_name))

    # 2. Which dimensions? --------------------------------------------------
    if picked is None:
        picked = select_checked(DIM_OPTIONS,
                                title="HEC Dimension Panels — choose dimensions",
                                defaults=DEFAULT_CHECKED,
                                button_text="Place dimensions")
    if picked is None:
        alert("Cancelled — no dimensions selected.", title="Cancelled")
        return stats
    if not picked:
        alert("Nothing ticked — no dimensions to place.", title="Nothing to do")
        return stats

    do_row     = OPT_ROW     in picked
    do_height  = OPT_HEIGHT  in picked
    do_width   = OPT_WIDTH   in picked
    do_replace = OPT_REPLACE in picked

    dim_labels = [p for p in picked if p != OPT_REPLACE]
    print("Dimensions to place: {}".format(", ".join(dim_labels) if dim_labels
                                           else "(none)"))
    if do_replace:
        print("Replace mode: ON — existing dimensions will be deleted first")

    # 3. Dimension type -----------------------------------------------------
    dim_type, used_fallback = find_dimension_type(doc)
    if dim_type is None:
        alert("No Linear dimension types exist in this project.\n\n"
              "Load or create a linear dimension style and run again.",
              title="No Dimension Type")
        stats["status"] = "error"
        return stats
    if used_fallback:
        print("NOTE: dimension style '{}' not found — using '{}' instead.".format(
            DEFAULT_DIM_TYPE_NAME, dim_type_name(dim_type)))
    else:
        print("Dimension style: {}".format(dim_type_name(dim_type)))

    # 4. Section views ------------------------------------------------------
    section_views = collect_section_views(doc, assembly_id)
    if not section_views:
        alert("No section views found for assembly:\n  {}\n\n"
              "Run 'Create DB Sections' (Tool 2) first.".format(assembly_name),
              title="No Sections")
        stats["status"] = "error"
        return stats
    print("Section views: {}".format(len(section_views)))
    print("")
    print("── Placing dimensions ──")

    # 5. Place --------------------------------------------------------------
    placed_row = placed_h = placed_w = 0
    skipped_row = skipped_h = skipped_w = 0
    replaced_count = 0
    no_panel = []
    errors = 0

    t = Transaction(doc, "HEC Dimension Panels")
    t.Start()

    for view in section_views:
        tag = view.Name
        panel = find_panel_in_view(doc, view)
        if panel is None:
            no_panel.append(tag)
            print("  {:<14} no host panel visible — skipped".format(tag))
            continue

        ext = panel_view_extents(panel, view)
        if ext is None:
            print("  {:<14} could not read panel bounding box — skipped".format(
                tag))
            errors += 1
            continue

        # Replace mode: delete existing dims before placement
        if do_replace:
            n_del = delete_all_dims_in_view(doc, view)
            if n_del:
                replaced_count += n_del
            have = set()   # everything cleared
        else:
            have = existing_dim_sides(doc, view, ext)

        parts = []

        # ── Row String ────────────────────────────────────────────────────
        if do_row:
            bars = identify_spacer_bars(doc, panel)
            orientation = detect_orientation(bars)

            if not bars:
                parts.append("row: no spacer bars found — skipped")
            elif orientation == "vertical":
                # Bars stack in Z → dim string on the RIGHT
                if "right" in have:
                    skipped_row += 1
                    parts.append("row(R): exists")
                else:
                    refs, notes = collect_row_refs_vertical(doc, panel, bars)
                    if len(refs) < 3:
                        # Need at least 3 refs (top + bar + bottom) for a
                        # meaningful row string; 2 = just panel endpoints
                        parts.append("row(R): too few refs ({}) — skipped".format(
                            len(refs)))
                    else:
                        try:
                            r = ext["r_max"] + DIM_OFFSET
                            line = Line.CreateBound(
                                view_point(view, r, ext["u_min"]),
                                view_point(view, r, ext["u_max"]))
                            doc.Create.NewDimension(view, line,
                                                    make_ref_array(refs),
                                                    dim_type)
                            placed_row += 1
                            parts.append("row(R): {} segs ({} bars)".format(
                                len(refs) - 1, len(bars)))
                        except Exception as ex:
                            errors += 1
                            parts.append("row(R): FAILED {}".format(ex))
                    if notes:
                        parts.append("[{}]".format("; ".join(notes)))

            elif orientation == "horizontal":
                # Bars spread in X/Y → dim string on the BOTTOM
                if "bottom" in have:
                    skipped_row += 1
                    parts.append("row(B): exists")
                else:
                    refs, notes = collect_row_refs_horizontal(doc, panel, bars, view)
                    if len(refs) < 3:
                        parts.append("row(B): too few refs ({}) — skipped".format(
                            len(refs)))
                    else:
                        try:
                            u = ext["u_min"] - DIM_OFFSET
                            line = Line.CreateBound(
                                view_point(view, ext["r_min"], u),
                                view_point(view, ext["r_max"], u))
                            doc.Create.NewDimension(view, line,
                                                    make_ref_array(refs),
                                                    dim_type)
                            placed_row += 1
                            parts.append("row(B): {} segs ({} bars)".format(
                                len(refs) - 1, len(bars)))
                        except Exception as ex:
                            errors += 1
                            parts.append("row(B): FAILED {}".format(ex))
                    if notes:
                        parts.append("[{}]".format("; ".join(notes)))

            else:
                parts.append("row: orientation undetermined ({} bar(s)) "
                             "— skipped".format(len(bars)))

        # ── Overall Height (left) ─────────────────────────────────────────
        if do_height:
            if "left" in have:
                skipped_h += 1
                parts.append("height: exists")
            else:
                top = get_refs(panel, FamilyInstanceReferenceType.Top)
                bot = get_refs(panel, FamilyInstanceReferenceType.Bottom)
                if not (top and bot):
                    errors += 1
                    parts.append("height: panel Top/Bottom ref missing")
                else:
                    try:
                        r = ext["r_min"] - DIM_OFFSET
                        line = Line.CreateBound(
                            view_point(view, r, ext["u_min"]),
                            view_point(view, r, ext["u_max"]))
                        doc.Create.NewDimension(
                            view, line, make_ref_array([bot[0], top[0]]),
                            dim_type)
                        placed_h += 1
                        parts.append("height: ok")
                    except Exception as ex:
                        errors += 1
                        parts.append("height: FAILED {}".format(ex))

        # ── Overall Width (top) ───────────────────────────────────────────
        if do_width:
            if "top" in have:
                skipped_w += 1
                parts.append("width: exists")
            else:
                left  = get_refs(panel, FamilyInstanceReferenceType.Left)
                right = get_refs(panel, FamilyInstanceReferenceType.Right)
                if not (left and right):
                    errors += 1
                    parts.append("width: panel Left/Right ref missing")
                else:
                    try:
                        u = ext["u_max"] + DIM_OFFSET
                        line = Line.CreateBound(
                            view_point(view, ext["r_min"], u),
                            view_point(view, ext["r_max"], u))
                        doc.Create.NewDimension(
                            view, line, make_ref_array([left[0], right[0]]),
                            dim_type)
                        placed_w += 1
                        parts.append("width: ok")
                    except Exception as ex:
                        errors += 1
                        parts.append("width: FAILED {}".format(ex))

        print("  {:<14} {}".format(tag, " | ".join(parts)))

    t.Commit()

    # ── Summary ───────────────────────────────────────────────────────────
    print("")
    print("═══ DONE ═══")
    print("Views processed:  {}".format(len(section_views)))
    if do_replace and replaced_count:
        print("Replaced:         {} existing dim(s) deleted".format(
            replaced_count))
    if do_row:
        print("Row strings:      placed {}  skipped(existing) {}".format(
            placed_row, skipped_row))
    if do_height:
        print("Overall heights:  placed {}  skipped(existing) {}".format(
            placed_h, skipped_h))
    if do_width:
        print("Overall widths:   placed {}  skipped(existing) {}".format(
            placed_w, skipped_w))
    if no_panel:
        print("⚠ No host panel found in {} view(s): {}".format(
            len(no_panel), ", ".join(no_panel)))
    if errors:
        print("⚠ {} problem(s) — see lines above".format(errors))
    print("")
    print("Open a Panel-XXX section to review the dimensions.")

    stats.update({
        "status": "ok", "views": len(section_views),
        "placed_row": placed_row, "placed_h": placed_h, "placed_w": placed_w,
        "skipped_row": skipped_row, "skipped_h": skipped_h, "skipped_w": skipped_w,
        "replaced": replaced_count, "no_panel": no_panel, "errors": errors,
    })
    return stats
