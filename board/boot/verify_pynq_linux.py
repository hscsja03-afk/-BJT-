"""Run as root on the custom carrier: load the paired overlay and read IDs only."""
import hashlib
import json
from pathlib import Path
import platform
import sys

import pynq
from pynq import Overlay
from zynq_bjt.mio import Mio

folder = Path('/home/xilinx/jupyter_notebooks/zynq_bjt/overlay')
bitfile = folder / 'bjt.bit'
evidence = dict(python=sys.version, pynq=pynq.__version__, kernel=platform.release(),
                files={p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                       for p in (bitfile, bitfile.with_suffix('.hwh'))})
Mio.preflight_from_pynq()
overlay = Overlay(str(bitfile), download=False)
info = overlay.ip_dict['adda_core_0']
assert info['phys_addr'] == 0x43C00000 and info['addr_range'] == 0x10000, info
overlay.download()
assert overlay.is_loaded()
io = overlay.adda_core_0.mmio
expected = {0x00: 0x41444441, 0x20: 1024, 0x30: 50000000,
            0x44: 0x54583101, 0x48: 0x47504901, 0x80: 0x41574701}
actual = {offset: io.read(offset) for offset in expected}
assert actual == expected, actual
evidence.update(overlay_loaded=True, mio_preflight='passed', registers={hex(k): hex(v) for k,v in actual.items()},
                control=io.read(0x04), dac_mode=io.read(0x10),
                analog_output_enable_commands=0, gpio_lines_exported=0,
                limit='No converter initialization, ADC acquisition, analog measurement or TFT visual verification')
assert evidence['dac_mode'] == 0, evidence
Path('/home/xilinx/pynq_linux_overlay_evidence.json').write_text(json.dumps(evidence, indent=2))
print(json.dumps(evidence, indent=2))
