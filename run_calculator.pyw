"""Start the PC Engineering Calculator (double-click, or: py -3.14 run_calculator.pyw)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from calculator.gui.app import main  # noqa: E402

if __name__ == "__main__":
    main()
