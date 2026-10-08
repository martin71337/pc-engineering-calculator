"""Scratchpad tab: quick line-by-line calculations with variables and units."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from .. import render, units
from ..scratch import Scratchpad, ScratchError
from .widgets import pretty_name

TIPS = ("Examples:   L = 24 ft    W = 12'6\"    L*W    ans -> yd^2    "
        "Q = 450 gpm -> cfs    sqrt(3^2 + 4^2)    sin(30)")


class ScratchpadTab(ttk.Frame):
    def __init__(self, master, app):
        super().__init__(master)
        self.app = app
        self.pad = Scratchpad()
        self.entries: list[str] = []
        self._hist_pos = None
        self._after = None
        self._images = []
        self._build()

    def _build(self):
        app = self.app
        paned = ttk.PanedWindow(self, orient="horizontal")
        paned.pack(fill="both", expand=True, padx=6, pady=6)

        left = ttk.Frame(paned)
        hist_frame = ttk.LabelFrame(left, text=" Calculations  (click one to edit it again) ", padding=2)
        hist_frame.pack(fill="both", expand=True)
        self.hist = tk.Text(hist_frame, wrap="word", relief="flat", background="white", padx=10,
                            pady=8, cursor="arrow", font=("Segoe UI", app.settings["font_size"] - 2),
                            spacing1=3, spacing3=3)
        vsb = ttk.Scrollbar(hist_frame, orient="vertical", command=self.hist.yview)
        self.hist.configure(yscrollcommand=vsb.set, state="disabled")
        self.hist.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        self.hist.tag_configure("result", font=("Segoe UI", app.settings["font_size"] + 1, "bold"),
                                foreground="#1b4f9c", lmargin1=40)
        self.hist.tag_configure("err", foreground="#c62828", lmargin1=40)
        self.hist.tag_configure("src", foreground="#777", font=("Consolas", app.settings["font_size"] - 3))

        prev_frame = ttk.Frame(left)
        prev_frame.pack(fill="x", pady=(6, 0))
        self.preview = tk.Label(prev_frame, bg="white", anchor="w", height=3, relief="flat", padx=8)
        self.preview.pack(fill="x")
        self.live = ttk.Label(prev_frame, text="", foreground="#1b4f9c")
        self.live.pack(fill="x", padx=8)

        entry_row = ttk.Frame(left)
        entry_row.pack(fill="x", pady=(4, 0))
        ttk.Label(entry_row, text="›", font=("Segoe UI", 16, "bold")).pack(side="left", padx=(2, 4))
        self.var = tk.StringVar()
        self.entry = ttk.Entry(entry_row, textvariable=self.var, font=app.editor_font)
        self.entry.pack(side="left", fill="x", expand=True)
        ttk.Button(entry_row, text="=", width=3, style="Accent.TButton",
                   command=self.run).pack(side="left", padx=(4, 0))
        ttk.Label(left, text=TIPS, foreground="#777", wraplength=900).pack(fill="x", pady=(4, 0))

        self.entry.bind("<Return>", lambda e: self.run())
        self.entry.bind("<KP_Enter>", lambda e: self.run())
        self.entry.bind("<Up>", lambda e: self._recall(-1))
        self.entry.bind("<Down>", lambda e: self._recall(1))
        self.entry.bind("<Escape>", lambda e: self.var.set(""))
        self.var.trace_add("write", lambda *a: self._schedule_preview())

        right = ttk.LabelFrame(paned, text=" Variables ", padding=4)
        self.vars_tv = ttk.Treeview(right, columns=("value",), show="tree headings", height=12)
        self.vars_tv.heading("#0", text="Name")
        self.vars_tv.heading("value", text="Value")
        self.vars_tv.column("#0", width=90, stretch=False)
        self.vars_tv.column("value", width=200)
        self.vars_tv.pack(fill="both", expand=True)
        self.vars_tv.bind("<Double-1>", self._insert_var)
        bar = ttk.Frame(right)
        bar.pack(fill="x", pady=(4, 0))
        ttk.Button(bar, text="Clear variables", command=self.clear_vars).pack(side="left")
        ttk.Button(bar, text="Clear history", command=self.clear_history).pack(side="left", padx=4)
        ttk.Label(right, text="Double-click a variable to insert it.", foreground="#777").pack(anchor="w")

        paned.add(left, weight=4)
        paned.add(right, weight=1)

    def focus(self):
        self.entry.focus_set()

    def _schedule_preview(self):
        self._hist_pos = None
        if self._after:
            self.after_cancel(self._after)
        self._after = self.after(200, self._update_preview)

    def _update_preview(self):
        self._after = None
        text = self.var.get().strip()
        if not text:
            self.preview.configure(image="", text="")
            self.live.configure(text="")
            return
        # Evaluate on a copy so the preview doesn't assign variables.
        probe = Scratchpad()
        probe.vars = dict(self.pad.vars)
        try:
            res = probe.run(text, self.app.angle_mode.get(), self.app.fmt)
            img = render.photo_image(res.latex, self.app.settings["font_size"] + 4) if res.latex else None
            self.preview.configure(image=img or "", text="" if img else text)
            self.preview.image = img
            self.live.configure(text="= " + res.text, foreground="#1b4f9c")
        except ScratchError as e:
            self.preview.configure(image="", text=text)
            self.live.configure(text=str(e), foreground="#b26a00")
        except Exception as e:  # never let the preview crash the app
            self.live.configure(text=str(e), foreground="#b26a00")

    def run(self):
        text = self.var.get().strip()
        if not text:
            return
        self.entries.append(text)
        start = self.hist.index("end-1c")
        self.hist.configure(state="normal")
        try:
            res = self.pad.run(text, self.app.angle_mode.get(), self.app.fmt)
            img = render.photo_image(res.latex, self.app.settings["font_size"] + 2) if res.latex else None
            if img is not None:
                self._images.append(img)
                self.hist.image_create("end", image=img, padx=4)
                self.hist.insert("end", "\n")
            else:
                self.hist.insert("end", text + "\n", ("src",))
            self.hist.insert("end", "= " + res.text + "\n", ("result",))
            self.var.set("")
            self.app.status(f"{res.name} = {res.text}" if res.name else "= " + res.text)
        except ScratchError as e:
            self.hist.insert("end", text + "\n", ("src",))
            self.hist.insert("end", "⚠ " + str(e) + "\n", ("err",))
            self.app.status(str(e), error=True)
        tag = f"entry{len(self.entries)}"
        self.hist.tag_add(tag, start, "end-1c")
        self.hist.tag_bind(tag, "<Button-1>", lambda e, t=text: self._edit(t))
        self.hist.configure(state="disabled")
        self.hist.see("end")
        self._refresh_vars()

    def _edit(self, text):
        self.var.set(text)
        self.entry.focus_set()
        self.entry.icursor("end")

    def _recall(self, step):
        if not self.entries:
            return "break"
        if self._hist_pos is None:
            self._hist_pos = len(self.entries)
        self._hist_pos = max(0, min(len(self.entries), self._hist_pos + step))
        text = self.entries[self._hist_pos] if self._hist_pos < len(self.entries) else ""
        pos = self._hist_pos
        self.var.set(text)
        self._hist_pos = pos
        self.entry.icursor("end")
        return "break"

    def _refresh_vars(self):
        tv = self.vars_tv
        tv.delete(*tv.get_children())
        for name, v in self.pad.vars.items():
            txt = units.format_quantity(v, self.app.fmt) if isinstance(v, units.Q_) else self.app.fmt(v)
            tv.insert("", "end", iid=name, text=pretty_name(name), values=(txt,))

    def _insert_var(self, _e=None):
        sel = self.vars_tv.selection()
        if sel:
            self.entry.insert("insert", sel[0])
            self.entry.focus_set()

    def clear_vars(self):
        self.pad.clear()
        self._refresh_vars()

    def clear_history(self):
        self.hist.configure(state="normal")
        self.hist.delete("1.0", "end")
        self.hist.configure(state="disabled")
        self._images.clear()
