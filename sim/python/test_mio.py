"""A failed input-direction write must not skip GPIO release or hide retries."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import errno

sys.path.insert(0, str(Path(__file__).resolve().parents[2]/'src/python'))
from zynq_bjt.mio import Mio, PINS, INACTIVE


class Tests(unittest.TestCase):
    def board(self):
        pins = Mio.__new__(Mio)
        pins.root = Path('/fake-gpio'); pins.base = 906
        pins.owned = [9, 10]; pins.directions = {9: False, 10: True}
        return pins

    def test_failed_input_still_unexports_all_owned_pins(self):
        pins = self.board(); releases = []
        def write(path, value):
            if path.name == 'direction' and 'gpio916' in str(path):
                raise OSError('input rejected')
            if path.name == 'unexport': releases.append(int(value))
        with patch.object(Path, 'write_text', write):
            with self.assertRaisesRegex(RuntimeError, 'MIO10 in'):
                pins.close()
        self.assertEqual(releases, [916, 915]); self.assertEqual(pins.owned, [])

    def test_failed_unexport_remains_owned_and_can_be_retried(self):
        pins = self.board(); releases = []
        def write(path, value):
            if path.name == 'unexport':
                releases.append(int(value))
                if int(value) == 916: raise OSError('unexport rejected')
        with patch.object(Path, 'write_text', write):
            with self.assertRaisesRegex(RuntimeError, 'MIO10 unexport'):
                pins.close()
        self.assertEqual(pins.owned, [10]); self.assertEqual(releases, [916, 915])
        with patch.object(Path, 'write_text', lambda path, value: None):
            pins.close()
        self.assertEqual(pins.owned, [])

    def test_zynq_output_only_pins_initialize_and_release_without_input_request(self):
        exported, modes, writes = set(), {}, []
        class Slcr:
            def read(self, offset): return (3 if offset//4 < 16 else 1) << 9
        def exists(path):
            name = path.parent.name if path.name == 'direction' else path.name
            return name.startswith('gpio') and name[4:].isdigit() and int(name[4:]) in exported
        def write(path, value):
            if path.name == 'export': exported.add(int(value)); return
            if path.name == 'unexport': exported.remove(int(value)); return
            pin = int(path.parent.name[4:])-906
            if path.name == 'direction':
                if pin in (7,8) and value == 'in': raise OSError(errno.EINVAL, 'Invalid argument')
                modes[pin] = value; writes.append((pin,value))
        with patch.object(Path, 'exists', exists), patch.object(Path, 'write_text', write):
            pins = Mio(Slcr(), 906, '/fake-gpio')
            self.assertEqual(modes[7], 'low'); self.assertEqual(modes[8], 'low')
            self.assertEqual(modes[9], 'in')
            for pin, value in INACTIVE.items():
                self.assertEqual(modes[pin], 'high' if value else 'low')
            for guard in (32,33,10,13,31):
                self.assertLess(writes.index((guard,'high')), writes.index((7,'low')))
            pins.output(29, False); self.assertEqual(modes[29], 'in')
            pins.output(29, True); self.assertEqual(modes[29], 'low')
            with self.assertRaisesRegex(ValueError, 'output-only'): pins.output(7, False)
            pins.write(7,1); pins.write(8,1)
            pins.close()
            self.assertEqual(modes[7], 'low'); self.assertEqual(modes[8], 'low')
            self.assertEqual(exported, set()); self.assertEqual(pins.owned, [])

    def test_output_only_idle_failure_still_attempts_unexport(self):
        pins = self.board(); pins.owned = [7,8]
        releases = []
        def write(path, value):
            if path.name == 'direction' and 'gpio914' in str(path):
                raise OSError('idle write failed')
            if path.name == 'unexport': releases.append(int(value))
        with patch.object(Path, 'write_text', write):
            with self.assertRaisesRegex(RuntimeError, 'MIO8 low'): pins.close()
        self.assertEqual(releases, [914,913]); self.assertEqual(pins.owned, [])


if __name__ == '__main__': unittest.main()
