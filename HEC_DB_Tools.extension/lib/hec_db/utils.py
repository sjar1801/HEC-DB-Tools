"""hec_db.utils — shared Revit API helpers.

Every function that touches the document receives `doc` as a parameter —
there is NO module-level doc here (only button scripts have `__revit__`).

CPython / PythonNet quirks handled here:
  - elem.Symbol.Family.Name can throw → safe_family_name()
  - XYZ has no __add__          → vadd() / vscale()
  - DimensionType.Name can throw → dim_type_name()

PyRevit v6 + CPython 3123  |  Revit 2025
Hunt Electric — MONARCH Job
"""

import clr
clr.AddReference("RevitAPI")
from Autodesk.Revit.DB import (
    FilteredElementCollector,
    BuiltInParameter,
    ElementId,
    View,
    XYZ,
)


# ── NAMES / PARAMETERS ──────────────────────────────────────────────────────

def safe_family_name(doc, elem):
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


def safe_type_name(elem):
    """Get type name, avoiding PythonNet Symbol.Name bug."""
    try:
        return elem.Name
    except Exception:
        pass
    try:
        p = elem.get_Parameter(BuiltInParameter.ALL_MODEL_TYPE_NAME)
        if p is not None:
            return p.AsString()
    except Exception:
        pass
    return ""


def comments_of(elem):
    """Return the Comments (ALL_MODEL_INSTANCE_COMMENTS) value, or ""."""
    try:
        p = elem.get_Parameter(BuiltInParameter.ALL_MODEL_INSTANCE_COMMENTS)
        if p and p.HasValue:
            return p.AsString() or ""
    except Exception:
        pass
    return ""


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


def _norm(s):
    """Normalise a name for forgiving comparison (spaces/case-insensitive)."""
    return "".join(str(s).split()).lower()


# ── VIEWS ───────────────────────────────────────────────────────────────────

def find_view_template(doc, name):
    """Return a View used as a template, matched by name."""
    for v in FilteredElementCollector(doc).OfClass(View):
        if v.IsTemplate and v.Name == name:
            return v
    return None


# ── GEOMETRY / REFERENCES ───────────────────────────────────────────────────

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


def get_refs(inst, ref_type):
    """List of stable references of the given FamilyInstanceReferenceType."""
    try:
        return list(inst.GetReferences(ref_type))
    except Exception:
        return []


def has_ref(inst, ref_type):
    """True if the instance has at least one ref of this type."""
    return len(get_refs(inst, ref_type)) > 0


# ── VECTOR MATHS (explicit — PythonNet has no XYZ.__add__) ──────────────────

def vdot(a, b):
    return a.X * b.X + a.Y * b.Y + a.Z * b.Z


def vadd(a, b):
    return XYZ(a.X + b.X, a.Y + b.Y, a.Z + b.Z)


def vscale(a, s):
    return XYZ(a.X * s, a.Y * s, a.Z * s)
