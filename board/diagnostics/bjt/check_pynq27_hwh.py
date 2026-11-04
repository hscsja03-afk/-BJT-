"""Exercise the pinned upstream PYNQ 2.7 XML parser on generated HWH, on a host.

Only pynq.ps architecture constants are substituted to select the Zynq parser.
This does not emulate PYNQ, Linux, ARM, GPIO, MMIO or FPGA programming.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType
from unittest.mock import patch
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[3]
URL = 'https://raw.githubusercontent.com/Xilinx/PYNQ/v2.7.0/pynq/pl_server/hwh_parser.py'
SHA256 = '9038f5b618da3ed5f88504d150f9481487a6f0a0f73ec0a79f530415a87c37f0'
PARSER = ROOT / 'build/tool_deps/pynq_2_7/hwh_parser.py'


def check(hwh, download_parser=False):
    if not PARSER.is_file():
        if not download_parser:
            raise FileNotFoundError('Pinned upstream parser missing; run with --download-parser')
        with urlopen(URL, timeout=30) as response:
            source = response.read()
        if hashlib.sha256(source).hexdigest() != SHA256:
            raise ValueError('Downloaded upstream parser hash differs from the reviewed source')
        PARSER.parent.mkdir(parents=True, exist_ok=True)
        PARSER.write_bytes(source)
    if hashlib.sha256(PARSER.read_bytes()).hexdigest() != SHA256:
        raise ValueError('Upstream parser was modified')
    arch = ModuleType('pynq.ps')
    arch.CPU_ARCH_IS_SUPPORTED = True
    arch.CPU_ARCH = arch.ZYNQ_ARCH = 'armv7l'
    arch.ZU_ARCH = 'aarch64'
    spec = importlib.util.spec_from_file_location('upstream_pynq27_hwh', PARSER)
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {'pynq': ModuleType('pynq'), 'pynq.ps': arch}):
        spec.loader.exec_module(module)
        parsed = module.HWH(str(hwh))
    info = parsed.ip_dict.get('adda_core_0', {})
    if info.get('phys_addr') != 0x43c00000 or info.get('addr_range') != 0x10000:
        raise ValueError('Upstream parser did not expose the driver address contract')
    if info.get('type') != 'xilinx.com:module_ref:adda_core:1.0':
        raise ValueError('Unexpected upstream module identity')
    if parsed.clock_dict[0]['enable'] != 1:
        raise ValueError('FCLK0 is not enabled in parsed metadata')
    return {
        'result': 'passed_xml_parser_check', 'python': sys.version,
        'upstream_url': URL, 'upstream_sha256': SHA256,
        'hwh_path': str(hwh), 'hwh_sha256': hashlib.sha256(hwh.read_bytes()).hexdigest(),
        'ip_keys': sorted(parsed.ip_dict),
        'peripheral': {k: info.get(k) for k in ('fullpath', 'type', 'phys_addr', 'addr_range', 'mem_id', 'memtype')},
        'clock_dict': parsed.clock_dict, 'board_tested': False,
        'limits': 'Host XML parsing with substituted Zynq architecture constants only; not an Overlay download, ARM/PYNQ runtime test or analog validation.',
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('hwh', type=Path, nargs='?', default=ROOT / 'build/work/baseline50/bjt.hwh')
    parser.add_argument('--download-parser', action='store_true')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    report = check(args.hwh.resolve(), args.download_parser)
    text = json.dumps(report, indent=2, ensure_ascii=False) + '\n'
    if args.output:
        args.output.write_text(text, encoding='utf-8')
    print(text, end='')


if __name__ == '__main__':
    main()
