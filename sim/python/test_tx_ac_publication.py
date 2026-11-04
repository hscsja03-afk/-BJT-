"""Publication gates use synthetic records in temporary folders, never hardware."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

SPEC=importlib.util.spec_from_file_location('publish_tx_ac',Path(__file__).resolve().parents[2]/'board/calibration/tx/finalize_tx_waves_lan.py')
publisher=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(publisher)


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory()
        self.root=Path(self.folder.name);self.previous_root=publisher.ROOT;publisher.ROOT=self.root
        data=self.root/'data';data.mkdir()
        self.run=self.root/'report/run';self.run.mkdir(parents=True)
        before=self.run/'data_before';before.mkdir()
        for name,content in [('dac_calibration.json',b'{"dc":"unchanged fixture"}'),
                             ('tx3_waveform_calibration.json',b'{"calibration_id":"old fixture"}')]:
            (data/name).write_bytes(content);(before/name).write_bytes(content)
        self.raw=self.run/'synthetic.bin';self.raw.write_bytes(b'synthetic test fixture, not measured data')
        metric=dict(vpp_v=.2,dc_v=0,raw_file=str(self.raw.relative_to(self.root)),
                    raw_sha256=hashlib.sha256(self.raw.read_bytes()).hexdigest())
        self.result=dict(status='complete',cleanup_confirmed=True,dc_calibration_unchanged=True,
            initialized={'identity':dict(dac_divider=8,bit_sha256='test-bit',hwh_sha256='test-hwh')},probe=1,
            frequencies_hz={s:[100000] for s in ('sine','square','triangle')},target_amplitudes_vpp=[.2],
            scope_idn='synthetic test scope',finished='test',warmup={},verification=[])
        for channel in (2,3):
            for shape in self.result['frequencies_hz']:
                self.result['warmup'][f'TX{channel}_{shape}']={'stability':dict(amplitude_stable=True,dc_stable=False)}
                self.result['verification'].append(dict(channel=channel,shape=shape,frequency_hz=100000,
                    target_vpp_v=.2,amplitude_passed=True,dc_passed=True,passed=True,amplitude_error_v=0,
                    offset_v=.9 if channel==2 else 0,zero_code=13000,peak_codes=1000,
                    measurement=dict(metric,dc_v=.9 if channel==2 else 0)))
        self.source=self.run/'result.json';self.save()

    def save(self):self.source.write_text(json.dumps(self.result),encoding='utf8')

    def tearDown(self):
        publisher.ROOT=self.previous_root;self.folder.cleanup()

    def test_complete_release_keeps_dc_and_drift_status(self):
        before=(self.root/'data/dac_calibration.json').read_bytes()
        publisher.publish(self.source)
        self.assertEqual((self.root/'data/dac_calibration.json').read_bytes(),before)
        for channel in (2,3):
            p=json.loads((self.root/f'data/tx{channel}_waveform_calibration.json').read_text(encoding='utf8'))
            self.assertEqual(p['bitstream_sha256'],'test-bit')
            self.assertTrue(p['shape_validation']['sine']['amplitude_only'])
            self.assertEqual(p['shape_validation']['sine']['offset_validation_status'],'drift_observed')

    def test_failed_or_missing_verification_never_publishes(self):
        original=copy.deepcopy(self.result)
        for failure in ('failed','missing','cleanup','unstable','inconsistent_measurement'):
            self.result=copy.deepcopy(original)
            if failure=='failed':self.result['verification'][0]['amplitude_passed']=False
            elif failure=='missing':self.result['verification'].pop()
            elif failure=='cleanup':self.result['cleanup_confirmed']=False
            elif failure=='unstable':self.result['warmup']['TX2_sine']['stability']['amplitude_stable']=False
            else:self.result['verification'][0]['measurement']['vpp_v']=.25
            self.save()
            with self.assertRaises(ValueError):publisher.publish(self.source)
            self.assertFalse((self.root/'data/tx2_waveform_calibration.json').exists())
            self.assertFalse((self.run/'published_data_before').exists())

    def test_raw_mutation_rejected(self):
        self.raw.write_bytes(b'changed')
        with self.assertRaises(ValueError):publisher.publish(self.source)
        self.assertFalse((self.root/'data/tx2_waveform_calibration.json').exists())

    def test_user_can_exclude_center_without_qualifying_it(self):
        self.result['verification'][0]['measurement']['dc_v']=1.0
        self.result['verification'][0]['dc_passed']=False
        self.result['verification'][0]['passed']=False
        self.save()
        publisher.publish(self.source,amplitude_only=True)
        p=json.loads((self.root/'data/tx2_waveform_calibration.json').read_text(encoding='utf8'))
        self.assertTrue(p['shape_validation']['sine']['amplitude_only'])
        self.assertEqual(p['shape_validation']['sine']['offset_validation_status'],'excluded_by_user')
        self.assertEqual(p['points'][0]['measurement']['dc_v'],1.0)

    def test_tx2_other_hardware_profile_is_preserved(self):
        variant=dict(calibration_id='other-bit-profile',bitstream_sha256='other-bit',hwh_sha256='other-hwh',
                     exact_nodes_only=True,points=[{'synthetic':True}])
        previous=dict(calibration_id='old-primary',bitstream_sha256='test-bit',hwh_sha256='test-hwh',
                      hardware_variants=[variant])
        data=self.root/'data/tx2_waveform_calibration.json'
        data.write_text(json.dumps(previous),encoding='utf8')
        (self.run/'data_before/tx2_waveform_calibration.json').write_bytes(data.read_bytes())
        publisher.publish(self.source)
        published=json.loads(data.read_text(encoding='utf8'))
        self.assertEqual(published['hardware_variants'],[variant])

    def test_concurrent_tx2_change_rejected(self):
        (self.root/'data/tx2_waveform_calibration.json').write_text('{"calibration_id":"newer"}')
        (self.run/'data_before/tx2_waveform_calibration.json').write_text('{"calibration_id":"older"}')
        with self.assertRaisesRegex(ValueError,'TX2 table changed'):publisher.publish(self.source)
        self.assertFalse((self.run/'published_data_before').exists())


if __name__=='__main__':unittest.main()
