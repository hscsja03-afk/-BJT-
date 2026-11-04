"""Read-only host audit of generated Nanya PS initialization; no board access."""
import hashlib
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REL = Path('vivado/linux_platform.gen/sources_1/bd/system/ip/system_ps7_0/ps7_init.tcl')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def profile(name):
    folder = ROOT / 'build/work' / name
    config = dict(line.split('=', 1) for line in
                  (folder / 'ps_config.txt').read_text().splitlines() if '=' in line)
    text = (folder / REL).read_text()
    procs = dict(re.findall(r'proc (\S+) \{\} \{\n(.*?)\n\}', text, re.S))
    regs = {}
    for address, mask, value in re.findall(
            r'mask_write (0[Xx][0-9A-Fa-f]+) (0[Xx][0-9A-Fa-f]+) (0[Xx][0-9A-Fa-f]+)',
            procs['ps7_ddr_init_data_3_0']):
        a, m, v = [int(x, 16) for x in (address, mask, value)]
        regs[a] = (regs.get(a, 0) & ~m) | (v & m)
    return folder, config, procs, regs


def main():
    old_folder, old_config, old_procs, old_regs = profile('linux_platform')
    folder, config, procs, regs = profile('linux_platform_nanya533')
    for name in ('ps7_pll_init_data_3_0', 'ps7_clock_init_data_3_0',
                 'ps7_mio_init_data_3_0', 'ps7_peripherals_init_data_3_0',
                 'ps7_post_config_3_0'):
        assert procs[name] == old_procs[name], name
    # Board geometry, delays and training must remain the same in this comparison.
    changed = {k: {'before': old_config.get(k), 'after': v}
               for k, v in config.items() if old_config.get(k) != v}
    allowed = {'PARTNO', 'SPEED_BIN', 'CL', 'T_RCD', 'T_RP', 'T_RC', 'T_FAW'}
    assert set(changed) <= {'CONFIG.PCW_UIPARAM_DDR_' + k for k in allowed}, changed
    freq = float(config['CONFIG.PCW_UIPARAM_ACT_DDR_FREQ_MHZ'])
    assert abs(freq - 533.333333) < 0.001
    period_ns = 1000 / freq
    # Field positions are documented in Vivado's generated ps7_init.c.
    fields = {
        'tRC': (0xF8006014, 0, 6, 47.91),
        'tRFC': (0xF8006014, 6, 8, 260),
        'tFAW': (0xF8006018, 10, 6, 50),
        'tRAS': (0xF8006018, 22, 5, 34),
        'tRCD': (0xF800601C, 28, 4, 13.91),
        'tRRD': (0xF8006020, 5, 3, 10),
        'tRP': (0xF8006020, 12, 4, 13.91),
        'tAA': (0xF8006020, 24, 5, 13.91),
    }
    timing = {}
    for name, (address, shift, width, minimum) in fields.items():
        cycles = (regs[address] >> shift) & ((1 << width) - 1)
        old_cycles = (old_regs[address] >> shift) & ((1 << width) - 1)
        actual = cycles * period_ns
        assert actual >= minimum, (name, actual, minimum)
        timing[name] = dict(cycles=cycles, ns=actual, minimum_ns=minimum,
                            previous_cycles=old_cycles, previous_ns=old_cycles * period_ns)
    assert timing['tAA']['ns'] <= 20
    assert timing['tRRD']['cycles'] >= 4
    assert timing['tRC']['cycles'] >= timing['tRAS']['cycles'] + timing['tRP']['cycles']
    # MR0 CL=8 uses A6:A4=100, A2=0. MR2 CWL=6 uses A5:A3=001.
    assert regs[0xF8006030] & 0x74 == 0x40
    assert regs[0xF800602C] & 0x38 == 0x08
    manifest = json.loads((ROOT / 'build/work/ddr_lane_probe/manifest.json').read_text())
    for path, key in [('board/ddr_lane_probe.c', 'source_sha256'),
                      ('build/work/ddr_lane_probe/ddr_lane_probe.elf', 'elf_sha256'),
                      ('build/work/ddr_lane_probe/symbols.txt', 'symbols_sha256')]:
        assert sha(ROOT / path) == manifest[key], path
    report = dict(status='offline_generated_parameters_checked', board_tested=False,
                  frequency_mhz=freq, changes=changed, timings=timing,
                  non_ddr_init_unchanged=True, same_ocm_probe_hashes_verified=True,
                  ps_init_sha256=sha(folder / REL), xsa_sha256=sha(folder / 'core_2v5.xsa'),
                  baseline_ps_init_sha256=sha(old_folder / REL),
                  limits='Checks selected generated timings only, not board timing/voltage/training or DDR stability.')
    out = ROOT / 'report/nanya_profile_audit.json'
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
