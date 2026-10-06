"""hec_db.ui — CPython-safe dialogs (no pyrevit.forms).

pyrevit.forms is IronPython-only and raises "not supported under CPython",
so we use .NET Windows Forms directly, with a Revit TaskDialog fallback.

PyRevit v6 + CPython 3123  |  Revit 2025
Hunt Electric — MONARCH Job
"""

import clr

clr.AddReference("RevitAPIUI")
from Autodesk.Revit.UI import TaskDialog

# Windows Forms for the dialogs
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


def alert(msg, title="HEC DB Tools"):
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
