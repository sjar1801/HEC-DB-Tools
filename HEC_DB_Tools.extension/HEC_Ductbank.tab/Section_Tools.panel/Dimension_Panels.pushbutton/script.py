#! python3
"""HEC Ductbank Dimension Panels — PyRevit Button  (Tool 5)

Prerequisites:
  - "Assign Panel IDs"   (Tool 1) — Comments populated
  - "Create DB Sections" (Tool 2) — section views exist, named Panel-XXX
  - "Rotate DB Sections" (Tool 3) — sections aimed square at their panels

What this tool does:
  - Finds the ductbank assembly (current selection → active view → prompt)
  - Lets you tick which dimensions to place (all on by default):
      * Row String        — segmented string through every rebar spacer
      * Overall Height    — single dim, panel Top → Bottom
      * Overall Width     — single dim, panel Left → Right
  - Optionally "Replace existing" — deletes all dims in each view before
    placing, so re-runs produce a clean slate
  - AUTO-DETECTS spacer bar orientation:
      * Bars spread horizontally (same Z)  → row string placed BELOW panel,
        using each bar's CenterLeftRight ref + panel Left/Right as endpoints
      * Bars spread vertically (different Z)→ row string placed to the RIGHT,
        using each bar's CenterFrontBack ref + panel Top/Bottom as endpoints
  - Spacer bars identified by REFERENCE FINGERPRINT (has BOTH CenterLeftRight
    AND CenterFrontBack refs), not by family name. Fallback: name ends '_R'.
  - Uses dimension style "ASSEMBLIES - CONTINUOUS - 3/32" - HEC - BLACK"
    (falls back to the first Linear dimension type if it's not loaded)
  - Everything runs inside ONE transaction

What this tool does NOT do:
  - Create / rotate / sheet the sections → Tools 2, 3, 4

PyRevit v6 + CPython 3123  |  Revit 2025
Hunt Electric — MONARCH Job
"""

import math

import clr
clr.AddReference("RevitAPI")
from Autodesk.Revit.DB import (
    FilteredElementCollector,
    FamilyInstance,
    FamilyInstanceReferenceType,
    AssemblyInstance,
    BuiltInParameter,
    Transaction,
    ElementId,
    Dimension,
    DimensionType,
    DimensionStyleType,
    ReferenceArray,
    Line,
    View,
    ViewSection,
    XYZ,
)

clr.AddReference("RevitAPIUI")
from Autodesk.Revit.UI import TaskDialog

# Windows Forms for the dialogs (pyrevit.forms is IronPython-only and raises
# "not supported under CPython", so we use .NET WinForms directly).
try:
    clr.AddReference("System.Windows.Forms")
    clr.AddReference("System.Drawing")
    from System.Windows.Forms import (
        Form, ListBox, CheckedListBox, Button, Label, DialogResult,
        FormStartPosition, FormBorderStyle, AnchorStyles, SelectionMode,
    )
    from System.Drawing import Point, Size
    WINFORMS_OK = True
except Exception:
    WINFORMS_OK = False

# ── CONFIG ──────────────────────────────────────────────────────────────────
DEFAULT_DIM_TYPE_NAME = 'ASSEMBLIES - CONTINUOUS - 3/32" - HEC - BLACK'

DIM_OFFSET   = 0.5     # ft — gap between panel extent and dimension line
Z_TOLERANCE  = 0.01    # ft — refs closer than this in Z are the same row line
X_TOLERANCE  = 0.01    # ft — refs closer than this in X are the same column
SIDE_MARGIN  = 0.05    # ft — how far past panel centre counts as "that side"

OPT_ROW     = "Row String"
OPT_HEIGHT  = "Overall Height"
OPT_WIDTH   = "Overall Width"
OPT_REPLACE = "Replace existing dimensions"
DIM_OPTIONS = [OPT_ROW, OPT_HEIGHT, OPT_WIDTH, OPT_REPLACE]
# Indices that are checked by default (first 3 on, Replace off)
DEFAULT_CHECKED = [True, True, True, False]
# ───────────────────────────────────────────────────────────────────────────

# ── PyRevit doc access ──────────────────────────────────────────────────────
uidoc = __revit__.ActiveUIDocument          # noqa: F821
doc   = uidoc.Document
# ───────────────────────────────────────────────────────────────────────────


# ── UI HELPERS (CPython-safe — no pyrevit.forms) ────────────────────────────

def alert(msg, title="HEC Dimension Panels"):
    """Modal message box via Revit TaskDialog (works under CPython)."""
    try:
        TaskDialog.Show(title, msg)
    except Exception:
        print("[{}] {}".format(title, msg))


def select_from_list(labels, title, button_text="OK"):
    """Show a single-select list dialog. Returns chosen label or None."""
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


def select_checked(labels, title, defaults=None, button_text="OK"):
    """Show a multi-select CheckedListBox dialog.

    *defaults* is a list of bools (same length as *labels*) indicating which
    items are ticked by default. If not provided, every item starts ticked.
    Returns the list of ticked labels (in original order), or None if the
    user cancelled. If WinForms is unavailable, returns the default-ticked
    items.
    """
    labels = list(labels)
    if not labels:
        return []
    if defaults is None:
        defaults = [True] * len(labels)
    if not WINFORMS_OK:
        return [l for l, d in zip(labels, defaults) if d]

    result = {"value": None}

    form = Form()
    form.Text = title
    form.StartPosition = FormStartPosition.CenterScreen
    form.FormBorderStyle = FormBorderStyle.FixedDialog
    form.MinimizeBox = False
    form.MaximizeBox = False
    form.ClientSize = Size(420, 260)
    form.TopMost = True

    lbl = Label()
    lbl.Text = "Tick the dimensions to place, then click '{}':".format(
        button_text)
    lbl.Location = Point(12, 10)
    lbl.AutoSize = True
    form.Controls.Add(lbl)

    clb = CheckedListBox()
    clb.Location = Point(12, 32)
    clb.Size = Size(396, 170)
    clb.CheckOnClick = True
    for i, item in enumerate(labels):
        checked = defaults[i] if i < len(defaults) else True
        clb.Items.Add(item, checked)
    form.Controls.Add(clb)

    def on_ok(sender, args):
        picked = []
        for i in range(clb.Items.Count):
            if clb.GetItemChecked(i):
                picked.append(str(clb.Items[i]))
        result["value"] = picked
        form.DialogResult = DialogResult.OK
        form.Close()

    def on_cancel(sender, args):
        result["value"] = None
        form.DialogResult = DialogResult.Cancel
        form.Close()

    ok = Button()
    ok.Text = button_text
    ok.Size = Size(180, 30)
    ok.Location = Point(12, 218)
    ok.Click += on_ok
    form.Controls.Add(ok)

    cancel = Button()
    cancel.Text = "Cancel"
    cancel.Size = Size(100, 30)
    cancel.Location = Point(308, 218)
    cancel.Click += on_cancel
    form.Controls.Add(cancel)

    form.AcceptButton = ok
    form.CancelButton = cancel
    form.ShowDialog()
    return result["value"]


# ── MODEL HELPERS ───────────────────────────────────────────────────────────

def pick_assembly():
    """Return the AssemblyInstance to document.

    Order of preference:
      1. Exactly one AssemblyInstance in the current selection → use it.
      2. Active view belongs to an assembly → use that.
      3. Otherwise prompt the user to pick from all assemblies in the model.
    Returns the AssemblyInstance element, "NONE_IN_MODEL", or None.
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
        title="Select the ductbank assembly to dimension",
        button_text="Dimension this assembly",
    )
    if not chosen:
        return None
    return option_map[chosen]


def collect_section_views(assembly_id):
    """Return every non-template section view that belongs to this assembly."""
    views = []
    for v in FilteredElementCollector(doc).OfClass(ViewSection).ToElements():
        if v.IsTemplate:
            continue
        try:
            if v.AssociatedAssemblyInstanceId != assembly_id:
                continue
        except Exception:
            continue
        views.append(v)
    views.sort(key=lambda x: x.Name)
    return views


def _norm(s):
    """Normalise a name for forgiving comparison (spaces/case-insensitive)."""
    return "".join(str(s).split()).lower()


def find_dimension_type():
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


def dim_type_name(dt):
    """Type name of a DimensionType (handles CPython Name quirks)."""
    try:
        p = dt.get_Parameter(BuiltInParameter.SYMBOL_NAME_PARAM)
        if p and p.HasValue:
            return p.AsString()
    except Exception:
        pass
    try:
        return dt.Name
    except Exception:
        return "<dim type {}>".format(dt.Id.IntegerValue)


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


def comments_of(elem):
    try:
        p = elem.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
        if p and p.HasValue:
            return p.AsString() or ""
    except Exception:
        pass
    return ""


def find_panel_in_view(view):
    """Return the host panel FamilyInstance shown in this section view.

    The host panel is the instance with the MOST sub-components. If several
    hosts are visible, prefer the one whose Comments equals the view name.
    """
    collector = (FilteredElementCollector(doc, view.Id)
                 .OfClass(FamilyInstance)
                 .WhereElementIsNotElementType())
    hosts = []
    for fi in collector:
        try:
            n = len(list(fi.GetSubComponentIds()))
        except Exception:
            n = 0
        if n > 0:
            hosts.append((n, fi))
    if not hosts:
        return None

    named = [h for h in hosts if comments_of(h[1]) == view.Name]
    if named:
        hosts = named
    hosts.sort(key=lambda h: h[0], reverse=True)
    return hosts[0][1]


def get_refs(inst, ref_type):
    """List of stable references of the given FamilyInstanceReferenceType."""
    try:
        return list(inst.GetReferences(ref_type))
    except Exception:
        return []


def has_ref(inst, ref_type):
    """True if the instance has at least one ref of this type."""
    return len(get_refs(inst, ref_type)) > 0


def loc_point(elem):
    """Return the Location.Point of elem, or None."""
    try:
        loc = elem.Location
        if hasattr(loc, "Point"):
            return loc.Point
    except Exception:
        pass
    return None


def bbox_z(elem):
    """(min_z, max_z) of the element's model bounding box, or (None, None)."""
    try:
        bb = elem.get_BoundingBox(None)
        if bb is not None:
            return bb.Min.Z, bb.Max.Z
    except Exception:
        pass
    return None, None


# ── VIEW-SPACE GEOMETRY (explicit XYZ maths — PythonNet has no XYZ.__add__) ─

def vdot(a, b):
    return a.X * b.X + a.Y * b.Y + a.Z * b.Z


def vadd(a, b):
    return XYZ(a.X + b.X, a.Y + b.Y, a.Z + b.Z)


def vscale(a, s):
    return XYZ(a.X * s, a.Y * s, a.Z * s)


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


def delete_all_dims_in_view(view):
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


def existing_dim_sides(view, ext):
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


# ── SPACER BAR DETECTION (ref-fingerprint first, name-fallback second) ──────

def identify_spacer_bars(panel):
    """Return list of (FamilyInstance, locPoint) for all spacer bar sub-comps.

    PRIMARY test: has BOTH CenterLeftRight AND CenterFrontBack references.
    FALLBACK: family name ends with '_R'.
    Returns [] if no sub-components or no bars found.
    """
    try:
        sub_ids = list(panel.GetSubComponentIds())
    except Exception:
        return []
    if not sub_ids:
        return []

    primary = []
    fallback = []

    for sid in sub_ids:
        el = doc.GetElement(sid)
        if not isinstance(el, FamilyInstance):
            continue
        pt = loc_point(el)
        if pt is None:
            continue

        has_clr = has_ref(el, FamilyInstanceReferenceType.CenterLeftRight)
        has_cfb = has_ref(el, FamilyInstanceReferenceType.CenterFrontBack)
        if has_clr and has_cfb:
            primary.append((el, pt))
        else:
            # Name fallback
            fname = safe_family_name(el) or ""
            if fname.endswith("_R"):
                fallback.append((el, pt))

    if primary:
        return primary
    return fallback


def detect_orientation(bars):
    """Determine whether spacer bars run horizontally or vertically.

    Compares the spread of the bars' location-Z values (vertical spread)
    versus their location-X/Y projected spread (horizontal spread).

    Returns "vertical"  if bars stack in Z  (row string goes on the right)
            "horizontal" if bars spread in X/Y (row string goes on the bottom)
            None         if undetermined (0 or 1 bar)
    """
    if len(bars) < 2:
        return None

    zs = [pt.Z for _, pt in bars]
    xs = [pt.X for _, pt in bars]
    ys = [pt.Y for _, pt in bars]

    z_spread = max(zs) - min(zs)
    x_spread = max(xs) - min(xs)
    y_spread = max(ys) - min(ys)
    horiz_spread = max(x_spread, y_spread)

    if z_spread < Z_TOLERANCE and horiz_spread > Z_TOLERANCE:
        return "horizontal"
    if z_spread > Z_TOLERANCE:
        return "vertical"
    return None


# ── REFERENCE COLLECTION (Strategy A) ───────────────────────────────────────

def collect_row_refs_vertical(panel, bars):
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


def collect_row_refs_horizontal(panel, bars, view):
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


# ── RUN ──────────────────────────────────────────────────────────────────────
print("── HEC Dimension Panels ──")

# 1. Assembly ---------------------------------------------------------------
assembly = pick_assembly()
if isinstance(assembly, str) and assembly == "NONE_IN_MODEL":
    alert("No assemblies exist in this model.\n\n"
          "Create your ductbank assembly first.", title="No Assembly")
    raise SystemExit
if assembly is None:
    alert("Cancelled — no assembly selected.", title="Cancelled")
    raise SystemExit

assembly_id = assembly.Id
try:
    assembly_name = assembly.Name
except Exception:
    assembly_name = "Assembly {}".format(assembly_id.IntegerValue)
print("Assembly: {}".format(assembly_name))

# 2. Which dimensions? ------------------------------------------------------
picked = select_checked(DIM_OPTIONS,
                        title="HEC Dimension Panels — choose dimensions",
                        defaults=DEFAULT_CHECKED,
                        button_text="Place dimensions")
if picked is None:
    alert("Cancelled — no dimensions selected.", title="Cancelled")
    raise SystemExit
if not picked:
    alert("Nothing ticked — no dimensions to place.", title="Nothing to do")
    raise SystemExit

do_row     = OPT_ROW     in picked
do_height  = OPT_HEIGHT  in picked
do_width   = OPT_WIDTH   in picked
do_replace = OPT_REPLACE in picked

dim_labels = [p for p in picked if p != OPT_REPLACE]
print("Dimensions to place: {}".format(", ".join(dim_labels) if dim_labels
                                       else "(none)"))
if do_replace:
    print("Replace mode: ON — existing dimensions will be deleted first")

# 3. Dimension type ---------------------------------------------------------
dim_type, used_fallback = find_dimension_type()
if dim_type is None:
    alert("No Linear dimension types exist in this project.\n\n"
          "Load or create a linear dimension style and run again.",
          title="No Dimension Type")
    raise SystemExit
if used_fallback:
    print("NOTE: dimension style '{}' not found — using '{}' instead.".format(
        DEFAULT_DIM_TYPE_NAME, dim_type_name(dim_type)))
else:
    print("Dimension style: {}".format(dim_type_name(dim_type)))

# 4. Section views ----------------------------------------------------------
section_views = collect_section_views(assembly_id)
if not section_views:
    alert("No section views found for assembly:\n  {}\n\n"
          "Run 'Create DB Sections' (Tool 2) first.".format(assembly_name),
          title="No Sections")
    raise SystemExit
print("Section views: {}".format(len(section_views)))
print("")
print("── Placing dimensions ──")

# 5. Place ------------------------------------------------------------------
placed_row = placed_h = placed_w = 0
skipped_row = skipped_h = skipped_w = 0
replaced_count = 0
no_panel = []
errors = 0

t = Transaction(doc, "HEC Dimension Panels")
t.Start()

for view in section_views:
    tag = view.Name
    panel = find_panel_in_view(view)
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
        n_del = delete_all_dims_in_view(view)
        if n_del:
            replaced_count += n_del
        have = set()   # everything cleared
    else:
        have = existing_dim_sides(view, ext)

    parts = []

    # ── Row String ────────────────────────────────────────────────────────
    if do_row:
        bars = identify_spacer_bars(panel)
        orientation = detect_orientation(bars)

        if not bars:
            parts.append("row: no spacer bars found — skipped")
        elif orientation == "vertical":
            # Bars stack in Z → dim string on the RIGHT
            if "right" in have:
                skipped_row += 1
                parts.append("row(R): exists")
            else:
                refs, notes = collect_row_refs_vertical(panel, bars)
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
                refs, notes = collect_row_refs_horizontal(panel, bars, view)
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

    # ── Overall Height (left) ─────────────────────────────────────────────
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

    # ── Overall Width (top) ───────────────────────────────────────────────
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

# ── Summary ──────────────────────────────────────────────────────────────────
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
