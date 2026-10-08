"""Build the standalone Windows app and zip it for sharing.

    py -3.14 -m pip install pyinstaller -r requirements.txt
    py -3.14 tools/build.py

Output: dist/PC-Calculator-Windows.zip  (unzip anywhere, run "PC Calculator.exe").
"""
import os
import shutil
import subprocess
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DIST = os.path.join(ROOT, "dist")
APP_DIR = os.path.join(DIST, "PC Calculator")
ZIP_BASE = os.path.join(DIST, "PC-Calculator-Windows")

README = """PC Engineering Calculator
=========================

1. Unzip this whole folder somewhere permanent (e.g. Documents\\PC Calculator).
2. Double-click "PC Calculator.exe".  No Python install is needed.
3. Optional: double-click "Create desktop shortcut.vbs" for a desktop icon.

If Windows SmartScreen says "Windows protected your PC", click "More info" ->
"Run anyway" (the app isn't code-signed).

Settings and your equation library are saved in %APPDATA%\\PCCalculator.
"""

# Creates a desktop shortcut pointing at the exe in the same folder as this script.
SHORTCUT_VBS = """Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
here = fso.GetParentFolderName(WScript.ScriptFullName)
Set lnk = sh.CreateShortcut(sh.SpecialFolders("Desktop") & "\\PC Calculator.lnk")
lnk.TargetPath = here & "\\PC Calculator.exe"
lnk.WorkingDirectory = here
lnk.IconLocation = here & "\\PC Calculator.exe, 0"
lnk.Description = "PC Engineering Calculator"
lnk.Save
MsgBox "Desktop shortcut created.", 64, "PC Calculator"
"""


def main():
    subprocess.check_call([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
                           "pc_calculator.spec"], cwd=ROOT)
    with open(os.path.join(APP_DIR, "README.txt"), "w", encoding="utf-8") as f:
        f.write(README)
    with open(os.path.join(APP_DIR, "Create desktop shortcut.vbs"), "w", encoding="utf-8") as f:
        f.write(SHORTCUT_VBS)
    if os.path.exists(ZIP_BASE + ".zip"):
        os.remove(ZIP_BASE + ".zip")
    shutil.make_archive(ZIP_BASE, "zip", DIST, "PC Calculator")
    size = os.path.getsize(ZIP_BASE + ".zip") / 1e6
    print(f"\nBuilt {ZIP_BASE}.zip ({size:.0f} MB)")


if __name__ == "__main__":
    main()
