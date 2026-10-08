"""Scratchpad: line-by-line calculator with variables and units.

Examples::

    L = 24 ft
    W = 12'6"
    L*W              -> 300 ft²
    ans -> yd^2      -> 33.3333 yd²
    sqrt(3^2 + 4^2)  -> 5
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np
import sympy as sp

from . import engine, units
from .units import Q_, ureg


class ScratchError(ValueError):
    pass


@dataclass
class ScratchResult:
    source: str
    latex: str
    value: object          # float or pint Quantity
    text: str              # formatted result
    name: str | None       # variable assigned, if any


_BARE_UNIT_FUNCS_MAP = {"min": "minute", "sec": "second"}
_BARE_UNIT_FUNCS = re.compile(r"(?<![\w.])(min|sec)(?![\w(]|\s*\()")
_SINGLE_LETTER_UNITS = set("msgNLJWK")
_ASSIGN = re.compile(r"^\s*([A-Za-z_]\w*)\s*=(?!=)(.*)$")
_TARGET = re.compile(r"\s*->\s*|\s*→\s*|\s+to\s+")


class Scratchpad:
    def __init__(self):
        self.vars: dict[str, object] = {}

    def clear(self) -> None:
        self.vars.clear()

    @staticmethod
    def _unit(name: str):
        """The pint unit for a bare name, or None. Most single letters are kept as variables."""
        if len(name) == 1 and name not in _SINGLE_LETTER_UNITS:
            return None
        try:
            return ureg.parse_units(name)
        except Exception:
            return None

    def _lookup(self, name: str, angle_mode: str):
        if name in self.vars:
            return self.vars[name]
        unit = self._unit(name)
        if unit is None:
            raise ScratchError(f"'{name}' is not defined. Assign it first, e.g.  {name} = 5")
        if units.is_angle(unit):
            # Angles become plain numbers in the current angle mode.
            return float(Q_(1, unit).to("degree" if angle_mode == "deg" else "radian").magnitude)
        return Q_(1, unit)

    def _unit_latex(self, expr) -> dict[str, str]:
        """Draw unit names upright (psi, not the Greek letter)."""
        out = {}
        for s in expr.free_symbols:
            if s.name in self.vars or self._unit(s.name) is None:
                continue
            out[s.name] = r"\mathrm{%s}" % s.name.replace("_", r"\_")
        return out

    def _typed_unit(self, value, text: str):
        """Show the result in the first typed unit of the same kind (3 m + 2 ft -> m)."""
        for name in re.findall(r"[A-Za-z_]\w*", text):
            v = self.vars.get(name)
            unit = v.units if isinstance(v, Q_) else (None if name in self.vars else self._unit(name))
            if unit is not None and not units.is_angle(unit) and                     Q_(1, unit).dimensionality == value.dimensionality:
                return value.to(unit)
        return value

    def run(self, line: str, angle_mode: str = "deg", fmt=None) -> ScratchResult:
        fmt = fmt or engine.format_number
        source = line.strip()
        if not source:
            raise ScratchError("Nothing to calculate")
        body = engine.strip_comment(source).strip()
        parts = _TARGET.split(body, maxsplit=1)
        target = parts[1].strip() if len(parts) == 2 else ""
        body = parts[0]
        name = None
        m = _ASSIGN.match(body)
        if m:
            name, body = m.group(1), m.group(2)
            if name in engine.RESERVED:
                raise ScratchError(f"'{name}' is a built-in function name")
        if "=" in body:
            raise ScratchError("Use the Worksheet tab to solve equations; here, use  name = value")
        # "5 min" / "30 sec" mean time units when not called like functions.
        expanded = _BARE_UNIT_FUNCS.sub(lambda m: _BARE_UNIT_FUNCS_MAP[m.group(1)],
                                        units.expand_feet_inches(body))
        try:
            eq = engine.parse_line(expanded, 0, angle_mode)
        except engine.ParseError as e:
            raise ScratchError(str(e)) from None
        if eq is None:
            raise ScratchError("Nothing to calculate")
        expr = eq.lhs
        syms = sorted(expr.free_symbols, key=lambda s: s.name)
        args = [self._lookup(s.name, angle_mode) for s in syms]
        try:
            f = sp.lambdify(syms, expr, modules="numpy")
            with np.errstate(all="ignore"):
                value = f(*args)
        except Exception as e:
            raise ScratchError(_friendly(e)) from None
        value = _clean(value)
        if target:
            value = _to_target(value, target, angle_mode)
        elif isinstance(value, Q_):
            value = self._typed_unit(value, expanded)
        if isinstance(value, Q_):
            text = units.format_quantity(value, fmt)
        else:
            text = fmt(value)
        if name:
            self.vars[name] = value
        self.vars["ans"] = value
        try:
            latex = engine.display_latex(expanded, self._unit_latex(expr))
            if name:
                latex = engine.to_latex(sp.Symbol(name)) + " = " + latex
        except engine.ParseError:
            latex = ""
        return ScratchResult(source=source, latex=latex, value=value, text=text, name=name)


def _friendly(e: Exception) -> str:
    msg = str(e)
    if "Cannot convert" in msg or "DimensionalityError" in type(e).__name__ or "dimension" in msg.lower():
        return "Unit mismatch: " + msg
    return msg or type(e).__name__


def _clean(value):
    if isinstance(value, Q_):
        mag = value.magnitude
        if isinstance(mag, np.ndarray) and mag.shape == ():
            value = Q_(float(mag), value.units)
        try:
            value = units.simplify_units(value.to_reduced_units())
        except Exception:
            pass
        if value.dimensionless and not units.is_angle(value.units):
            return float(value.to("dimensionless").magnitude)
        return value
    if isinstance(value, (np.ndarray, np.generic)):
        value = value.item() if np.ndim(value) == 0 else value
    if isinstance(value, complex):
        if abs(value.imag) > 1e-12 * max(1.0, abs(value.real)):
            raise ScratchError("Result is a complex number (e.g. square root of a negative)")
        value = value.real
    try:
        return float(value)
    except (TypeError, ValueError):
        raise ScratchError("Result is not a single number") from None


def _to_target(value, target: str, angle_mode: str):
    try:
        unit = units.parse_unit(target)
    except units.UnitError as e:
        raise ScratchError(str(e)) from None
    if not isinstance(value, Q_):
        if units.is_angle(unit):
            return Q_(value, "degree" if angle_mode == "deg" else "radian").to(unit)
        if Q_(1, unit).dimensionless:
            return Q_(value, "dimensionless").to(unit)
        raise ScratchError(f"Result has no units, so it can't be converted to {target}")
    try:
        return value.to(unit)
    except Exception:
        raise ScratchError(f"Can't convert {units.format_unit(value.units)} to {target}") from None
