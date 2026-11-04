from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src/python'))
from zynq_bjt.tx1 import Tx1


class FakeMMIO:
    def __init__(self, lines=3): self.lines = lines; self.writes = []
    def read(self, address): return 0x54583101 if address == 0x44 else self.lines << 8
    def write(self, address, value): self.writes.append((address, value))


class RegisterTx1(Tx1):
    def __init__(self):
        super().__init__(FakeMMIO(), lambda _: None)
        self.registers = {1: 0x2195, 2: 0, 3: 0x0200, 4: 0x0200, 7: 0, 8: 0x8000}
        self.transactions = []
    def transfer(self, register, value=None):
        self.transactions.append((register, value))
        if value is None: return self.registers[register]
        self.registers[register] = value


class Tests(unittest.TestCase):
    def test_initialization_stays_powered_down_and_preserves_reserved_bits(self):
        tx = RegisterTx1(); tx.initialize_muted()
        self.assertFalse(tx.state()['enabled'])
        self.assertEqual(tx.state()['code'], 0)
        self.assertEqual(tx.registers[3], 0x201)
        self.assertEqual(tx.registers[4], 0x301)
        self.assertEqual(tx.registers[8], 0x8000)
        self.assertEqual(tx.state()['code_basis'], 'pending_until_enabled')
        tx.code(33)
        self.assertFalse(tx.state()['enabled'])
        tx.enable(True)
        self.assertTrue(tx.state()['enabled'])
        self.assertEqual(tx.state()['code'], 33)
        self.assertEqual(tx.state()['code_basis'], 'device_register_readback')

    def test_repeated_muted_apply_commits_only_latest_value_once(self):
        tx = RegisterTx1(); tx.initialize_muted()
        tx.code(1000); tx.code(2000); tx.code(0); tx.code(1638)
        self.assertEqual([v for r,v in tx.transactions if r==8 and v is not None], [])
        self.assertEqual(tx.state()['code'],1638)
        self.assertEqual(tx.state()['device_code'],2048)
        tx.enable(True)
        self.assertEqual([v for r,v in tx.transactions if r==8 and v is not None],[0x6660])
        tx.enable(True)
        self.assertEqual([v for r,v in tx.transactions if r==8 and v is not None],[0x6660])

    def test_zero_start_then_live_change_and_stop_restart(self):
        tx=RegisterTx1();tx.initialize_muted();tx.enable(True)
        self.assertEqual(tx.registers[8],0)
        tx.code(1638)
        self.assertEqual(tx.registers[8],0x6660)
        tx.enable(False);tx.code(819);tx.code(2048)
        self.assertEqual(tx.registers[8],0x6660)
        tx.enable(True)
        self.assertEqual(tx.registers[8],0x8000)
        tx.enable(False);tx.enable(True)
        self.assertTrue(tx.state()['enabled'])
        self.assertEqual(tx.state()['code'],2048)

    def test_partial_enable_failure_prevents_second_commit_retry(self):
        tx=RegisterTx1();tx.initialize_muted();tx.code(1638)
        original=tx.verified
        def fail_enable(reg,value):
            if reg==3 and value==0:raise RuntimeError('transport failure')
            return original(reg,value)
        tx.verified=fail_enable
        with self.assertRaisesRegex(RuntimeError,'transport failure'):tx.enable(True)
        with self.assertRaisesRegex(RuntimeError,'not initialized'):tx.enable(True)
        self.assertEqual([v for r,v in tx.transactions if r==8 and v is not None],[0x6660])

    def test_nack_releases_both_open_drain_pins(self):
        io = FakeMMIO()
        with self.assertRaisesRegex(RuntimeError, 'NACK'): Tx1(io, lambda _: None).transfer(8, 0)
        self.assertEqual(io.writes[-1], (0x40, 3))
        self.assertTrue(all(0 <= value <= 3 for address, value in io.writes))

    def test_stuck_clock_times_out_and_releases_lines(self):
        io = FakeMMIO(lines=0)
        with self.assertRaisesRegex(RuntimeError, 'STOP also failed'): Tx1(io, lambda _: None).transfer(1)
        self.assertEqual(io.writes[-1], (0x40, 3))
        self.assertLess(len(io.writes), 20)


if __name__ == '__main__': unittest.main()
