"""Reusable Tk widgets: equation editor, math preview, insert palette, variable grid, results."""
from __future__ import annotations

import re
import tkinter as tk
from tkinter import ttk

from .. import render

GREEK = [("α", "alpha"), ("β", "beta"), ("γ", "gamma"), ("δ", "delta"), ("ε", "epsilon"),
         ("ζ", "zeta"), ("η", "eta"), ("θ", "theta"), ("κ", "kappa"), ("λ", "lambda"),
         ("μ", "mu"), ("ν", "nu"), ("ξ", "xi"), ("ρ", "rho"), ("σ", "sigma"), ("τ", "tau"),
         ("υ", "upsilon"), ("φ", "phi"), ("χ", "chi"), ("ψ", "psi"), ("ω", "omega"),
         ("Γ", "Gamma"), ("Δ", "Delta"), ("Θ", "Theta"), ("Λ", "Lambda"), ("Σ", "Sigma"),
         ("Φ", "Phi"), ("Ψ", "Psi"), ("Ω", "Omega")]
GREEK_CHAR = {name: ch for ch, name in GREEK}

COMMON_UNITS = ["ft", "in", "yd", "mi", "m", "mm", "cm", "km",
                "ft^2", "in^2", "acre", "m^2", "ft^3", "yd^3", "gal", "m^3", "L",
                "cfs", "gpm", "mgd", "m^3/s", "L/s", "ft/s", "m/s",
                "lbf", "kip", "N", "kN", "psi", "ksi", "psf", "ksf", "Pa", "kPa", "MPa",
                "kip*ft", "lbf*ft", "kN*m", "klf", "plf", "kN/m", "pcf", "kN/m^3",
                "in^4", "ft^4", "mm^4", "deg", "rad", "percent", "s", "min", "hr", "day",
                "degF", "degC", "lb", "kg", "slug"]

# label, template ("|" marks where the cursor goes / where a selection is wrapped), tooltip
PALETTE = [
    ("( )", "(|)", "Parentheses (wraps the selection)"),
    ("x²", "^2|", "Square"),
    ("xʸ", "^(|)", "Power"),
    ("√", "sqrt(|)", "Square root"),
    ("∛", "cbrt(|)", "Cube root"),
    ("ⁿ√", "root(|, n)", "n-th root: root(x, n)"),
    ("a⁄b", "(|)/()", "Fraction"),
    ("π", "pi|", "Pi"),
    ("eˣ", "exp(|)", "e to the power"),
    ("ln", "ln(|)", "Natural log"),
    ("log", "log(|)", "Log base 10;  log(x, b) for base b"),
    ("|x|", "abs(|)", "Absolute value"),
    ("=", " = |", "Equals"),
    ("sin", "sin(|)", "Sine"),
    ("cos", "cos(|)", "Cosine"),
    ("tan", "tan(|)", "Tangent"),
    ("asin", "asin(|)", "Inverse sine"),
    ("acos", "acos(|)", "Inverse cosine"),
    ("atan", "atan(|)", "Inverse tangent"),
    ("min", "min(|, )", "Smaller of two values"),
    ("max", "max(|, )", "Larger of two values"),
    ("#", "  # |", "Comment (ignored by the solver)"),
]


def pretty_name(name: str) -> str:
    """theta -> θ, sigma_max -> σ_max (for labels only)."""
    head, sep, tail = name.partition("_")
    return GREEK_CHAR.get(head, head) + sep + tail


class Tooltip:
    def __init__(self, widget, text: str):
        self.widget, self.text, self.tip = widget, text, None
        widget.bind("<Enter>", self._show, add="+")
        widget.bind("<Leave>", self._hide, add="+")

    def _show(self, _e=None):
        if self.tip or not self.text:
            return
        x = self.widget.winfo_rootx() + 10
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4
        self.tip = tk.Toplevel(self.widget)
        self.tip.wm_overrideredirect(True)
        self.tip.wm_geometry(f"+{x}+{y}")
        tk.Label(self.tip, text=self.text, bg="#ffffe0", relief="solid", borderwidth=1,
                 padx=6, pady=2).pack()

    def _hide(self, _e=None):
        if self.tip:
            self.tip.destroy()
            self.tip = None


# ---------------------------------------------------------------------------
# Equation editor
# ---------------------------------------------------------------------------

class EquationEditor(ttk.Frame):
    """Multi-line text editor with line numbers, error marks and bracket matching."""

    def __init__(self, master, font, on_change=None, on_cursor=None, **kw):
        super().__init__(master, **kw)
        self.on_change = on_change
        self.on_cursor = on_cursor
        self._after = None
        self._errors: dict[int, int | None] = {}
        self.gutter = tk.Canvas(self, width=40, bg="#f0f0f0", highlightthickness=0)
        self.text = tk.Text(self, wrap="none", undo=True, maxundo=-1, autoseparators=True,
                            font=font, padx=8, pady=6, relief="flat", borderwidth=0,
                            insertwidth=2, selectbackground="#b5d5ff", selectforeground="black",
                            background="white", foreground="#111")
        vsb = ttk.Scrollbar(self, orient="vertical", command=self._yview)
        hsb = ttk.Scrollbar(self, orient="horizontal", command=self.text.xview)
        self.text.configure(yscrollcommand=lambda a, b: (vsb.set(a, b), self._redraw_gutter()),
                            xscrollcommand=hsb.set)
        self.gutter.grid(row=0, column=0, sticky="ns")
        self.text.grid(row=0, column=1, sticky="nsew")
        vsb.grid(row=0, column=2, sticky="ns")
        hsb.grid(row=1, column=1, sticky="ew")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(1, weight=1)

        t = self.text
        t.tag_configure("curline", background="#f4f8ff")
        t.tag_configure("comment", foreground="#3a7d44")
        t.tag_configure("errline", background="#fff0f0")
        t.tag_configure("errchar", background="#ff9a9a", underline=True)
        t.tag_configure("match", background="#ffe58a")
        t.tag_raise("sel")
        t.bind("<<Modified>>", self._modified)
        for ev in ("<KeyRelease>", "<ButtonRelease-1>", "<FocusIn>"):
            t.bind(ev, self._cursor_moved, add="+")
        t.bind("<Configure>", lambda e: self._redraw_gutter())
        t.bind("(", self._paren_wrap)
        t.bind("<Control-a>", self._select_all)
        t.bind("<Tab>", self._tab)

    # -- basic API --------------------------------------------------------
    def get(self) -> str:
        return self.text.get("1.0", "end-1c")

    def set(self, value: str) -> None:
        self.text.delete("1.0", "end")
        self.text.insert("1.0", value)
        self.text.edit_reset()
        # A programmatic load is not a user edit: clear Tk's flag so <<Modified>> is ignored.
        self.text.edit_modified(False)
        self.text.mark_set("insert", "1.0")
        self._fire()

    def current_line(self) -> int:
        return int(self.text.index("insert").split(".")[0])

    def line_text(self, line: int) -> str:
        return self.text.get(f"{line}.0", f"{line}.end")

    def replace_line(self, line: int, value: str) -> None:
        self.text.edit_separator()
        self.text.delete(f"{line}.0", f"{line}.end")
        self.text.insert(f"{line}.0", value)
        self.text.edit_separator()

    def insert_line_after(self, line: int, value: str) -> None:
        self.text.edit_separator()
        self.text.insert(f"{line}.end", "\n" + value)
        self.text.mark_set("insert", f"{line + 1}.end")
        self.text.edit_separator()
        self.text.focus_set()

    def append(self, value: str) -> None:
        cur = self.get()
        sep = "" if not cur or cur.endswith("\n") else "\n"
        self.text.insert("end", sep + value)
        self.text.see("end")

    def goto_line(self, line: int) -> None:
        self.text.mark_set("insert", f"{line}.end")
        self.text.see("insert")
        self.text.focus_set()
        self._cursor_moved()

    def insert_template(self, template: str) -> None:
        before, _, after = template.partition("|")
        t = self.text
        t.edit_separator()
        if t.tag_ranges("sel") and after:
            sel = t.get("sel.first", "sel.last")
            t.delete("sel.first", "sel.last")
            t.insert("insert", before + sel + after)
        else:
            if t.tag_ranges("sel"):
                t.delete("sel.first", "sel.last")
            t.insert("insert", before + after)
            t.mark_set("insert", f"insert-{len(after)}c")
        t.edit_separator()
        t.focus_set()
        self._cursor_moved()

    def mark_errors(self, errors: dict[int, int | None]) -> None:
        self._errors = errors
        t = self.text
        t.tag_remove("errline", "1.0", "end")
        t.tag_remove("errchar", "1.0", "end")
        for line, col in errors.items():
            t.tag_add("errline", f"{line}.0", f"{line}.end+1c")
            if col is not None:
                t.tag_add("errchar", f"{line}.{col}", f"{line}.{col + 1}")
        self._redraw_gutter()

    # -- internals --------------------------------------------------------
    def _yview(self, *args):
        self.text.yview(*args)
        self._redraw_gutter()

    def _select_all(self, _e=None):
        self.text.tag_add("sel", "1.0", "end-1c")
        return "break"

    def _tab(self, _e=None):
        self.text.tk_focusNext().focus_set()
        return "break"

    def _paren_wrap(self, _e=None):
        if self.text.tag_ranges("sel"):
            self.insert_template("(|)")
            return "break"
        return None

    def _modified(self, _e=None):
        if not self.text.edit_modified():
            return
        self.text.edit_modified(False)
        if self._after:
            self.after_cancel(self._after)
        self._after = self.after(250, self._fire)
        self._highlight_comments()
        self._redraw_gutter()

    def _fire(self):
        self._after = None
        self._highlight_comments()
        self._redraw_gutter()
        if self.on_change:
            self.on_change()

    def flush(self) -> None:
        """Run a pending change notification right away."""
        if self._after:
            self.after_cancel(self._after)
            self._fire()

    def _highlight_comments(self):
        t = self.text
        t.tag_remove("comment", "1.0", "end")
        for i, line in enumerate(self.get().split("\n"), start=1):
            k = line.find("#")
            if k >= 0:
                t.tag_add("comment", f"{i}.{k}", f"{i}.end")

    def _cursor_moved(self, _e=None):
        t = self.text
        t.tag_remove("curline", "1.0", "end")
        t.tag_add("curline", "insert linestart", "insert lineend+1c")
        t.tag_lower("curline")
        self._match_brackets()
        if self.on_cursor:
            self.on_cursor(self.current_line())

    def _match_brackets(self):
        t = self.text
        t.tag_remove("match", "1.0", "end")
        line, col = map(int, t.index("insert").split("."))
        s = self.line_text(line)
        for pos in (col - 1, col):
            if 0 <= pos < len(s) and s[pos] in "()":
                other = _matching(s, pos)
                if other is not None:
                    t.tag_add("match", f"{line}.{pos}", f"{line}.{pos + 1}")
                    t.tag_add("match", f"{line}.{other}", f"{line}.{other + 1}")
                return

    def _redraw_gutter(self):
        c = self.gutter
        c.delete("all")
        i = self.text.index("@0,0")
        width = int(c.winfo_width()) or 40
        while True:
            info = self.text.dlineinfo(i)
            if info is None:
                break
            n = int(i.split(".")[0])
            color = "#d32f2f" if n in self._errors else "#999999"
            c.create_text(width - 6, info[1] + 2, anchor="ne", text=str(n), fill=color,
                          font=("Segoe UI", 9, "bold" if n in self._errors else "normal"))
            nxt = self.text.index(f"{i}+1line")
            if nxt == i:
                break
            i = nxt


def _matching(s: str, pos: int) -> int | None:
    step, open_, close = (1, "(", ")") if s[pos] == "(" else (-1, ")", "(")
    depth = 0
    i = pos
    while 0 <= i < len(s):
        if s[i] == open_:
            depth += 1
        elif s[i] == close:
            depth -= 1
            if depth == 0:
                return i
        i += step
    return None


# ---------------------------------------------------------------------------
# Palette
# ---------------------------------------------------------------------------

class InsertPalette(ttk.Frame):
    def __init__(self, master, editor_getter, **kw):
        super().__init__(master, **kw)
        self.editor_getter = editor_getter
        for i, (label, tpl, tip) in enumerate(PALETTE):
            b = ttk.Button(self, text=label, width=max(3, len(label) + 1), style="Palette.TButton",
                           command=lambda t=tpl: self._insert(t), takefocus=False)
            b.grid(row=0, column=i, padx=1, pady=1)
            Tooltip(b, f"{tip}   →  {tpl.replace('|', '')}")
        mb = ttk.Menubutton(self, text="αβγ", width=5, style="Palette.TMenubutton")
        menu = tk.Menu(mb, tearoff=False)
        for k, (ch, name) in enumerate(GREEK):
            menu.add_command(label=f"{ch}   {name}", command=lambda n=name: self._insert(n + "|"),
                             columnbreak=(k > 0 and k % 10 == 0))
        mb["menu"] = menu
        mb.grid(row=0, column=len(PALETTE), padx=1)
        Tooltip(mb, "Greek letters (typed as names, e.g. theta)")

    def _insert(self, tpl):
        ed = self.editor_getter()
        if ed is not None:
            ed.insert_template(tpl)


# ---------------------------------------------------------------------------
# Scrollable frame
# ---------------------------------------------------------------------------

class ScrollFrame(ttk.Frame):
    def __init__(self, master, bg="white", horizontal=False, **kw):
        super().__init__(master, **kw)
        self.canvas = tk.Canvas(self, highlightthickness=0, background=bg)
        self.vsb = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = tk.Frame(self.canvas, background=bg)
        self._win = self.canvas.create_window(0, 0, window=self.inner, anchor="nw")
        self.canvas.configure(yscrollcommand=self.vsb.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.vsb.grid(row=0, column=1, sticky="ns")
        if horizontal:
            self.hsb = ttk.Scrollbar(self, orient="horizontal", command=self.canvas.xview)
            self.canvas.configure(xscrollcommand=self.hsb.set)
            self.hsb.grid(row=1, column=0, sticky="ew")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        self.inner.bind("<Configure>", lambda e: self._fit())
        self.canvas.bind("<Configure>", lambda e: self._fit())

    def _fit(self):
        # Fill the visible width, but never squeeze the content below its natural width.
        width = max(self.canvas.winfo_width(), self.inner.winfo_reqwidth())
        self.canvas.itemconfigure(self._win, width=width)
        self.canvas.configure(scrollregion=(0, 0, width, self.inner.winfo_reqheight()))
        for w in (self.canvas, self.inner):
            w.bind("<Enter>", lambda e: self._bind_wheel(True))
            w.bind("<Leave>", lambda e: self._bind_wheel(False))

    def _bind_wheel(self, on: bool):
        if on:
            self.canvas.bind_all("<MouseWheel>", self._wheel)
        else:
            self.canvas.unbind_all("<MouseWheel>")

    def _wheel(self, e):
        if self.canvas.yview() != (0.0, 1.0):
            self.canvas.yview_scroll(int(-e.delta / 120), "units")

    def see_widget(self, w):
        self.update_idletasks()
        top = w.winfo_y()
        h = max(1, self.inner.winfo_height())
        vis0, vis1 = self.canvas.yview()
        if not (vis0 * h <= top <= vis1 * h - w.winfo_height()):
            self.canvas.yview_moveto(max(0.0, (top - 20) / h))


# ---------------------------------------------------------------------------
# Math preview
# ---------------------------------------------------------------------------

class MathPreview(ScrollFrame):
    """Shows each editor line typeset as math, so long equations can be checked at a glance."""

    def __init__(self, master, on_click=None, size=16, **kw):
        super().__init__(master, **kw)
        self.on_click = on_click
        self.size = size
        self.rows: list[tuple] = []
        self.current = None
        self.inner.columnconfigure(1, weight=1)

    def show(self, items: list[dict]) -> None:
        """items: dicts with line, latex|None, error|None, comment|None, source."""
        while len(self.rows) < len(items):
            num = tk.Label(self.inner, anchor="ne", fg="#999", bg="white", font=("Segoe UI", 9),
                           width=4)
            body = tk.Label(self.inner, anchor="w", justify="left", bg="white", padx=6, pady=4)
            r = len(self.rows)
            num.grid(row=r, column=0, sticky="ne", pady=(6, 0))
            body.grid(row=r, column=1, sticky="ew")
            for w in (num, body):
                w.bind("<Button-1>", lambda e, k=r: self._clicked(k))
            self.rows.append((num, body, {}))
        for k, (num, body, meta) in enumerate(self.rows):
            if k >= len(items):
                num.grid_remove()
                body.grid_remove()
                continue
            num.grid()
            body.grid()
            it = items[k]
            meta.clear()
            meta.update(it)
            num.configure(text=str(it["line"]))
            img = None
            if it.get("error"):
                body.configure(image="", text=f"⚠ {it['error']}\n    {it['source'].strip()}",
                               fg="#c62828", font=("Segoe UI", 10))
            elif it.get("latex") is not None:
                img = render.photo_image(it["latex"], self.size)
                if img is None:
                    body.configure(image="", text=it["source"].strip(), fg="#222",
                                   font=("Consolas", 11))
                else:
                    body.configure(image=img, text="")
                if it.get("comment"):
                    body.configure(compound="left", text="    " + it["comment"], fg="#3a7d44",
                                   font=("Segoe UI", 10, "italic"))
                else:
                    body.configure(compound="none")
            else:
                body.configure(image="", text=it.get("comment", ""), fg="#3a7d44",
                               font=("Segoe UI", 10, "italic"), compound="none")
            body.image = img
        self._highlight()

    def set_current(self, line: int | None) -> None:
        self.current = line
        self._highlight()

    def _highlight(self):
        for num, body, meta in self.rows:
            on = meta.get("line") == self.current and self.current is not None
            bg = "#eaf2ff" if on else "white"
            num.configure(bg=bg)
            body.configure(bg=bg)
            if on and body.winfo_ismapped():
                self.see_widget(body)

    def _clicked(self, k):
        if k < len(self.rows) and self.on_click:
            line = self.rows[k][2].get("line")
            if line:
                self.on_click(line)


# ---------------------------------------------------------------------------
# Variable grid
# ---------------------------------------------------------------------------

class _Row:
    def __init__(self, name):
        self.name = name
        self.solve = tk.BooleanVar(value=False)
        self.value = tk.StringVar()
        self.unit = tk.StringVar()
        self.result = tk.StringVar()
        self.guess = tk.StringVar()
        self.lo = tk.StringVar()
        self.hi = tk.StringVar()
        self.widgets: list = []
        self.result_entry = None

    def state(self) -> dict:
        return {"value": self.value.get(), "unit": self.unit.get(), "solve": self.solve.get(),
                "guess": self.guess.get(), "min": self.lo.get(), "max": self.hi.get()}

    def load(self, d: dict) -> None:
        self.value.set(d.get("value", ""))
        self.unit.set(d.get("unit", ""))
        self.solve.set(bool(d.get("solve", False)))
        self.guess.set(d.get("guess", ""))
        self.lo.set(d.get("min", ""))
        self.hi.set(d.get("max", ""))


class VariableGrid(ScrollFrame):
    HEAD = [("Solve", 5), ("Variable", 10), ("Value", 12), ("Unit", 8), ("Result", 16),
            ("Guess", 7), ("Min", 6), ("Max", 6)]

    def __init__(self, master, font, on_change=None, on_enter=None, **kw):
        super().__init__(master, bg="white", horizontal=True, **kw)
        self.font = font
        self.on_change = on_change
        self.on_enter = on_enter
        self.rows: dict[str, _Row] = {}
        self.order: list[str] = []
        self.show_solver_cols = True
        self._loading = False
        self.header = []
        for c, (h, w) in enumerate(self.HEAD):
            lab = tk.Label(self.inner, text=h, bg="#eef1f5", font=("Segoe UI", 9, "bold"),
                           anchor="w", padx=4, pady=3)
            lab.grid(row=0, column=c, sticky="ew", padx=(0, 1))
            self.header.append(lab)
        Tooltip(self.header[0], "Tick to solve for this variable even if it has a value\n"
                                "(blank values are always solved for)")
        Tooltip(self.header[2], "Known value. May include units: 12.5 ft, 3 in, 12'6\", 450 gpm.\n"
                                "Leave blank to solve for it.")
        Tooltip(self.header[3], "Optional unit. For unknowns, the unit you want the answer in.")
        Tooltip(self.header[5], "Starting value for the iterative solver; also picks which\n"
                                "root is reported when there are several.")
        Tooltip(self.header[6], "Optional lower limit for the solution")
        Tooltip(self.header[7], "Optional upper limit for the solution")
        self.inner.columnconfigure(4, weight=1)
        self.empty = tk.Label(self.inner, text="Variables appear here as you type equations.",
                              bg="white", fg="#888", font=("Segoe UI", 10, "italic"), pady=12)
        self.empty.grid(row=1, column=0, columnspan=8)

    def _make_row(self, name: str) -> _Row:
        row = _Row(name)
        f = self.font
        cb = ttk.Checkbutton(self.inner, variable=row.solve, takefocus=False)
        lab = tk.Label(self.inner, text=pretty_name(name), bg="white", anchor="w",
                       font=(f[0], f[1], "bold"), padx=4)
        val = ttk.Entry(self.inner, textvariable=row.value, width=12, font=f)
        unit = ttk.Combobox(self.inner, textvariable=row.unit, width=7, font=f, values=COMMON_UNITS)
        res = ttk.Entry(self.inner, textvariable=row.result, width=16, font=f, state="readonly",
                        style="Result.TEntry", takefocus=False)
        guess = ttk.Entry(self.inner, textvariable=row.guess, width=7, font=f)
        lo = ttk.Entry(self.inner, textvariable=row.lo, width=6, font=f)
        hi = ttk.Entry(self.inner, textvariable=row.hi, width=6, font=f)
        row.widgets = [cb, lab, val, unit, res, guess, lo, hi]
        row.result_entry = res
        for w in (val, unit, guess, lo, hi):
            w.bind("<Return>", lambda e: (self.on_enter() if self.on_enter else None, "break")[1])
            w.bind("<KP_Enter>", lambda e: (self.on_enter() if self.on_enter else None, "break")[1])
        for v in (row.solve, row.value, row.unit, row.guess, row.lo, row.hi):
            v.trace_add("write", lambda *a: self._changed())
        return row

    def _changed(self):
        if not self._loading and self.on_change:
            self.on_change()

    def set_names(self, names: list[str]) -> None:
        if names == self.order:
            return
        for n in self.order:
            if n not in names:
                for w in self.rows[n].widgets:
                    w.grid_remove()
        for n in names:
            if n not in self.rows:
                self.rows[n] = self._make_row(n)
        for r, n in enumerate(names, start=1):
            for c, w in enumerate(self.rows[n].widgets):
                w.grid(row=r, column=c, sticky="ew", padx=(0, 1), pady=1)
                if c >= 5 and not self.show_solver_cols:
                    w.grid_remove()
        self.order = list(names)
        if names:
            self.empty.grid_remove()
        else:
            self.empty.grid()

    def toggle_solver_columns(self, show: bool) -> None:
        self.show_solver_cols = show
        for c in (5, 6, 7):
            if show:
                self.header[c].grid()
            else:
                self.header[c].grid_remove()
        for n in self.order:
            for w in self.rows[n].widgets[5:]:
                (w.grid if show else w.grid_remove)()

    def row(self, name: str) -> _Row:
        return self.rows[name]

    def state(self, visible_only=True) -> dict:
        names = self.order if visible_only else list(self.rows)
        return {n: self.rows[n].state() for n in names}

    def load_state(self, data: dict) -> None:
        self._loading = True
        try:
            for name, d in data.items():
                if name not in self.rows:
                    self.rows[name] = self._make_row(name)
                self.rows[name].load(d)
        finally:
            self._loading = False

    def clear_results(self) -> None:
        for r in self.rows.values():
            r.result.set("")

    def set_result(self, name: str, text: str) -> None:
        if name in self.rows:
            self.rows[name].result.set(text)
            self.rows[name].result_entry.configure(style="Result.TEntry")

    def mark_stale(self) -> None:
        for r in self.rows.values():
            if r.result.get():
                r.result_entry.configure(style="Stale.TEntry")

    def focus_first_empty(self) -> None:
        for n in self.order:
            r = self.rows[n]
            if not r.value.get().strip():
                r.widgets[2].focus_set()
                return


# ---------------------------------------------------------------------------
# Results view
# ---------------------------------------------------------------------------

class ResultsView(ttk.Frame):
    def __init__(self, master, font_size=11, **kw):
        super().__init__(master, **kw)
        self.text = tk.Text(self, wrap="word", font=("Segoe UI", font_size), relief="flat",
                            padx=10, pady=8, background="white", cursor="arrow",
                            spacing1=2, spacing3=2)
        vsb = ttk.Scrollbar(self, orient="vertical", command=self.text.yview)
        self.text.configure(yscrollcommand=vsb.set)
        self.text.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        t = self.text
        t.tag_configure("h", font=("Segoe UI", font_size + 2, "bold"), spacing1=8, foreground="#1f3b63")
        t.tag_configure("good", foreground="#1b7f3b")
        t.tag_configure("warn", foreground="#b26a00")
        t.tag_configure("err", foreground="#c62828", font=("Segoe UI", font_size, "bold"))
        t.tag_configure("dim", foreground="#777", font=("Segoe UI", font_size - 1))
        t.tag_configure("mono", font=("Consolas", font_size - 1))
        t.tag_configure("big", font=("Segoe UI", font_size + 3))
        t.configure(state="disabled")
        self._images = []
        self._math_size = 16
        t.bind("<Control-c>", lambda e: self._copy())
        t.bind("<Button-1>", lambda e: t.focus_set())

    def _copy(self):
        try:
            sel = self.text.get("sel.first", "sel.last")
        except tk.TclError:
            return "break"
        self.clipboard_clear()
        self.clipboard_append(sel)
        return "break"

    def clear(self):
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        for child in self.text.winfo_children():
            child.destroy()
        self.text.configure(state="disabled")
        self._images.clear()

    def write(self, s: str, *tags):
        self.text.configure(state="normal")
        self.text.insert("end", s, tags)
        self.text.configure(state="disabled")

    def heading(self, s: str):
        if self.text.index("end-1c") != "1.0":
            self.write("\n")
        self.write(s + "\n", "h")

    def math(self, latex: str, fallback: str = "", size: int | None = None):
        img = render.photo_image(latex, size or self._math_size)
        self.text.configure(state="normal")
        if img is None:
            self.text.insert("end", fallback or latex, ("mono",))
        else:
            self._images.append(img)
            self.text.image_create("end", image=img, padx=2, pady=2)
        self.text.configure(state="disabled")

    def button(self, label: str, command):
        b = ttk.Button(self.text, text=label, command=command, style="Small.TButton",
                       takefocus=False, cursor="hand2")
        self.text.configure(state="normal")
        self.text.window_create("end", window=b, padx=4)
        self.text.configure(state="disabled")

    def error(self, msg: str):
        self.clear()
        self.write("⚠ " + msg + "\n", "err")

    def see_top(self):
        self.text.yview_moveto(0)


def num_latex(s: str) -> str:
    """'1.23e-6' -> '1.23\\times10^{-6}' for typeset display."""
    m = re.fullmatch(r"(-?[\d.]+)e(-?\d+)", s)
    if m:
        return rf"{m.group(1)}\times10^{{{m.group(2)}}}"
    return s.replace("∞", r"\infty")


def unit_latex(u: str) -> str:
    if not u:
        return ""
    u = u.replace("\\", "").replace("{", "").replace("}", "").replace(" ", r"\ ")
    return r"\ \mathrm{" + u + "}"
