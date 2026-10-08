"""Settings, equation library and worksheet files (all JSON)."""
from __future__ import annotations

import json
import os
from pathlib import Path

APP_DIR = Path(os.environ.get("APPDATA") or Path.home()) / "PCCalculator"
SETTINGS_FILE = APP_DIR / "settings.json"
LIBRARY_FILE = APP_DIR / "library.json"
WORKSHEET_EXT = ".pcalc"

DEFAULT_SETTINGS = {
    "angle_mode": "deg",
    "unit_system": "US",
    "number_format": "auto",
    "digits": 6,
    "font_size": 14,
    "show_iterations": False,
    "recent": [],
    "geometry": "",
}

STARTER_LIBRARY = [
    {"name": "Quadratic equation", "category": "Math",
     "text": "a*x^2 + b*x + c = 0",
     "notes": "Solve for x; both real roots are listed."},
    {"name": "Right triangle", "category": "Math",
     "text": "c^2 = a^2 + b^2\ntheta = atan(a/b)   # angle opposite side a",
     "notes": "Enter any two of a, b, c (or one side and theta)."},
    {"name": "Continuity", "category": "Hydraulics",
     "text": "Q = V*A",
     "notes": "Flow = velocity x area."},
    {"name": "Manning's equation (US)", "category": "Hydraulics",
     "text": "Q = 1.49/n*A*R^(2/3)*S^(1/2)   # Q cfs, A ft², R ft, S ft/ft",
     "notes": "US customary form. Use unit system 'US' if you attach units."},
    {"name": "Manning's - trapezoidal channel (US)", "category": "Hydraulics",
     "text": ("A = (b + z*y)*y              # flow area\n"
              "P = b + 2*y*sqrt(1 + z^2)    # wetted perimeter\n"
              "R = A/P                      # hydraulic radius\n"
              "Q = 1.49/n*A*R^(2/3)*S^(1/2)\n"
              "V = Q/A"),
     "notes": "Give Q, b, z, n, S and solve for normal depth y (iterative)."},
    {"name": "Hazen-Williams velocity (US)", "category": "Hydraulics",
     "text": "V = 1.318*C*R^0.63*S^0.54   # V ft/s, R ft",
     "notes": "C = roughness coefficient, S = friction slope."},
    {"name": "Simple beam, uniform load", "category": "Structural",
     "text": "M = w*L^2/8\nDelta = 5*w*L^4/(384*E*I)",
     "notes": "Watch units: attach units or keep everything consistent."},
]


def _read_json(path: Path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def load_settings() -> dict:
    s = dict(DEFAULT_SETTINGS)
    data = _read_json(SETTINGS_FILE, {})
    if isinstance(data, dict):
        s.update({k: v for k, v in data.items() if k in DEFAULT_SETTINGS})
    return s


def save_settings(settings: dict) -> None:
    try:
        _write_json(SETTINGS_FILE, settings)
    except OSError:
        pass


def add_recent(settings: dict, path: str) -> None:
    recent = [p for p in settings.get("recent", []) if os.path.normcase(p) != os.path.normcase(path)]
    settings["recent"] = [path] + recent[:9]


def load_library() -> list[dict]:
    data = _read_json(LIBRARY_FILE, None)
    if not isinstance(data, list):
        return [dict(e) for e in STARTER_LIBRARY]
    return [e for e in data if isinstance(e, dict) and "name" in e and "text" in e]


def save_library(entries: list[dict]) -> None:
    _write_json(LIBRARY_FILE, entries)


def save_worksheet(path: str, data: dict) -> None:
    data = dict(data)
    data["format"] = "pc-calculator-worksheet"
    data["version"] = 1
    _write_json(Path(path), data)


def load_worksheet(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict) or "equations" not in data:
        raise ValueError("Not a calculator worksheet file")
    return data
