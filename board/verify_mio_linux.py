"""Board check for the MIO7/8 Linux restriction; no converter/output enable."""
import argparse
import json
from pathlib import Path
import time
from pynq import GPIO, MMIO
from zynq_bjt.mio import Mio, PINS, INACTIVE


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--report', required=True)
    args = parser.parse_args()
    root = Path('/sys/class/gpio')
    core = MMIO(0x43c00000, 0x10000)
    evidence = {'timestamp': time.time(), 'gpio_base': GPIO.get_gpio_base(),
                'control_before': core.read(4), 'dac_mode_before': core.read(0x10),
                'converter_initialization_performed': False, 'output_enable_commands': 0}
    pins = None
    try:
        pins = Mio.from_pynq()
        evidence['owned'] = list(pins.owned)
        evidence['directions'] = {str(p): (pins.path(p)/'direction').read_text().strip() for p in PINS}
        evidence['values'] = {str(p): pins.read(p) for p in PINS}
        assert evidence['directions']['7'] == evidence['directions']['8'] == 'out'
        assert evidence['directions']['9'] == 'in'
        assert all(evidence['values'][str(p)] == v for p,v in INACTIVE.items())
        pins.output(29, False)
        assert (pins.path(29)/'direction').read_text().strip() == 'in'
        pins.output(29, True)
        assert (pins.path(29)/'direction').read_text().strip() == 'out'
        evidence['bidirectional_mio29'] = 'passed'
        pins.close()
        evidence['exported_after'] = [p.name for p in root.glob('gpio[0-9]*')]
        assert not evidence['exported_after']
        evidence['control_after'] = core.read(4)
        evidence['dac_mode_after'] = core.read(0x10)
        assert evidence['control_before'] == evidence['control_after']
        assert evidence['dac_mode_before'] == evidence['dac_mode_after']
        evidence['passed'] = True
    except BaseException as error:
        evidence['error'] = repr(error)
        raise
    finally:
        if pins is not None:
            try: pins.close()
            except Exception as error: evidence['cleanup_error'] = repr(error)
        Path(args.report).write_text(json.dumps(evidence, indent=2), encoding='utf-8')
        print(json.dumps(evidence, indent=2))


if __name__ == '__main__': main()
