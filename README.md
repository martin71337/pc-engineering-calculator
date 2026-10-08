# PC Engineering Calculator

A desktop equation solver for formulas that are too long for a handheld calculator.
Type equations the way you'd write them, check them in a typeset preview, fill in the
values you know, and solve for the rest, iteratively if needed. Units are optional.

## Download (no Python needed)

1. Go to the **Releases** page of this repository and download `PC-Calculator-Windows.zip`.
2. Unzip the whole folder somewhere permanent (e.g. `Documents\PC Calculator`).
3. Double-click **`PC Calculator.exe`**. Optionally run `Create desktop shortcut.vbs`.

If Windows SmartScreen says "Windows protected your PC", click **More info → Run anyway**
(the app isn't code-signed).

## Running from source

Needs Python 3.11+ (tested on 3.14):

```bash
py -3.14 -m pip install -r requirements.txt
py -3.14 run_calculator.pyw
```

Or double-click **`Launch Calculator.bat`**.

To build the standalone zip yourself:

```bash
py -3.14 -m pip install pyinstaller
py -3.14 tools/build.py
```

## Tabs

### Worksheet: equation solver
1. Type one equation per line in **Equations**. Text after `#` is a comment.
2. The **Preview** shows each line as typeset math. Use it to check brackets and exponents.
3. Every variable appears in the **Variables** table. Fill in known values and leave the
   unknown(s) blank (or tick **Solve**).
4. Press **▶ Solve** (Ctrl+Enter or F5).

- Several equations are solved together. Definitions like `R = A/P` are substituted
  automatically, then the remaining equation(s) are solved exactly or iteratively.
- The iterative solver scans for **every real root**. If there are several, the others are
  listed with **Use** buttons. **Guess / Min / Max** control which root you get.
- Lines without `=` are evaluated after solving, which is useful for checks (`Q/A`).
- **Plot…** graphs both sides of the current line against a variable, with intersections marked.
- **Rearrange…** isolates any variable symbolically. **Simplify / Expand / Factor / d/dx / ∫ dx**
  work on the line the cursor is on. Results can be inserted back into the worksheet.
- **Results → Values** copies answers into the Value column for the next calculation.
- **File → Save** writes a `.pcalc` worksheet (equations, values, units, settings).
- **Library** (Ctrl+L) holds reusable formulas. A few examples are included, and you can save your own.

### Scratchpad: quick calculations
Line-by-line calculator with variables and units:

```
L = 24 ft
W = 12'6"
L*W              → 300 ft²
ans -> yd^2      → 33.3333 yd²
100 psi * 2 in^2 → 200 lbf
```

### Unit Converter
Pick a category (length, area, volume, flow, pressure, force, moment, line load,
unit weight, temperature, angle, slope/grade, …) to see a value in every unit, or type a
conversion such as `3.5 cfs to gpm`.

## Syntax cheat sheet

| Write | Meaning |
|---|---|
| `x^2`, `x^(2/3)` | powers (`**` also works) |
| `2x`, `2(x+1)`, `a b`, `A(1+z)` | implicit multiplication |
| `x/2y` | `x/(2y)`: a number next to a name binds tightly |
| `( ) [ ] { }` | all are parentheses |
| `sqrt cbrt root(x,n) abs exp ln` | functions |
| `log(x)` / `log(x, b)` | base-10 / base-b logarithm |
| `sin cos tan asin acos atan atan2(y,x) sinh …` | trig (follows the Deg/Rad switch) |
| `min max floor ceil sign x!` | misc |
| `pi` | π  (Euler's number is `exp(1)`) |
| `R_h`, `sigma_max`, `theta`, `lambda` | subscripts and Greek letters in the preview |

**Every single letter is a variable**, including `e`, `E`, `I`, `S`, `N` and `Q`.

## Units (optional)

Values may include units: `12.5 ft`, `3 in`, `12'6"`, `450 gpm`, `2.5 ksi`, `30 deg`.
On an unknown, the **Unit** column is the unit you want the answer in.

The **Unit system** setting controls what the numbers are converted to before solving:

* **US (ft, lb, s)**: lengths in ft, forces in lbf, pressures in lbf/ft². Use this for
  US-customary empirical formulas such as Manning's `1.49` or Hazen-Williams.
* **SI (m, kg, s)**: metres, newtons, pascals.
* **As entered**: units are labels only, and numbers are used exactly as typed.

In US and SI, temperatures are converted to absolute scales (°R / K) before solving, so
`68 degF` enters the math as 527.67. Use **As entered** if a formula expects °F or °C.

Extra units defined here: `cfs gpm gpd mgd psf ksf pcf kcf plf klf acre_ft`
(`pcf` is a unit *weight*, lbf/ft³).

## Files

```
run_calculator.pyw        entry point
pc_calculator.spec        PyInstaller recipe (tools/build.py builds dist/PC-Calculator-Windows.zip)
tools/make_icon.py        draws calculator/assets/calculator.ico
calculator/engine.py      parsing, symbolic algebra, numeric solvers (sympy + scipy)
calculator/units.py       unit handling (pint)
calculator/scratch.py     scratchpad evaluator
calculator/render.py      typeset math (matplotlib mathtext)
calculator/storage.py     settings / library / worksheet files (%APPDATA%\PCCalculator)
calculator/gui/           Tkinter interface
tests/test_engine.py      py -3.14 -m unittest discover tests
```
