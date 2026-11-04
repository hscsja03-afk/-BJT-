"""Keep desktop measurements beside the project, independent of launch cwd."""
from pathlib import Path
import sys


def workspace_path(override=None, *, executable=None, source=None):
    if override is not None:
        return Path(override).expanduser().resolve()
    anchor = Path(executable or sys.executable) if (executable or getattr(sys, 'frozen', False)) else Path(source or __file__)
    anchor = anchor.resolve()
    for parent in anchor.parents:
        if (parent/'src/python/zynq_bjt').is_dir() and (parent/'board').is_dir():
            return parent/'measurements'
    # A portable distribution keeps its data next to the executable.
    return anchor.parent/'measurements'
