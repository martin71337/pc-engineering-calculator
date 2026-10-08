"""Worksheet tab: type equations, fill in known values, solve for the rest."""
from __future__ import annotations

import datetime as _dt
import gc
import os
import queue
import re
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

import sympy as sp

from .. import engine, storage, units
from .plotwin import PlotWindow
from .widgets import (EquationEditor, InsertPalette, MathPreview, ResultsView, VariableGrid,
                      num_latex, pretty_name, unit_latex)

WELCOME = """# Type one equation per line. Text after # is a comment.
# Fill in known values on the right, leave the unknown blank, press Solve (Ctrl+Enter).
A = (b + z*y)*y              # flow area of a trapezoidal channel
P = b + 2*y*sqrt(1 + z^2)    # wetted perimeter
R = A/P                      # hydraulic radius
Q = 1.49/n*A*R^(2/3)*S^(1/2) # Manning's equation (US units)
"""
WELCOME_VALUES = {"Q": {"value": "100", "unit": "cfs"}, "b": {"value": "10", "unit": "ft"},
                  "z": {"value": "2"}, "n": {"value": "0.013"}, "S": {"value": "0.001"},
                  "y": {"unit": "ft"}}


class WorksheetTab(ttk.Frame):
    def __init__(self, master, app):
        super().__init__(master)
        self.app = app
        self.path: str | None = None
        self.modified = False
        self.parsed: list = []
        self.names: list[str] = []
        self.last: dict | None = None    # last solve: values (calc numbers), result object
        self.history: list[dict] = []
        self._busy = False
        self._cancel: threading.Event | None = None
        self._job = 0
        self.unit_system = tk.StringVar(value=app.settings["unit_system"])
        self._build()
        self.unit_system.trace_add("write", lambda *a: self._inputs_changed())

    # ------------------------------------------------------------------ UI
    def _build(self):
        app = self.app
        top = ttk.Frame(self, padding=(6, 4))
        top.pack(side="top", fill="x")
        InsertPalette(top, lambda: self.editor).pack(side="left")

        outer = ttk.PanedWindow(self, orient="horizontal")
        outer.pack(fill="both", expand=True, padx=6, pady=(0, 6))

        left = ttk.PanedWindow(outer, orient="vertical")
        ed_frame = ttk.LabelFrame(left, text=" Equations ", padding=2)
        self.editor = EquationEditor(ed_frame, font=app.editor_font, on_change=self._text_changed,
                                     on_cursor=self._cursor_moved)
        self.editor.pack(fill="both", expand=True)
        pv_frame = ttk.LabelFrame(left, text=" Preview  (check what you typed) ", padding=2)
        self.preview = MathPreview(pv_frame, on_click=self.editor.goto_line,
                                   size=app.settings["font_size"] + 3)
        self.preview.canvas.configure(height=260)
        self.editor.text.configure(height=14)
        self.preview.pack(fill="both", expand=True)
        left.add(ed_frame, weight=3)
        left.add(pv_frame, weight=2)

        right_outer = ttk.Frame(outer)
        opts = ttk.Frame(right_outer, padding=(2, 0, 2, 4))
        opts.pack(side="top", fill="x")
        ttk.Label(opts, text="Angles:").pack(side="left")
        for val, lab in (("deg", "Deg"), ("rad", "Rad")):
            ttk.Radiobutton(opts, text=lab, value=val, variable=app.angle_mode,
                            command=app.angle_changed).pack(side="left")
        ttk.Label(opts, text="     Unit system:").pack(side="left")
        cb = ttk.Combobox(opts, state="readonly", width=28,
                          values=[units.SYSTEMS[k] for k in units.SYSTEMS])
        cb.pack(side="left", padx=(4, 0))
        cb.bind("<<ComboboxSelected>>", lambda e: self.unit_system.set(
            [k for k, v in units.SYSTEMS.items() if v == cb.get()][0]))
        self.unit_system.trace_add("write", lambda *a: cb.set(units.SYSTEMS[self.unit_system.get()]))
        cb.set(units.SYSTEMS[self.unit_system.get()])

        right = ttk.PanedWindow(right_outer, orient="vertical")
        right.pack(fill="both", expand=True)
        var_frame = ttk.LabelFrame(right, text=" Variables ", padding=2)
        self.grid_ = VariableGrid(var_frame, font=app.grid_font, on_change=self._inputs_changed,
                                  on_enter=self.solve)
        self.grid_.canvas.configure(height=330)
        btns = ttk.Frame(var_frame, padding=(0, 4, 0, 0))
        self.solve_btn = ttk.Button(btns, text="▶ Solve", style="Accent.TButton", command=self.solve,
                                    width=9)
        self.solve_btn.pack(side="left")
        self.cancel_btn = ttk.Button(btns, text="Cancel", command=self.cancel)
        for label, cmd in (("Plot…", lambda: self._pick_var(self.plot, self.plot_btn, unknown_first=True)),
                           ("Rearrange…", lambda: self._pick_var(self.rearrange, self.rearr_btn)),
                           ("Simplify", lambda: self.transform("simplify")),
                           ("Expand", lambda: self.transform("expand")),
                           ("Factor", lambda: self.transform("factor")),
                           ("d/dx…", lambda: self._pick_var(self.derivative, self.diff_btn)),
                           ("∫ dx…", lambda: self._pick_var(self.integral, self.int_btn))):
            b = ttk.Button(btns, text=label, command=cmd, style="Tool.TButton", width=len(label) + 1)
            b.pack(side="left", padx=(3, 0))
            if label.startswith("Rearr"):
                self.rearr_btn = b
            elif label.startswith("d/dx"):
                self.diff_btn = b
            elif label.startswith("∫"):
                self.int_btn = b
            elif label.startswith("Plot"):
                self.plot_btn = b
        btns2 = ttk.Frame(var_frame)
        ttk.Button(btns2, text="Results → Values", command=self.results_to_values).pack(side="left")
        ttk.Button(btns2, text="Clear values", command=self.clear_values).pack(side="left", padx=4)
        ttk.Button(btns2, text="History…", command=self.show_history).pack(side="left")
        self.show_opts = tk.BooleanVar(value=True)
        ttk.Checkbutton(btns2, text="Guess / Min / Max", variable=self.show_opts,
                        command=lambda: self.grid_.toggle_solver_columns(self.show_opts.get())
                        ).pack(side="right")
        # Pack buttons at the bottom before the grid so they are never squeezed out.
        btns2.pack(side="bottom", fill="x", pady=(4, 0))
        btns.pack(side="bottom", fill="x")
        self.grid_.pack(side="top", fill="both", expand=True)

        res_frame = ttk.LabelFrame(right, text=" Results ", padding=2)
        self.results = ResultsView(res_frame, font_size=app.settings["font_size"] - 3)
        self.results.text.configure(height=8)
        self.results._math_size = app.settings["font_size"] + 2
        self.results.pack(fill="both", expand=True)
        right.add(var_frame, weight=3)
        right.add(res_frame, weight=2)

        outer.add(left, weight=1)
        outer.add(right_outer, weight=1)
        def place_sash(e):
            if e.width > 400:
                outer.sashpos(0, int(e.width * 0.47))
                outer.unbind("<Configure>", bind_id)

        bind_id = outer.bind("<Configure>", place_sash, add="+")

        for w in (self.editor.text,):
            w.bind("<Control-Return>", lambda e: (self.solve(), "break")[1])
        self.bind_all("<F5>", lambda e: self.solve() if self.winfo_ismapped() else None)

    def start(self):
        """Called by the app after the window is built: load the example."""
        self.load_data({"equations": WELCOME, "variables": WELCOME_VALUES,
                        "unit_system": "US"}, path=None)
        self.results.clear()
        self.results.heading("Welcome")
        self.results.write("This example finds the normal depth y of a trapezoidal channel.\n"
                           "Press ")
        self.results.write("▶ Solve", "good")
        self.results.write(" (or Ctrl+Enter / F5).\n\n"
                           "Start your own with File → New (Ctrl+N), or pick a formula from "
                           "Library (Ctrl+L). Help → Syntax (F1) lists everything you can type.\n",
                           "dim")

    # ----------------------------------------------------------- parsing
    def _text_changed(self):
        self._reparse()
        self._set_modified(True)
        self.grid_.mark_stale()

    def _reparse(self):
        text = self.editor.get()
        angle = self.app.angle_mode.get()
        self.parsed = engine.parse_lines(text, angle)
        errors = {}
        items = []
        order: list[tuple[int, int, str]] = []
        for ln, src, res in self.parsed:
            comment = src.split("#", 1)[1].strip() if "#" in src else None
            if res is None:
                if comment is not None:
                    items.append({"line": ln, "latex": None, "comment": comment, "source": src})
                continue
            if isinstance(res, engine.ParseError):
                errors[ln] = res.col
                items.append({"line": ln, "error": str(res), "source": src})
                continue
            try:
                tex = engine.display_latex(src)
            except engine.ParseError:
                tex = None
            items.append({"line": ln, "latex": tex, "comment": comment, "source": src})
            body = engine.normalize(engine.strip_comment(src))
            for s in res.symbols:
                m = re.search(r"(?<![\w.])" + re.escape(s.name) + r"(?!\w)", body)
                order.append((ln, m.start() if m else 9999, s.name))
        self.editor.mark_errors(errors)
        self.preview.show(items)
        names = []
        for _, _, n in sorted(order):
            if n not in names:
                names.append(n)
        self.names = names
        self.grid_.set_names(names)
        nerr = len(errors)
        neq = sum(1 for _, _, r in self.parsed if isinstance(r, engine.Equation))
        if nerr:
            self.app.status(f"{nerr} line(s) with errors - see the red marks", error=True)
        else:
            self.app.status(f"{neq} line(s), {len(names)} variable(s)")

    def _cursor_moved(self, line):
        self.preview.set_current(line)

    def _inputs_changed(self):
        self.grid_.mark_stale()
        self._set_modified(True)

    def _set_modified(self, value: bool):
        if self.modified != value:
            self.modified = value
            self.app.update_title()

    def refresh_settings(self):
        self.preview.size = self.app.settings["font_size"] + 3
        self.results._math_size = self.app.settings["font_size"] + 2
        self._reparse()

    # ------------------------------------------------------- collect input
    def _equations(self):
        self.editor.flush()
        bad = [(ln, r) for ln, _, r in self.parsed if isinstance(r, engine.ParseError)]
        if bad:
            ln, e = bad[0]
            self.editor.goto_line(ln)
            raise engine.SolveError(f"Line {ln}: {e}")
        return [r for _, _, r in self.parsed if isinstance(r, engine.Equation)]

    def _read(self, name: str, field: str, text: str, unit: str):
        angle = self.app.angle_mode.get()
        try:
            v = units.parse_value(text, unit, angle)
        except units.UnitError as e:
            raise engine.SolveError(f"{pretty_name(name)} {field}: {e}") from None
        if v is None:
            return None
        return units.to_calc(v, self.unit_system.get(), angle)

    def _specs(self) -> dict[str, engine.VarSpec]:
        specs = {}
        for name in self.names:
            st = self.grid_.row(name).state()
            unit = st["unit"].strip()
            if unit:
                try:
                    units.parse_unit(unit)
                except units.UnitError as e:
                    raise engine.SolveError(f"{pretty_name(name)}: {e}") from None
            value = self._read(name, "value", st["value"], unit)
            spec = engine.VarSpec(name)
            spec.guess = self._read(name, "guess", st["guess"], unit)
            spec.lo = self._read(name, "min", st["min"], unit)
            spec.hi = self._read(name, "max", st["max"], unit)
            if st["solve"]:
                if spec.guess is None:
                    spec.guess = value
            else:
                spec.value = value
            specs[name] = spec
        return specs

    def _known_values(self) -> dict[str, float]:
        out = {}
        for name, spec in self._specs().items():
            if spec.value is not None:
                out[name] = spec.value
        return out

    # ------------------------------------------------------- async runner
    def _run(self, label: str, fn, on_done):
        """Run fn(cancel_event) on a worker thread, then on_done(result) on the Tk thread."""
        if self._busy:
            return
        self._busy = True
        self._cancel = threading.Event()
        self.solve_btn.configure(state="disabled")
        self.cancel_btn.pack(side="left", padx=(4, 0), after=self.solve_btn)
        self.app.status(label + "…")
        self.configure(cursor="watch")
        cancel = self._cancel
        self._job += 1
        job = self._job
        results: queue.Queue = queue.Queue()
        # Free unreachable Tk objects (images) here on the Tk thread, so the garbage
        # collector doesn't end up deleting them from the worker thread.
        gc.collect()

        def work():
            try:
                results.put(("ok", fn(cancel), cancel))
            except Exception as e:  # reported to the user
                results.put(("err", e, cancel))

        threading.Thread(target=work, daemon=True).start()
        self.after(40, lambda: self._poll(job, results, on_done))

    def _poll(self, job, results, on_done):
        if job != self._job:
            return  # cancelled or superseded: drop it without touching the UI
        try:
            kind, payload, cancel = results.get_nowait()
        except queue.Empty:
            self.after(40, lambda: self._poll(job, results, on_done))
            return
        self._busy = False
        self.solve_btn.configure(state="normal")
        self.cancel_btn.pack_forget()
        self.configure(cursor="")
        if cancel.is_set():
            self.app.status("Cancelled")
            return
        if kind == "err":
            self._show_error(payload)
        else:
            try:
                on_done(payload)
            except Exception as e:
                self._show_error(e)

    def cancel(self):
        if self._cancel is not None:
            self._cancel.set()
        self._job += 1
        self._busy = False
        self.solve_btn.configure(state="normal")
        self.cancel_btn.pack_forget()
        self.configure(cursor="")
        self.app.status("Cancelled")

    def _show_error(self, e: Exception):
        msg = str(e) or type(e).__name__
        if isinstance(e, TimeoutError):
            msg = "That took too long and was stopped."
        elif not isinstance(e, (engine.SolveError, engine.ParseError, units.UnitError)):
            msg = f"{type(e).__name__}: {msg}"
        self.results.error(msg)
        self.app.status(msg, error=True)

    # ------------------------------------------------------------- solve
    def solve(self):
        if self._busy:
            return
        try:
            eqs = self._equations()
            if not eqs:
                raise engine.SolveError("Type an equation first, e.g.  Q = V*A")
            specs = self._specs()
        except (engine.SolveError, units.UnitError) as e:
            self._show_error(e)
            return
        ctx = self._context()

        def fn(cancel):
            return engine.solve_equations(eqs, specs, cancel=cancel)

        self._run("Solving", fn, lambda res: self._show_solution(res, ctx))

    def _context(self) -> dict:
        """Unit system, angle mode and unit columns in effect for a solve."""
        return {"system": self.unit_system.get(), "angle": self.app.angle_mode.get(),
                "units": {n: self.grid_.row(n).unit.get().strip() for n in self.names}}

    def _fmt_result(self, name: str, value: float, ctx: dict | None = None) -> tuple[str, str, str]:
        """(display text, number text, unit text) for a solved value, in the unit the solve used."""
        ctx = ctx or (self.last or {}).get("ctx") or self._context()
        unit = ctx["units"].get(name, "")
        q = units.from_calc(value, unit, ctx["system"], ctx["angle"])
        if isinstance(q, units.Q_):
            num = self.app.fmt(q.magnitude)
            u = units.format_unit(q.units)
            return f"{num} {u}", num, u
        num = self.app.fmt(q)
        return num, num, ""

    def _show_solution(self, res: engine.SolveResult, ctx: dict):
        self.grid_.clear_results()
        r = self.results
        r.clear()
        self.last = {"values": dict(res.values), "result": res, "ctx": ctx}
        ordered = [n for n in self.names if n in res.values]
        if ordered:
            r.heading("Solution")
        for name in ordered:
            text, num, u = self._fmt_result(name, res.values[name])
            self.grid_.set_result(name, text)
            r.math(engine.to_latex(sp.Symbol(name)) + " = " + num_latex(num) + unit_latex(u),
                   f"{name} = {text}", size=r._math_size + 2)
            r.write("   ")
            r.button("Copy", lambda t=text.split(" ")[0]: self._copy(t))
            r.write("\n")
            alts = res.alternates.get(name)
            if alts:
                r.write(f"    Other solutions for {pretty_name(name)}: ", "warn")
                for a in alts[:8]:
                    at, an, au = self._fmt_result(name, a)
                    r.write(at, "warn")
                    r.button("Use", lambda nm=name, v=an: self._use_alternate(nm, v))
                    r.write("  ")
                r.write("\n    (the answer closest to Guess is shown; without a Guess the smallest "
                        "positive one)\n", "dim")
        if not ordered and not res.expressions:
            r.heading("Check")
            r.write("Every variable has a value - nothing to solve. "
                    "Clear a value (or tick Solve) to make it the unknown.\n", "dim")

        if res.expressions:
            r.heading("Values")
            for ln, text, v in res.expressions:
                try:
                    tex = engine.display_latex(text)
                except engine.ParseError:
                    tex = None
                num = self.app.fmt(v)
                if tex:
                    r.math(tex + " = " + num_latex(num), f"{text} = {num}")
                else:
                    r.write(f"{text} = {num}")
                r.write(f"   (line {ln})\n", "dim")

        if res.formulas:
            r.heading("Exact formula")
            for f in res.formulas:
                if ctx["angle"] == "deg":
                    f = engine.to_degree_form(f)
                r.math(engine.to_latex(f), engine.to_input_text(f))
                r.button("Insert", lambda f=f: self.editor.append(engine.to_input_text(f)))
                r.write("\n")

        bad = [c for c in res.checks if not c[3]]
        if res.checks:
            if bad:
                r.heading("Check")
                for ln, a, b, ok in bad:
                    r.write(f"⚠ Line {ln} does not balance: left = {self.app.fmt(a)}, "
                            f"right = {self.app.fmt(b)}\n", "warn")
                r.write("Too many values may have been given (the problem is over-specified).\n", "dim")
            else:
                r.write("\n✓ All equations balance with these values.\n", "good")

        units_used = any(self.grid_.row(n).unit.get().strip() or
                         re.search(r"[A-Za-z'\"]", self.grid_.row(n).value.get() or "")
                         for n in self.names)
        if units_used:
            sysname = units.SYSTEMS[self.unit_system.get()]
            r.write(f"Units: values were converted to {sysname} before solving.\n", "dim")
        if res.steps:
            r.write("How it was solved: " + "; ".join(res.steps) + ".\n", "dim")
        if self.app.settings.get("show_iterations") and res.iteration_log:
            r.heading("Iterations (last 1-D solve)")
            r.write(f"{'#':>4}  {'x':>22}  {'f(x)':>22}\n", "mono")
            for i, x, fx in res.iteration_log[:60]:
                r.write(f"{i:>4}  {x:>22.15g}  {fx:>22.6g}\n", "mono")
        r.see_top()
        self.app.status("Solved" if ordered else "Done")
        self._add_history(res)

    def _copy(self, text: str):
        self.clipboard_clear()
        self.clipboard_append(text)
        self.app.status(f"Copied {text}")

    def _use_alternate(self, name: str, value_text: str):
        row = self.grid_.row(name)
        row.guess.set(value_text)
        if not self.show_opts.get():
            self.show_opts.set(True)
            self.grid_.toggle_solver_columns(True)
        self.solve()

    def results_to_values(self):
        if not self.last:
            self.app.status("Solve first", error=True)
            return
        ctx = self.last["ctx"]
        if ctx["system"] != self.unit_system.get() or ctx["angle"] != self.app.angle_mode.get() \
                or any(ctx["units"].get(n, "") != self.grid_.row(n).unit.get().strip()
                       for n in self.last["values"] if n in self.grid_.rows):
            self._show_error(engine.SolveError("Units or angle mode changed since the last solve - "
                                               "press Solve again first."))
            return
        for name, v in self.last["values"].items():
            if name not in self.grid_.rows:
                continue
            row = self.grid_.row(name)
            _, num, _ = self._fmt_result(name, v)
            row.value.set(num)
            row.solve.set(False)
        self.app.status("Results copied into the Value column")

    def clear_values(self):
        if not messagebox.askyesno("Clear values", "Clear all values, guesses and limits?",
                                   parent=self):
            return
        for name in self.grid_.order:
            row = self.grid_.row(name)
            for v in (row.value, row.guess, row.lo, row.hi):
                v.set("")
            row.solve.set(False)
        self.grid_.clear_results()

    # ---------------------------------------------------------- history
    def _add_history(self, res):
        summary = ", ".join(f"{n} = {self._fmt_result(n, v)[0]}" for n, v in res.values.items())
        self.history.insert(0, {
            "time": _dt.datetime.now().strftime("%H:%M:%S"),
            "summary": summary or "(check only)",
            "data": self.get_data(),
        })
        del self.history[50:]

    def show_history(self):
        win = tk.Toplevel(self)
        win.title("Solve history (this session)")
        win.geometry("760x360")
        win.transient(self.winfo_toplevel())
        tv = ttk.Treeview(win, columns=("time", "result"), show="headings")
        tv.heading("time", text="Time")
        tv.heading("result", text="Results")
        tv.column("time", width=80, stretch=False)
        tv.column("result", width=640)
        for i, h in enumerate(self.history):
            tv.insert("", "end", iid=str(i), values=(h["time"], h["summary"]))
        tv.pack(fill="both", expand=True, padx=6, pady=6)
        bar = ttk.Frame(win, padding=6)
        bar.pack(fill="x")

        def restore():
            sel = tv.selection()
            if not sel:
                return
            h = self.history[int(sel[0])]
            self.load_data(h["data"], path=self.path, keep_modified=True)
            win.destroy()

        ttk.Button(bar, text="Restore worksheet", command=restore).pack(side="left")
        ttk.Button(bar, text="Close", command=win.destroy).pack(side="right")
        tv.bind("<Double-1>", lambda e: restore())
        if not self.history:
            ttk.Label(bar, text="Nothing solved yet.").pack(side="left", padx=10)

    # ------------------------------------------------- symbolic operations
    def _current_equation(self) -> tuple[int, engine.Equation]:
        self.editor.flush()
        line = self.editor.current_line()
        for ln, _, r in self.parsed:
            if ln == line:
                if isinstance(r, engine.ParseError):
                    raise engine.SolveError(f"Line {ln}: {r}")
                if r is None:
                    break
                return ln, r
        raise engine.SolveError("Click on an equation line in the editor first")

    def _pick_var(self, action, button, unknown_first=False):
        try:
            ln, eq = self._current_equation()
        except engine.SolveError as e:
            self._show_error(e)
            return
        names = [n for n in self.names if sp.Symbol(n) in eq.symbols]
        if not names:
            self._show_error(engine.SolveError("This line has no variables"))
            return
        if len(names) == 1:
            action(ln, eq, names[0])
            return
        if unknown_first:
            unknown = [n for n in names if not self.grid_.row(n).value.get().strip()
                       or self.grid_.row(n).solve.get()]
            if len(unknown) == 1:
                action(ln, eq, unknown[0])
                return
        menu = tk.Menu(self, tearoff=False)
        for n in names:
            menu.add_command(label=pretty_name(n), command=lambda n=n: action(ln, eq, n))
        menu.tk_popup(button.winfo_rootx(), button.winfo_rooty() + button.winfo_height())

    def _show_symbolic(self, title: str, ln: int, exprs: list, replace_ok=True):
        if self.app.angle_mode.get() == "deg":
            # Results are in radian form internally; convert so re-parsing in Deg mode matches.
            exprs = [engine.to_degree_form(e) for e in exprs]
        r = self.results
        r.clear()
        r.heading(title)
        for e in exprs:
            r.math(engine.to_latex(e), engine.to_input_text(e), size=r._math_size + 1)
            r.write("\n")
            txt = engine.to_input_text(e)
            r.button("Insert below", lambda t=txt: self.editor.insert_line_after(ln, t))
            if replace_ok:
                r.button("Replace line", lambda t=txt: self.editor.replace_line(ln, t))
            r.button("Copy", lambda t=txt: self._copy(t))
            r.write("\n")
        r.write(f"\n(from line {ln})\n", "dim")
        self.app.status(title)

    def rearrange(self, ln, eq, var):
        if not eq.is_equation:
            self._show_error(engine.SolveError("Rearrange needs an equation (with '=')"))
            return
        self._run(f"Rearranging for {var}", lambda _c: engine.rearrange(eq, var),
                  lambda sols: self._show_symbolic(f"Rearranged for {pretty_name(var)}", ln, sols))

    def transform(self, how):
        try:
            ln, eq = self._current_equation()
        except engine.SolveError as e:
            self._show_error(e)
            return
        self._run(how.capitalize(), lambda _c: engine.transform(eq, how),
                  lambda out: self._show_symbolic(how.capitalize(), ln, [out]))

    def derivative(self, ln, eq, var):
        self._run("Differentiating", lambda _c: engine.derivative(eq, var),
                  lambda out: self._show_symbolic(f"Derivative with respect to {pretty_name(var)}",
                                                  ln, [out], replace_ok=False))

    def integral(self, ln, eq, var):
        lims = simpledialog.askstring(
            "Integrate", f"Limits for {var}, e.g.  0, 10\n(leave blank for the indefinite integral)",
            parent=self)
        if lims is None:
            return
        a = b = None
        if lims.strip():
            parts = [p for p in re.split(r"[,;]|\s+to\s+", lims) if p.strip()]
            if len(parts) != 2:
                self._show_error(engine.SolveError("Enter two limits separated by a comma"))
                return
            try:
                a = sp.nsimplify(engine.evaluate_constant(parts[0], self.app.angle_mode.get()))
                b = sp.nsimplify(engine.evaluate_constant(parts[1], self.app.angle_mode.get()))
            except Exception as e:
                self._show_error(engine.SolveError(f"Bad limit: {e}"))
                return

        def fn(_cancel):
            return [engine.integral(eq, var, a, b)]

        def done(out):
            v = out[0]
            if a is not None and not v.free_symbols:
                r = self.results
                r.clear()
                r.heading(f"Definite integral over {pretty_name(var)} from {a} to {b}")
                tex = engine.to_latex(v)
                num = self.app.fmt(float(sp.N(v)))
                r.math(tex + (" = " + num_latex(num) if tex != num else ""), num, size=r._math_size + 1)
                r.write("   ")
                r.button("Copy", lambda: self._copy(num))
                r.write("\n")
                self.app.status("Integrated")
            else:
                self._show_symbolic(f"Integral with respect to {pretty_name(var)}  (+ C)", ln, out,
                                    replace_ok=False)

        self._run("Integrating", fn, done)

    def plot(self, ln, eq, var):
        try:
            values = self._known_values()
        except engine.SolveError as e:
            self._show_error(e)
            return
        values.pop(var, None)
        fallback = dict(self.last["values"]) if self.last and \
            self.last["ctx"]["system"] == self.unit_system.get() and \
            self.last["ctx"]["angle"] == self.app.angle_mode.get() else {}
        try:
            lhs, rhs, sym = engine.single_variable_view(self._equations(), ln, values, var, fallback)
            spec = self._specs().get(var)
        except (engine.SolveError, units.UnitError) as e:
            self._show_error(e)
            return
        center = None
        if self.last and var in self.last["values"]:
            center = self.last["values"][var]
        elif spec and spec.guess is not None:
            center = spec.guess
        if spec and spec.lo is not None and spec.hi is not None:
            lo, hi = spec.lo, spec.hi
        elif center is not None:
            span = max(abs(center), 1.0) * 2
            lo, hi = center - span, center + span
            if spec and spec.lo is not None:
                lo = spec.lo
            if spec and spec.hi is not None:
                hi = spec.hi
        else:
            lo = spec.lo if spec and spec.lo is not None else -10.0
            hi = spec.hi if spec and spec.hi is not None else 10.0
        PlotWindow(self.winfo_toplevel(), lhs, rhs, sym, lo, hi,
                   title=f"Line {ln}:  {eq.text}", fmt=self.app.fmt, mark=center)

    # ------------------------------------------------------- files
    def get_data(self) -> dict:
        return {"equations": self.editor.get(), "variables": self.grid_.state(),
                "unit_system": self.unit_system.get(), "angle_mode": self.app.angle_mode.get()}

    def load_data(self, data: dict, path: str | None, keep_modified=False):
        if data.get("angle_mode") in ("deg", "rad"):
            self.app.angle_mode.set(data["angle_mode"])
        if data.get("unit_system") in units.SYSTEMS:
            self.unit_system.set(data["unit_system"])
        self.grid_.load_state(data.get("variables", {}))
        self.editor.set(data.get("equations", ""))
        self.grid_.clear_results()
        self.last = None
        self.path = path
        self._set_modified(keep_modified)
        self.app.update_title()

    def confirm_discard(self) -> bool:
        if not self.modified:
            return True
        ans = messagebox.askyesnocancel("Unsaved changes", "Save changes to this worksheet first?",
                                        parent=self)
        if ans is None:
            return False
        if ans:
            return self.save()
        return True

    def new(self):
        if not self.confirm_discard():
            return
        for row in self.grid_.rows.values():
            row.load({})
        self.load_data({"equations": "", "variables": {}}, path=None)
        self.results.clear()
        self.editor.text.focus_set()

    def open(self, path: str | None = None):
        if not self.confirm_discard():
            return
        if path is None:
            path = filedialog.askopenfilename(
                parent=self, title="Open worksheet",
                filetypes=[("Calculator worksheets", "*" + storage.WORKSHEET_EXT), ("All files", "*.*")])
            if not path:
                return
        try:
            data = storage.load_worksheet(path)
        except Exception as e:
            messagebox.showerror("Open", f"Could not open {path}:\n{e}", parent=self)
            return
        for row in self.grid_.rows.values():
            row.load({})
        self.load_data(data, path)
        self.results.clear()
        storage.add_recent(self.app.settings, path)
        self.app.save_settings()
        self.app.rebuild_recent_menu()
        self.app.status(f"Opened {os.path.basename(path)}")

    def save(self) -> bool:
        if not self.path:
            return self.save_as()
        try:
            storage.save_worksheet(self.path, self.get_data())
        except OSError as e:
            messagebox.showerror("Save", f"Could not save:\n{e}", parent=self)
            return False
        self._set_modified(False)
        storage.add_recent(self.app.settings, self.path)
        self.app.save_settings()
        self.app.rebuild_recent_menu()
        self.app.status(f"Saved {os.path.basename(self.path)}")
        return True

    def save_as(self) -> bool:
        path = filedialog.asksaveasfilename(
            parent=self, title="Save worksheet", defaultextension=storage.WORKSHEET_EXT,
            filetypes=[("Calculator worksheets", "*" + storage.WORKSHEET_EXT), ("All files", "*.*")])
        if not path:
            return False
        self.path = path
        return self.save()
