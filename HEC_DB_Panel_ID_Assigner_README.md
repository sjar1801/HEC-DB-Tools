# HEC DB Panel ID Assigner — Dynamo Script (v3)

## What It Does
Assigns unique sequential IDs (`Panel-001`, `Panel-002`, …) to ductbank panel family instances **visible in the active view only**. Supports multiple panel family types and catches **shared nested instances** inside standard DB assemblies (90s, Ts, straights, etc.).

## Target Families (v3)
The script targets these family names — edit the Code Block node to add/remove:

| Family Name | Description |
|---|---|
| `HEC_EF-DB_SIDE_PANEL` | Standard side panel |
| `HEC_EF-DB_ASPVSF` | Angled side panel with stayform |
| `HEC_NESTED-EF-DB_ASP` | Nested angled side panel (type: DB_PANEL_ADJ) |

## How It Works (v3 Changes)

### Problem solved
v2 used `FilteredElementCollector(doc, viewId)` which only found **directly placed** panel instances. Panels nested inside standard DB assemblies (horizontal 90s, etc.) were invisible to that collector — even though they're shared families.

### v3 Strategy
1. **Document-wide collector** — `FilteredElementCollector(doc)` finds ALL shared nested panel instances across the entire project (per Autodesk KB: *"Shared families can act independently of their host family"*)
2. **SuperComponent chain filter** — For each panel found, walks up the `SuperComponent` ancestry. If the panel itself OR any host ancestor is visible in the active view, it's included
3. **Location-based sort** — Panels sorted by X → Y → Z coordinates for consistent, spatial ordering
4. **Write to Comments** — Built-in `Comments` parameter writes ONLY to the target panel element, never cascading to nested rebar, angle iron, or stayform

## Inputs (Dynamo Nodes)
| Node | Default | Purpose |
|---|---|---|
| **Target Family Names** | `["HEC_EF-DB_SIDE_PANEL", "HEC_EF-DB_ASPVSF", "HEC_NESTED-EF-DB_ASP"]` | Code Block — edit to add/remove families |
| **ID Prefix** | `Panel` | Text before the number |
| **Parameter Name** | `Comments` | Swap to shared parameter for production |

## Output (Watch Node)
```
=== HEC DB Panel ID Assigner v3 ===
Active View: '{view name}'

--- Project Totals (all views) ---
  HEC_EF-DB_ASPVSF: 12
  HEC_EF-DB_SIDE_PANEL: 48
  HEC_NESTED-EF-DB_ASP: 6
  TOTAL: 66

--- Active View Results ---
Panels in active view: 14
Successfully tagged: 14

--- Details ---
OK  | Panel-001 | ID:123456 | HEC_EF-DB_SIDE_PANEL:SIDE PANEL - STAYFORM (nested)
OK  | Panel-002 | ID:123457 | HEC_EF-DB_SIDE_PANEL:SIDE PANEL - NO STAYFORM (direct)
...
```

Each line shows:
- **OK / SKIP / ERR** status
- The assigned Panel ID
- Revit Element ID
- Family name : Type name
- **(nested)** or **(direct)** — whether it lives inside a host assembly or is freestanding

## How to Run
1. Open your Revit project and navigate to the view containing your ductbank assembly
2. Open Dynamo (`Manage` → `Dynamo`)
3. Open `HEC_DB_Panel_ID_Assigner.dyn`
4. Verify the family names in the Code Block match your project
5. Set Run mode to **Manual**, click **Run**
6. Check the Watch node output for results

## Adding New Family Names
Double-click the **"Target Family Names"** Code Block and add to the list:
```
["HEC_EF-DB_SIDE_PANEL",
 "HEC_EF-DB_ASPVSF",
 "HEC_NESTED-EF-DB_ASP",
 "YOUR_NEW_FAMILY_HERE"];
```

## Production Swap
When ready to move off Comments:
1. Change the **Parameter Name** input from `Comments` to your dedicated shared parameter name
2. Make sure that shared parameter is added to all target family types

## Requirements
- Revit 2025
- Dynamo 2.19+ (CPython3 engine)
- Panel families must be loaded in the project

## References
- Autodesk KB: Shared nested families act independently of host — [link](https://www.autodesk.com/support/technical/article/caas/sfdcarticles/sfdcarticles/Unable-to-hide-shared-nested-family-after-loading-to-Revit-project.html)
- Autodesk API: FilteredElementCollector — [Revit 2025 docs](https://help.autodesk.com/view/RVT/2025/ENU/?guid=6359776d)
- Autodesk KB: Built-in parameters don't cascade to nested families
