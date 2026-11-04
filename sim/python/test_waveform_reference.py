import unittest
import json
import tempfile
from pathlib import Path
from zynq_bjt.waveform_reference import resolve


class WaveformReferenceTests(unittest.TestCase):
    def setUp(self):
        self.profile=dict(dac_sample_rate_hz=125000000,calibration_id='test',points=[
            dict(shape=s,frequency_hz=f,target_vpp_v=a,zero_code=13000,peak_codes=p,passed=True)
            for s in ('sine','square','triangle') for f in (10000,100000) for a,p in ((.05,200),(.1,400))])

    def test_exact_interpolated_and_extrapolated(self):
        for shape in ('sine','square','triangle'):
            self.assertEqual(resolve(self.profile,shape,10000,.05)['amplitude_basis'],'scope_verified_grid')
            p=resolve(self.profile,shape,50000,.075)
            self.assertAlmostEqual(p['peak_codes'],300)
            self.assertEqual(p['amplitude_basis'],'interpolated_grid_unverified')
            p=resolve(self.profile,shape,200000,.2)
            self.assertEqual(p['peak_codes'],800)
            self.assertEqual(p['amplitude_basis'],'extrapolated_grid_unverified')

    def test_partial_tx3_override_only_changes_exact_measured_request(self):
        self.profile['exact_overrides']=dict(points=[dict(shape='sine',frequency_hz=10000,
            target_vpp_v=.05,zero_code=14000,peak_codes=250,passed=False,amplitude_passed=True)],
            shape_validation={'sine':dict(amplitude_only=True,amplitude_stability_qualified=True,
                                           offset_validation_status='excluded_by_user')})
        p=resolve(self.profile,'sine',10000,.05)
        self.assertEqual((p['zero_code'],p['peak_codes']),(14000,250))
        self.assertEqual(p['offset_validation_status'],'excluded_by_user')
        p=resolve(self.profile,'sine',50000,.075)
        self.assertEqual((p['zero_code'],p['peak_codes']),(13000,300))
        self.assertEqual(resolve(self.profile,'square',10000,.05)['peak_codes'],200)
        self.profile['exact_overrides']['shape_validation']['sine']['amplitude_stability_qualified']=False
        self.assertEqual(resolve(self.profile,'sine',10000,.05)['amplitude_basis'],'scope_checked_unstable_reference')
        self.profile['exact_overrides']['points'][0]['amplitude_passed']=False
        with self.assertRaises(ValueError):resolve(self.profile,'sine',10000,.05)

    def test_tx2_ac_reference_preserves_dc_and_agent_recomputes_codes(self):
        from zynq_bjt.frontend import Calibration
        from zynq_bjt.desktop_output import prepare
        from zynq_bjt.desktop_session import Session,waveform
        root=Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as folder:
            data=Path(folder)/'data';data.mkdir()
            for source in (root/'data').glob('*.json'):
                (data/source.name).write_bytes(source.read_bytes())
            before=(data/'dac_calibration.json').read_bytes()
            original=Calibration(data).dac_code(1,.9)
            profile=dict(self.profile,offset_v=.9,bitstream_sha256='bit',hwh_sha256='hwh')
            (data/'tx2_waveform_calibration.json').write_text(json.dumps(profile),encoding='utf8')
            cal=Calibration(data)
            self.assertEqual(cal.dac_code(1,.9),original)
            self.assertIsNone(cal.tx2_waveform_parameters('sine',1000,.05,.9))
            self.assertIsNone(cal.tx2_waveform_parameters('sine',10000,.5,.9))
            self.assertIsNone(cal.tx2_waveform_parameters('sine',10000,.05,.5))
            identity=dict(bit_sha256='bit',hwh_sha256='hwh',dac_divider=8)
            cal.validate_tx2_waveform_identity(identity)
            for change in ({'bit_sha256':'wrong'},{'hwh_sha256':'wrong'},{'dac_divider':20}):
                with self.assertRaises(ValueError):cal.validate_tx2_waveform_identity(dict(identity,**change))
            session=Session(data,Path(folder)/'results',simulated=True);session.initialize()
            try:
                values=dict(offset=.9,peak=.025,frequency_hz=10000,phase_degrees=30,duty_percent=50)
                for shape in ('sine','square','triangle'):
                    request=prepare(1,shape,'voltage',values,cal,confirmed=True)['request']
                    self.assertEqual(request['phase_degrees'],210)
                    expected=waveform(request)[0]
                    altered=dict(request,offset=1,peak=1,phase_degrees=0)
                    status=session.output(altered)
                    self.assertEqual(status['outputs'][1]['code'],expected[0])
                    self.assertEqual(status['output_settings']['1']['phase_degrees'],210)
                    with self.assertRaises(ValueError):
                        session.output(dict(request,tx2_waveform_calibration_id='stale'))
                dc=prepare(1,'dc','voltage',values,cal,confirmed=True)['request']
                self.assertNotIn('tx2_waveform_calibration_id',dc)
                self.assertEqual(dc['mode'],'dc_voltage')
            finally:session.close()
            self.assertEqual((data/'dac_calibration.json').read_bytes(),before)

    def test_unverified_missing_and_invalid_rejected(self):
        self.profile['points'][0]['passed']=False
        with self.assertRaises(ValueError):resolve(self.profile,'sine',50000,.075)
        for v in (0,-1,float('nan'),float('inf'),100):
            with self.assertRaises(ValueError):resolve(self.profile,'square',10000,v)

    def test_partial_tx2_profiles_never_fill_holes_or_cross_hardware(self):
        import copy
        from zynq_bjt.frontend import Calibration
        root=Path(__file__).resolve().parents[2]
        cal=Calibration(root/'data')
        primary=dict(self.profile,offset_v=.9,exact_nodes_only=True,
            bitstream_sha256='boot',hwh_sha256='boot-hwh',
            points=[self.profile['points'][0],self.profile['points'][3]])
        variant=copy.deepcopy(primary);variant.update(calibration_id='native',bitstream_sha256='native',hwh_sha256='native-hwh')
        variant['points'][0]['peak_codes']=250
        primary['hardware_variants']=[variant]
        cal.tx2_waveform_library=primary;cal.select_tx2_waveform_profile()
        self.assertEqual(cal.tx2_waveform_parameters('sine',10000,.05,.9)['peak_codes'],200)
        for frequency,amp in ((50000,.075),(10000,.1),(100000,.05),(200000,.2)):
            self.assertIsNone(cal.tx2_waveform_parameters('sine',frequency,amp,.9))
        cal.select_tx2_waveform_profile(dict(bit_sha256='native',hwh_sha256='native-hwh'))
        self.assertEqual(cal.tx2_waveform_parameters('sine',10000,.05,.9)['peak_codes'],250)
        cal.select_tx2_waveform_profile(dict(bit_sha256='native',hwh_sha256='wrong'))
        self.assertIsNone(cal.tx2_waveform_parameters('sine',10000,.05,.9))
        cal.select_tx2_waveform_profile()
        self.assertEqual(cal.tx2_waveform_parameters('sine',10000,.05,.9)['peak_codes'],200)

    def test_new_sine_checks_do_not_qualify_old_other_waveforms(self):
        self.profile['offset_validation_status']='drift_observed'
        self.profile['shape_validation']={'sine':{'offset_validation_status':'session_grid_verified'}}
        self.assertEqual(resolve(self.profile,'sine',10000,.05)['offset_validation_status'],'session_grid_verified')
        for shape in ('square','triangle'):
            self.assertEqual(resolve(self.profile,shape,10000,.05)['offset_validation_status'],'drift_observed')

    def test_amplitude_only_reference_requires_explicit_scope_and_keeps_dc_failure(self):
        row=self.profile['points'][0];row.update(passed=False,amplitude_passed=True,dc_passed=False)
        with self.assertRaises(ValueError):resolve(self.profile,'sine',10000,.05)
        self.profile['shape_validation']={'sine':{'amplitude_only':True,'offset_validation_status':'drift_observed'}}
        plan=resolve(self.profile,'sine',10000,.05)
        self.assertEqual(plan['amplitude_basis'],'scope_verified_grid')
        self.assertEqual(plan['offset_validation_status'],'drift_observed')
        row['amplitude_passed']=False
        with self.assertRaises(ValueError):resolve(self.profile,'sine',10000,.05)

    def test_bitstream_identity_rejects_stale_hardware_calibration(self):
        from zynq_bjt.frontend import Calibration
        cal=Calibration.__new__(Calibration)
        cal.tx3_waveforms={'bitstream_sha256':'validated-bit'}
        cal.validate_waveform_identity({'bit_sha256':'validated-bit'})
        for identity in ({},{'bit_sha256':'other-bit'}):
            with self.assertRaises(ValueError):cal.validate_waveform_identity(identity)
        cal.tx3_waveforms=None;cal.validate_waveform_identity({})

    def test_unstable_reference_keeps_failed_stability_visible(self):
        self.profile['shape_validation']={'square':{'amplitude_stability_qualified':False}}
        plan=resolve(self.profile,'square',10000,.05)
        self.assertEqual(plan['amplitude_basis'],'scope_checked_unstable_reference')
        self.assertFalse(plan['amplitude_stability_qualified'])
        self.assertFalse(resolve(self.profile,'square',50000,.075)['amplitude_stability_qualified'])
        self.assertEqual(resolve(self.profile,'sine',10000,.05)['amplitude_basis'],'scope_verified_grid')

    def test_desktop_and_agent_share_modern_reference(self):
        from zynq_bjt.frontend import Calibration
        from zynq_bjt.desktop_output import prepare
        from zynq_bjt.desktop_session import Session, waveform
        root=Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as folder:
            data=Path(folder)/'data';data.mkdir()
            for source in (root/'data').glob('*.json'):(data/source.name).write_bytes(source.read_bytes())
            (data/'tx3_waveform_calibration.json').write_text(json.dumps(self.profile),encoding='utf-8')
            cal=Calibration(data)
            self.assertEqual(cal.sine_samples(10000,.05)[0],13000)
            s=Session(data,Path(folder)/'results',simulated=True);s.initialize()
            try:
                for shape in ('sine','square','triangle'):
                    plan=prepare(2,shape,'voltage',dict(offset=0,peak=.025,frequency_hz=10000,phase_degrees=0,duty_percent=50),cal)
                    request=dict(plan['request'],wiring_confirmed=True,action='apply')
                    expected=waveform(request)[0]
                    # 板端按自身校准重算，拒绝依赖客户端提交的码值。
                    request['offset']=32768;request['peak']=1
                    status=s.output(request)
                    self.assertEqual(status['outputs'][2]['code'],expected[0])
                    self.assertEqual(status['output_settings']['2']['sine_amplitude_basis'],'scope_verified_grid')
            finally:s.close()
