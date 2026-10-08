"""Main window."""
from __future__ import annotations

import os
import sys
import tkinter as tk
from tkinter import font as tkfont
from tkinter import messagebox, ttk

from .. import engine, render, storage, units
from .converter_tab import ConverterTab
from .scratchpad_tab import ScratchpadTab
from .worksheet_tab import WorksheetTab

APP_NAME = "PC Engineering Calculator"
_ASSETS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets")
ICON_ICO = os.path.join(_ASSETS, "calculator.ico")
ICON_PNG = os.path.join(_ASSETS, "calculator.png")

HELP_TEXT = """\
TYPING EQUATIONS  (Worksheet tab)
  One equation per line:      Q = 1.49/n*A*R^(2/3)*S^(1/2)
  Comments start with #:      R = A/P      # hydraulic radius
  Powers:  x^2   x^(2/3)      Multiply:  2*x   2x   2(x+1)   a b   (implicit is OK)
  Brackets  ( ) [ ] { }  all work as parentheses.
  "Number then name" binds tightly:  x/2y  means  x/(2y)
  Names can be long and use underscores:  R_h, sigma_max, Q_peak, lambda, theta
  Any single letter is a variable - including e, E, I, S, N, Q.  (Use exp(1) for Euler's e.)

FUNCTIONS
  sqrt(x)  cbrt(x)  root(x, n)  abs(x)  exp(x)  ln(x)  log(x) = base 10  log(x, b)
  sin cos tan sec csc cot   asin acos atan atan2(y, x)   sinh cosh tanh
  min(a, b)  max(a, b)  floor(x)  ceil(x)  sign(x)  x!     constant: pi
  Angles follow the Deg/Rad switch (top right).

SOLVING
  1. Type the equations.  2. Fill in known values in the Variables table.
  3. Leave the unknown(s) blank (or tick "Solve").  4. Press Solve  (Ctrl+Enter or F5).
  - Several equations are solved together (substitution, then iteration if needed).
  - Iterative solving scans for every real root; set Guess / Min / Max to choose one.
  - Lines with no '=' are evaluated after solving (handy for checks).
  - Plot… graphs both sides of the current line against a variable - a picture of the answer.

SYMBOLIC TOOLS  (act on the line the cursor is on)
  Rearrange…  isolate any variable       Simplify / Expand / Factor
  d/dx…       derivative                 ∫ dx…  integral (give limits for a number)

UNITS (optional)
  Values may include units:  12.5 ft   3 in   12'6"   450 gpm   2.5 ksi   30 deg
  Unit column on an unknown = the unit you want the answer in.
  Unit system:  US (ft, lb, s) or SI (m, kg, s) - inputs are converted to it before solving,
  so empirical formulas (Manning 1.49, Hazen-Williams) work.  "As entered" = units are labels.
  Custom units: cfs gpm gpd mgd psf ksf pcf (= lbf/ft³) plf klf acre_ft

SCRATCHPAD
  Line-by-line calculator with units:   L = 24 ft    W = 12'6"    L*W    ans -> yd^2
  Up/Down arrows recall earlier lines.

KEYS
  Ctrl+Enter / F5  Solve          Ctrl+N  New         Ctrl+O  Open      Ctrl+S  Save
  Ctrl+L  Library                 Ctrl+Z / Ctrl+Y  Undo / Redo           F1  this help
"""


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.settings = storage.load_settings()
        self.withdraw()
        self.title(APP_NAME)
        self._set_icon()
        self._setup_scaling()
        self.angle_mode = tk.StringVar(value=self.settings["angle_mode"])
        self._make_fonts()
        self._make_styles()
        self._make_menu()

        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True)
        self.worksheet = WorksheetTab(self.nb, self)
        self.scratch = ScratchpadTab(self.nb, self)
        self.converter = ConverterTab(self.nb, self)
        self.nb.add(self.worksheet, text="  Worksheet  ")
        self.nb.add(self.scratch, text="  Scratchpad  ")
        self.nb.add(self.converter, text="  Unit Converter  ")
        self.nb.bind("<<NotebookTabChanged>>", self._tab_changed)

        self.statusbar = ttk.Label(self, text="", anchor="w", padding=(8, 3), relief="sunken")
        self.statusbar.pack(side="bottom", fill="x")

        geo = self.settings.get("geometry") or ""
        self.geometry(geo if geo else "1400x880")
        self.minsize(1000, 640)
        self.protocol("WM_DELETE_WINDOW", self.quit_app)
        self._bind_keys()
        self.worksheet.start()
        self.update_title()
        self.deiconify()
        self.worksheet.editor.text.focus_set()

    # ------------------------------------------------------------- setup
    def _set_icon(self):
        """Window/taskbar icon; also inherited by dialogs and plot windows."""
        try:
            if sys.platform == "win32" and os.path.exists(ICON_ICO):
                self.iconbitmap(default=ICON_ICO)
            elif os.path.exists(ICON_PNG):
                self._icon_img = tk.PhotoImage(file=ICON_PNG)
                self.iconphoto(True, self._icon_img)
        except tk.TclError:
            pass

    def _setup_scaling(self):
        px_per_in = self.winfo_fpixels("1i")
        render.DPI = int(round(100 * px_per_in / 96))

    def _make_fonts(self):
        size = int(self.settings["font_size"])
        self.editor_font = ("Consolas", size)
        self.grid_font = ("Segoe UI", max(9, size - 3))
        for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont"):
            try:
                tkfont.nametofont(name).configure(family="Segoe UI", size=10)
            except tk.TclError:
                pass

    def _make_styles(self):
        st = ttk.Style(self)
        if "vista" in st.theme_names():
            st.theme_use("vista")
        st.configure("Accent.TButton", font=("Segoe UI", 10, "bold"), foreground="#0b5394")
        st.configure("Small.TButton", font=("Segoe UI", 8), padding=(4, 0))
        st.configure("Tool.TButton", padding=(2, 2))
        st.configure("Palette.TButton", font=("Segoe UI", 10), padding=(2, 1))
        st.configure("Palette.TMenubutton", font=("Segoe UI", 10), padding=(2, 1))
        st.configure("Result.TEntry", foreground="#1b7f3b")
        st.map("Result.TEntry", foreground=[("readonly", "#1b7f3b")])
        st.configure("Stale.TEntry", foreground="#9e9e9e")
        st.map("Stale.TEntry", foreground=[("readonly", "#9e9e9e")])
        st.configure("TNotebook.Tab", font=("Segoe UI", 10, "bold"), padding=(10, 4))
        line = tkfont.Font(family="Segoe UI", size=10).metrics("linespace")
        st.configure("Treeview", rowheight=int(line * 1.35))

    def _make_menu(self):
        m = tk.Menu(self)
        fm = tk.Menu(m, tearoff=False)
        fm.add_command(label="New worksheet", accelerator="Ctrl+N", command=lambda: self.worksheet.new())
        fm.add_command(label="Open…", accelerator="Ctrl+O", command=lambda: self.worksheet.open())
        self.recent_menu = tk.Menu(fm, tearoff=False)
        fm.add_cascade(label="Open recent", menu=self.recent_menu)
        fm.add_separator()
        fm.add_command(label="Save", accelerator="Ctrl+S", command=lambda: self.worksheet.save())
        fm.add_command(label="Save as…", accelerator="Ctrl+Shift+S", command=lambda: self.worksheet.save_as())
        fm.add_separator()
        fm.add_command(label="Exit", command=self.quit_app)
        m.add_cascade(label="File", menu=fm)

        em = tk.Menu(m, tearoff=False)
        em.add_command(label="Undo", accelerator="Ctrl+Z",
                       command=lambda: self._editor_cmd("edit_undo"))
        em.add_command(label="Redo", accelerator="Ctrl+Y",
                       command=lambda: self._editor_cmd("edit_redo"))
        em.add_separator()
        em.add_command(label="Solve", accelerator="Ctrl+Enter", command=lambda: self.worksheet.solve())
        m.add_cascade(label="Edit", menu=em)

        lm = tk.Menu(m, tearoff=False)
        lm.add_command(label="Equation library…", accelerator="Ctrl+L", command=self.open_library)
        lm.add_command(label="Save to library…", command=self.save_to_library)
        m.add_cascade(label="Library", menu=lm)

        sm = tk.Menu(m, tearoff=False)
        sm.add_radiobutton(label="Degrees", value="deg", variable=self.angle_mode, command=self.angle_changed)
        sm.add_radiobutton(label="Radians", value="rad", variable=self.angle_mode, command=self.angle_changed)
        sm.add_separator()
        sm.add_command(label="Preferences…", command=self.open_settings)
        m.add_cascade(label="Settings", menu=sm)

        hm = tk.Menu(m, tearoff=False)
        hm.add_command(label="Syntax and features", accelerator="F1", command=self.show_help)
        hm.add_command(label="About", command=lambda: messagebox.showinfo(
            "About", f"{APP_NAME}\n\nEquation solver for long formulas: typeset preview, "
                     "symbolic algebra (sympy), iterative solving (scipy) and optional units (pint).",
            parent=self))
        m.add_cascade(label="Help", menu=hm)
        self.config(menu=m)
        self.rebuild_recent_menu()

    def rebuild_recent_menu(self):
        self.recent_menu.delete(0, "end")
        recent = [p for p in self.settings.get("recent", []) if os.path.exists(p)]
        if not recent:
            self.recent_menu.add_command(label="(none)", state="disabled")
        for p in recent:
            self.recent_menu.add_command(label=p, command=lambda p=p: self.worksheet.open(p))

    def _bind_keys(self):
        self.bind_all("<Control-n>", lambda e: self.worksheet.new())
        self.bind_all("<Control-o>", lambda e: self.worksheet.open())
        self.bind_all("<Control-s>", lambda e: self.worksheet.save())
        self.bind_all("<Control-S>", lambda e: self.worksheet.save_as())
        self.bind_all("<Control-l>", lambda e: self.open_library())
        self.bind_all("<F1>", lambda e: self.show_help())
        self.worksheet.editor.text.bind("<Control-y>", lambda e: (self._editor_cmd("edit_redo"), "break")[1])

    def _editor_cmd(self, cmd):
        try:
            getattr(self.worksheet.editor.text, cmd)()
        except tk.TclError:
            pass

    def _tab_changed(self, _e=None):
        if self.nb.select() == str(self.scratch):
            self.scratch.focus()

    # -------------------------------------------------------- helpers
    def fmt(self, x) -> str:
        return engine.format_number(x, self.settings["number_format"], self.settings["digits"])

    def status(self, msg: str, error: bool = False):
        self.statusbar.configure(text=msg, foreground="#c62828" if error else "#333")

    def update_title(self):
        ws = self.worksheet
        name = os.path.basename(ws.path) if ws.path else "Untitled"
        self.title(f"{'*' if ws.modified else ''}{name} - {APP_NAME}")

    def save_settings(self):
        self.settings["angle_mode"] = self.angle_mode.get()
        storage.save_settings(self.settings)

    def angle_changed(self):
        self.save_settings()
        self.worksheet._reparse()
        self.worksheet.grid_.mark_stale()
        self.status(f"Angles in {'degrees' if self.angle_mode.get() == 'deg' else 'radians'}")

    def quit_app(self):
        if not self.worksheet.confirm_discard():
            return
        self.settings["geometry"] = self.geometry() if self.state() == "normal" else ""
        self.save_settings()
        self.destroy()

    # -------------------------------------------------------- dialogs
    def show_help(self):
        win = tk.Toplevel(self)
        win.title("Syntax and features")
        win.geometry("860x720")
        t = tk.Text(win, wrap="word", font=("Consolas", 10), padx=12, pady=10, relief="flat")
        t.insert("1.0", HELP_TEXT)
        t.configure(state="disabled")
        vsb = ttk.Scrollbar(win, orient="vertical", command=t.yview)
        t.configure(yscrollcommand=vsb.set)
        t.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

    def open_settings(self):
        SettingsDialog(self)

    def apply_settings(self):
        self._make_fonts()
        self.editor_font = ("Consolas", int(self.settings["font_size"]))
        self.worksheet.editor.text.configure(font=self.editor_font)
        self.scratch.entry.configure(font=self.editor_font)
        self.worksheet.refresh_settings()
        self.converter.refresh_settings()
        self.save_settings()

    def open_library(self):
        LibraryDialog(self)

    def save_to_library(self):
        ed = self.worksheet.editor.text
        try:
            text = ed.get("sel.first", "sel.last")
        except tk.TclError:
            text = self.worksheet.editor.get()
        text = text.strip()
        if not text:
            messagebox.showinfo("Library", "Type (or select) the equations to save first.", parent=self)
            return
        SaveToLibraryDialog(self, text)


class SettingsDialog(tk.Toplevel):
    def __init__(self, app: App):
        super().__init__(app)
        self.app = app
        self.title("Preferences")
        self.transient(app)
        self.resizable(False, False)
        s = app.settings
        f = ttk.Frame(self, padding=14)
        f.pack(fill="both", expand=True)
        self.fmt = tk.StringVar(value=s["number_format"])
        self.digits = tk.IntVar(value=s["digits"])
        self.size = tk.IntVar(value=s["font_size"])
        self.system = tk.StringVar(value=units.SYSTEMS[s["unit_system"]])
        self.iters = tk.BooleanVar(value=s["show_iterations"])
        r = 0
        ttk.Label(f, text="Number format").grid(row=r, column=0, sticky="w", pady=3)
        ttk.Combobox(f, textvariable=self.fmt, state="readonly", width=12,
                     values=["auto", "fix", "sci", "eng"]).grid(row=r, column=1, sticky="w")
        ttk.Label(f, text="auto = significant figures, fix = decimal places,\n"
                          "sci = scientific, eng = engineering (powers of 1000)",
                  foreground="#777").grid(row=r, column=2, sticky="w", padx=8)
        r += 1
        ttk.Label(f, text="Digits").grid(row=r, column=0, sticky="w", pady=3)
        ttk.Spinbox(f, from_=1, to=15, textvariable=self.digits, width=6).grid(row=r, column=1, sticky="w")
        r += 1
        ttk.Label(f, text="Text size").grid(row=r, column=0, sticky="w", pady=3)
        ttk.Spinbox(f, from_=10, to=24, textvariable=self.size, width=6).grid(row=r, column=1, sticky="w")
        r += 1
        ttk.Label(f, text="Default unit system\n(for new worksheets)").grid(row=r, column=0, sticky="w", pady=3)
        ttk.Combobox(f, textvariable=self.system, state="readonly", width=28,
                     values=list(units.SYSTEMS.values())).grid(row=r, column=1, columnspan=2, sticky="w")
        r += 1
        ttk.Checkbutton(f, text="Show the iteration log after solving", variable=self.iters).grid(
            row=r, column=0, columnspan=3, sticky="w", pady=6)
        r += 1
        bar = ttk.Frame(f)
        bar.grid(row=r, column=0, columnspan=3, sticky="e", pady=(8, 0))
        ttk.Button(bar, text="OK", style="Accent.TButton", command=self.ok).pack(side="left", padx=4)
        ttk.Button(bar, text="Cancel", command=self.destroy).pack(side="left")
        self.grab_set()

    def ok(self):
        s = self.app.settings
        s["number_format"] = self.fmt.get()
        try:
            s["digits"] = max(1, min(15, int(self.digits.get())))
            s["font_size"] = max(10, min(24, int(self.size.get())))
        except (tk.TclError, ValueError):
            pass
        s["unit_system"] = [k for k, v in units.SYSTEMS.items() if v == self.system.get()][0]
        s["show_iterations"] = bool(self.iters.get())
        self.app.apply_settings()
        self.destroy()


class LibraryDialog(tk.Toplevel):
    def __init__(self, app: App):
        super().__init__(app)
        self.app = app
        self.title("Equation library")
        self.geometry("900x520")
        self.transient(app)
        self.entries = storage.load_library()
        paned = ttk.PanedWindow(self, orient="horizontal")
        paned.pack(fill="both", expand=True, padx=8, pady=8)
        self.tv = ttk.Treeview(paned, columns=("cat",), show="tree headings")
        self.tv.heading("#0", text="Name")
        self.tv.heading("cat", text="Category")
        self.tv.column("#0", width=260)
        self.tv.column("cat", width=110)
        paned.add(self.tv, weight=1)
        right = ttk.Frame(paned)
        paned.add(right, weight=2)
        self.text = tk.Text(right, height=10, font=("Consolas", 11), wrap="none", relief="flat",
                            background="#fafafa")
        self.text.pack(fill="both", expand=True)
        self.notes = ttk.Label(right, text="", foreground="#555", wraplength=520, justify="left")
        self.notes.pack(fill="x", pady=6)
        bar = ttk.Frame(self, padding=(8, 0, 8, 8))
        bar.pack(fill="x")
        ttk.Button(bar, text="Add to worksheet", style="Accent.TButton", command=self.add).pack(side="left")
        ttk.Button(bar, text="Replace worksheet", command=self.replace).pack(side="left", padx=4)
        ttk.Button(bar, text="Delete", command=self.delete).pack(side="left", padx=12)
        ttk.Button(bar, text="Close", command=self.destroy).pack(side="right")
        self.tv.bind("<<TreeviewSelect>>", lambda e: self.show())
        self.tv.bind("<Double-1>", lambda e: self.add())
        self.fill()

    def fill(self):
        self.tv.delete(*self.tv.get_children())
        for i, e in enumerate(self.entries):
            self.tv.insert("", "end", iid=str(i), text=e["name"], values=(e.get("category", ""),))
        if self.entries:
            self.tv.selection_set("0")

    def _sel(self):
        sel = self.tv.selection()
        return self.entries[int(sel[0])] if sel else None

    def show(self):
        e = self._sel()
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        if e:
            self.text.insert("1.0", e["text"])
            self.notes.configure(text=e.get("notes", ""))
        self.text.configure(state="disabled")

    def add(self):
        e = self._sel()
        if e:
            self.app.worksheet.editor.append(e["text"])
            self.app.nb.select(self.app.worksheet)
            self.destroy()

    def replace(self):
        e = self._sel()
        if e and self.app.worksheet.confirm_discard():
            self.app.worksheet.modified = False
            self.app.worksheet.new()
            self.app.worksheet.editor.set(e["text"])
            self.app.nb.select(self.app.worksheet)
            self.destroy()

    def delete(self):
        e = self._sel()
        if e and messagebox.askyesno("Delete", f"Delete '{e['name']}' from the library?", parent=self):
            self.entries.remove(e)
            storage.save_library(self.entries)
            self.fill()


class SaveToLibraryDialog(tk.Toplevel):
    def __init__(self, app: App, text: str):
        super().__init__(app)
        self.app = app
        self.text_value = text
        self.title("Save to library")
        self.transient(app)
        f = ttk.Frame(self, padding=12)
        f.pack(fill="both", expand=True)
        self.name = tk.StringVar()
        self.cat = tk.StringVar(value="My equations")
        ttk.Label(f, text="Name").grid(row=0, column=0, sticky="w")
        e = ttk.Entry(f, textvariable=self.name, width=40)
        e.grid(row=0, column=1, sticky="ew", pady=3)
        ttk.Label(f, text="Category").grid(row=1, column=0, sticky="w")
        cats = sorted({x.get("category", "") for x in storage.load_library()} | {"My equations"})
        ttk.Combobox(f, textvariable=self.cat, values=cats, width=38).grid(row=1, column=1, sticky="ew", pady=3)
        ttk.Label(f, text="Notes").grid(row=2, column=0, sticky="nw")
        self.notes = tk.Text(f, width=40, height=3, font=("Segoe UI", 10))
        self.notes.grid(row=2, column=1, sticky="ew", pady=3)
        prev = tk.Text(f, width=60, height=min(8, text.count("\n") + 1), font=("Consolas", 10),
                       background="#fafafa", relief="flat")
        prev.insert("1.0", text)
        prev.configure(state="disabled")
        prev.grid(row=3, column=0, columnspan=2, sticky="ew", pady=6)
        bar = ttk.Frame(f)
        bar.grid(row=4, column=0, columnspan=2, sticky="e")
        ttk.Button(bar, text="Save", style="Accent.TButton", command=self.save).pack(side="left", padx=4)
        ttk.Button(bar, text="Cancel", command=self.destroy).pack(side="left")
        e.focus_set()
        self.grab_set()

    def save(self):
        name = self.name.get().strip()
        if not name:
            messagebox.showinfo("Save", "Give it a name.", parent=self)
            return
        lib = storage.load_library()
        lib.append({"name": name, "category": self.cat.get().strip(), "text": self.text_value,
                    "notes": self.notes.get("1.0", "end").strip()})
        try:
            storage.save_library(lib)
        except OSError as e:
            messagebox.showerror("Save", str(e), parent=self)
            return
        self.app.status(f"Saved '{name}' to the library")
        self.destroy()


def main():
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
            # Own taskbar identity, so Windows shows our icon instead of Python's.
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("PCEngineeringCalculator")
        except Exception:
            pass
    app = App()
    app.mainloop()
