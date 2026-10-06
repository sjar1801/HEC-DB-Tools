"""hec_db.sheets — Tool 4: Place On Sheets.

Packs every section view of a ductbank assembly onto sheets using
PLACE-MEASURE-MOVE layout:
  * places each viewport at a temp spot, asks Revit for the REAL rendered
    size (GetBoxOutline + GetLabelOutline), then moves it into position
  * lays viewports left-to-right, wraps to a new row when the row is full
  * starts a new overflow sheet when the current sheet is full
Sheets are created with AssemblyViewUtils.CreateSheet() and renamed
"[AssemblyName] — Panel Builds", "… Panel Builds 2", …

PyRevit v6 + CPython 3123  |  Revit 2025
Hunt Electric — MONARCH Job
"""

import clr
clr.AddReference("RevitAPI")
from Autodesk.Revit.DB import (
    FilteredElementCollector,
    FamilySymbol,
    BuiltInCategory,
    BuiltInParameter,
    Transaction,
    ElementTransformUtils,
    AssemblyViewUtils,
    Viewport,
    XYZ,
)

from hec_db.constants import (
    SHEET_W, SHEET_H, MARGIN_LEFT, MARGIN_RIGHT, MARGIN_TOP, MARGIN_BOTTOM,
    PAD_X, PAD_Y, SHEET_SUFFIX,
)
from hec_db.ui import alert, select_from_list
from hec_db.assembly import pick_assembly, collect_section_views


# ── HELPERS ─────────────────────────────────────────────────────────────────

def pick_title_block(doc):
    """Show a pick list of every title block FamilySymbol loaded in the project.

    Returns the chosen FamilySymbol's ElementId, "NONE_LOADED" if nothing is
    loaded, or None if the user cancelled. Only title blocks ACTUALLY LOADED
    are shown, so the user can never pick a missing one.
    """
    symbols = list(
        FilteredElementCollector(doc)
        .OfCategory(BuiltInCategory.OST_TitleBlocks)
        .OfClass(FamilySymbol)
    )
    if not symbols:
        return "NONE_LOADED"

    # Build "Family : Type" labels, keep a map back to the symbol
    option_map = {}
    for fs in symbols:
        try:
            fam_name = fs.Family.Name
        except Exception:
            fam_name = "<family>"
        try:
            type_name = fs.get_Parameter(
                BuiltInParameter.SYMBOL_NAME_PARAM).AsString()
        except Exception:
            type_name = None
        if not type_name:
            try:
                type_name = fs.Name
            except Exception:
                type_name = "<type>"
        label = "{} : {}".format(fam_name, type_name)
        option_map[label] = fs

    labels = sorted(option_map.keys())
    chosen = select_from_list(
        labels,
        title="Select Title Block for Panel Build sheets",
        button_text="Use this title block",
    )
    if not chosen:
        return None

    fs = option_map[chosen]
    if not fs.IsActive:
        # Activation must happen inside a transaction — caller handles that if
        # needed, but FamilySymbol.Activate requires an open transaction.
        pass
    return fs.Id


def measure_viewport(vp):
    """Return (width, height, center_x, center_y) of a placed Viewport.

    Uses GetBoxOutline() + GetLabelOutline() — Revit's own rendered sizes,
    so the result is exact regardless of view scale or crop box quirks.
    The height is the FULL envelope (view content + title label below).
    """
    box = vp.GetBoxOutline()            # view content area on sheet
    bmin, bmax = box.MinimumPoint, box.MaximumPoint
    x0, y0 = bmin.X, bmin.Y
    x1, y1 = bmax.X, bmax.Y

    # Include the label strip (title below the viewport)
    try:
        lbl = vp.GetLabelOutline()
        lmin, lmax = lbl.MinimumPoint, lbl.MaximumPoint
        x0 = min(x0, lmin.X)
        y0 = min(y0, lmin.Y)
        x1 = max(x1, lmax.X)
        y1 = max(y1, lmax.Y)
    except Exception:
        pass  # no label — just use the box

    w = x1 - x0
    h = y1 - y0
    cx = (x0 + x1) / 2.0
    cy = (y0 + y1) / 2.0
    return (w, h, cx, cy)


def rename_sheet(sheet, name):
    """Set the sheet NAME parameter (not number). Silent on read-only."""
    try:
        p = sheet.get_Parameter(BuiltInParameter.SHEET_NAME)
        if p and not p.IsReadOnly:
            p.Set(name)
    except Exception:
        pass


# ── ORCHESTRATOR ────────────────────────────────────────────────────────────

def place_on_sheets(doc, uidoc, assembly=None, tb_id=None):
    """Tool 4 orchestrator. Creates sheets and packs section viewports.

    *assembly* — AssemblyInstance to use. If None, resolved via pick_assembly.
    *tb_id*    — title block FamilySymbol ElementId. If None, user is prompted.

    Manages its own Transaction. Prints progress. Returns a stats dict:
      {"status": "ok"|"cancelled"|"error", "sheets": n, "placed": n,
       "views": n, "skipped": [(name, reason), ...]}
    """
    stats = {"status": "cancelled", "sheets": 0, "placed": 0,
             "views": 0, "skipped": []}

    print("── HEC Place On Sheets ──")

    # 1. Title block --------------------------------------------------------
    if tb_id is None:
        tb_id = pick_title_block(doc)
    # NOTE: never use == between a .NET object and a str under CPython/PythonNet —
    # it dispatches to ElementId.op_Equality and throws. Check the type instead.
    if isinstance(tb_id, str) and tb_id == "NONE_LOADED":
        alert("No title blocks are loaded in this project.\n\n"
              "Load a title block family (e.g. the 30x42 BAER block) and run again.",
              "No Title Block")
        stats["status"] = "error"
        return stats
    if tb_id is None:
        print("Cancelled — no title block selected.")
        return stats

    # 2. Assembly -----------------------------------------------------------
    if assembly is None:
        assembly = pick_assembly(
            uidoc, doc,
            title="Select the ductbank assembly to document",
            button_text="Place sections for this assembly")
    if isinstance(assembly, str) and assembly == "NONE_IN_MODEL":
        alert("No assemblies exist in this model.\n\n"
              "Create your ductbank assembly first.", "No Assembly")
        stats["status"] = "error"
        return stats
    if assembly is None:
        print("Cancelled — no assembly selected.")
        return stats

    assembly_id = assembly.Id
    try:
        assembly_name = assembly.Name
    except Exception:
        assembly_name = "Assembly {}".format(assembly_id.IntegerValue)
    print("Assembly: {}".format(assembly_name))

    # 3. Section views ------------------------------------------------------
    section_views = collect_section_views(doc, assembly_id)
    if not section_views:
        alert("No section views found for assembly:\n  {}\n\n"
              "Run 'Create DB Sections' (Tool 2) first.".format(assembly_name),
              "No Sections")
        stats["status"] = "error"
        return stats
    print("Section views to place: {}".format(len(section_views)))
    stats["views"] = len(section_views)

    # 4. Usable drawing rectangle ------------------------------------------
    usable_x0 = MARGIN_LEFT
    usable_y0 = MARGIN_BOTTOM
    usable_x1 = SHEET_W - MARGIN_RIGHT
    usable_y1 = SHEET_H - MARGIN_TOP
    usable_w  = usable_x1 - usable_x0
    usable_h  = usable_y1 - usable_y0

    # 5. Place-measure-move packing -----------------------------------------
    #
    # Strategy: place each viewport at a TEMP position on the sheet, ask Revit
    # for the REAL rendered size (GetBoxOutline + GetLabelOutline), then move the
    # viewport to its correct grid position. This eliminates all crop-box and
    # view-scale guesswork — Revit tells us the actual footprint.
    #
    # If a viewport won't fit on the current sheet, we delete it from this sheet
    # and push the view to the next sheet's queue.

    print("")
    print("── Packing viewports (place-measure-move) ──")

    t = Transaction(doc, "Place DB Sections on Sheets")
    t.Start()

    # Activate the chosen title block symbol (requires open transaction)
    try:
        tb_symbol = doc.GetElement(tb_id)
        if tb_symbol is not None and not tb_symbol.IsActive:
            tb_symbol.Activate()
            doc.Regenerate()
    except Exception:
        pass

    # Temp placement point — sheet center, far from borders
    TEMP_PT = XYZ(SHEET_W / 2.0, SHEET_H / 2.0, 0)

    view_queue     = list(section_views)
    sheet_index    = 0
    placed_total   = 0
    skipped_views  = []   # views that couldn't be placed at all
    created_sheets = []

    while view_queue:
        sheet_index += 1

        # Create the assembly sheet with the chosen title block
        sheet = AssemblyViewUtils.CreateSheet(doc, assembly_id, tb_id)
        doc.Regenerate()

        if sheet_index == 1:
            sheet_name = "{} — {}".format(assembly_name, SHEET_SUFFIX)
        else:
            sheet_name = "{} — {} {}".format(assembly_name, SHEET_SUFFIX, sheet_index)
        rename_sheet(sheet, sheet_name)
        created_sheets.append(sheet)
        print("")
        print("Sheet {}: {} - {}".format(sheet_index, sheet.SheetNumber, sheet_name))

        cur_x = usable_x0
        cur_y = usable_y1   # start at top, work downward
        row_h = 0.0
        next_batch = []
        placed_this_sheet = 0

        for view in view_queue:
            # ── Step A: can we even add this view? ──
            if not Viewport.CanAddViewToSheet(doc, sheet.Id, view.Id):
                print("  SKIP: {} — already on another sheet".format(view.Name))
                skipped_views.append((view.Name, "already placed on a sheet"))
                continue

            # ── Step B: place at temp position so Revit renders it ──
            try:
                vp = Viewport.Create(doc, sheet.Id, view.Id, TEMP_PT)
                doc.Regenerate()
            except Exception as ex:
                print("  SKIP: {} — viewport creation failed: {}".format(
                    view.Name, ex))
                skipped_views.append((view.Name, str(ex)))
                continue

            # ── Step C: measure the REAL size ──
            try:
                vp_w, vp_h, cur_cx, cur_cy = measure_viewport(vp)
            except Exception:
                # Fallback: if outline methods fail, use a small default
                vp_w, vp_h = 0.3, 0.3
                cur_cx, cur_cy = TEMP_PT.X, TEMP_PT.Y

            print("  measured: {:<16}  {:.3f} x {:.3f} ft".format(
                view.Name, vp_w, vp_h))

            # ── Step D: too big for the entire usable area? ──
            if vp_w > usable_w + 0.01 or vp_h > usable_h + 0.01:
                print("    → TOO LARGE for any sheet ({:.2f}x{:.2f} usable). "
                      "Removing.".format(usable_w, usable_h))
                doc.Delete(vp.Id)
                skipped_views.append((view.Name,
                    "too large: {:.2f}x{:.2f} ft".format(vp_w, vp_h)))
                continue

            # ── Step E: does it fit in the current row? ──
            if (cur_x + vp_w > usable_x1 + 0.01) and (cur_x > usable_x0 + 0.01):
                # wrap to next row
                cur_x = usable_x0
                cur_y -= (row_h + PAD_Y)
                row_h = 0.0

            # ── Step F: does it fit vertically on this sheet? ──
            if cur_y - vp_h < usable_y0 - 0.01:
                # Doesn't fit → delete from this sheet, push to next
                doc.Delete(vp.Id)
                next_batch.append(view)
                print("    → overflow to next sheet")
                continue

            # ── Step G: compute target center and move ──
            target_cx = cur_x + vp_w / 2.0
            target_cy = cur_y - vp_h / 2.0
            dx = target_cx - cur_cx
            dy = target_cy - cur_cy

            if abs(dx) > 0.001 or abs(dy) > 0.001:
                ElementTransformUtils.MoveElement(
                    doc, vp.Id, XYZ(dx, dy, 0))

            placed_this_sheet += 1
            placed_total += 1
            print("    → placed @ ({:.3f}, {:.3f})".format(target_cx, target_cy))

            # Advance cursor
            cur_x += vp_w + PAD_X
            if vp_h > row_h:
                row_h = vp_h

        print("  → {} viewport(s) on this sheet".format(placed_this_sheet))

        # Safety: if nothing placed and queue didn't shrink, stop to avoid a loop
        if placed_this_sheet == 0 and len(next_batch) == len(view_queue):
            print("  (nothing placeable remaining — stopping)")
            break

        view_queue = next_batch

    t.Commit()

    # ── Summary ───────────────────────────────────────────────────────────
    print("")
    print("═══ DONE ═══")
    print("Sheets created:    {}".format(len(created_sheets)))
    print("Viewports placed:  {}/{}".format(placed_total, len(section_views)))
    if skipped_views:
        print("")
        print("⚠ {} view(s) could not be placed:".format(len(skipped_views)))
        for nm, reason in skipped_views:
            print("    {} — {}".format(nm, reason))
    print("")
    print("Review the sheets in the Project Browser under this assembly.")

    stats.update({"status": "ok", "sheets": len(created_sheets),
                  "placed": placed_total, "skipped": skipped_views})
    return stats
