"""Optional units support built on pint.

Values typed by the user may carry units ("12.5 ft", "450 gpm", 12'6").
Before going into the engine they are converted to plain numbers in the
worksheet's *calculation system*:

* ``US``   - ft, slug, s, °R  (so force comes out in lbf, pressure in lbf/ft²)
* ``SI``   - m, kg, s, K      (force in N, pressure in Pa)
* ``asis`` - units are labels only; the number is used exactly as typed

Empirical formulas (Manning's 1.49, Hazen-Williams...) only work in the
system they were written for, which is why the system is user-selectable.
"""
from __future__ import annotations

import math
import re

import pint

ureg = pint.UnitRegistry(autoconvert_offset_to_baseunit=True)
Q_ = ureg.Quantity

_EXTRA = [
    "cfs = foot ** 3 / second",
    "gpm = gallon / minute",
    "gpd = gallon / day",
    "mgd = 1e6 * gallon / day",
    "pcf = force_pound / foot ** 3",
    "psf = force_pound / foot ** 2",
    "ksf = kip / foot ** 2",
    "kcf = kip / foot ** 3",
    "plf = force_pound / foot",
    "klf = kip / foot",
    "kipft = kip * foot",
    "ftlb = foot * force_pound",
    "acre_ft = acre_foot",
]
for _d in _EXTRA:
    try:
        ureg.parse_units(_d.split("=")[0].strip())
    except Exception:
        ureg.define(_d)

SYSTEMS = {"US": "US (ft, lb, s)", "SI": "SI (m, kg, s)", "asis": "As entered (units are labels)"}

_BASE = {
    "US": {"[length]": "foot", "[mass]": "slug", "[time]": "second", "[temperature]": "degR",
           "[current]": "ampere", "[substance]": "mole", "[luminosity]": "candela"},
    "SI": {"[length]": "meter", "[mass]": "kilogram", "[time]": "second", "[temperature]": "kelvin",
           "[current]": "ampere", "[substance]": "mole", "[luminosity]": "candela"},
}


class UnitError(ValueError):
    pass


# ---------------------------------------------------------------------------
# Reading values
# ---------------------------------------------------------------------------

_NUM = r"\d+(?:\.\d*)?|\.\d+"
_FT_IN = re.compile(rf"^\s*(-)?\s*({_NUM})\s*'\s*(?:-?\s*({_NUM})\s*(?:\"|in)?)?\s*$")


def expand_feet_inches(text: str) -> str:
    """Rewrite 12'6" / 12' / 6" inside an expression as (12.5 ft) etc."""
    def ft_in(m):
        return f"({float(m.group(1)) + float(m.group(2)) / 12:.12g} ft)"

    text = re.sub(rf"({_NUM})\s*'\s*-?\s*({_NUM})\s*\"", ft_in, text)
    text = re.sub(rf"({_NUM})\s*'", r"(\1 ft)", text)
    text = re.sub(rf"({_NUM})\s*\"", r"(\1 in)", text)
    return text


_METRIC_HINTS = ("meter", "newton", "pascal", "gram", "liter", "joule", "watt", "hectare", "bar")
_EXTRA_DEFS = {d.split("=")[0].strip(): d.split("=")[1].strip() for d in _EXTRA}
_CUSTOM = {d.split("=")[0].strip(): set(re.findall(r"[A-Za-z_]\w*", d.split("=")[1])) for d in _EXTRA}


def _has_cancellation(unit) -> bool:
    """True when unit factors pull a base dimension in opposite directions (psi*in^2)."""
    signs: dict = {}
    for name, exp in unit._units.items():
        for dim, p in ureg.Unit(name).dimensionality.items():
            signs.setdefault(dim, set()).add(p * exp > 0)
    return any(len(v) > 1 for v in signs.values())


# Valid conversions, but never chosen automatically for a result.
_NO_AUTO = {"force_kilogram", "force_ton", "british_thermal_unit", "horsepower", "knot", "rod",
            "chain", "grade", "turn", "year", "standard_atmosphere", "bar", "inch_Hg", "foot_H2O",
            "kilowatt_hour"}


def _units_of(u: str):
    return ureg.parse_expression(u).units if ("*" in u or "/" in u) else ureg.parse_units(u)


def simplify_units(q):
    """Tidy a multi-unit result: klf*ft^2 -> kip*ft, gpm*min -> gal, psi*in^2 -> lbf."""
    if not isinstance(q, Q_) or len(q.units._units) < 2:
        return q
    # 1. Expand custom aliases (klf -> kip/ft) and cancel same-kind units.
    expanded = ureg.dimensionless
    for name, exp in q.units._units.items():
        expanded = expanded * (_units_of(_EXTRA_DEFS[name]) if name in _EXTRA_DEFS else ureg.Unit(name)) ** exp
    try:
        q2 = q.to(expanded).to_reduced_units()
        n, n2 = len(q.units._units), len(q2.units._units)
        if n2 < n or (n2 <= n and not _has_cancellation(q2.units)):
            q = q2
    except Exception:
        pass
    current = dict(q.units._units)
    if len(current) < 2 or not _has_cancellation(q.units):
        return q
    # 2. Units still cancel dimensionally: pick a simpler unit of the same kind.
    names = set()
    for n in current:
        names |= _CUSTOM.get(n, {n})
    metric = any(h in n for n in names for h in _METRIC_HINTS)
    best = None
    for items in CATEGORIES.values():
        for _, u in items:
            cu = _units_of(u)
            cand = dict(cu._units)
            if cu.dimensionality != q.dimensionality or len(cand) >= len(current)                     or set(cand) & _NO_AUTO:
                continue
            cand_names = set()
            for c in cand:
                cand_names |= _CUSTOM.get(c, {c})
            mag = abs(float(q.to(cu).magnitude)) or 1.0
            score = (len(names & cand_names) * 10
                     + (5 if metric == any(h in n for n in cand_names for h in _METRIC_HINTS) else 0)
                     - 0.1 * abs(math.log10(mag) - 1.5))
            if best is None or score > best[0]:
                best = (score, cu)
    return q.to(best[1]) if best else q


def parse_unit(unit_text: str):
    unit_text = (unit_text or "").strip()
    if not unit_text:
        return None
    try:
        return ureg.parse_units(_unit_aliases(unit_text))
    except Exception:
        raise UnitError(f"Unknown unit '{unit_text}'") from None


def _unit_aliases(text: str) -> str:
    t = text.replace("²", "^2").replace("³", "^3").replace("·", "*").replace("°F", "degF") \
            .replace("°C", "degC").replace("°", "degree")
    return t


_NUMBER_UNIT = re.compile(r"\s*([-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)\s*([A-Za-z°].*)")


def _number_unit(text: str):
    """'0 degC', '12.5 ft/s' -> Quantity built directly (pint's expression parser would
    multiply 0 * degC and lose the temperature offset)."""
    m = _NUMBER_UNIT.fullmatch(text)
    if not m:
        return None
    try:
        return Q_(float(m.group(1)), ureg.parse_units(_unit_aliases(m.group(2).strip())))
    except Exception:
        return None


def parse_value(text: str, unit_text: str = "", angle_mode: str = "rad"):
    """Read a value field. Returns None (blank), a float, or a pint Quantity."""
    from . import engine  # local import keeps units usable on its own

    text = (text or "").strip()
    if "(" not in text:
        # Thousands separators only (1,250.5); commas inside min(1,2) or log(8,2) are arguments.
        text = re.sub(r"(?<=\d),(?=\d{3}(?!\d))", "", text)
    if not text:
        return None
    unit = parse_unit(unit_text)
    m = _FT_IN.match(text)
    if m:
        ft = float(m.group(2)) + (float(m.group(3)) / 12 if m.group(3) else 0.0)
        q = Q_(-ft if m.group(1) else ft, "foot")
    elif (q := _number_unit(text)) is None:
        try:
            q = engine.evaluate_constant(text, angle_mode)
        except Exception:
            try:
                q = ureg.parse_expression(_unit_aliases(expand_feet_inches(text)))
            except Exception:
                raise UnitError(f"Can't read value '{text}'") from None
    if isinstance(q, Q_) and q.unitless:
        q = float(q.magnitude)
    if unit is None:
        return q if isinstance(q, Q_) else float(q)
    if isinstance(q, Q_):
        try:
            return q.to(unit)
        except pint.DimensionalityError:
            raise UnitError(f"'{text}' can't be expressed in {unit_text}") from None
    return Q_(float(q), unit)


# ---------------------------------------------------------------------------
# Conversion to / from calculation numbers
# ---------------------------------------------------------------------------

def is_angle(unit) -> bool:
    try:
        _, root = ureg.get_root_units(unit)
        return str(root) == "radian"
    except Exception:
        return False


def system_unit(dimensionality, system: str):
    base = _BASE[system]
    u = ureg.dimensionless
    for dim, power in dimensionality.items():
        u = u * ureg.Unit(base[dim]) ** power
    return u


def to_calc(value, system: str, angle_mode: str = "rad") -> float:
    """Convert a float/Quantity to the number the engine should use."""
    if value is None:
        raise UnitError("No value")
    if not isinstance(value, Q_):
        return float(value)
    q = value
    if q.unitless:
        return float(q.magnitude)
    if is_angle(q.units):
        return float(q.to("degree" if angle_mode == "deg" else "radian").magnitude)
    if q.dimensionless:
        return float(q.to("dimensionless").magnitude)
    if system == "asis":
        return float(q.magnitude)
    # Temperatures go to absolute scales (degR / K), so input and output always agree.
    return float(q.to(system_unit(q.dimensionality, system)).magnitude)


def from_calc(number: float, unit_text: str, system: str, angle_mode: str = "rad"):
    """Interpret an engine result in the user's desired unit (or return the plain number)."""
    unit = parse_unit(unit_text)
    if unit is None:
        return float(number)
    if is_angle(unit):
        return Q_(number, "degree" if angle_mode == "deg" else "radian").to(unit)
    if Q_(1, unit).dimensionless:
        return Q_(number, "dimensionless").to(unit)
    if system == "asis":
        return Q_(number, unit)
    return Q_(number, system_unit(unit.dimensionality, system)).to(unit)


_FRIENDLY = {
    "US": ["force_pound", "force_pound/foot**2", "force_pound*foot", "force_pound/foot**3",
           "force_pound/foot", "foot*force_pound/second"],
    "SI": ["newton", "pascal", "newton*meter", "newton/meter**3", "newton/meter", "watt"],
}


def calc_unit_label(unit_text: str, system: str) -> str:
    """Name of the unit a plain engine number is in, e.g. 'ft' for length in US."""
    unit = parse_unit(unit_text)
    if unit is None or system == "asis" or Q_(1, unit).dimensionless or is_angle(unit):
        return ""
    for cand in _FRIENDLY[system]:
        cu = ureg.parse_expression(cand).units
        if cu.dimensionality == unit.dimensionality:
            return format_unit(cu)
    return format_unit(system_unit(unit.dimensionality, system))


def format_unit(unit) -> str:
    s = f"{unit:~P}"
    return s.replace("force_pound", "lbf")


def format_quantity(value, fmt=None) -> str:
    fmt = fmt or (lambda x: f"{x:.6g}")
    if isinstance(value, Q_):
        u = format_unit(value.units)
        return f"{fmt(value.magnitude)} {u}".strip()
    return fmt(value)


# ---------------------------------------------------------------------------
# Unit converter
# ---------------------------------------------------------------------------

CATEGORIES: dict[str, list[tuple[str, str]]] = {
    "Length": [("ft", "foot"), ("in", "inch"), ("yd", "yard"), ("mi", "mile"),
               ("US survey ft", "survey_foot"), ("m", "meter"), ("cm", "centimeter"),
               ("mm", "millimeter"), ("km", "kilometer"), ("chain (66 ft)", "chain"),
               ("rod", "rod")],
    "Area": [("ft²", "foot**2"), ("in²", "inch**2"), ("yd²", "yard**2"), ("acre", "acre"),
             ("mi²", "mile**2"), ("m²", "meter**2"), ("cm²", "centimeter**2"),
             ("mm²", "millimeter**2"), ("hectare", "hectare"), ("km²", "kilometer**2")],
    "Volume": [("ft³", "foot**3"), ("in³", "inch**3"), ("yd³", "yard**3"), ("gal (US)", "gallon"),
               ("acre-ft", "acre_foot"), ("m³", "meter**3"), ("L", "liter"), ("mL", "milliliter")],
    "Flow rate": [("cfs (ft³/s)", "cfs"), ("gpm", "gpm"), ("gpd", "gpd"), ("MGD", "mgd"),
                  ("acre-ft/day", "acre_foot/day"), ("m³/s", "meter**3/second"),
                  ("m³/hr", "meter**3/hour"), ("L/s", "liter/second"), ("L/min", "liter/minute")],
    "Velocity": [("ft/s", "foot/second"), ("ft/min", "foot/minute"), ("mph", "mile/hour"),
                 ("m/s", "meter/second"), ("km/h", "kilometer/hour"), ("knot", "knot")],
    "Pressure / stress": [("psi", "psi"), ("ksi", "ksi"), ("psf", "psf"), ("ksf", "ksf"),
                          ("ft of water", "foot_H2O"), ("in of mercury", "inch_Hg"),
                          ("Pa", "pascal"), ("kPa", "kilopascal"), ("MPa", "megapascal"),
                          ("bar", "bar"), ("atm", "atmosphere")],
    "Force": [("lbf", "force_pound"), ("kip", "kip"), ("ton (2000 lbf)", "force_short_ton"),
              ("N", "newton"), ("kN", "kilonewton"), ("kgf", "kilogram_force")],
    "Moment / torque": [("lbf·ft", "force_pound*foot"), ("lbf·in", "force_pound*inch"),
                        ("kip·ft", "kip*foot"), ("kip·in", "kip*inch"), ("N·m", "newton*meter"),
                        ("kN·m", "kilonewton*meter")],
    "Line load": [("plf (lbf/ft)", "plf"), ("klf (kip/ft)", "klf"), ("kN/m", "kilonewton/meter"),
                  ("N/m", "newton/meter")],
    "Unit weight": [("pcf (lbf/ft³)", "pcf"), ("kcf", "kcf"), ("kN/m³", "kilonewton/meter**3"),
                    ("N/m³", "newton/meter**3")],
    "Density (mass)": [("lb/ft³", "pound/foot**3"), ("slug/ft³", "slug/foot**3"),
                       ("kg/m³", "kilogram/meter**3"), ("g/cm³", "gram/centimeter**3")],
    "Mass": [("lb", "pound"), ("slug", "slug"), ("ton (short)", "short_ton"), ("kg", "kilogram"),
             ("tonne", "metric_ton"), ("g", "gram")],
    "Temperature": [("°F", "degF"), ("°C", "degC"), ("K", "kelvin"), ("°R", "degR")],
    "Angle": [("degree", "degree"), ("radian", "radian"), ("gradian", "gradian"),
              ("arcminute", "arcminute"), ("arcsecond", "arcsecond"), ("revolution", "revolution")],
    "Energy / work": [("ft·lbf", "foot*force_pound"), ("BTU", "BTU"), ("kWh", "kilowatt_hour"),
                      ("J", "joule"), ("kJ", "kilojoule")],
    "Power": [("hp", "horsepower"), ("ft·lbf/s", "foot*force_pound/second"), ("W", "watt"),
              ("kW", "kilowatt"), ("BTU/hr", "BTU/hour")],
    "Time": [("s", "second"), ("min", "minute"), ("hr", "hour"), ("day", "day"), ("year", "year")],
}


def _prune_categories():
    for cat, items in list(CATEGORIES.items()):
        ok = []
        for label, u in items:
            try:
                ureg.parse_units(u) if "*" not in u and "/" not in u else ureg.parse_expression(u)
                ok.append((label, u))
            except Exception:
                pass
        CATEGORIES[cat] = ok


_prune_categories()


def convert_all(value: float, unit: str, category: str) -> list[tuple[str, float]]:
    q = Q_(value, ureg.parse_expression(unit).units if "*" in unit or "/" in unit else unit)
    out = []
    for label, u in CATEGORIES[category]:
        target = ureg.parse_expression(u).units if ("*" in u or "/" in u) else ureg.parse_units(u)
        out.append((label, float(q.to(target).magnitude)))
    return out


def convert_text(text: str):
    """Free-form conversion: '3.5 cfs to gpm', '12'6" -> m'. Returns a Quantity."""
    m = re.split(r"\s+to\s+|\s*->\s*|\s*→\s*", text.strip(), maxsplit=1)
    if len(m) != 2 or not m[1].strip():
        raise UnitError("Type something like:  3.5 cfs to gpm")
    src, dst = m
    q = parse_value(src)
    if not isinstance(q, Q_):
        raise UnitError(f"'{src}' has no units")
    try:
        return q.to(parse_unit(dst))
    except pint.DimensionalityError:
        raise UnitError(f"Can't convert {format_unit(q.units)} to {dst.strip()}") from None


# Slope is handled separately because % / ratio / angle aren't linear conversions.
SLOPE_KINDS = ("percent (%)", "ratio H:V (run per 1 rise)", "ratio V:H (rise per 1 run)",
               "degrees", "ft/ft")


def slope_conversions(value: float, kind: str) -> list[tuple[str, str]]:
    if kind.startswith("percent"):
        g = value / 100
    elif kind.startswith("ratio H:V"):
        if value == 0:
            raise UnitError("H:V ratio can't be 0")
        g = 1 / value
    elif kind.startswith("ratio V:H") or kind == "ft/ft":
        g = value
    else:
        g = math.tan(math.radians(value))
    out = [("percent (%)", f"{g * 100:.6g} %"),
           ("ft/ft (rise/run)", f"{g:.6g}"),
           ("ratio H:V", f"{1 / g:.6g} : 1" if g else "∞ : 1 (flat)"),
           ("ratio V:H", f"{g:.6g} : 1"),
           ("degrees", f"{math.degrees(math.atan(g)):.6g}°"),
           ("inches per foot", f"{g * 12:.6g} in/ft")]
    return out
