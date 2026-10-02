#! python3
"""HEC Ductbank Place On Sheets — PyRevit Button  (Tool 4 of 4)

Prerequisites:
  - "Assign Panel IDs"   (Tool 1) — Comments populated
  - "Create DB Sections" (Tool 2) — section views exist, named Panel-XXX
  - "Rotate DB Sections" (Tool 3) — sections aimed at their panels

What this tool does:
  - Lets you PICK the title block to use (any title block loaded in the project)
  - Finds the ductbank assembly (uses your current selection, or prompts)
  - Collects every section view that belongs to that assembly
  - Sorts them by name (= panel ID order)
  - Packs them onto sheets using SIZE-AWARE layout:
      * reads each view's real printed size (crop box ÷ view scale)
      * lays viewports left-to-right, wraps to a new row when the row is full
      * starts a new overflow sheet when the current sheet is full
  - Creates sheets with AssemblyViewUtils.CreateSheet() and renames them
      "[AssemblyName] — Panel Builds", "… Panel Builds 2", "… Panel Builds 3" …

What this tool does NOT do:
  - Create or rotate sections → Tools 2 and 3

PyRevit v6 + CPython 3123  |  Revit 2025
Hunt Electric — MONARCH Job
"""

import clr
clr.AddReference("RevitAPI")
from Autodesk.Revit.DB import (
    FilteredElementCollector,
    FamilySymbol,
    AssemblyInstance,
    BuiltInCategory,
    BuiltInParameter,
    Transaction,
    ElementId,
    AssemblyViewUtils,
    Viewport,
    View,
    XYZ,
)

from pyrevit import forms

# ── Layout constants ─────────────────────────────────────────────────────────
# All values in FEET (Revit internal units). Tune to match your title block.
# These describe the usable drawing rectangle INSIDE the title block border.
SHEET_W       = 3.5     # 42" nominal sheet width
SHEET_H       = 2.5     # 30" nominal sheet height
MARGIN_LEFT   = 0.125   # ~1.5" from left edge
MARGIN_RIGHT  = 0.625   # ~7.5" from right edge (title block info strip)
MARGIN_TOP    = 0.125   # ~1.5" from top edge
MARGIN_BOTTOM = 0.25    # ~3" from bottom edge (title block info area)
PAD_X         = 0.083   # ~1" horizontal gap between viewports
PAD_Y         = 0.083   # ~1" vertical gap between viewports
# ─────────────────────────────────────────────────────────────────────────────

SHEET_SUFFIX = "Panel Builds"

# ── PyRevit doc access ──────────────────────────────────────────────────────
uidoc = __revit__.ActiveUIDocument          # noqa: F821
doc   = uidoc.Document
# ───────────────────────────────────────────────────────────────────────────


# ── HELPERS ─────────────────────────────────────────────────────────────────

def pick_title_block():
    """Show a pick list of every title block FamilySymbol loaded in the project.

    Returns the chosen FamilySymbol's ElementId, or None if nothing loaded /
    user cancelled. Only title blocks ACTUALLY LOADED are shown, so the user
    can never pick a missing one.
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
    chosen = forms.SelectFromList.show(
        labels,
        title="Select Title Block for Panel Build sheets",
        multiselect=False,
        button_name="Use this title block",
    )
    if not chosen:
        return None

    fs = option_map[chosen]
    if not fs.IsActive:
        # Activation must happen inside a transaction — caller handles that if
        # needed, but FamilySymbol.Activate requires an open transaction.
        pass
    return fs.Id


def pick_assembly():
    """Return the AssemblyInstance to document.

    Order of preference:
      1. Exactly one AssemblyInstance in the current selection → use it.
      2. Active view belongs to an assembly → use that.
      3. Otherwise prompt the user to pick from all assemblies in the model.
    Returns the AssemblyInstance element, or None.
    """
    # 1. Current selection
    sel_ids = uidoc.Selection.GetElementIds()
    sel_assemblies = []
    for sid in sel_ids:
        el = doc.GetElement(sid)
        if isinstance(el, AssemblyInstance):
            sel_assemblies.append(el)
    if len(sel_assemblies) == 1:
        return sel_assemblies[0]

    # 2. Active view's assembly
    try:
        av = doc.ActiveView
        if hasattr(av, "AssociatedAssemblyInstanceId"):
            aid = av.AssociatedAssemblyInstanceId
            if aid and aid != ElementId.InvalidElementId:
                el = doc.GetElement(aid)
                if isinstance(el, AssemblyInstance):
                    return el
    except Exception:
        pass

    # 3. Prompt from all assemblies
    all_assemblies = list(
        FilteredElementCollector(doc)
        .OfClass(AssemblyInstance)
    )
    if not all_assemblies:
        return "NONE_IN_MODEL"
    if len(all_assemblies) == 1:
        return all_assemblies[0]

    option_map = {}
    for a in all_assemblies:
        try:
            nm = a.Name
        except Exception:
            nm = "Assembly {}".format(a.Id.IntegerValue)
        label = "{}  (id {})".format(nm, a.Id.IntegerValue)
        option_map[label] = a

    chosen = forms.SelectFromList.show(
        sorted(option_map.keys()),
        title="Select the ductbank assembly to document",
        multiselect=False,
        button_name="Place sections for this assembly",
    )
    if not chosen:
        return None
    return option_map[chosen]


def collect_section_views(assembly_id):
    """Return every non-template section view that belongs to this assembly.

    Scoped by AssociatedAssemblyInstanceId — same pattern as Tools 2 & 3 —
    so DB-2 never picks up DB-1's views. Sorted by Name (= panel ID order).
    """
    views = []
    for v in FilteredElementCollector(doc).OfClass(View).ToElements():
        if v.IsTemplate:
            continue
        if not hasattr(v, "AssociatedAssemblyInstanceId"):
            continue
        if v.AssociatedAssemblyInstanceId != assembly_id:
            continue
        # Only views that can live on a sheet (sections/details)
        views.append(v)
    views.sort(key=lambda x: x.Name)
    return views


def get_viewport_size(view):
    """Return (width_ft, height_ft) of the view as printed on the sheet.

    Sheet size = model crop extents ÷ view scale. Falls back to a small
    default if the crop box can't be read.
    """
    try:
        crop = view.CropBox
        model_w = abs(crop.Max.X - crop.Min.X)
        model_h = abs(crop.Max.Y - crop.Min.Y)
    except Exception:
        model_w, model_h = 1.0, 1.0

    try:
        scale = float(view.Scale)
        if scale <= 0:
            scale = 1.0
    except Exception:
        scale = 1.0

    w = model_w / scale
    h = model_h / scale
    # Guard against degenerate zero sizes
    if w <= 0:
        w = 0.1
    if h <= 0:
        h = 0.1
    return (w, h)


def rename_sheet(sheet, name):
    """Set the sheet NAME parameter (not number). Silent on read-only."""
    try:
        p = sheet.get_Parameter(BuiltInParameter.SHEET_NAME)
        if p and not p.IsReadOnly:
            p.Set(name)
    except Exception:
        pass


# ── RUN ──────────────────────────────────────────────────────────────────────
print("── HEC Place On Sheets ──")

# 1. Title block ------------------------------------------------------------
tb_id = pick_title_block()
if tb_id == "NONE_LOADED":
    forms.alert(
        "No title blocks are loaded in this project.\n\n"
        "Load a title block family (e.g. the 30x42 BAER block) and run again.",
        title="No Title Block", exitscript=True)
if tb_id is None:
    forms.alert("Cancelled — no title block selected.",
                title="Cancelled", exitscript=True)

# 2. Assembly ---------------------------------------------------------------
assembly = pick_assembly()
if assembly == "NONE_IN_MODEL":
    forms.alert(
        "No assemblies exist in this model.\n\n"
        "Create your ductbank assembly first.",
        title="No Assembly", exitscript=True)
if assembly is None:
    forms.alert("Cancelled — no assembly selected.",
                title="Cancelled", exitscript=True)

assembly_id = assembly.Id
try:
    assembly_name = assembly.Name
except Exception:
    assembly_name = "Assembly {}".format(assembly_id.IntegerValue)
print("Assembly: {}".format(assembly_name))

# 3. Section views ----------------------------------------------------------
section_views = collect_section_views(assembly_id)
if not section_views:
    forms.alert(
        "No section views found for assembly:\n  {}\n\n"
        "Run 'Create DB Sections' (Tool 2) first.".format(assembly_name),
        title="No Sections", exitscript=True)
print("Section views to place: {}".format(len(section_views)))

# 4. Usable drawing rectangle ----------------------------------------------
usable_x0 = MARGIN_LEFT
usable_y0 = MARGIN_BOTTOM
usable_x1 = SHEET_W - MARGIN_RIGHT
usable_y1 = SHEET_H - MARGIN_TOP
usable_w  = usable_x1 - usable_x0
usable_h  = usable_y1 - usable_y0

# 5. Pack + place -----------------------------------------------------------
print("")
print("── Packing viewports ──")

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

view_queue   = list(section_views)
sheet_index  = 0
placed_total = 0
skipped_big  = []   # views too large for any sheet
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
        vp_w, vp_h = get_viewport_size(view)

        # View bigger than the whole usable area → cannot ever fit
        if vp_w > usable_w or vp_h > usable_h:
            skipped_big.append((view.Name, vp_w, vp_h))
            print("  SKIP (too large): {}  ({:.2f} x {:.2f} ft, "
                  "usable {:.2f} x {:.2f})".format(
                      view.Name, vp_w, vp_h, usable_w, usable_h))
            continue

        # Wrap to a new row if this view won't fit in the current row
        if (cur_x + vp_w > usable_x1) and (cur_x > usable_x0):
            cur_x = usable_x0
            cur_y -= (row_h + PAD_Y)
            row_h = 0.0

        # Doesn't fit vertically on this sheet → push to next sheet
        if cur_y - vp_h < usable_y0:
            next_batch.append(view)
            continue

        center_x = cur_x + vp_w / 2.0
        center_y = cur_y - vp_h / 2.0

        try:
            if Viewport.CanAddViewToSheet(doc, sheet.Id, view.Id):
                Viewport.Create(
                    doc, sheet.Id, view.Id, XYZ(center_x, center_y, 0))
                placed_this_sheet += 1
                placed_total += 1
                print("  OK: {:<16} @ ({:.2f}, {:.2f})  size {:.2f} x {:.2f}".format(
                    view.Name, center_x, center_y, vp_w, vp_h))
            else:
                print("  WARNING: cannot add {} to sheet "
                      "(already placed elsewhere?)".format(view.Name))
        except Exception as vex:
            print("  WARNING: viewport failed for {}: {}".format(view.Name, vex))

        cur_x += vp_w + PAD_X
        if vp_h > row_h:
            row_h = vp_h

    print("  → {} viewport(s) on this sheet".format(placed_this_sheet))

    # Safety: if nothing got placed and nothing advanced, stop to avoid a loop
    if placed_this_sheet == 0 and len(next_batch) == len(view_queue):
        print("  (nothing placeable remaining — stopping)")
        break

    view_queue = next_batch

t.Commit()

# ── Summary ──────────────────────────────────────────────────────────────────
print("")
print("═══ DONE ═══")
print("Sheets created:    {}".format(len(created_sheets)))
print("Viewports placed:  {}/{}".format(placed_total, len(section_views)))
if skipped_big:
    print("")
    print("⚠ {} view(s) too large to fit on any sheet:".format(len(skipped_big)))
    for nm, w, h in skipped_big:
        print("    {}  ({:.2f} x {:.2f} ft)".format(nm, w, h))
    print("  Check the view scale or crop box, or use a larger title block.")
print("")
print("Review the sheets in the Project Browser under this assembly.")
