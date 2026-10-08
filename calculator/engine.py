"""Math engine: parsing, evaluation, symbolic manipulation and solving.

Nothing in here touches the GUI, so it can be unit tested on its own.
All numbers handled here are plain floats; unit conversion happens in
``units.py`` before values reach the engine.
"""
from __future__ import annotations

import functools
import keyword
from decimal import Decimal
import math
import re
import threading
from dataclasses import dataclass, field

import numpy as np
import sympy as sp
from scipy import optimize
from sympy.parsing.sympy_parser import (
    auto_number,
    auto_symbol,
    convert_xor,
    factorial_notation,
    implicit_multiplication,
    parse_expr,
)
from sympy.printing.latex import LatexPrinter
from sympy.printing.str import StrPrinter


class ParseError(ValueError):
    """Raised when a line can't be understood. ``col`` is a 0-based column or None."""

    def __init__(self, message: str, col: int | None = None):
        super().__init__(message)
        self.col = col


class SolveError(ValueError):
    pass


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def _log(x, base=10, **kw):
    """log(x) is base 10 (calculator convention); log(x, b) is base b."""
    return sp.log(x, base, **kw)


def _root(x, n, **kw):
    """n-th root; negative numbers give the real root for odd n (cbrt(-8) = -2)."""
    if kw.get("evaluate") is False:
        return sp.Pow(x, sp.Pow(n, -1, evaluate=False), evaluate=False)
    x, n = sp.sympify(x), sp.sympify(n)
    if n.is_integer and n.is_odd and not x.is_nonnegative:
        if x.is_number:
            return -sp.Pow(-x, 1 / n) if x.is_negative else sp.Pow(x, 1 / n)
        # Keep the real odd root once values are substituted: cbrt(x) at x = -8 is -2.
        return sp.sign(x) * sp.Pow(sp.Abs(x), 1 / n)
    return sp.Pow(x, 1 / n)


def _cbrt(x, **kw):
    if kw.get("evaluate") is False:
        return sp.Pow(x, sp.Rational(1, 3), evaluate=False)
    return _root(x, 3)


def _ln(x, **kw):
    return sp.log(x, **kw)


FUNCTIONS = {
    "sin": sp.sin, "cos": sp.cos, "tan": sp.tan,
    "sec": sp.sec, "csc": sp.csc, "cot": sp.cot,
    "asin": sp.asin, "acos": sp.acos, "atan": sp.atan, "atan2": sp.atan2,
    "arcsin": sp.asin, "arccos": sp.acos, "arctan": sp.atan,
    "sinh": sp.sinh, "cosh": sp.cosh, "tanh": sp.tanh,
    "asinh": sp.asinh, "acosh": sp.acosh, "atanh": sp.atanh,
    "sqrt": sp.sqrt, "cbrt": _cbrt, "root": _root,
    "exp": sp.exp, "ln": _ln, "log": _log, "log10": _log,
    "abs": sp.Abs, "Abs": sp.Abs,
    "min": sp.Min, "Min": sp.Min, "max": sp.Max, "Max": sp.Max,
    "floor": sp.floor, "ceil": sp.ceiling, "ceiling": sp.ceiling, "sign": sp.sign,
}
CONSTANTS = {"pi": sp.pi}
RESERVED = set(FUNCTIONS) | set(CONSTANTS)

_GREEK = ("alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu nu xi "
          "omicron pi rho sigma tau upsilon phi chi psi omega").split()
_GREEK_LOWER = "αβγδεζηθικλμνξοπρστυφχψω"
_GREEK_UPPER = "ΑΒΓΔΕΖΗΘΙΚΛΜΝΞΟΠΡΣΤΥΦΧΨΩ"

_UNICODE = {
    "×": "*", "·": "*", "⋅": "*", "÷": "/", "−": "-", "–": "-", "—": "-",
    "½": "(1/2)", "¼": "(1/4)", "¾": "(3/4)",
    "[": "(", "]": ")", "{": "(", "}": ")",
}
for _name, _lo, _up in zip(_GREEK, _GREEK_LOWER, _GREEK_UPPER):
    _UNICODE[_lo] = f" {_name} "
    _UNICODE[_up] = f" {_name.capitalize()} "
_UNICODE["π"] = " pi "
_UNICODE["ς"] = " sigma "

_KEYWORDS = set(keyword.kwlist) | {"True", "False", "None"}
_KW_SUFFIX = "_kw_"
_NAME_CALL = re.compile(r"(?<![\w.])([A-Za-z_]\w*)(\s*)\(")
_ALLOWED = re.compile(r"[A-Za-z0-9_\s+\-*/^().,=!]")

_TRANSFORMS = (auto_symbol, auto_number, factorial_notation, convert_xor, implicit_multiplication)


def strip_comment(text: str) -> str:
    return text.split("#", 1)[0]


_SUPER = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹⁻⁺", "0123456789-+")
_SUB = str.maketrans("₀₁₂₃₄₅₆₇₈₉", "0123456789")


def normalize(text: str) -> str:
    """Map unicode math symbols and brackets to plain parser syntax."""
    # x⁴ -> x^(4),  x⁻¹ -> x^(-1),  A₁ -> A_1
    text = re.sub(r"[⁰¹²³⁴⁵⁶⁷⁸⁹⁻⁺]+", lambda m: "^(" + m.group().translate(_SUPER) + ")", text)
    text = re.sub(r"[₀₁₂₃₄₅₆₇₈₉]+", lambda m: "_" + m.group().translate(_SUB), text)
    text = re.sub(r"√\s*(\d+(?:\.\d+)?|[A-Za-z_]\w*)", r"sqrt(\1)", text)
    text = text.replace("√", "sqrt")
    for k, v in _UNICODE.items():
        text = text.replace(k, v)
    return text


def _check_syntax(text: str) -> None:
    """Catch common typing mistakes and report where they are."""
    for i, ch in enumerate(text):
        if not _ALLOWED.match(ch):
            raise ParseError(f"Unexpected character '{ch}'", i)
    stack = []
    for i, ch in enumerate(text):
        if ch == "(":
            stack.append(i)
        elif ch == ")":
            if not stack:
                raise ParseError("Extra closing parenthesis ')'", i)
            stack.pop()
    if stack:
        raise ParseError("Missing closing parenthesis for '(' here", stack[-1])
    m = re.search(r"[+\-*/^,]\s*$", text)
    if m:
        raise ParseError(f"Expression ends with '{m.group().strip()}'", m.start())
    m = re.search(r"(?<![*])[*/^]\s*[*/^]|[+\-*/^]\s*\)|\(\s*[*/^]|\(\s*\)", text)
    if m and "**" not in m.group():
        raise ParseError(f"Unexpected '{m.group().strip()}'", m.start())


# "2 ft", "6 in", "2x^2", "3.5e3 lbf" -> grouped so "6 in / 1 ft" means (6 in)/(1 ft).
_NUM_NAME = re.compile(
    r"(?<![\w.])((?>\d+\.?\d*(?:[eE][+-]?\d+)?|\.\d+(?:[eE][+-]?\d+)?))\s*"
    r"((?>[A-Za-z_]\w*(?:\s*\^\s*(?:-?\d+(?:\.\d+)?|\([^()]*\)))?))(?!\s*\()")


def group_implicit(src: str) -> str:
    """Make number-name juxtaposition bind tighter than * and /."""
    return _NUM_NAME.sub(r"(\1*\2)", src)


def _prepare(src: str) -> tuple[str, dict]:
    """Rename Python keywords and turn name(...) into name*(...) for non-functions."""
    # Treat ** exactly like ^ so "2x**2" groups the same way as "2x^2".
    src = group_implicit(src.replace("**", "^"))
    local = {}

    def kw(m):
        name = m.group(0)
        if name in _KEYWORDS:
            alias = name + _KW_SUFFIX
            local[alias] = sp.Symbol(name)
            return alias
        return name

    src = re.sub(r"(?<![\w.])[A-Za-z_]\w*", kw, src)

    def call(m):
        name = m.group(1)
        if name in FUNCTIONS:
            return m.group(0)
        return f"{name}*{m.group(2)}("

    src = _NAME_CALL.sub(call, src)
    return src, local


_TRIG_NAMES = ("sin", "cos", "tan", "sec", "csc", "cot")
_ATRIG_NAMES = ("asin", "acos", "atan", "atan2", "arcsin", "arccos", "arctan")


def _global_dict(angle_mode: str = "rad") -> dict:
    g = {
        "Symbol": sp.Symbol, "Function": sp.Function, "Integer": sp.Integer,
        "Float": sp.Float, "Rational": sp.Rational, "factorial": sp.factorial,
        "Add": sp.Add, "Mul": sp.Mul, "Pow": sp.Pow,
    }
    g.update(FUNCTIONS)
    g.update(CONSTANTS)
    if angle_mode == "deg":
        # Trig takes degrees and inverse trig returns degrees.
        for name in _TRIG_NAMES:
            g[name] = (lambda f: lambda x, **kw: f(x * sp.pi / 180))(FUNCTIONS[name])
        for name in _ATRIG_NAMES:
            g[name] = (lambda f: lambda *a, **kw: f(*a) * 180 / sp.pi)(FUNCTIONS[name])
    return g


@functools.lru_cache(maxsize=4096)
def parse_side(text: str, evaluate: bool = True, angle_mode: str = "rad") -> sp.Expr:
    """Parse one side of an equation (no '=').

    With angle_mode='deg' trig functions are converted to radian form at parse
    time, so the returned expression is always ready for numeric work.
    """
    stripped = text.strip()
    if not stripped:
        raise ParseError("Empty expression")
    _check_syntax(stripped)
    src, local = _prepare(stripped)
    try:
        expr = parse_expr(src, local_dict=local, global_dict=_global_dict(angle_mode),
                          transformations=_TRANSFORMS, evaluate=evaluate)
    except ParseError:
        raise
    except TypeError as e:
        raise ParseError(f"Wrong number of arguments to a function ({e})") from None
    except Exception as e:  # SyntaxError, TokenError, sympy errors...
        raise ParseError(f"Could not understand '{stripped}'") from e
    if not isinstance(expr, sp.Expr):
        raise ParseError(f"Could not understand '{stripped}'")
    return expr


@dataclass(frozen=True)
class Equation:
    text: str
    lhs: sp.Expr
    rhs: sp.Expr | None  # None: a bare expression, not an equation
    line: int = 0

    @property
    def is_equation(self) -> bool:
        return self.rhs is not None

    @property
    def residual(self) -> sp.Expr:
        return self.lhs - self.rhs if self.rhs is not None else self.lhs

    @property
    def symbols(self) -> set:
        s = set(self.lhs.free_symbols)
        if self.rhs is not None:
            s |= self.rhs.free_symbols
        return s


def _split_sides(text: str) -> tuple[str, str | None, int]:
    if "==" in text:
        raise ParseError("Use a single '=' for equations", text.index("=="))
    parts = text.split("=")
    if len(parts) > 2:
        second = text.index("=", text.index("=") + 1)
        raise ParseError("Only one '=' allowed per line", second)
    if len(parts) == 1:
        return parts[0], None, 0
    if not parts[0].strip():
        raise ParseError("Nothing on the left of '='", 0)
    if not parts[1].strip():
        raise ParseError("Nothing on the right of '='", len(text) - 1)
    return parts[0], parts[1], len(parts[0]) + 1


def _parse_with_offset(text: str, offset: int, evaluate: bool, angle_mode: str = "rad") -> sp.Expr:
    try:
        return parse_side(text, evaluate, angle_mode)
    except ParseError as e:
        col = None if e.col is None else e.col + offset + (len(text) - len(text.lstrip()))
        raise ParseError(str(e), col) from None


def parse_line(text: str, line: int = 0, angle_mode: str = "rad",
               evaluate: bool = True) -> Equation | None:
    """Parse one editor line. Returns None for blank/comment lines."""
    body = normalize(strip_comment(text))
    if not body.strip():
        return None
    left, right, roff = _split_sides(body)
    lhs = _parse_with_offset(left, 0, evaluate, angle_mode)
    rhs = None if right is None else _parse_with_offset(right, roff, evaluate, angle_mode)
    return Equation(text=strip_comment(text).strip(), lhs=lhs, rhs=rhs, line=line)


def parse_lines(text: str, angle_mode: str = "rad") -> list[tuple[int, str, Equation | ParseError | None]]:
    """Parse a block of text; returns (line_number_1_based, source, result)."""
    out = []
    for i, src in enumerate(text.splitlines(), start=1):
        try:
            out.append((i, src, parse_line(src, i, angle_mode)))
        except ParseError as e:
            out.append((i, src, e))
    return out


# ---------------------------------------------------------------------------
# Printing
# ---------------------------------------------------------------------------

def _tidy(e):
    """Rebuild an unevaluated tree, folding integer fractions like 1/2 into Rationals."""
    if not e.args or e.is_Atom:
        return e
    args = [_tidy(a) for a in e.args]
    if e.is_Mul:
        # Fold typed fractions like 2/3 (Integer * Integer**-1) and drop "1 *".
        merged, i = [], 0
        while i < len(args):
            a = args[i]
            nxt = args[i + 1] if i + 1 < len(args) else None
            if a.is_Integer and nxt is not None and nxt.is_Pow and nxt.args[0].is_Integer                     and nxt.args[1] == -1:
                merged.append(sp.Rational(a, nxt.args[0]))
                i += 2
            else:
                merged.append(a)
                i += 1
        if len(merged) > 1:
            merged = [a for a in merged if a != 1] or [sp.Integer(1)]
        if len(merged) == 1:
            return merged[0]
        return sp.Mul(*merged, evaluate=False)
    try:
        return e.func(*args, evaluate=False)
    except TypeError:
        return e.func(*args)


class _Latex(LatexPrinter):
    def _print_log(self, expr, exp=None):
        if len(expr.args) == 2:
            arg = self._print(expr.args[0])
            base = self._print(expr.args[1])
            tex = r"\log_{%s}{\left(%s \right)}" % (base, arg)
            return tex if exp is None else r"%s^{%s}" % (tex, exp)
        return r"\ln{\left(%s \right)}" % self._print(expr.args[0]) if exp is None else \
            r"\ln^{%s}{\left(%s \right)}" % (exp, self._print(expr.args[0]))

    def _print_Symbol(self, expr, style="plain"):
        m = _DERIV_NAME.match(expr.name)
        if m:  # dy_dx -> dy/dx as a fraction
            return r"\frac{d%s}{d%s}" % (self._print(sp.Symbol(m.group(1))),
                                         self._print(sp.Symbol(m.group(2))))
        return super()._print_Symbol(expr, style)


_DERIV_NAME = re.compile(r"^d([A-Za-z][A-Za-z0-9]*)_d([A-Za-z][A-Za-z0-9]*)$")
_TRIG_FUNCS = (sp.sin, sp.cos, sp.tan, sp.sec, sp.csc, sp.cot)
_ATRIG_FUNCS = (sp.asin, sp.acos, sp.atan, sp.atan2)


def to_degree_form(expr):
    """Undo the degree-mode parse transform so text re-parsed in degree mode means the same.

    Degree-mode parsing turns sin(x) into sin(pi*x/180) and asin(v) into 180*asin(v)/pi;
    this maps such results back (sin(pi*x/180) -> sin(x)).
    """
    if not isinstance(expr, sp.Basic) or not expr.has(*_TRIG_FUNCS, *_ATRIG_FUNCS):
        return expr
    if isinstance(expr, sp.Equality):
        return sp.Eq(to_degree_form(expr.lhs), to_degree_form(expr.rhs), evaluate=False)
    expr = expr.replace(lambda e: isinstance(e, _ATRIG_FUNCS), lambda e: e * sp.pi / 180)
    expr = expr.replace(lambda e: isinstance(e, _TRIG_FUNCS),
                        lambda e: e.func(sp.expand(e.args[0] * 180 / sp.pi)))
    return expr


def to_latex(expr, order: str | None = None, mul_symbol: str | None = None) -> str:
    settings = {}
    if order:
        settings["order"] = order
    if mul_symbol:
        settings["mul_symbol"] = mul_symbol
    return _Latex(settings).doprint(expr)


def display_latex(text: str, symbol_latex: dict[str, str] | None = None) -> str:
    """LaTeX for a line exactly as typed (not simplified). Raises ParseError.

    ``symbol_latex`` overrides how particular names are drawn (e.g. units upright).
    """
    body = normalize(strip_comment(text))
    left, right, roff = _split_sides(body)
    sides = [_tidy(_parse_with_offset(left, 0, False))]
    if right is not None:
        sides.append(_tidy(_parse_with_offset(right, roff, False)))
    out = []
    for side in sides:
        if symbol_latex:
            rep = {s: sp.Symbol(symbol_latex[s.name]) for s in side.free_symbols
                   if s.name in symbol_latex}
            side = side.xreplace(rep)
        out.append(to_latex(side, order="none", mul_symbol="dot"))
    return " = ".join(out)


class _InputPrinter(StrPrinter):
    """Prints sympy expressions back in this calculator's input syntax."""

    def _print_log(self, expr):
        if len(expr.args) == 2:
            return "log(%s, %s)" % (self._print(expr.args[0]), self._print(expr.args[1]))
        return "ln(%s)" % self._print(expr.args[0])

    def _print_Exp1(self, expr):
        return "exp(1)"

    def _print_ImaginaryUnit(self, expr):
        return "sqrt(-1)"

    def _print_Abs(self, expr):
        return "abs(%s)" % self._print(expr.args[0])

    def _print_ceiling(self, expr):
        return "ceil(%s)" % self._print(expr.args[0])

    def _print_Pow(self, expr, rational=False):
        return super()._print_Pow(expr, rational).replace("**", "^")

    def _print_Rational(self, expr):
        return "%s/%s" % (expr.p, expr.q)


def to_input_text(expr) -> str:
    if isinstance(expr, sp.Equality):
        return f"{to_input_text(expr.lhs)} = {to_input_text(expr.rhs)}"
    return _InputPrinter({"order": None}).doprint(expr).replace("**", "^")


# ---------------------------------------------------------------------------
# Numbers
# ---------------------------------------------------------------------------

def format_number(x, mode: str = "auto", digits: int = 6) -> str:
    """Format a float. mode: auto (significant figures), fix, sci, eng."""
    if isinstance(x, complex):
        if abs(x.imag) <= 1e-12 * max(1.0, abs(x.real)):
            x = x.real
        else:
            return f"{format_number(x.real, mode, digits)} {'+' if x.imag >= 0 else '-'} " \
                   f"{format_number(abs(x.imag), mode, digits)}i"
    x = float(x)
    if math.isnan(x):
        return "undefined"
    if math.isinf(x):
        return "∞" if x > 0 else "-∞"
    digits = max(1, int(digits))
    if x == 0:
        return "0"
    if mode == "fix":
        return f"{x:,.{digits}f}".replace(",", "")
    if mode == "sci":
        return _tidy_exp(f"{x:.{digits - 1}e}")
    if mode == "eng":
        exp3 = int(math.floor(math.log10(abs(x)) / 3) * 3)
        # Decimal avoids 10**exp3 underflowing to 0 for tiny (subnormal) numbers.
        mant = float(Decimal(repr(x)).scaleb(-exp3))
        dec = max(0, digits - 1 - int(math.floor(math.log10(abs(mant)))))
        s = f"{mant:.{dec}f}"
        return s if exp3 == 0 else f"{s}e{exp3}"
    s = f"{x:.{digits}g}"
    return _tidy_exp(s)


def _tidy_exp(s: str) -> str:
    if "e" in s:
        mant, exp = s.split("e")
        return f"{mant}e{int(exp)}"
    return s


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def run_with_timeout(fn, timeout: float, *args, **kwargs):
    """Run fn in a daemon thread; raise TimeoutError if it takes too long."""
    box = {}

    def target():
        try:
            box["v"] = fn(*args, **kwargs)
        except BaseException as e:  # noqa: BLE001 - re-raised in caller
            box["e"] = e

    t = threading.Thread(target=target, daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        raise TimeoutError
    if "e" in box:
        raise box["e"]
    return box["v"]


def _as_real(y):
    y = np.asarray(y)
    if np.iscomplexobj(y):
        out = np.where(np.abs(y.imag) <= 1e-9 * np.maximum(1.0, np.abs(y.real)), y.real, np.nan)
        return out.astype(float)
    return y.astype(float)


def make_function(expr, sym):
    """Vectorized float function of one variable; invalid points give NaN."""
    f = sp.lambdify(sym, expr, modules="numpy")

    def fv(x):
        x = np.asarray(x, dtype=float)
        with np.errstate(all="ignore"):
            try:
                y = f(x)
            except (ZeroDivisionError, OverflowError, ValueError, TypeError):
                y = np.vectorize(_safe_scalar(f))(x)
        return np.broadcast_to(_as_real(y), x.shape).astype(float)

    return fv


def _safe_scalar(f):
    def g(x):
        try:
            return complex(f(x))
        except Exception:
            return complex("nan")
    return g


def _close(a: float, b: float, rel: float = 1e-9) -> bool:
    if not (math.isfinite(a) and math.isfinite(b)):
        return False
    return abs(a - b) <= rel * max(1.0, abs(a), abs(b))


def _eval_float(expr) -> float:
    v = complex(sp.N(expr, 17))
    if abs(v.imag) > 1e-9 * max(1.0, abs(v.real)):
        raise SolveError("Result is complex (not a real number)")
    return v.real


def evaluate_constant(text: str, angle_mode: str = "rad") -> float:
    """Evaluate a typed numeric expression like 'sqrt(2)*3/4' (no variables)."""
    eq = parse_line(text, 0, angle_mode)
    if eq is None:
        raise ParseError("Empty")
    if eq.is_equation:
        raise ParseError("Expected a number, not an equation")
    if eq.lhs.free_symbols:
        names = ", ".join(sorted(s.name for s in eq.lhs.free_symbols))
        raise ParseError(f"Unknown name(s): {names}")
    return _eval_float(eq.lhs)


# ---------------------------------------------------------------------------
# Solving
# ---------------------------------------------------------------------------

@dataclass
class VarSpec:
    name: str
    value: float | None = None   # known value (in calculation units); None -> unknown
    guess: float | None = None
    lo: float | None = None
    hi: float | None = None


@dataclass
class Root1D:
    roots: list[float]
    primary: float
    method: str
    log: list[tuple[int, float, float]] = field(default_factory=list)


@dataclass
class SolveResult:
    values: dict[str, float] = field(default_factory=dict)
    alternates: dict[str, list[float]] = field(default_factory=dict)
    steps: list[str] = field(default_factory=list)
    checks: list[tuple[int, float, float, bool]] = field(default_factory=list)  # line, lhs, rhs, ok
    expressions: list[tuple[int, str, float]] = field(default_factory=list)    # line, text, value
    formulas: list[sp.Equality] = field(default_factory=list)
    iteration_log: list[tuple[int, float, float]] = field(default_factory=list)
    reduced: tuple | None = None   # (lhs, rhs, Symbol) of the last 1-D equation solved


def solve_1d(lhs, rhs, sym, spec: VarSpec | None = None) -> Root1D:
    """Find real roots of lhs = rhs in one variable."""
    spec = spec or VarSpec(sym.name)
    expr = sp.expand(lhs - rhs) if (lhs - rhs).is_polynomial(sym) else lhs - rhs
    lo, hi, guess = spec.lo, spec.hi, spec.guess
    if lo is not None and hi is not None and lo > hi:
        lo, hi = hi, lo

    def in_range(r):
        return (lo is None or r >= lo - 1e-12 * max(1, abs(lo))) and \
               (hi is None or r <= hi + 1e-12 * max(1, abs(hi)))

    roots: list[float] = []
    method = ""
    logs: dict[float, list] = {}
    poly_ok = None

    if expr.free_symbols == {sym} and expr.is_polynomial(sym):
        poly = sp.Poly(expr, sym)
        if poly.degree() >= 1:
            coeffs = [float(c) for c in poly.all_coeffs()]

            def poly_ok(r, coeffs=coeffs):
                # Residual must be tiny compared with the size of the polynomial's terms.
                n = len(coeffs) - 1
                terms = [c * r ** (n - k) for k, c in enumerate(coeffs)]
                return abs(sum(terms)) <= 1e-8 * sum(abs(t) for t in terms)

            try:
                for r in poly.nroots(n=15, maxsteps=200):
                    c = complex(r)
                    if abs(c.imag) <= 1e-6 * abs(c) and poly_ok(c.real):
                        roots.append(c.real)
                method = f"polynomial (degree {poly.degree()})"
            except Exception:
                roots = []
    elif not expr.free_symbols:
        raise SolveError(f"Equation does not contain {sym}")

    f = make_function(lhs - rhs, sym)
    fl = make_function(lhs, sym)
    fr = make_function(rhs, sym)

    def fs(x):
        return float(f(np.array([x]))[0])

    def converged(x):
        a, b = float(fl(np.array([x]))[0]), float(fr(np.array([x]))[0])
        return np.isfinite(a) and np.isfinite(b) and abs(a - b) <= 1e-8 * max(1.0, abs(a), abs(b))

    if not roots:
        # Scan for sign changes, then refine each bracket with Brent's method.
        if lo is not None and hi is not None:
            grid = np.linspace(lo, hi, 4001)
            if lo > 0 and hi / lo > 100:
                grid = np.union1d(grid, np.geomspace(lo, hi, 2000))
        else:
            pos = np.geomspace(1e-8, 1e8, 3200)
            grid = np.concatenate([-pos[::-1], [0.0], pos])
            if lo is not None:
                grid = grid[grid >= lo]
                grid = np.union1d(grid, [lo])
            if hi is not None:
                grid = grid[grid <= hi]
                grid = np.union1d(grid, [hi])
        if guess is not None and np.isfinite(guess):
            span = max(abs(guess), 1.0)
            grid = np.union1d(grid, np.linspace(guess - span, guess + span, 401))
        y = f(grid)
        finite = np.isfinite(y)
        for i in np.nonzero(finite & (y == 0))[0]:
            roots.append(float(grid[i]))
        for i in range(len(grid) - 1):
            if not (finite[i] and finite[i + 1]):
                continue
            ya, yb = y[i], y[i + 1]
            if ya * yb < 0:
                rec = []

                def fw(x, rec=rec):
                    v = fs(x)
                    rec.append((len(rec) + 1, x, v))
                    return v

                try:
                    r = optimize.brentq(fw, grid[i], grid[i + 1], xtol=1e-15,
                                        maxiter=300)
                except (ValueError, RuntimeError):
                    continue
                fr_ = fs(r)
                if np.isfinite(fr_) and abs(fr_) <= min(abs(ya), abs(yb)):
                    roots.append(float(r))
                    logs[float(r)] = rec
        method = "bracketing scan + Brent's method"

    if not roots or guess is not None:
        # Newton from the guess (or a few default starts) - catches touching roots that
        # have no sign change; with a Guess it also runs when other roots were found.
        dexpr = sp.diff(lhs - rhs, sym)
        df = make_function(dexpr, sym)
        starts = [guess] if guess is not None else []
        if not roots:
            starts += [x for x in (1.0, 0.5, 10.0, 0.1, 100.0, -1.0) if x not in starts]
        found_before = bool(roots)
        for x0 in starts:
            if x0 is None or not in_range(x0):
                continue
            rec = []

            def fw(x, rec=rec):
                v = fs(x)
                rec.append((len(rec) + 1, x, v))
                return v

            try:
                r = optimize.newton(fw, x0, fprime=lambda x: float(df(np.array([x]))[0]),
                                    maxiter=200, tol=1e-14)
            except (RuntimeError, ZeroDivisionError, OverflowError, ValueError):
                try:
                    rec.clear()
                    r = optimize.newton(fw, x0, maxiter=200, tol=1e-14)
                except Exception:
                    continue
            if np.isfinite(r) and converged(r) and in_range(r):
                roots.append(float(r))
                logs[float(r)] = rec
                if not found_before:
                    method = f"Newton's method from x0 = {format_number(x0)}"
                break

    roots = [r for r in roots if in_range(r) and
             (converged(r) or (poly_ok is not None and poly_ok(r)))]
    roots = _dedupe(sorted(roots))
    if not roots:
        where = ""
        if lo is not None or hi is not None:
            where = f" between {format_number(lo) if lo is not None else '-∞'} and " \
                    f"{format_number(hi) if hi is not None else '∞'}"
        raise SolveError(f"No real solution found for {sym.name}{where}. "
                         f"Try a different Guess or set Min/Max.")
    primary = _pick_primary(roots, guess)
    log = logs.get(primary) or next((v for k, v in logs.items() if _close(k, primary)), [])
    return Root1D(roots=roots, primary=primary, method=method, log=log)


def _dedupe(roots: list[float]) -> list[float]:
    """Merge numerically equal roots; tolerance scales with the roots themselves."""
    if not roots:
        return []
    tol = 1e-8 * max(abs(r) for r in roots)
    out: list[float] = []
    for r in roots:
        if not out or abs(r - out[-1]) > tol:
            out.append(r)
    return out


def _pick_primary(roots: list[float], guess: float | None) -> float:
    if guess is not None:
        return min(roots, key=lambda r: abs(r - guess))
    pos = [r for r in roots if r > 0]
    if pos:
        return min(pos)
    return max(roots)


def solve_system(eqs: list[tuple], syms: list, specs: dict[str, VarSpec]) -> tuple[dict, str]:
    """Solve n equations [(lhs, rhs), ...] for n symbols. Returns ({sym: value}, method)."""
    residuals = [l - r for l, r in eqs]
    try:
        A, b = sp.linear_eq_to_matrix(residuals, syms)
        An = np.array(A.evalf(), dtype=float)
        bn = np.array(b.evalf(), dtype=float).ravel()
    except Exception:  # nonlinear (or non-numeric coefficients)
        An = None
    if An is not None:
        if np.linalg.matrix_rank(An) < len(syms):
            raise SolveError("The equations are not independent (singular system) - "
                             "check for duplicate or redundant equations.")
        x = np.linalg.solve(An, bn)
        return {s: float(v) for s, v in zip(syms, x)}, "linear system (Gaussian elimination)"

    F = sp.lambdify([syms], residuals, modules="numpy")
    J = sp.lambdify([syms], sp.Matrix(residuals).jacobian(syms), modules="numpy")
    Fl = sp.lambdify([syms], [l for l, _ in eqs], modules="numpy")
    Fr = sp.lambdify([syms], [r for _, r in eqs], modules="numpy")

    def fvec(x):
        with np.errstate(all="ignore"):
            return _as_real(np.array(F(list(x)), dtype=complex))

    def jac(x):
        with np.errstate(all="ignore"):
            return _as_real(np.array(J(list(x)), dtype=complex))

    def ok(x):
        with np.errstate(all="ignore"):
            a = _as_real(np.array(Fl(list(x)), dtype=complex))
            b = _as_real(np.array(Fr(list(x)), dtype=complex))
        if not (np.all(np.isfinite(a)) and np.all(np.isfinite(b))):
            return False
        return bool(np.all(np.abs(a - b) <= 1e-8 * np.maximum(1.0, np.maximum(np.abs(a), np.abs(b)))))

    def in_bounds(x):
        for s, v in zip(syms, x):
            sp_ = specs.get(s.name)
            if sp_ and ((sp_.lo is not None and v < sp_.lo - 1e-9 * max(1, abs(sp_.lo)))
                        or (sp_.hi is not None and v > sp_.hi + 1e-9 * max(1, abs(sp_.hi)))):
                return False
        return True

    base = []
    for s in syms:
        sp_ = specs.get(s.name, VarSpec(s.name))
        if sp_.guess is not None:
            base.append(sp_.guess)
        elif sp_.lo is not None and sp_.hi is not None:
            base.append((sp_.lo + sp_.hi) / 2)
        elif sp_.lo is not None:
            base.append(sp_.lo + 1.0 if sp_.lo <= 0 else sp_.lo * 2)
        elif sp_.hi is not None:
            base.append(sp_.hi - 1.0 if sp_.hi >= 0 else sp_.hi * 2)
        else:
            base.append(1.0)
    base = np.array(base, dtype=float)
    rng = np.random.default_rng(12345)
    starts = [base] + [base * m for m in (0.5, 2.0, 10.0, 0.1, -1.0)]
    starts += [base * rng.uniform(0.1, 10, size=len(base)) for _ in range(30)]
    best = None
    for x0 in starts:
        for method in ("hybr", "lm"):
            try:
                sol = optimize.root(fvec, x0, jac=jac, method=method)
            except Exception:
                continue
            x = sol.x
            if ok(x):
                if in_bounds(x):
                    return {s: float(v) for s, v in zip(syms, x)}, f"Newton-type iteration ({method})"
                best = best if best is not None else x
    if best is not None:
        raise SolveError("Found a solution only outside the Min/Max limits: " +
                         ", ".join(f"{s.name} = {format_number(v)}" for s, v in zip(syms, best)))
    raise SolveError("The iterative solver did not converge. Enter Guess values close to the "
                     "expected answer for: " + ", ".join(s.name for s in syms))


def _definition(lhs, rhs, unknowns: set):
    """If the equation is 'X = expr' (or 'expr = X') with X unknown, return (X, expr)."""
    for a, b in ((lhs, rhs), (rhs, lhs)):
        if isinstance(a, sp.Symbol) and a in unknowns and a not in b.free_symbols:
            return a, b
    return None


@dataclass
class _Branch:
    """Partial result of solving the remaining equations (used for trying alternate roots)."""
    solved: dict = field(default_factory=dict)
    defs: list = field(default_factory=list)
    steps: list = field(default_factory=list)
    alternates: dict = field(default_factory=dict)
    log: list = field(default_factory=list)
    reduced: tuple | None = None
    consistent: bool = True


def _sub(work, sym, value):
    return [(ln, l.xreplace({sym: value}), r.xreplace({sym: value})) for ln, l, r in work]


def _solve_work(work, unsolved, specs, cancel, depth=0) -> _Branch:
    """Solve the (line, lhs, rhs) list for the unsolved symbols.

    Strategy: equations with a single unknown first, then eliminate 'X = expr'
    definitions, then solve what's left simultaneously. When a single-unknown
    equation has several roots, each is tried and the first one that keeps the
    remaining equations consistent wins.
    """
    b = _Branch()
    work = list(work)
    unsolved = set(unsolved)
    while unsolved:
        if cancel is not None and cancel.is_set():
            raise SolveError("Cancelled")
        live = [w for w in work if (w[1].free_symbols | w[2].free_symbols) & unsolved]
        if not live:
            names = ", ".join(sorted(s.name for s in unsolved))
            raise SolveError(f"Not enough equations to find: {names}. Enter more values or add equations.")
        single = [w for w in live if len((w[1].free_symbols | w[2].free_symbols) & unsolved) == 1]
        if single:
            w = single[0]
            ln, l, r = w
            sym = next(iter((l.free_symbols | r.free_symbols) & unsolved))
            r1 = solve_1d(l, r, sym, specs.get(sym.name))
            rest = [x for x in work if x is not w]
            b.steps.append(f"Line {ln}: solved for {sym.name} ({r1.method})")
            b.log, b.reduced = r1.log, (l, r, sym)
            candidates = [r1.primary] + [x for x in r1.roots if x != r1.primary]
            if len(candidates) > 1 and rest and depth < 6:
                chosen = None
                for cand in candidates[:6]:
                    try:
                        sub = _solve_work(_sub(rest, sym, sp.Float(cand, 17)), unsolved - {sym},
                                          specs, cancel, depth + 1)
                    except SolveError as e:
                        if str(e) == "Cancelled":
                            raise
                        continue
                    if chosen is None or (sub.consistent and not chosen[1].consistent):
                        chosen = (cand, sub)
                    if sub.consistent:
                        break
                if chosen is not None:
                    cand, sub = chosen
                    b.solved[sym] = cand
                    b.alternates[sym.name] = [x for x in r1.roots if x != cand]
                    if cand != r1.primary:
                        b.steps.append(f"used {sym.name} = {format_number(cand)} because it agrees "
                                       f"with the other equations")
                    b.solved.update(sub.solved)
                    b.defs += sub.defs
                    b.steps += sub.steps
                    b.alternates.update(sub.alternates)
                    if sub.log:
                        b.log, b.reduced = sub.log, sub.reduced
                    b.consistent = sub.consistent
                    return b
            b.solved[sym] = r1.primary
            if len(r1.roots) > 1:
                b.alternates[sym.name] = [x for x in r1.roots if x != r1.primary]
            unsolved.discard(sym)
            work = _sub(rest, sym, sp.Float(r1.primary, 17))
            continue
        d = w = None
        for w in live:
            d = _definition(w[1], w[2], unsolved)
            if d:
                break
        if d:
            sym, expr = d
            b.defs.append((w[0], sym, expr))
            b.steps.append(f"Line {w[0]}: substituted {sym.name} into the other equations")
            unsolved.discard(sym)
            work = _sub([x for x in work if x is not w], sym, expr)
            continue
        syms = sorted(unsolved, key=lambda s: s.name)
        if len(live) == len(syms):
            vals, method = solve_system([(l, r) for _, l, r in live], syms, specs)
            b.steps.append(f"Lines {', '.join(str(x[0]) for x in live)}: solved together "
                           f"for {', '.join(s.name for s in syms)} ({method})")
            work = [x for x in work if not any(x is y for y in live)]
            for s_, v in vals.items():
                b.solved[s_] = v
                work = _sub(work, s_, sp.Float(v, 17))
            unsolved.clear()
            break
        if len(live) < len(syms):
            raise SolveError(f"Not enough equations: {len(syms)} unknowns "
                             f"({', '.join(s.name for s in syms)}) but only {len(live)} "
                             f"equation(s) left. Enter more values or add equations.")
        raise SolveError(f"Too many equations ({len(live)}) for {len(syms)} unknown(s) "
                         f"({', '.join(s.name for s in syms)}). Remove an equation or clear "
                         f"another value so it becomes an unknown.")
    # Whatever is left is fully numeric: it must balance for this branch to be consistent.
    for _, l, r in work:
        if l.free_symbols or r.free_symbols:
            continue
        try:
            if not _close(_eval_float(l), _eval_float(r), 1e-7):
                b.consistent = False
        except SolveError:
            b.consistent = False
    return b


def solve_equations(equations: list[Equation], specs: dict[str, VarSpec],
                    cancel: threading.Event | None = None) -> SolveResult:
    """Solve a worksheet: knowns from specs, everything else is unknown."""
    res = SolveResult()
    eqs = [e for e in equations if e.is_equation]
    exprs = [e for e in equations if not e.is_equation]
    for n, s_ in specs.items():
        for label, v in (("value", s_.value), ("guess", s_.guess), ("min", s_.lo), ("max", s_.hi)):
            if v is not None and not math.isfinite(v):
                raise SolveError(f"{n} {label} is not a finite number")
    known = {sp.Symbol(n): sp.Float(s_.value, 17) for n, s_ in specs.items() if s_.value is not None}
    all_syms = set().union(*(e.symbols for e in equations)) if equations else set()
    unknowns = {s_ for s_ in all_syms if s_ not in known}
    eq_syms = set().union(*(e.symbols for e in eqs)) if eqs else set()
    missing = sorted(s_.name for s_ in unknowns - eq_syms)
    if missing:
        raise SolveError("No value given for: " + ", ".join(missing))

    work = [(e.line, e.lhs.xreplace(known), e.rhs.xreplace(known)) for e in eqs]
    unsolved = {s_ for s_ in unknowns if s_ in eq_syms}
    usable = [w for w in work if (w[1].free_symbols | w[2].free_symbols) & unsolved]
    if len(usable) < len(unsolved):
        names = ", ".join(sorted(s_.name for s_ in unsolved))
        raise SolveError(f"Not enough equations: {len(unsolved)} unknowns ({names}) but only "
                         f"{len(usable)} equation(s) contain them. Enter more values or add equations.")

    # Exact formula when there's exactly one equation and one unknown.
    if len(eqs) == 1 and len(unsolved) == 1:
        sym = next(iter(unsolved))
        try:
            sols = run_with_timeout(sp.solve, 4, eqs[0].lhs - eqs[0].rhs, sym)
            # Only worth showing when it's a formula in other variables, not just numbers.
            res.formulas = [sp.Eq(sym, s_) for s_ in sols if s_.free_symbols][:6]
        except Exception:
            pass

    branch = _solve_work(work, unsolved, specs, cancel)
    solved = dict(branch.solved)
    res.steps, res.alternates = branch.steps, branch.alternates
    res.iteration_log, res.reduced = branch.log, branch.reduced

    # Back-substitute eliminated definitions (most recent first).
    for ln, sym, expr in reversed(branch.defs):
        val = expr.xreplace({k: sp.Float(v, 17) for k, v in solved.items()})
        if val.free_symbols:
            raise SolveError(f"Could not determine {sym.name}: still depends on "
                             + ", ".join(s_.name for s_ in val.free_symbols))
        solved[sym] = _eval_float(val)

    for sym, v in solved.items():
        spec = specs.get(sym.name)
        if not math.isfinite(v):
            raise SolveError(f"{sym.name} came out infinite or undefined")
        if spec and ((spec.lo is not None and v < spec.lo - 1e-9 * max(1, abs(spec.lo))) or
                     (spec.hi is not None and v > spec.hi + 1e-9 * max(1, abs(spec.hi)))):
            raise SolveError(f"The equations give {sym.name} = {format_number(v)}, which is "
                             f"outside its Min/Max limits.")

    res.values = {s_.name: float(v) for s_, v in solved.items()}
    allvals = dict(known)
    allvals.update({s_: sp.Float(v, 17) for s_, v in solved.items()})

    for e in eqs:
        try:
            a = _eval_float(e.lhs.xreplace(allvals))
            b = _eval_float(e.rhs.xreplace(allvals))
        except Exception:
            continue
        res.checks.append((e.line, a, b, _close(a, b, 1e-7)))
    for e in exprs:
        v = e.lhs.xreplace(allvals)
        if v.free_symbols:
            raise SolveError(f"Line {e.line}: no value for " + ", ".join(sorted(s_.name for s_ in v.free_symbols)))
        res.expressions.append((e.line, e.text, _eval_float(v)))
    return res


# ---------------------------------------------------------------------------
# Symbolic operations on a single line
# ---------------------------------------------------------------------------

SYMBOLIC_TIMEOUT = 10


def rearrange(eq: Equation, var: str) -> list[sp.Equality]:
    sym = sp.Symbol(var)
    if sym not in eq.symbols:
        raise SolveError(f"'{var}' does not appear in this line")
    expr = eq.residual
    try:
        sols = run_with_timeout(sp.solve, SYMBOLIC_TIMEOUT, expr, sym)
    except TimeoutError:
        raise SolveError("Rearranging took too long - this equation may not have a closed-form "
                         "answer. Use Solve to find it numerically.") from None
    except NotImplementedError:
        sols = []
    if not sols:
        # Retry assuming every variable is positive (typical for physical quantities);
        # this removes sign()/Abs() from real roots such as cbrt(x).
        pos = {s: sp.Symbol(s.name, positive=True) for s in expr.free_symbols}
        back = {v: k for k, v in pos.items()}
        try:
            sols = run_with_timeout(sp.solve, SYMBOLIC_TIMEOUT, expr.xreplace(pos), pos[sym])
            sols = [s.xreplace(back) for s in sols]
        except (TimeoutError, NotImplementedError):
            sols = []
    if not sols:
        raise SolveError(f"Could not isolate {var} (no closed-form answer found). "
                         "Use Solve to find it numerically.")
    return [sp.Eq(sym, s) for s in sols]


def transform(eq: Equation, how: str) -> sp.Basic:
    fn = {"simplify": sp.simplify, "expand": sp.expand, "factor": sp.factor}[how]

    def go():
        if eq.is_equation:
            return sp.Eq(fn(eq.lhs), fn(eq.rhs), evaluate=False)
        return fn(eq.lhs)

    try:
        return run_with_timeout(go, SYMBOLIC_TIMEOUT)
    except TimeoutError:
        raise SolveError(f"{how.capitalize()} took too long.") from None


def _target_expr(eq: Equation):
    """For 'y = f(x)' use f; for other equations use lhs - rhs; for expressions the expression."""
    if eq.is_equation:
        if isinstance(eq.lhs, sp.Symbol) and eq.lhs not in eq.rhs.free_symbols:
            return eq.lhs, eq.rhs
        return None, eq.lhs - eq.rhs
    return None, eq.lhs


def derivative(eq: Equation, var: str):
    sym = sp.Symbol(var)
    name, expr = _target_expr(eq)
    d = run_with_timeout(lambda: sp.simplify(sp.diff(expr, sym)),
                         SYMBOLIC_TIMEOUT)
    # "dy_dx = ..." is a valid line when inserted (drawn as dy/dx); otherwise just the expression.
    label = f"d{name.name}_d{var}" if name is not None else ""
    if label and _DERIV_NAME.match(label):
        return sp.Eq(sp.Symbol(label), d, evaluate=False)
    return d


def integral(eq: Equation, var: str, a=None, b=None):
    sym = sp.Symbol(var)
    _, expr = _target_expr(eq)
    if a is not None and b is not None:
        try:
            v = run_with_timeout(lambda: sp.integrate(expr, (sym, a, b)), SYMBOLIC_TIMEOUT)
            if not v.has(sp.Integral):
                return v
        except TimeoutError:
            pass
        # Numeric fallback
        from scipy import integrate as si
        free = expr.free_symbols - {sym}
        if free:
            raise SolveError("Definite integral needs values for: " + ", ".join(s.name for s in free))
        f = make_function(expr, sym)
        val, _ = si.quad(lambda x: float(f(np.array([x]))[0]), float(a), float(b), limit=200)
        return sp.Float(val)
    try:
        v = run_with_timeout(lambda: sp.integrate(expr, sym), SYMBOLIC_TIMEOUT)
    except TimeoutError:
        raise SolveError("Integration took too long.") from None
    if v.has(sp.Integral):
        raise SolveError("No closed-form antiderivative found. Give limits for a numeric answer.")
    return v


def single_variable_view(equations: list[Equation], line: int, values: dict[str, float],
                         var: str, fallback: dict[str, float] | None = None):
    """Reduce one line to (lhs(var), rhs(var)) for plotting.

    Other variables are replaced by, in order of preference: known ``values``,
    definition lines ('X = ...') from the worksheet, then ``fallback`` values
    (e.g. results of the last solve).
    """
    sym = sp.Symbol(var)
    target = next((e for e in equations if e.line == line), None)
    if target is None:
        raise SolveError("Put the cursor on an equation line to plot it")
    subs = {sp.Symbol(k): sp.Float(v, 17) for k, v in values.items() if k != var}
    late = {sp.Symbol(k): sp.Float(v, 17) for k, v in (fallback or {}).items()
            if k != var and sp.Symbol(k) not in subs}
    lhs = target.lhs
    rhs = target.rhs if target.is_equation else None

    def free_of(l, r):
        return (l.free_symbols | (r.free_symbols if r is not None else set())) - {sym}

    defs = {}
    for e in equations:
        if e is target or not e.is_equation:
            continue
        d = _definition(e.lhs, e.rhs, set(e.symbols) - {sym})
        if d and d[0] != sym and d[0] not in subs:
            defs[d[0]] = d[1]
    for _ in range(len(defs) + 1):
        pending = {s: defs[s] for s in free_of(lhs, rhs) if s in defs}
        if not pending:
            break
        lhs = lhs.xreplace(pending)
        rhs = rhs.xreplace(pending) if rhs is not None else None
    for table in (subs, late):
        lhs = lhs.xreplace(table)
        rhs = rhs.xreplace(table) if rhs is not None else None
    free = free_of(lhs, rhs)
    if free:
        raise SolveError("To plot against " + var + ", give values for: " +
                         ", ".join(sorted(s.name for s in free)))
    if sym not in (lhs.free_symbols | (rhs.free_symbols if rhs is not None else set())):
        raise SolveError(f"This line does not depend on {var}")
    return lhs, rhs, sym
