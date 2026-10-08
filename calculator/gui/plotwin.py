"""Plot window: both sides of an equation against one variable, intersections marked."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

import numpy as np
import sympy as sp
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from matplotlib.figure import Figure
from scipy import optimize

from .. import engine, render


def _label(prefix: str, tex: str | None, expr) -> str:
    """Legend label; falls back to plain text if mathtext can't draw the LaTeX."""
    if tex and render.latex_png(tex, 10) is not None:
        return f"{prefix}:  ${tex}$"
    return f"{prefix}:  {engine.to_input_text(expr)}"


class PlotWindow(tk.Toplevel):
    def __init__(self, master, lhs, rhs, sym, lo: float, hi: float, title: str, fmt, mark=None):
        super().__init__(master)
        self.title(f"Plot - {title}")
        self.geometry("900x620")
        self.fmt = fmt
        self.sym = sym
        self.mark = mark
        self.fl = engine.make_function(lhs, sym)
        self.fr = engine.make_function(rhs, sym) if rhs is not None else None
        short_l = sp.N(lhs, 5)
        short_r = sp.N(rhs, 5) if rhs is not None else None
        self.lhs_label = _label("left side", engine.to_latex(short_l), short_l)
        self.rhs_label = _label("right side", engine.to_latex(short_r), short_r) if rhs is not None else None
        self.title_text = title

        bar = ttk.Frame(self, padding=6)
        bar.pack(side="top", fill="x")
        ttk.Label(bar, text=f"{sym.name} from").pack(side="left")
        self.lo_var = tk.StringVar(value=self._g(lo))
        self.hi_var = tk.StringVar(value=self._g(hi))
        e1 = ttk.Entry(bar, textvariable=self.lo_var, width=12)
        e1.pack(side="left", padx=4)
        ttk.Label(bar, text="to").pack(side="left")
        e2 = ttk.Entry(bar, textvariable=self.hi_var, width=12)
        e2.pack(side="left", padx=4)
        ttk.Button(bar, text="Replot", command=self.draw).pack(side="left", padx=6)
        for e in (e1, e2):
            e.bind("<Return>", lambda ev: self.draw())
        self.info = ttk.Label(bar, text="", foreground="#1b7f3b")
        self.info.pack(side="left", padx=12)

        self.fig = Figure(figsize=(8, 5.4), dpi=100)
        self.ax = self.fig.add_subplot(111)
        self.canvas = FigureCanvasTkAgg(self.fig, master=self)
        NavigationToolbar2Tk(self.canvas, self).update()
        self.canvas.get_tk_widget().pack(fill="both", expand=True)
        self.draw()

    @staticmethod
    def _g(x):
        return f"{x:.6g}"

    def draw(self):
        try:
            lo = engine.evaluate_constant(self.lo_var.get())
            hi = engine.evaluate_constant(self.hi_var.get())
        except Exception:
            self.info.configure(text="Enter numeric limits", foreground="#c62828")
            return
        if lo == hi:
            hi = lo + 1
        if lo > hi:
            lo, hi = hi, lo
        x = np.linspace(lo, hi, 1500)
        yl = self.fl(x)
        ax = self.ax
        ax.clear()
        ax.grid(True, alpha=0.3)
        ax.axhline(0, color="#999", lw=0.8)
        ax.plot(x, yl, color="#1f6fd1", lw=2, label=self.lhs_label)
        roots = []
        if self.fr is not None:
            yr = self.fr(x)
            ax.plot(x, yr, color="#e07b00", lw=2, label=self.rhs_label)
            diff = yl - yr
            fdiff = lambda t: float(self.fl(np.array([t]))[0] - self.fr(np.array([t]))[0])
        else:
            diff = yl
            fdiff = lambda t: float(self.fl(np.array([t]))[0])
        ok = np.isfinite(diff)
        for i in range(len(x) - 1):
            if ok[i] and ok[i + 1] and diff[i] * diff[i + 1] < 0:
                try:
                    r = optimize.brentq(fdiff, x[i], x[i + 1])
                except ValueError:
                    continue
                if abs(fdiff(r)) <= min(abs(diff[i]), abs(diff[i + 1])):
                    roots.append(r)
            elif ok[i] and diff[i] == 0:
                roots.append(x[i])
        for r in roots:
            yv = float(self.fl(np.array([r]))[0])
            ax.plot([r], [yv], "o", color="#c62828", ms=7, zorder=5)
            ax.annotate(f"{self.sym.name} = {self.fmt(r)}", (r, yv), textcoords="offset points",
                        xytext=(6, 8), fontsize=10, color="#c62828")
        if self.mark is not None and lo <= self.mark <= hi:
            ax.axvline(self.mark, color="#1b7f3b", ls="--", lw=1)
        finite = np.concatenate([yl[np.isfinite(yl)]] +
                                ([self.fr(x)[np.isfinite(self.fr(x))]] if self.fr else []))
        if finite.size:
            lo_y, hi_y = np.percentile(finite, [1, 99])
            pad = (hi_y - lo_y) * 0.1 or 1.0
            ax.set_ylim(lo_y - pad, hi_y + pad)
        ax.set_xlim(lo, hi)
        ax.set_xlabel(self.sym.name)
        ax.set_title(self.title_text, fontsize=11)
        try:
            ax.legend(loc="best", fontsize=10)
        except Exception:
            ax.legend([], [])
        self.canvas.draw_idle()
        if self.fr is not None:
            msg = ("Solutions where the curves cross: " + ", ".join(self.fmt(r) for r in roots)) \
                if roots else "The curves don't cross in this range"
        else:
            msg = ("Zeros: " + ", ".join(self.fmt(r) for r in roots)) if roots else "No zeros in this range"
        self.info.configure(text=msg, foreground="#1b7f3b" if roots else "#b26a00")
