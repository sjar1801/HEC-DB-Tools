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
  - Packs them onto sheets using PLACE-MEASURE-MOVE layout:
      * places each viewport at a temp spot, asks Revit for the REAL rendered
        size (GetBoxOutline + GetLabelOutline), then moves it into position
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
    ElementTransformUtils,
    AssemblyViewUtils,
    Viewport,
    View,
    ViewSection,
    XYZ,
)

clr.AddReference("RevitAPIUI")
from Autodesk.Revit.UI import TaskDialog

# Windows Forms for the pick-list dialog (pyrevit.forms is IronPython-only and
# raises "not supported under CPython", so we use .NET WinForms directly).
try:
    clr.AddReference("System.Windows.Forms")
    clr.AddReference("System.Drawing")
    from System.Windows.Forms import (
        Form, ListBox, Button, Label, DialogResult, FormStartPosition,
        FormBorderStyle, AnchorStyles, SelectionMode,
    )
    from System.Drawing import Point, Size
    WINFORMS_OK = True
except Exception:
    WINFORMS_OK = False

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


# ── UI HELPERS (CPython-safe — no pyrevit.forms) ────────────────────────────

def alert(msg, title="HEC Place On Sheets"):
    """Modal message box via Revit TaskDialog (works under CPython)."""
    try:
        TaskDialog.Show(title, msg)
    except Exception:
        print("[{}] {}".format(title, msg))


def select_from_list(labels, title, button_text="OK"):
    """Show a single-select list dialog. Returns chosen label or None.

    Uses .NET Windows Forms directly. If WinForms is unavailable for some
    reason, falls back to a TaskDialog with command links (max 4 items) or
    auto-picks when there is only one option.
    """
    labels = list(labels)
    if not labels:
        return None
    if len(labels) == 1:
        return labels[0]

    if WINFORMS_OK:
        result = {"value": None}

        form = Form()
        form.Text = title
        form.StartPosition = FormStartPosition.CenterScreen
        form.FormBorderStyle = FormBorderStyle.Sizable
        form.MinimizeBox = False
        form.MaximizeBox = False
        form.ClientSize = Size(520, 380)
        form.TopMost = True

        lbl = Label()
        lbl.Text = "Select one item and click '{}':".format(button_text)
        lbl.Location = Point(12, 10)
        lbl.AutoSize = True
        form.Controls.Add(lbl)

        lb = ListBox()
        lb.Location = Point(12, 32)
        lb.Size = Size(496, 290)
        lb.SelectionMode = SelectionMode.One
        lb.Anchor = (AnchorStyles.Top | AnchorStyles.Bottom |
                     AnchorStyles.Left | AnchorStyles.Right)
        for item in labels:
            lb.Items.Add(item)
        lb.SelectedIndex = 0
        form.Controls.Add(lb)

        def on_ok(sender, args):
            if lb.SelectedItem is not None:
                result["value"] = str(lb.SelectedItem)
                form.DialogResult = DialogResult.OK
                form.Close()

        def on_cancel(sender, args):
            result["value"] = None
            form.DialogResult = DialogResult.Cancel
            form.Close()

        ok = Button()
        ok.Text = button_text
        ok.Size = Size(180, 30)
        ok.Location = Point(12, 336)
        ok.Anchor = AnchorStyles.Bottom | AnchorStyles.Left
        ok.Click += on_ok
        form.Controls.Add(ok)

        cancel = Button()
        cancel.Text = "Cancel"
        cancel.Size = Size(100, 30)
        cancel.Location = Point(408, 336)
        cancel.Anchor = AnchorStyles.Bottom | AnchorStyles.Right
        cancel.Click += on_cancel
        form.Controls.Add(cancel)

        # Double-click an item = OK
        lb.DoubleClick += on_ok

        form.AcceptButton = ok
        form.CancelButton = cancel
        form.ShowDialog()
        return result["value"]

    # Fallback: TaskDialog command links (first 4 only)
    from Autodesk.Revit.UI import TaskDialogCommandLinkId, TaskDialogResult
    td = TaskDialog(title)
    td.MainInstruction = title
    link_ids = [TaskDialogCommandLinkId.CommandLink1,
                TaskDialogCommandLinkId.CommandLink2,
                TaskDialogCommandLinkId.CommandLink3,
                TaskDialogCommandLinkId.CommandLink4]
    shown = labels[:4]
    for i, item in enumerate(shown):
        td.AddCommandLink(link_ids[i], item)
    if len(labels) > 4:
        td.MainContent = ("Only the first 4 of {} options are shown. "
                          "Cancel and purge unused families to shorten "
                          "the list.").format(len(labels))
    td.CommonButtons = 0
    td.AllowCancellation = True
    res = td.Show()
    results = [TaskDialogResult.CommandLink1, TaskDialogResult.CommandLink2,
               TaskDialogResult.CommandLink3, TaskDialogResult.CommandLink4]
    for i, r in enumerate(results[:len(shown)]):
        if res == r:
            return shown[i]
    return None


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

    chosen = select_from_list(
        sorted(option_map.keys()),
        title="Select the ductbank assembly to document",
        button_text="Place sections for this assembly",
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
    for v in FilteredElementCollector(doc).OfClass(ViewSection).ToElements():
        if v.IsTemplate:
            continue
        try:
            if v.AssociatedAssemblyInstanceId != assembly_id:
                continue
        except Exception:
            continue
        # ViewSection only → excludes the assembly 3D view, Plan Detail,
        # schedules, and (critically) the sheets themselves on re-runs.
        views.append(v)
    views.sort(key=lambda x: x.Name)
    return views


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


# ── RUN ──────────────────────────────────────────────────────────────────────
print("── HEC Place On Sheets ──")

# 1. Title block ------------------------------------------------------------
tb_id = pick_title_block()
# NOTE: never use == between a .NET object and a str under CPython/PythonNet —
# it dispatches to ElementId.op_Equality and throws. Check the type instead.
if isinstance(tb_id, str) and tb_id == "NONE_LOADED":
    alert("No title blocks are loaded in this project.\n\n"
          "Load a title block family (e.g. the 30x42 BAER block) and run again.",
          "No Title Block")
    raise SystemExit
if tb_id is None:
    print("Cancelled — no title block selected.")
    raise SystemExit

# 2. Assembly ---------------------------------------------------------------
assembly = pick_assembly()
if isinstance(assembly, str) and assembly == "NONE_IN_MODEL":
    alert("No assemblies exist in this model.\n\n"
          "Create your ductbank assembly first.", "No Assembly")
    raise SystemExit
if assembly is None:
    print("Cancelled — no assembly selected.")
    raise SystemExit

assembly_id = assembly.Id
try:
    assembly_name = assembly.Name
except Exception:
    assembly_name = "Assembly {}".format(assembly_id.IntegerValue)
print("Assembly: {}".format(assembly_name))

# 3. Section views ----------------------------------------------------------
section_views = collect_section_views(assembly_id)
if not section_views:
    alert("No section views found for assembly:\n  {}\n\n"
          "Run 'Create DB Sections' (Tool 2) first.".format(assembly_name),
          "No Sections")
    raise SystemExit
print("Section views to place: {}".format(len(section_views)))

# 4. Usable drawing rectangle ----------------------------------------------
usable_x0 = MARGIN_LEFT
usable_y0 = MARGIN_BOTTOM
usable_x1 = SHEET_W - MARGIN_RIGHT
usable_y1 = SHEET_H - MARGIN_TOP
usable_w  = usable_x1 - usable_x0
usable_h  = usable_y1 - usable_y0

# 5. Place-measure-move packing ---------------------------------------------
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

# ── Summary ──────────────────────────────────────────────────────────────────
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
