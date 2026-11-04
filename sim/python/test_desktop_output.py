"""Voltage/code UI requests must produce the intended existing DAC commands."""
from pathlib import Path
import sys
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'src/python'))
from zynq_bjt.desktop_output import prepare,defaults,output_summary
from zynq_bjt.desktop_session import Session as BaseSession, waveform
from zynq_bjt.frontend import Calibration


def Session(*args, **kwargs):
    # 此文件保留旧参考表的兼容检查；多点表由test_waveform_reference覆盖。
    session=BaseSession(*args, **kwargs)
    session.cal.tx3_waveforms=None
    return session


class Tests(unittest.TestCase):
    def setUp(self):
        self.cal=Calibration(ROOT/'data')
        self.cal.tx3_waveforms=None

    def plan(self,ch,wave,unit,**values):
        return prepare(ch,wave,unit,dict(defaults(ch,wave,unit,self.cal),**values),self.cal,confirmed=True,action='start')

    def test_tx3_shared_peak_is_half_legacy_vpp(self):
        for peak in (.025,.01,.005,.03,.05,.1,.5,1.0):
            p=self.plan(2,'sine','voltage',peak=peak)
            self.assertEqual(p['request']['mode'],'sine_voltage')
            self.assertEqual(p['request']['vpp'],2*peak)
            self.assertAlmostEqual(max(p['preview'])-min(p['preview']),2*peak)
            self.assertAlmostEqual(max(p['preview']),peak)

    def test_tx2_voltage_shapes_commit_correct_positive_and_negative_levels(self):
        for wave in ('sine','square','triangle'):
            p=self.plan(1,wave,'voltage',offset=.9,peak=.2)
            codes,_,_=waveform(p['request'])
            self.assertEqual(min(codes),self.cal.dac_code(1,1.1)[0])
            self.assertEqual(max(codes),self.cal.dac_code(1,.7)[0])
            # This channel is inverted; positive voltage requires fewer codes.
            for volts,code in zip(p['preview'],codes):self.assertEqual(code,self.cal.dac_code(1,volts)[0])

    def test_tx1_voltage_and_code_still_use_original_driver_modes(self):
        self.assertEqual(self.plan(0,'dc','voltage',offset=1)['request']['mode'],'dc_voltage')
        self.assertEqual(self.plan(0,'dc','code',offset=1638)['request']['offset'],1638)
        with self.assertRaises(ValueError):self.plan(0,'sine','code')
        with self.assertRaises(ValueError):self.plan(0,'dc','code',offset=4096)

    def test_invalid_voltage_wave_rejected_without_changing_output(self):
        with tempfile.TemporaryDirectory() as folder:
            s=Session(ROOT/'data',folder,simulated=True);s.initialize();before=list(s.board.codes)
            for ch,wave,values in [(1,'square',dict(offset=.1,peak=.2)),(2,'sine',dict(peak=10)),
                                   (2,'sine',dict(phase_degrees=45)),(2,'sine',dict(offset=.1)),
                                   (2,'triangle',dict(offset=1000))]:
                with self.assertRaises(ValueError):s.output(self.plan(ch,wave,'voltage',**values)['request'])
            self.assertEqual(s.board.codes,before);self.assertFalse(any(s.board.enabled));s.close()

    def test_dc_and_stop_ignore_inactive_invalid_fields(self):
        p=self.plan(0,'dc','voltage',offset=1,peak='unfinished',frequency_hz='-',duty_percent='')
        self.assertEqual(p['preview'],[1]*256)
        self.assertEqual(prepare(2,'triangle','voltage',{},self.cal,action='stop')['request']['action'],'stop')

    def test_tx3_other_voltage_shapes_are_explicitly_nominal(self):
        p=self.plan(2,'triangle','voltage',peak=.02)
        self.assertIn('标称',p['basis'])
        codes,_,_=waveform(p['request'])
        zero=self.cal.dac['channels'][2]['zero_code']
        self.assertTrue(min(codes)<zero<max(codes))
        self.assertEqual(self.plan(2,'dc','voltage')['request']['offset'],zero)

    def test_expanded_sine_scales_without_clipping_and_labels_estimate(self):
        import math
        for frequency in (10000,100000,155000,3000000,6000000):
            for peak in (.03,.05,.1,.5,1.):
                p=self.plan(2,'sine','voltage',frequency_hz=frequency,peak=peak)
                self.assertIn('参考表比例估算',p['basis'])
                samples=self.cal.sine_samples(frequency,2*peak)
                info=self.cal.sine_parameters(frequency,2*peak)
                self.assertTrue(all(0<=v<=65535 for v in samples))
                self.assertLess(abs((max(samples)-min(samples))-2*info['peak_codes']),1.01)
                for i,v in enumerate(samples):
                    self.assertLessEqual(abs(v-(info['zero_code']+info['peak_codes']*math.sin(2*math.pi*i/256))),.500001)
        reference_peak=self.cal.dac['channels'][2]['sine_50mv']['target_vpp_uv']/2e6
        self.assertEqual(self.plan(2,'sine','voltage',peak=reference_peak)['request']['sine_amplitude_basis'],
                         'scope_verified_warm_point' if self.cal.warm_sine_reference() else
                         'scaled_reference_unverified' if self.cal.dac['channels'][2]['sine_50mv']['validation_status']=='drifting_scope_reference_estimate' else 'scope_verified_reference')

    def test_warm_record_covers_only_matching_frequency_amplitude_and_codes(self):
        import copy
        point=self.cal.warm_sine_reference()
        self.assertIsNotNone(point)
        original=copy.deepcopy(self.cal.dac)
        plan=self.plan(2,'sine','voltage',frequency_hz=100000,peak=.035)
        self.assertEqual(plan['request']['sine_amplitude_basis'],'scope_verified_warm_point')
        self.assertIn('已完成预热后单点校准复核',plan['basis'])
        self.assertIn('校准条件',plan['basis'])
        self.assertNotIn('未通过校准复核',plan['basis'])
        for frequency,peak in ((100001,.035),(10000,.035),(100000,.034),(3000000,.035)):
            other=self.plan(2,'sine','voltage',frequency_hz=frequency,peak=peak)
            self.assertEqual(other['request']['sine_amplitude_basis'],'scaled_reference_unverified')
            self.assertIn('参考表比例估算',other['basis'])
        for field,value in (('zero_code',28000),('dac_sample_rate_hz',50000000)):
            self.cal.dac=copy.deepcopy(original)
            self.cal.dac['channels'][2]['sine_50mv'][field]=value
            self.assertIsNone(self.cal.warm_sine_reference())
        self.cal.dac=copy.deepcopy(original)
        p=self.cal.dac['channels'][2]['sine_50mv']
        p['peak_codes'][p['frequency_hz'].index(100000)]+=1
        self.assertIsNone(self.cal.warm_sine_reference())
        self.cal.dac=copy.deepcopy(original)
        del self.cal.dac['channels'][2]['sine_50mv']['warm_reference']['setting']['amplitude_vpp_v']
        self.assertIsNone(self.cal.warm_sine_reference())

    def test_session_status_preserves_scoped_warm_record_without_trusting_client(self):
        with tempfile.TemporaryDirectory() as folder:
            s=Session(ROOT/'data',folder,simulated=True);s.initialize()
            request=dict(channel=2,mode='sine_voltage',frequency_hz=100000,vpp=.07,
                         action='apply',wiring_confirmed=True,sine_amplitude_basis='scaled_reference_unverified')
            status=s.output(request)
            self.assertEqual(status['output_settings']['2']['sine_amplitude_basis'],'scope_verified_warm_point')
            self.assertIn('预热后已复核',output_summary(status))
            self.assertFalse(status['analog_calibration_qualified'])
            status=s.output(dict(request,frequency_hz=3000000,sine_amplitude_basis='scope_verified_warm_point'))
            self.assertEqual(status['output_settings']['2']['sine_amplitude_basis'],'scaled_reference_unverified')
            self.assertFalse(any(x['enabled'] for x in status['outputs']))
            s.close()

    def test_code_headroom_boundary_and_nonfinite_amplitudes(self):
        for frequency in (10000,100000,6000000):
            limit=self.cal.sine_parameters(frequency,.05)['max_vpp']
            samples=self.cal.sine_samples(frequency,limit)
            self.assertEqual(min(samples),0)
            self.assertLessEqual(max(samples),65535)
            for invalid in (limit*1.0001,0,-.05,float('nan'),float('inf')):
                with self.assertRaises(ValueError):self.cal.sine_samples(frequency,invalid)

    def test_board_status_recomputes_amplitude_basis_for_legacy_request(self):
        with tempfile.TemporaryDirectory() as folder:
            s=Session(ROOT/'data',folder,simulated=True);s.initialize()
            request=dict(channel=2,mode='sine_voltage',frequency_hz=100000,vpp=.2,
                         action='start',wiring_confirmed=True,sine_amplitude_basis='scope_verified_reference')
            status=s.output(request)
            self.assertEqual(status['output_settings']['2']['sine_amplitude_basis'],'scaled_reference_unverified')
            self.assertIn('幅度估算 / 未校准',output_summary(status))
            s.close()

    def test_all_default_shapes_and_units_are_accepted_by_unchanged_session(self):
        with tempfile.TemporaryDirectory() as folder:
            s=Session(ROOT/'data',folder,simulated=True);s.initialize()
            for ch in range(3):
                for wave in (('dc',) if ch==0 else ('dc','sine','square','triangle')):
                    for unit in ('voltage','code'):
                        p=self.plan(ch,wave,unit)
                        s.output(p['request']);self.assertTrue(s.board.output(ch).enabled)
                        s.output(dict(channel=ch,action='stop'))
            self.assertFalse(any(s.board.enabled));s.close()

    def test_status_keeps_each_applied_unit_and_original_waveform(self):
        with tempfile.TemporaryDirectory() as folder:
            s=Session(ROOT/'data',folder,simulated=True);s.initialize()
            s.output(self.plan(0,'dc','voltage',offset=.2)['request'])
            # Voltage square is transported as a custom table; show 方波.
            s.output(self.plan(1,'square','voltage',offset=.9,peak=.1)['request'])
            status=s.output(self.plan(2,'sine','code',offset=23012,peak=800)['request'])
            lines=output_summary(status).splitlines()
            self.assertIn('直流 · 设定 0.2 V',lines[0]);self.assertNotIn('码',lines[0])
            self.assertIn('方波',lines[1]);self.assertIn('0.2 Vpp',lines[1])
            self.assertNotIn('CSV',lines[1]);self.assertNotIn('码',lines[1])
            self.assertIn('正弦',lines[2]);self.assertIn('1600 码峰峰值',lines[2])
            self.assertIn('偏置 23012 码',lines[2])
            stopped=output_summary(s.stop())
            self.assertEqual(stopped.count('停止'),3);self.assertIn('0.2 V',stopped)
            s.close()

    def test_status_preserves_tx3_voltage_sine_amplitude_and_pending_dc(self):
        settings={'0':self.plan(0,'dc','voltage',offset=.2)['request'],
                  '2':self.plan(2,'sine','voltage',peak=.025,frequency_hz=100000)['request']}
        state=dict(outputs=[dict(enabled=False,code=328,code_basis='pending_until_enabled'),
                            dict(enabled=False,code=7667),dict(enabled=True,code=23012)],output_settings=settings)
        lines=output_summary(state).splitlines()
        self.assertIn('待启动设定 0.2 V',lines[0])
        self.assertIn('未确认',lines[1]);self.assertNotIn('7667',lines[1])
        self.assertIn('正弦 · 设定 100 kHz · 0.05 Vpp',lines[2])
        self.assertNotIn('23012',lines[2])

    def test_legacy_request_fallback_and_failure_invalidates_setting(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as folder:
            s=Session(ROOT/'data',folder,simulated=True);s.initialize()
            s.output(dict(channel=0,mode='dc_code',offset=328,action='start',wiring_confirmed=True))
            self.assertIn('直流 · 设定 328 码',output_summary(s.status()))
            with patch.object(s.board,'set_code',side_effect=RuntimeError('write failed')):
                with self.assertRaises(RuntimeError):s.output(self.plan(0,'dc','voltage',offset=.4)['request'])
            self.assertNotIn('0',s.output_settings)
            self.assertIn('未确认',output_summary(s.status()).splitlines()[0])
            s.close()

if __name__=='__main__':unittest.main()
