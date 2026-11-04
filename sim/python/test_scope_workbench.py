"""Scope math and acquisition-state regressions; no hardware access."""
import csv
import json
import math
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'src/python'))
from zynq_bjt.scope_display import edge_positions, measure, nice_step, sample_at


def frame(sequence=1, dc=False, over=False):
    words = [[round(32768+(0 if dc else 8000*math.sin(2*math.pi*i/50+c))) for i in range(1024)] for c in range(2)]
    if over:
        words[0][100] |= 65536
    return dict(sequence=sequence, words=words, sample_rates_hz=[50e6, 49.5e6], captured_at=0,
                simulated=True, starts_aligned=False)


class ScopeMathTests(unittest.TestCase):
    def test_interpolated_edges_polarity_hysteresis_and_gaps(self):
        self.assertEqual(edge_positions([-2, 2, 1, -1, 1], 0, hysteresis=.5), [.5, 3.5])
        self.assertEqual(edge_positions([2, -2], 0, rising=False), [.5])
        self.assertEqual(edge_positions([-2, None, 2], 0), [])
        self.assertEqual(edge_positions([-2, 2, -.1, .1], 0, hysteresis=.5), [.5])

    def test_frequency_rms_and_insufficient_periods(self):
        values = [1+2*math.sin(2*math.pi*i/50) for i in range(1000)]
        result = measure(values, 50e6)
        self.assertAlmostEqual(result['frequency'], 1e6)
        self.assertAlmostEqual(result['mean'], 1)
        self.assertAlmostEqual(result['rms'], math.sqrt(3))
        self.assertAlmostEqual(result['ac_rms'], math.sqrt(2))
        self.assertIsNone(measure(values[:70], 50e6)['frequency'])
        self.assertIsNone(measure([1]*1024, 50e6)['frequency'])

    def test_invalid_measurements_are_not_partial_averages(self):
        for values, invalid in (([1, None, 2], False), ([1, float('nan')], False), ([1, 2], True)):
            self.assertTrue(all(v is None for v in measure(values, 50e6, invalid=invalid).values()))

    def test_cursor_no_extrapolation_or_interpolation_across_invalid(self):
        self.assertEqual(sample_at([1, 3, 5], 2, .25), 2)
        self.assertEqual(sample_at([1, 3, 5], 2, 1), 5)
        for t in (-.1, 1.1): self.assertIsNone(sample_at([1, 3, 5], 2, t))
        self.assertIsNone(sample_at([1, None, 5], 2, .25))
        self.assertEqual(nice_step(.21), .5)


class ScopeUiTests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        from zynq_bjt.desktop import App
        self.temp = tempfile.TemporaryDirectory(dir=ROOT/'build')
        self.root = tk.Tk()
        self.app = App(self.root, workspace=self.temp.name)
        self.app.show_page('scope')
        self.scope = self.app.scope
        self.scope.accepting = True
        self.root.update()

    def tearDown(self):
        for job in self.root.tk.call('after', 'info'):
            self.root.tk.call('after', 'cancel', job)
        self.root.destroy()
        self.temp.cleanup()

    def test_fft_toggle_and_persistence(self):
        scope=self.scope
        scope.persistence.set('8 帧')
        for sequence in range(12): self.assertTrue(scope.receive(frame(sequence)))
        self.assertGreater(len(scope.ax.lines), 15)
        self.assertLessEqual(len(scope.ax.lines), 22)
        scope.display_mode.set('FFT 频域'); scope.redraw()
        self.assertEqual(len(scope.ax.lines),2)
        self.assertIn('dBV',scope.ax.get_ylabel())
        fft_path=Path(self.temp.name)/'fft.csv'
        scope.export_spectrum(fft_path)
        with fft_path.open(encoding='utf-8-sig') as stream:
            rows=list(csv.DictReader(stream))
        self.assertEqual(len(rows),1026)
        self.assertEqual(rows[0]['unit'],'V')
        scope.fft_scale.set('RMS');scope.redraw()
        self.assertEqual(scope.ax.get_ylabel(),'V RMS')
        scope.display_mode.set('时域');scope.redraw()
        scope.clear_history();self.assertEqual(len(scope.history),0)
        scope.receive(frame(13));scope.change_units()
        self.assertEqual(len(scope.history),0)

    def test_auto_normal_single_and_stop_late_frame(self):
        scope = self.scope
        self.assertTrue(scope.receive(frame()))
        scope.mode.set('Normal 正常'); scope.level.set('5')
        self.assertFalse(scope.receive(frame(2)))
        self.assertEqual(self.app.last_frame['sequence'], 1)
        self.assertIn('WAIT', scope.state.get())
        scope.mode.set('Auto 自动')
        self.assertTrue(scope.receive(frame(3)))
        self.assertIsNone(scope.trigger_time)
        scope.single_pending = True; self.app.live = True
        self.assertFalse(scope.receive(frame(4)))
        scope.level.set('0')
        self.assertTrue(scope.receive(frame(5)))
        self.assertFalse(self.app.live)
        self.assertFalse(scope.accepting)
        self.assertFalse(scope.receive(frame(6)))
        self.assertEqual(self.app.last_frame['sequence'], 5)

    def test_overrange_cannot_trigger_and_measurements_are_blank(self):
        scope = self.scope
        scope.single_pending = True
        self.assertFalse(scope.receive(frame(over=True)))
        scope.single_pending = False
        self.assertTrue(scope.receive(frame(over=True)))
        self.assertIn('OR 1', scope.stats[0].get())
        self.assertIn('Vpp —', scope.stats[0].get())

    def test_per_channel_axes_and_whole_record_fit(self):
        scope = self.scope
        scope.receive(frame()); scope.autoset(); scope.fit_time()
        x0, x1 = scope.ax.get_xlim()
        for values, rate in zip(scope.frame['words'], scope.frame['sample_rates_hz']):
            self.assertLessEqual(x0, -(scope.trigger_time or 0)*1e6+1e-5)
            self.assertGreaterEqual(x1, ((len(values)-1)/rate-(scope.trigger_time or 0))*1e6-1e-5)
        old_second = list(scope.ax.lines[2].get_ydata())
        scope.scale[0].set('1'); scope.redraw()
        self.assertEqual(list(scope.ax.lines[2].get_ydata()), old_second)
        scope.visible[0].set(False); scope.visible[1].set(False); scope.autoset()
        self.assertTrue(scope.visible[0].get())
        scope.units.set('ADC 原始码'); scope.change_units()
        self.assertGreater(float(scope.center[0].get()), 30000)

    def test_cursors_persist_across_frames_and_invalid_inputs_hold_display(self):
        scope = self.scope
        scope.receive(frame()); scope.cursors.set(True)
        scope.click_cursor(SimpleNamespace(inaxes=scope.ax, xdata=1, button=1))
        scope.click_cursor(SimpleNamespace(inaxes=scope.ax, xdata=2, button=3))
        self.assertIn('1 µs', scope.cursor_text.get())
        self.assertIn('1 MHz', scope.cursor_text.get())
        scope.receive(frame(2))
        self.assertEqual(scope.cursor_times, [1, 2])
        scope.scale[0].set('nan'); scope.redraw()
        self.assertIn('参数无效', scope.state.get())
        self.assertFalse(scope.receive(frame(3)))
        self.assertEqual(scope.frame['sequence'], 2)

    def test_autoset_shows_four_cycles_and_keeps_them_on_next_frame(self):
        scope=self.scope;scope.receive(frame());scope.autoset()
        low,high=scope.ax.get_xlim()
        self.assertAlmostEqual((high-low)*1e-6*1e6,4,delta=.05)
        self.assertIsNone(scope._full_frame_settings)
        timebase=scope.timebase.get();scope.receive(frame(2))
        self.assertEqual(scope.timebase.get(),timebase)
        scope.fit_time()
        self.assertGreater(scope.ax.get_xlim()[1]-scope.ax.get_xlim()[0],20)

    def test_cursor_buttons_are_fixed_and_hidden_channel_has_no_readouts(self):
        scope=self.scope;scope.receive(frame());scope.cursors.set(True)
        for x,button in ((1,1),(2,1),(3,3),(4,1),(5,2)):
            scope.click_cursor(SimpleNamespace(inaxes=scope.ax,xdata=x,button=button))
        self.assertEqual(scope.cursor_times,[4,3])
        scope.visible[1].set(False);scope.redraw()
        self.assertEqual(scope.channel_readouts[1].winfo_manager(),'')
        self.assertEqual(scope.metric_strips[1].values,[])
        self.assertEqual(scope.badges[1].get(),'')
        self.assertTrue(all(not widget.grid_info() for widget in scope.channel_fields[1]))
        scope.display_mode.set('FFT 频域');scope.redraw()
        self.assertEqual(scope.metric_strips[1].values,[])
        scope.visible[1].set(True);scope.redraw()
        self.assertEqual(scope.channel_readouts[1].winfo_manager(),'pack')
        self.assertTrue(all(widget.grid_info() for widget in scope.channel_fields[1]))
        scope.cursors.set(False);scope.redraw()
        self.assertEqual(scope.cursor_strip.winfo_manager(),'')

    def test_stop_cancels_scheduled_capture_without_output_command(self):
        calls = []
        self.app.submit = lambda op, *a: calls.append(op)
        self.app.live = True
        self.scope.schedule()
        job = self.scope.capture_job
        self.scope.stop()
        self.assertNotIn(job, self.root.tk.call('after', 'info'))
        self.scope.next_capture()
        self.assertEqual(calls, [])

    def test_repeated_frames_reuse_axes_and_explain_short_window(self):
        scope=self.scope
        scope.receive(frame());baseline=scope.ax.lines[0]
        scope.receive(frame(2))
        self.assertIs(scope.ax.lines[0],baseline)
        self.assertIn('µs 实采窗口',scope.info.get())
        self.assertIn('10 kHz约0.20周期',scope.basis.get())
        scope.timebase.set('10');scope.redraw()
        self.assertTrue(scope.ax.patches)
        patch_count=len(scope.ax.patches)
        scope.receive(frame(3));self.assertEqual(len(scope.ax.patches),patch_count)

    def test_long_window_shows_true_10khz_cycles_and_uses_adc_clock_for_calibration(self):
        scope=self.scope
        data=frame()
        data.update(sample_stride=20,adc_sample_rates_hz=[50e6,50e6],sample_rates_hz=[2.5e6,2.5e6])
        data['words']=[[round(32768+4000*math.sin(2*math.pi*10000*i/2.5e6)) for i in range(1024)] for c in range(2)]
        scope.receive(data);scope.autoset()
        self.assertTrue(all(c['nominal_dc_calibrated'] for c in scope.converted))
        self.assertIn('10 kHz约4.09周期',scope.basis.get())
        self.assertIn('10 kHz',scope.stats[0].get())
        self.assertAlmostEqual(scope.ax.get_xlim()[1]-scope.ax.get_xlim()[0],400,delta=2)

    def test_full_frame_follows_changed_trigger_without_cropping_samples(self):
        scope=self.scope
        scope.receive(frame());scope.autoset();scope.fit_time()
        changed=frame(2)
        changed['words']=[words[17:]+words[:17] for words in changed['words']]
        scope.receive(changed)
        low,high=scope.ax.get_xlim()
        for words,rate in zip(changed['words'],changed['sample_rates_hz']):
            self.assertLessEqual(low,-(scope.trigger_time or 0)*1e6+1e-4)
            self.assertGreaterEqual(high,((len(words)-1)/rate-(scope.trigger_time or 0))*1e6-1e-4)

    def test_export_preserves_frame_rates_and_display_metadata(self):
        self.scope.receive(frame(19))
        self.scope.stop()
        self.app.save_frame()
        directory = next((self.app.results/'仪器'/'示波器').iterdir())
        original = json.loads((directory/'frame.json').read_text())
        self.assertEqual(original, frame(19))
        with (directory/'samples.csv').open(encoding='utf-8-sig', newline='') as f:
            rows = list(csv.DictReader(f))
        self.assertEqual(len(rows), 1024)
        self.assertNotEqual(rows[-1]['rx1_time_s'], rows[-1]['rx2_time_s'])
        self.assertEqual(rows[-1]['simulated'], '1')
        settings = json.loads((directory/'display_settings.json').read_text(encoding='utf-8'))
        self.assertFalse(settings['starts_aligned'])
        self.assertEqual(settings['trigger_kind'], 'software_in_frame')
        self.assertEqual(settings['acquisition_state'], 'STOP')
        self.assertGreater((directory/'waveform.png').stat().st_size, 1000)


if __name__ == '__main__': unittest.main()
