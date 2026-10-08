# PyInstaller build recipe.  Build with:  py -3.14 tools/build.py
# Produces dist/PC Calculator/PC Calculator.exe (a folder that runs without Python installed).
from PyInstaller.utils.hooks import collect_data_files

datas = [("calculator/assets", "calculator/assets")]
datas += collect_data_files("pint")          # unit definition files
datas += collect_data_files("matplotlib")    # mathtext fonts for the typeset preview

a = Analysis(
    ["run_calculator.pyw"],
    pathex=["."],
    datas=datas,
    hiddenimports=["matplotlib.backends.backend_tkagg", "PIL._tkinter_finder"],
    excludes=["PyQt5", "PyQt6", "PySide2", "PySide6", "IPython", "jupyter", "notebook",
              "pytest", "pandas", "tests"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="PC Calculator",
    icon="calculator/assets/calculator.ico",
    console=False,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="PC Calculator", upx=False)
