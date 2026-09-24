# HEC-DB-Tools

PyRevit extension and supporting scripts for **Hunt Electric (HEC)** ductbank panel
workflows — **MONARCH** job. Built for **Autodesk Revit 2025**.

These tools automate the repetitive spooling work around ductbank assemblies:
assigning sequential panel IDs and generating per-panel detail sections and
assembly sheets.

---

## Repository structure

```
HEC-DB-Tools/
├── HEC_DB_Tools.extension/          ← the PyRevit extension (main deliverable)
│   ├── README_SETUP.md              ← install + CPython engine setup instructions
│   └── HEC_Ductbank.tab/
│       └── Panel_Tools.panel/
│           └── Assign_Panel_IDs.pushbutton/
│               └── script.py        ← Panel ID Assigner button (working)
│
├── Dynamo reference scripts          ← original Dynamo Python Script node sources
│   ├── HEC_DB_Panel_ID_Assigner_v7.py   (complete, working)
│   ├── HEC_DB_Section_Creator.py        (being converted to PyRevit)
│   └── HEC_DB_Panel_ID_Assigner_README.md
│
└── Probe / diagnostic scripts        ← one-off investigation tools (safe to ignore)
    ├── HEC_DB_HorizontalDetail_Probe.py
    ├── HEC_DB_Marker_Rotate_Probe.py
    ├── HEC_DB_Marker_Rotate_Probe_v2.py
    ├── HEC_DB_Panel_Side_Probe.py
    ├── HEC_DB_Panel_Side_Probe_v2.py
    └── HEC_DB_Section_Orientation_Probe.py
```

### What each group is

- **`HEC_DB_Tools.extension/`** — the real tool. Drop this folder into a PyRevit
  extensions directory and the **HEC Ductbank** ribbon tab appears in Revit with
  the panel tools. Runs on the **CPython 3** engine.
- **Dynamo reference scripts** — the original `.py` bodies used inside Dynamo Python
  Script nodes. Kept for reference and to make the PyRevit conversion traceable.
- **Probe / diagnostic scripts** — throwaway scripts written to investigate the
  Revit API behavior of assembly section views (orientation, crop boxes, section
  marker rotation). Not part of the shipped tool.

---

## Install

See **[`HEC_DB_Tools.extension/README_SETUP.md`](HEC_DB_Tools.extension/README_SETUP.md)**
for full setup, including how to make sure PyRevit runs the extension on the
**CPython 3** engine (required).

Quick version:
1. Copy `HEC_DB_Tools.extension/` into your PyRevit extensions folder.
2. Reload PyRevit (or restart Revit).
3. The **HEC Ductbank** tab appears in the ribbon.

---

## Status

| Tool | Platform | Status |
|------|----------|--------|
| Panel ID Assigner | PyRevit button | ✅ Complete and working |
| Section Creator | PyRevit button | 🚧 In progress — converting from Dynamo |

The Section Creator is being moved to PyRevit specifically to gain control over
assembly **section view orientation** (the section marker can be rotated in
PyRevit, which is not possible from the Dynamo CPython engine).

---

*Internal HEC VDC tooling — MONARCH job.*
