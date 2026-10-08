"""Unit converter tab."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from .. import engine, units

SLOPE = "Slope / grade"


class ConverterTab(ttk.Frame):
    def __init__(self, master, app):
        super().__init__(master, padding=8)
        self.app = app
        self._build()

    def _build(self):
        app = self.app
        top = ttk.LabelFrame(self, text=" Quick convert ", padding=8)
        top.pack(fill="x")
        ttk.Label(top, text="Type a conversion:").pack(side="left")
        self.quick = tk.StringVar()
        e = ttk.Entry(top, textvariable=self.quick, font=app.editor_font, width=40)
        e.pack(side="left", padx=6, fill="x", expand=True)
        e.bind("<Return>", lambda ev: self.do_quick())
        ttk.Button(top, text="Convert", style="Accent.TButton", command=self.do_quick).pack(side="left")
        self.quick_out = ttk.Label(top, text="", font=("Segoe UI", app.settings["font_size"], "bold"),
                                   foreground="#1b4f9c", width=28)
        self.quick_out.pack(side="left", padx=10)
        ttk.Label(self, text="e.g.   3.5 cfs to gpm     12'6\" -> m     68 degF to degC     2.5 ksi to MPa",
                  foreground="#777").pack(anchor="w", pady=(2, 8))

        body = ttk.Frame(self)
        body.pack(fill="both", expand=True)
        cats = ttk.LabelFrame(body, text=" Category ", padding=4)
        cats.pack(side="left", fill="y")
        self.cat_list = tk.Listbox(cats, exportselection=False, height=20, activestyle="none",
                                   font=("Segoe UI", app.settings["font_size"] - 3), width=18)
        for c in list(units.CATEGORIES) + [SLOPE]:
            self.cat_list.insert("end", c)
        self.cat_list.pack(fill="y", expand=True)
        self.cat_list.bind("<<ListboxSelect>>", lambda e: self._category_changed())

        main = ttk.LabelFrame(body, text=" Convert ", padding=8)
        main.pack(side="left", fill="both", expand=True, padx=(8, 0))
        row = ttk.Frame(main)
        row.pack(fill="x")
        ttk.Label(row, text="Value").pack(side="left")
        self.value = tk.StringVar(value="1")
        ve = ttk.Entry(row, textvariable=self.value, width=16, font=app.editor_font)
        ve.pack(side="left", padx=6)
        ttk.Label(row, text="from").pack(side="left")
        self.from_unit = ttk.Combobox(row, state="readonly", width=26, font=app.grid_font)
        self.from_unit.pack(side="left", padx=6)
        self.value.trace_add("write", lambda *a: self.update_table())
        self.from_unit.bind("<<ComboboxSelected>>", lambda e: self.update_table())
        self.msg = ttk.Label(main, text="", foreground="#c62828")
        self.msg.pack(anchor="w", pady=(4, 0))

        self.tv = ttk.Treeview(main, columns=("value", "unit"), show="headings", height=16)
        self.tv.heading("value", text="Value")
        self.tv.heading("unit", text="Unit")
        self.tv.column("value", width=220, anchor="e")
        self.tv.column("unit", width=220)
        self.tv.pack(fill="both", expand=True, pady=(6, 0))
        self.tv.bind("<Double-1>", self._copy_row)
        ttk.Label(main, text="Double-click a row to copy the value.", foreground="#777").pack(anchor="w")

        self.cat_list.selection_set(0)
        self._category_changed()

    def _category(self) -> str:
        sel = self.cat_list.curselection()
        return self.cat_list.get(sel[0]) if sel else "Length"

    def _category_changed(self):
        cat = self._category()
        if cat == SLOPE:
            labels = list(units.SLOPE_KINDS)
        else:
            labels = [lab for lab, _ in units.CATEGORIES[cat]]
        self.from_unit.configure(values=labels)
        self.from_unit.set(labels[0])
        self.update_table()

    def update_table(self):
        self.tv.delete(*self.tv.get_children())
        self.msg.configure(text="")
        text = self.value.get().strip()
        if not text:
            return
        try:
            v = engine.evaluate_constant(text, self.app.angle_mode.get())
        except Exception:
            self.msg.configure(text="Enter a number (expressions like 3*12+6 are fine)")
            return
        cat = self._category()
        try:
            if cat == SLOPE:
                for label, val in units.slope_conversions(v, self.from_unit.get()):
                    self.tv.insert("", "end", values=(val, label))
                return
            unit = dict(units.CATEGORIES[cat])[self.from_unit.get()]
            for label, val in units.convert_all(v, unit, cat):
                self.tv.insert("", "end", values=(self.app.fmt(val), label))
        except Exception as e:
            self.msg.configure(text=str(e))

    def _copy_row(self, _e=None):
        sel = self.tv.selection()
        if not sel:
            return
        val = str(self.tv.item(sel[0], "values")[0]).split(" ")[0]
        self.clipboard_clear()
        self.clipboard_append(val)
        self.app.status(f"Copied {val}")

    def do_quick(self):
        try:
            q = units.convert_text(self.quick.get())
            self.quick_out.configure(text="= " + units.format_quantity(q, self.app.fmt),
                                     foreground="#1b4f9c")
        except Exception as e:
            self.quick_out.configure(text=str(e), foreground="#c62828")

    def refresh_settings(self):
        self.update_table()
