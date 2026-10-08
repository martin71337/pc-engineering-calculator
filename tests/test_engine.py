"""Tests for the math engine, units and scratchpad.  Run:  py -3.14 -m unittest discover tests"""
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import sympy as sp  # noqa: E402

from calculator import engine, units  # noqa: E402
from calculator.engine import ParseError, SolveError, VarSpec, parse_line, parse_lines, solve_equations  # noqa: E402
from calculator.scratch import Scratchpad, ScratchError  # noqa: E402

MANNING_TRAP = """A = (b + z*y)*y
P = b + 2*y*sqrt(1 + z^2)
R = A/P
Q = 1.49/n*A*R^(2/3)*S^(1/2)"""


def eqs(text, angle="rad"):
    return [r for _, _, r in parse_lines(text, angle) if r is not None]


def known(**kw):
    return {k: VarSpec(k, v) for k, v in kw.items()}


class ParsingTests(unittest.TestCase):
    def test_engineering_letters_are_variables(self):
        eq = parse_line("y = E*I + S*N + Q + e + gamma + beta + lambda")
        names = {s.name for s in eq.symbols}
        self.assertEqual(names, {"y", "E", "I", "S", "N", "Q", "e", "gamma", "beta", "lambda"})

    def test_implicit_multiplication_and_power(self):
        eq = parse_line("y = 2x^2 + 3(a + b) + a b")
        x, a, b = sp.symbols("x a b")
        self.assertEqual(sp.expand(eq.rhs - (2 * x**2 + 3 * (a + b) + a * b)), 0)

    def test_number_name_binds_tightly(self):
        eq = parse_line("y = x/2z")
        x, z = sp.symbols("x z")
        self.assertEqual(sp.simplify(eq.rhs - x / (2 * z)), 0)

    def test_name_before_paren_is_multiplication(self):
        eq = parse_line("y = A(1 + z)")
        A, z = sp.symbols("A z")
        self.assertEqual(sp.expand(eq.rhs - A * (1 + z)), 0)

    def test_log_is_base_10_and_ln_is_natural(self):
        self.assertAlmostEqual(engine.evaluate_constant("log(1000)"), 3.0)
        self.assertAlmostEqual(engine.evaluate_constant("ln(exp(2))"), 2.0)
        self.assertAlmostEqual(engine.evaluate_constant("log(8, 2)"), 3.0)

    def test_cbrt_of_negative_is_real(self):
        self.assertAlmostEqual(engine.evaluate_constant("cbrt(-27)"), -3.0)

    def test_unicode_and_brackets(self):
        eq = parse_line("y = √x + π·θ² + [a + b]")
        self.assertEqual({s.name for s in eq.symbols}, {"y", "x", "theta", "a", "b"})
        eq = parse_line("Δ = 5w L⁴/(384 E I) + x⁻¹ + A₁")
        w, L, E, I, x, A1 = sp.symbols("w L E I x A_1")
        self.assertEqual(sp.simplify(eq.rhs - (5 * w * L**4 / (384 * E * I) + 1 / x + A1)), 0)

    def test_comments_and_blank_lines(self):
        self.assertIsNone(parse_line("   # just a note"))
        self.assertEqual(len(eqs("x = 1  # note\n\n# c\ny = 2")), 2)

    def test_errors_have_positions(self):
        cases = {"x = (a + b": "parenthesis", "x = a +": "ends with", "x == 2": "single",
                 "a = 1 = b": "Only one", "q = 5 $": "Unexpected", "x = (a))": "Extra"}
        for text, words in cases.items():
            with self.subTest(text=text):
                with self.assertRaises(ParseError) as cm:
                    parse_line(text)
                self.assertIn(words, str(cm.exception))
                self.assertIsNotNone(cm.exception.col)

    def test_display_keeps_typed_structure(self):
        tex = engine.display_latex("Q = 1.49/n*A*R^(2/3)*S^(1/2)")
        self.assertIn(r"\frac{2}{3}", tex)
        self.assertIn("1.49", tex)

    def test_input_text_round_trip(self):
        for f in engine.rearrange(parse_line("y = ln(x) + log(x)"), "x"):
            back = parse_line(engine.to_input_text(f))
            self.assertEqual(sp.simplify(back.lhs - back.rhs - (f.lhs - f.rhs)), 0)


class SolveTests(unittest.TestCase):
    def test_evaluate_long_expression(self):
        res = solve_equations(eqs("y = (3.2*a^2 + sqrt(b)/7 - c^(1/3))*(a + b)/(c - 1)"),
                              known(a=2.5, b=49, c=8))
        expected = (3.2 * 2.5**2 + 7 / 7 - 2) * (2.5 + 49) / 7
        self.assertAlmostEqual(res.values["y"], expected, places=10)

    def test_rearrange(self):
        sols = engine.rearrange(parse_line("Q = V*A"), "A")
        Q, V = sp.symbols("Q V")
        self.assertEqual(sols[0].rhs, Q / V)

    def test_quadratic_both_roots(self):
        res = solve_equations(eqs("a*x^2 + b*x + c = 0"), known(a=1, b=-3, c=2))
        roots = sorted([res.values["x"]] + res.alternates.get("x", []))
        self.assertEqual(len(roots), 2)
        self.assertAlmostEqual(roots[0], 1.0)
        self.assertAlmostEqual(roots[1], 2.0)
        self.assertTrue(res.formulas)

    def test_guess_picks_root(self):
        res = solve_equations(eqs("x^2 = 4"), {"x": VarSpec("x", guess=-3)})
        self.assertAlmostEqual(res.values["x"], -2.0)

    def test_bounds_limit_roots(self):
        res = solve_equations(eqs("x^3 - 6x^2 + 11x - 6 = 0"), {"x": VarSpec("x", lo=1.5, hi=2.5)})
        self.assertAlmostEqual(res.values["x"], 2.0)
        self.assertNotIn("x", res.alternates)

    def test_all_roots_of_cubic(self):
        res = solve_equations(eqs("x^3 - 6x^2 + 11x - 6 = 0"), {})
        roots = sorted([res.values["x"]] + res.alternates["x"])
        for r, e in zip(roots, (1, 2, 3)):
            self.assertAlmostEqual(r, e, places=9)

    def test_transcendental_iterative(self):
        res = solve_equations(eqs("x = cos(x)"), {})
        self.assertAlmostEqual(res.values["x"], 0.7390851332151607, places=12)

    def test_manning_trapezoid_normal_depth(self):
        res = solve_equations(eqs(MANNING_TRAP), known(Q=100, b=10, z=2, n=0.013, S=0.001))
        y = res.values["y"]
        A = (10 + 2 * y) * y
        P = 10 + 2 * y * math.sqrt(5)
        Q = 1.49 / 0.013 * A * (A / P) ** (2 / 3) * math.sqrt(0.001)
        self.assertAlmostEqual(Q, 100.0, places=8)
        self.assertAlmostEqual(y, 1.7186756, places=6)
        self.assertTrue(all(ok for *_, ok in res.checks))

    def test_manning_solve_for_other_variables(self):
        res = solve_equations(eqs(MANNING_TRAP), known(y=1.7186756066552, b=10, z=2, n=0.013, S=0.001))
        self.assertAlmostEqual(res.values["Q"], 100.0, places=5)
        res = solve_equations(eqs(MANNING_TRAP), known(Q=100, y=1.7186756066552, z=2, n=0.013, S=0.001))
        self.assertAlmostEqual(res.values["b"], 10.0, places=5)

    def test_linear_system(self):
        res = solve_equations(eqs("2x + 3y = 7\nx - y = 1"), {})
        self.assertAlmostEqual(res.values["x"], 2.0)
        self.assertAlmostEqual(res.values["y"], 1.0)

    def test_nonlinear_system(self):
        res = solve_equations(eqs("x^2 + y^2 = 25\nx*y = 12"), {"x": VarSpec("x", guess=4),
                                                                  "y": VarSpec("y", guess=3)})
        self.assertAlmostEqual(res.values["x"], 4.0, places=8)
        self.assertAlmostEqual(res.values["y"], 3.0, places=8)

    def test_underdetermined_message(self):
        with self.assertRaises(SolveError) as cm:
            solve_equations(eqs("a = b + c"), {})
        self.assertIn("Not enough equations", str(cm.exception))

    def test_overspecified_check_flags(self):
        res = solve_equations(eqs("a = b + c"), known(a=5, b=1, c=1))
        self.assertFalse(res.checks[0][3])

    def test_expression_lines_evaluated(self):
        res = solve_equations(eqs("x = 3\nx^2 + 1"), {})
        self.assertAlmostEqual(res.expressions[0][2], 10.0)

    def test_degree_mode(self):
        res = solve_equations(eqs("y = sin(x)\nt = asin(0.5)", "deg"), known(x=30))
        self.assertAlmostEqual(res.values["y"], 0.5)
        self.assertAlmostEqual(res.values["t"], 30.0)
        self.assertAlmostEqual(engine.evaluate_constant("cos(60)", "deg"), 0.5)

    def test_symbolic_ops(self):
        out = engine.transform(parse_line("y = (x + 1)^2"), "expand")
        x = sp.Symbol("x")
        self.assertEqual(out.rhs, x**2 + 2 * x + 1)
        d = engine.derivative(parse_line("y = x^3"), "x")
        self.assertEqual(d.rhs, 3 * x**2)
        self.assertEqual(engine.integral(parse_line("y = x^2"), "x", 0, 3), 9)

    def test_plot_view_substitutes_definitions(self):
        lhs, rhs, sym = engine.single_variable_view(eqs(MANNING_TRAP), 4,
                                                    {"Q": 100, "b": 10, "z": 2, "n": 0.013, "S": 0.001},
                                                    "y")
        self.assertEqual(rhs.free_symbols, {sym})


class ReviewRegressionTests(unittest.TestCase):
    """Issues found in code review."""

    def test_double_star_power_with_implicit_multiplication(self):
        x, y = sp.symbols("x y")
        self.assertEqual(parse_line("y = 2x**2").rhs, 2 * x**2)
        self.assertEqual(sp.simplify(parse_line("z = x/2y**2").rhs - x / (2 * y**2)), 0)

    def test_degree_mode_round_trip(self):
        out = engine.transform(parse_line("y = sin(x)", 0, "deg"), "simplify")
        text = engine.to_input_text(engine.to_degree_form(out))
        res = solve_equations([parse_line(text, 0, "deg")], known(x=30))
        self.assertAlmostEqual(res.values["y"], 0.5)

    def test_bounds_checked_for_linear_and_definitions(self):
        for text in ("2x + 3y = 7\nx - y = 1", "x = y + 1\nx + y = 3"):
            with self.subTest(text=text), self.assertRaises(SolveError):
                solve_equations(eqs(text), {"x": VarSpec("x", lo=10)})

    def test_tiny_complex_roots_not_real(self):
        with self.assertRaises(SolveError):
            solve_equations(eqs("x^2 + 1e-20 = 0"), {})

    def test_tiny_distinct_roots_kept(self):
        res = solve_equations(eqs("(x - 1e-10)*(x + 1e-10) = 0"), {"x": VarSpec("x", guess=1e-10)})
        self.assertAlmostEqual(res.values["x"], 1e-10, delta=1e-16)
        self.assertEqual(len(res.alternates["x"]), 1)

    def test_real_cube_root_of_symbol(self):
        self.assertAlmostEqual(solve_equations(eqs("y = cbrt(x)"), known(x=-8)).values["y"], -2.0)
        self.assertAlmostEqual(solve_equations(eqs("cbrt(x) = -2"), {}).values["x"], -8.0, places=9)
        self.assertEqual(str(engine.rearrange(parse_line("y = cbrt(x)"), "x")[0].rhs), "y**3")

    def test_touching_root_near_guess(self):
        res = solve_equations(eqs("(x - 2.1234567)^2*(exp(x) - exp(3)) = 0"),
                              {"x": VarSpec("x", guess=2.1, lo=0, hi=4)})
        self.assertAlmostEqual(res.values["x"], 2.1234567, places=5)

    def test_branch_consistent_with_other_equations(self):
        res = solve_equations(eqs("x^2 = 4\nx + y = 1\nx - y = -5"), {})
        self.assertAlmostEqual(res.values["x"], -2.0)
        self.assertAlmostEqual(res.values["y"], 3.0)
        self.assertTrue(all(c[3] for c in res.checks))

    def test_nonfinite_values_rejected(self):
        with self.assertRaises(SolveError):
            solve_equations(eqs("x = 1"), known(x=float("inf")))

    def test_derivative_inserts_as_valid_line(self):
        d = engine.derivative(parse_line("y = x^3"), "x")
        back = parse_line(engine.to_input_text(d))
        self.assertEqual(back.lhs, sp.Symbol("dy_dx"))
        self.assertIn(r"\frac{dy}{dx}", engine.to_latex(d))

    def test_eng_format_subnormal(self):
        self.assertTrue(engine.format_number(5e-324, "eng").endswith("e-324"))

    def test_value_field_commas(self):
        self.assertEqual(units.parse_value("min(1,2)"), 1.0)
        self.assertAlmostEqual(units.parse_value("log(8,2)"), 3.0)
        self.assertEqual(units.parse_value("1,250.5"), 1250.5)

    def test_temperatures_use_absolute_scales(self):
        v = units.to_calc(units.parse_value("0 degC"), "SI")
        self.assertAlmostEqual(v, 273.15)
        self.assertAlmostEqual(units.from_calc(v, "K", "SI").magnitude, 273.15)
        self.assertAlmostEqual(units.from_calc(v, "degC", "SI").magnitude, 0.0, places=9)
        v = units.to_calc(units.parse_value("68 degF"), "US")
        self.assertAlmostEqual(units.from_calc(v, "degF", "US").magnitude, 68.0, places=9)


class FormatTests(unittest.TestCase):
    def test_formats(self):
        f = engine.format_number
        self.assertEqual(f(123456.789), "123457")
        self.assertEqual(f(2.5, "fix", 3), "2.500")
        self.assertEqual(f(12345.6, "sci", 4), "1.235e4")
        self.assertEqual(f(0.000012345, "eng", 5), "12.345e-6")


class UnitTests(unittest.TestCase):
    def test_cfs_to_gpm(self):
        q = units.convert_text("1 cfs to gpm")
        self.assertAlmostEqual(q.magnitude, 448.831, places=3)

    def test_feet_inches(self):
        self.assertAlmostEqual(units.parse_value("12'6\"").to("ft").magnitude, 12.5)
        self.assertAlmostEqual(units.parse_value("3", "in").to("ft").magnitude, 0.25)

    def test_us_system_conversion(self):
        self.assertAlmostEqual(units.to_calc(units.parse_value("18 in"), "US"), 1.5)
        self.assertAlmostEqual(units.to_calc(units.parse_value("1 psi"), "US"), 144.0)
        self.assertAlmostEqual(units.to_calc(units.parse_value("1 ft"), "SI"), 0.3048)
        self.assertAlmostEqual(units.to_calc(units.parse_value("1 ft"), "asis"), 1.0)

    def test_angles_follow_angle_mode(self):
        self.assertAlmostEqual(units.to_calc(units.parse_value("30 deg"), "SI", "deg"), 30.0)
        self.assertAlmostEqual(units.to_calc(units.parse_value("30 deg"), "SI", "rad"), math.pi / 6)

    def test_manning_inputs_in_inches_match_feet(self):
        def depth(b_text, unit_out):
            b = units.to_calc(units.parse_value(b_text), "US")
            res = solve_equations(eqs(MANNING_TRAP), known(Q=100, b=b, z=2, n=0.013, S=0.001))
            return units.from_calc(res.values["y"], unit_out, "US").to("ft").magnitude
        self.assertAlmostEqual(depth("10 ft", "ft"), depth("120 in", "in"), places=9)

    def test_as_entered_ignores_units(self):
        self.assertEqual(units.to_calc(units.parse_value("120 in"), "asis"), 120.0)

    def test_from_calc(self):
        self.assertAlmostEqual(units.from_calc(1.5, "in", "US").magnitude, 18.0)
        self.assertEqual(units.from_calc(2.0, "", "US"), 2.0)

    def test_bad_unit(self):
        with self.assertRaises(units.UnitError):
            units.parse_unit("furlongz")

    def test_slope(self):
        out = dict(units.slope_conversions(2, "ratio H:V (run per 1 rise)"))
        self.assertEqual(out["percent (%)"], "50 %")


class ScratchpadTests(unittest.TestCase):
    def setUp(self):
        self.pad = Scratchpad()

    def run_(self, line):
        return self.pad.run(line, "deg").text

    def test_units_and_variables(self):
        self.run_("L = 24 ft")
        self.run_("W = 12'6\"")
        self.assertEqual(self.run_("L*W"), "300 ft²")
        self.assertEqual(self.run_("ans -> yd^2"), "33.3333 yd²")

    def test_mixed_units(self):
        self.assertEqual(self.run_("2 ft + 6 in"), "2.5 ft")
        self.assertEqual(self.run_("6 in / 1 ft"), "0.5")
        self.assertEqual(self.run_("100 psi * 2 in^2"), "200 lbf")
        self.assertEqual(self.run_("450 gpm * 5 min"), "2250 gal")

    def test_angles(self):
        self.assertEqual(self.run_("sin(30)"), "0.5")
        self.assertEqual(self.run_("sin(30 deg)"), "0.5")

    def test_errors(self):
        with self.assertRaises(ScratchError):
            self.run_("undefined_thing + 1")
        with self.assertRaises(ScratchError):
            self.run_("3 ft + 2 s")
        with self.assertRaises(ScratchError):
            self.run_("sqrt(-1)")


if __name__ == "__main__":
    unittest.main()
