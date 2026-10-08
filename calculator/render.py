"""Typeset math rendering: LaTeX -> PNG (matplotlib mathtext) -> Tk PhotoImage."""
from __future__ import annotations

import base64
import functools
import io

import matplotlib

matplotlib.use("TkAgg")
from matplotlib.font_manager import FontProperties  # noqa: E402
from matplotlib.mathtext import math_to_image  # noqa: E402


@functools.lru_cache(maxsize=1024)
def latex_png(latex: str, size: int = 16, color: str = "#000000", dpi: int = 100) -> bytes | None:
    """Render LaTeX math to PNG bytes. Returns None if mathtext can't handle it."""
    buf = io.BytesIO()
    try:
        math_to_image(f"${latex}$", buf, prop=FontProperties(size=size, math_fontfamily="dejavusans"),
                      dpi=dpi, format="png", color=color)
    except Exception:
        return None
    return buf.getvalue()


# Set by the app from the screen DPI so math matches the size of normal text.
DPI = 100


def photo_image(latex: str, size: int = 16, color: str = "#000000"):
    """Tk PhotoImage for the LaTeX, or None. Must be called from the Tk thread."""
    import tkinter as tk

    data = latex_png(latex, size, color, DPI)
    if data is None:
        return None
    return tk.PhotoImage(data=base64.b64encode(data).decode("ascii"))
