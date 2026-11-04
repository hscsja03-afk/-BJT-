"""Source entry and PyInstaller entry for the Windows workbench."""
import sys
from pathlib import Path

if not getattr(sys, 'frozen', False):
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root/'src/python'))
    sys.path.insert(0, str(root/'build/tool_deps/ssh_runtime'))

from zynq_bjt.desktop import main

main()
