"""Desktop boundary tests: real gating, cancellation, cleanup, protocol lease."""
from dataclasses import asdict
import io
import json
from pathlib import Path
import queue
import sys
import tempfile
import threading
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src/python'))
from zynq_bjt.desktop_session import Session, waveform, MEASUREMENTS
from zynq_bjt.desktop_agent import serve, PREFIX
from zynq_bjt.desktop_transport import SshTransport


class Pipe:
    def __init__(self): self.lines = queue.Queue()
    def __iter__(self): return self
    def __next__(self):
        line = self.lines.get(timeout=5)
        if line is None: raise StopIteration
        return line
    def send(self, message): self.lines.put(json.dumps(message)+'\n')


class Output:
    def __init__(self): self.messages = queue.Queue()
    def write(self, value): self.messages.put(json.loads(value[len(PREFIX):]))
    def flush(self): pass
    def reply(self, number, timeout=5):
        end = time.monotonic()+timeout
        while time.monotonic() < end:
            msg = self.messages.get(timeout=max(.01, end-time.monotonic()))
            if msg.get('id') == number: return msg
        raise TimeoutError()


class Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.session = Session(ROOT/'data', self.temp.name, simulated=True)

    def tearDown(self):
        self.session.close(); self.temp.cleanup()

    def test_readonly_connection_does_not_create_board_or_outputs(self):
        status = self.session.status()
        self.assertFalse(status['initialized'])
        self.assertIsNone(self.session.board)
        with self.assertRaisesRegex(RuntimeError, '初始化'):
            self.session.output(dict(channel=0, action='start', offset=100))
        self.assertEqual(list(Path(self.temp.name).iterdir()), [])

    def test_adc_clock_switch_preserves_gpio_and_changes_physical_and_record_rates(self):
        self.session.initialize()
        self.session.gpio(dict(mask=127,value=21))
        status=self.session.dispatch('adc_clock',dict(adc_divider=16))
        self.assertEqual(status['sample_rates_hz'],[62500000.]*2)
        self.assertEqual(status['gpio']['output'],21)
        frame=self.session.capture(dict(sample_count=4096,sample_stride=4))
        self.assertEqual(tuple(frame['adc_sample_rates_hz']),(62500000.,)*2)
        self.assertEqual(tuple(frame['sample_rates_hz']),(15625000.,)*2)
        self.assertEqual(len(frame['words'][0]),4096)

    def test_adc_switch_does_not_interrupt_enabled_tx(self):
        self.session.initialize();board=self.session.board
        board.enable(2,True)
        with self.assertRaisesRegex(ValueError,'停止TX'):
            self.session.adc_clock(dict(adc_divider=16))
        self.assertIs(self.session.board,board)
        self.assertTrue(board.output(2).enabled)

    def test_invalid_adc_divider_rejected_before_initialization(self):
        for divider in (0,4,True,16.0,'16'):
            with self.assertRaises(ValueError):self.session.adc_clock(dict(adc_divider=divider))
        self.assertIsNone(self.session.board)

    def test_hardware_scan_and_unsupported_profiles_reject_without_writes(self):
        self.session.initialize()
        board = self.session.board
        board.simulated = False
        self.session.simulated = False
        request = dict(measurement='input', fixture_confirmed=True,
                       config=dict(tx1_stop_v=.06, frames_per_point=2))
        with self.assertRaisesRegex(ValueError, 'qualified'): self.session.scan(request)
        board.simulated = True; self.session.simulated = True
        for profile, method in [('unknown', 'step'), ('npn_small', 'pulse')]:
            with self.assertRaises(ValueError):
                self.session.scan(dict(request, profile=profile, method=method))
        self.assertFalse(any(board.enabled)); self.assertEqual(board.gpio_value, 0)
        self.assertEqual(list(Path(self.temp.name).iterdir()), [])

    def test_cancel_preserves_data_and_stops_owned_outputs(self):
        self.session.initialize()
        self.session.board.gpio(127, 21)
        def emit(kind, value):
            if kind == 'point': self.session.cancel.set()
        result = self.session.scan(dict(measurement='input', config=dict(tx1_stop_v=.3,
            settle_s=0, frame_gap_s=0, curve_settle_s=0, frames_per_point=2)), emit)
        self.assertEqual(result['state']['status'], 'cancelled')
        self.assertEqual(result['state']['points'], 1)
        self.assertTrue((Path(result['directory'])/'frames.jsonl').exists())
        self.assertFalse(any(self.session.board.enabled[:2]))
        self.assertEqual(self.session.board.gpio_value, 21)

    def test_all_four_measurements_write_explicit_simulation_records(self):
        self.session.initialize()
        for name, (cls, _, csv_name) in MEASUREMENTS.items():
            config = asdict(cls()); config['settle_s'] = 0
            if name == 'input': config.update(tx1_stop_v=.06, frame_gap_s=0, curve_settle_s=0)
            if 'source_adc_per_v' in config: config['source_adc_per_v'] = .206
            result = self.session.scan(dict(measurement=name, config=config))
            self.assertEqual(result['state']['status'], 'complete', result['state'].get('error'))
            self.assertTrue(result['state']['simulated'])
            self.assertTrue((Path(result['directory'])/csv_name).is_file())
            self.assertFalse(any(self.session.board.enabled))

    def test_output_validation_precedes_any_side_effect(self):
        self.session.initialize()
        before = list(self.session.board.codes)
        for request in [dict(channel=0, offset=4096, mode='dc_code'),
                        dict(channel=1, offset=65000, peak=1000, mode='sine_code'),
                        dict(channel=0, offset=.1, mode='sine_voltage')]:
            with self.assertRaises(ValueError):
                self.session.output(dict(request, action='start', wiring_confirmed=True))
        self.assertEqual(self.session.board.codes, before)
        self.assertFalse(any(self.session.board.enabled))
        for value in (float('nan'), float('inf'), -1):
            with self.assertRaises(ValueError): waveform(dict(mode='sine_code', peak=value))

    def test_close_mutes_and_restores_original_gpio(self):
        self.session.initialize(); board = self.session.board
        self.session.output(dict(channel=0, action='start', mode='dc_code', offset=100, wiring_confirmed=True))
        self.session.gpio(dict(mask=127, value=127))
        result = self.session.close()
        self.assertTrue(result['cleanup_confirmed'])
        self.assertFalse(any(board.enabled)); self.assertEqual(board.gpio_value, 0)

    def test_manual_gpio_preserves_all_dac_enable_combinations_and_settings(self):
        self.session.initialize()
        board = self.session.board
        for channel in range(3):
            self.session.output(dict(channel=channel, action='start', mode='dc_code',
                                     offset=100+channel, wiring_confirmed=True))
        for enabled_mask in range(8):
            for channel in range(3): board.enable(channel, bool(enabled_mask & (1 << channel)))
            before = self.session.status()
            for bit in range(7):
                for value in (0, 1):
                    status = self.session.gpio(dict(mask=1 << bit, value=value << bit))
                    self.assertEqual(status['outputs'], before['outputs'])
                    self.assertEqual(status['output_settings'], before['output_settings'])
            self.session.gpio(dict(mask=127, value=0x55))
            status = self.session.stop()
            self.assertEqual(status['gpio']['output'], 0)
            self.assertEqual(status['gpio']['sense'], 0)
            self.assertFalse(any(o['enabled'] for o in status['outputs']))

    def test_gpio_only_use_and_stop_do_not_initialize_analog_channels(self):
        from unittest.mock import patch
        with patch.object(self.session, 'initialize', side_effect=AssertionError('Unexpected initialization')):
            self.session.gpio(dict(mask=127, value=0x55))
            status = self.session.stop()
            self.assertFalse(status['initialized'])
            self.assertTrue(status['gpio_active'])
            self.assertEqual(status['gpio']['output'], 0)
            self.session.close()
            self.assertEqual(self.session.status()['gpio']['output'], 0)
        self.session.gpio(dict(mask=127, value=0x55))
        self.session.initialize()
        self.assertEqual(self.session.board.gpio()['output'], 0x55)
        board = self.session.board
        self.session.stop(); self.session.close()
        self.assertEqual(board.gpio()['output'], 0)

    def test_real_gpio_only_writes_gpio_register_without_board_initialization(self):
        from types import SimpleNamespace
        from unittest.mock import Mock, patch
        from sim.test_driver import Registers
        regs = Registers()
        overlay = SimpleNamespace(ip_dict={'adda_core_0': dict(phys_addr=0x43c00000, addr_range=0x10000)},
                                  is_loaded=lambda: True, adda_core_0=SimpleNamespace(mmio=regs))
        pynq = SimpleNamespace(Overlay=Mock(return_value=overlay))
        bit = Path(self.temp.name)/'test.bit'
        bit.write_bytes(b'test'); bit.with_suffix('.hwh').write_bytes(b'test')
        self.session.bitfile = str(bit)
        self.session.simulated = False
        with patch.dict(sys.modules, pynq=pynq), patch.object(self.session, '_claim_lock') as lock, \
                patch('zynq_bjt.runtime.Board.from_pynq', side_effect=AssertionError('Analog hardware claimed')):
            status = self.session.gpio(dict(mask=2, value=2))
            self.assertEqual(status['gpio']['output'], 0x17)
            self.assertFalse(status['initialized'])
            stopped = self.session.stop(); self.session.close()
            self.assertEqual(stopped['gpio']['output'], 0)
            self.assertEqual(regs.writes, [(0x50, 0x202), (0x50, 0x7f00)])
            self.assertEqual(lock.call_count, 2)
            self.assertTrue(all(call.kwargs == {'download': False} for call in pynq.Overlay.call_args_list))

    def test_cancel_all_measurements_then_explicit_stop_resets_manual_gpio(self):
        self.session.initialize()
        for name, (cls, _, _) in MEASUREMENTS.items():
            with self.subTest(measurement=name):
                self.session.cancel.clear()
                self.session.gpio(dict(mask=127, value=0x55))
                config = asdict(cls()); config['settle_s'] = 0
                if name == 'input': config.update(tx1_stop_v=.06, curve_settle_s=0, frame_gap_s=0)
                if name == 'ac': config.update(repeat_count=2, max_bisection_iterations=2)
                def cancel_on_point(kind, value):
                    if kind == 'point': self.session.cancel.set()
                result = self.session.scan(dict(measurement=name, config=config, prepare_outputs=True), cancel_on_point)
                self.assertEqual(result['state']['status'], 'cancelled', result['state'].get('error'))
                self.assertEqual(self.session.board.gpio()['output'], 0x55)
                status = self.session.stop()
                self.assertEqual(status['gpio']['output'], 0)
                self.assertFalse(any(o['enabled'] for o in status['outputs']))

    def test_stop_attempts_every_dac_and_gpio_even_if_one_fails(self):
        from unittest.mock import patch
        self.session.initialize(); board = self.session.board
        self.session.gpio(dict(mask=127, value=127))
        for channel in range(3): board.enable(channel, True)
        enable = board.enable
        def fail_one(channel, enabled):
            if channel == 0: raise RuntimeError('mute failed')
            return enable(channel, enabled)
        with patch.object(board, 'enable', side_effect=fail_one) as mute:
            with self.assertRaisesRegex(RuntimeError, 'TX1: mute failed'): self.session.stop()
            self.assertEqual(mute.call_count, 3)
        self.assertEqual(board.enabled, [True, False, False])
        self.assertEqual(board.gpio()['output'], 0)
        with patch.object(board, 'gpio', side_effect=RuntimeError('reset failed')):
            with self.assertRaisesRegex(RuntimeError, 'GPIO: reset failed'): self.session.stop()
        self.assertFalse(any(board.enabled))

    def test_protocol_eof_and_lease_expiry_cancel_active_scan(self):
        for eof in (False, True):
            with tempfile.TemporaryDirectory() as directory:
                session = Session(ROOT/'data', directory, simulated=True)
                stream, output = Pipe(), Output()
                worker = threading.Thread(target=serve, args=(session, stream, output),
                    kwargs={'lease_seconds': .4}, daemon=True); worker.start()
                stream.send(dict(id=1, op='initialize'))
                self.assertTrue(output.reply(1)['ok'])
                board = session.board
                stream.send(dict(id=2, op='scan', args=dict(measurement='input', config=dict(curve_settle_s=2))))
                deadline = time.monotonic()+2
                while not list(Path(directory).glob('*/run.json')) and time.monotonic()<deadline: time.sleep(.01)
                if eof: stream.lines.put(None)
                worker.join(3)
                self.assertFalse(worker.is_alive())
                state = json.loads(next(Path(directory).rglob('run.json')).read_text(encoding='utf-8'))
                self.assertEqual(state['status'], 'cancelled')
                self.assertFalse(any(board.enabled))
                self.assertIsNone(session.board)
                if not eof: stream.lines.put(None)

    def test_cancel_before_scan_execution_is_not_lost(self):
        stream, output = Pipe(), Output()
        self.session.initialize()
        stream.send(dict(id=3, op='scan', args=dict(measurement='input')))
        stream.send(dict(op='cancel'))
        worker = threading.Thread(target=serve, args=(self.session, stream, output),
                                  kwargs={'lease_seconds': 2}, daemon=True); worker.start()
        reply = output.reply(3)
        if reply['ok']: self.assertEqual(reply['value']['state']['status'], 'cancelled')
        else: self.assertIn('cancelled', reply['error'])
        stream.lines.put(None); worker.join(2)
        self.assertFalse(worker.is_alive())

    def test_missing_board_heartbeat_marks_connection_unknown(self):
        from unittest.mock import Mock
        events = []
        transport = SshTransport(lambda kind, value: events.append((kind, value)))
        transport.channel = Mock()
        transport.alive = True
        transport.last_reply = time.monotonic()-20
        transport._heartbeat()
        self.assertFalse(transport.alive)
        transport.channel.close.assert_called_once()
        self.assertEqual(events[0][0], 'connection_lost')
        self.assertIn('未知', events[0][1])

    def test_prepare_outputs_initializes_and_mutes_before_all_measurement_types(self):
        events=[]
        for name,(cls,_,_) in MEASUREMENTS.items():
            config=asdict(cls());config['settle_s']=0
            if name=='input':config.update(tx1_stop_v=.06,frame_gap_s=0,curve_settle_s=0)
            if name=='ac':config.update(repeat_count=2,max_bisection_iterations=2)
            if self.session.board:
                for c in range(3):self.session.board.enable(c,True)
                self.session.output_settings={'0':dict(mode='dc_voltage',offset=.2)}
            result=self.session.scan(dict(measurement=name,config=config,prepare_outputs=True),
                lambda kind,value:events.append((kind,value)))
            self.assertEqual(result['state']['status'],'complete',result['state'].get('error'))
            self.assertTrue(all(not v['enabled'] for v in result['state']['initial_outputs']))
            self.assertFalse(any(self.session.board.enabled))
            self.assertEqual(self.session.output_settings,{})
        statuses=[v for k,v in events if k=='instrument_status']
        self.assertTrue(statuses and statuses[-1]['initialized'])
        self.assertFalse(any(v['enabled'] for v in statuses[-1]['outputs']))

    def test_prepare_failure_attempts_all_channels_and_never_starts_curve(self):
        from unittest.mock import patch
        self.session.initialize();board=self.session.board
        for c in range(3):board.enable(c,True)
        original=board.enable;attempts=[]
        def fail_one(c,enabled):
            attempts.append((c,enabled))
            if c==0:raise RuntimeError('mute failed')
            return original(c,enabled)
        with patch.object(board,'enable',side_effect=fail_one):
            with self.assertRaisesRegex(RuntimeError,'测量准备检查'):
                self.session.scan(dict(measurement='input',prepare_outputs=True))
        self.assertEqual(attempts,[(0,False),(1,False),(2,False)])
        self.assertEqual(board.enabled,[True,False,False])
        self.assertEqual(list(Path(self.temp.name).iterdir()),[])

    def test_cancellation_during_preparation_completes_mute_but_does_not_scan(self):
        from unittest.mock import patch
        self.session.initialize();board=self.session.board
        for c in range(3):board.enable(c,True)
        original=board.enable;attempts=[]
        def cancel_on_mute(c,enabled):
            attempts.append((c,enabled));self.session.cancel.set()
            return original(c,enabled)
        with patch.object(board,'enable',side_effect=cancel_on_mute):
            with self.assertRaises(InterruptedError):
                self.session.scan(dict(measurement='input',prepare_outputs=True))
        self.assertEqual(attempts,[(0,False),(1,False),(2,False)])
        self.assertFalse(any(board.enabled))
        self.assertEqual(list(Path(self.temp.name).iterdir()),[])

    def test_bad_config_does_not_initialize_or_change_outputs(self):
        request=dict(measurement='input',prepare_outputs=True,config=dict(tx1_step_v=-1))
        with self.assertRaises(ValueError):self.session.scan(request)
        self.assertIsNone(self.session.board)
        self.session.initialize()
        for c in range(3):self.session.board.enable(c,True)
        with self.assertRaises(ValueError):self.session.scan(request)
        self.assertTrue(all(self.session.board.enabled))


if __name__ == '__main__': unittest.main()
