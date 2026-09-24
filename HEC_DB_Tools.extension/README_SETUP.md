# HEC Ductbank Tools — PyRevit Extension

## Quick Install

1. **Copy the entire `HEC_DB_Tools.extension` folder** to:
   ```
   %APPDATA%\pyRevit\Extensions\
   ```
   Full path example:
   ```
   C:\Users\YourName\AppData\Roaming\pyRevit\Extensions\HEC_DB_Tools.extension\
   ```

2. **Restart Revit** (or reload PyRevit: pyRevit tab → Reload)

3. A new **"HEC Ductbank"** tab will appear in the Revit ribbon with a
   **"Panel Tools"** panel containing the button(s).

## CPython Requirement

These scripts require CPython 3 (NOT IronPython). Each script has
`#! python3` as its first line, which tells PyRevit v6 to use the
CPython 3123 engine automatically.

**Verify your CPython is active:**
- pyRevit tab → Settings → Engines section
- "Active CPython Engine" should show `CPython (3123): CPython Engine`
- (You already confirmed this ✓)

## Folder Structure

```
HEC_DB_Tools.extension/
├── README_SETUP.md              ← this file
└── HEC_Ductbank.tab/
    └── Panel_Tools.panel/
        └── Assign_Panel_IDs.pushbutton/
            └── script.py        ← Panel ID Assigner
```

## Button: Assign Panel IDs

- **What it does:** Finds all HEC ductbank panel families in the
  active view and writes Panel-001, Panel-002, etc. to their
  Comments parameter.
- **How to use:** Open a view containing panels → click the button.
- **Output:** Results print to the PyRevit output window.

## Target Families (hardcoded in script)

- HEC_EF-DB_SIDE_PANEL
- HEC_EF-DB_ASPVSF
- HEC_NESTED_EF-DB_ASP
- HEC_NESTED_EF-DB90_ASP

Edit the `TARGET_FAMILIES` list at the top of `script.py` to add or
change families.
