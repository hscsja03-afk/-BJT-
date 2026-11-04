import math
from pathlib import Path
import tempfile
import unittest
import numpy as np
from zynq_bjt.desktop_session import Session
from zynq_bjt.scope_display import spectrum
from zynq_bjt.result_paths import create_run,relative_run
from zynq_bjt.datasheet_extract import extract,cached_extract

ROOT=Path(__file__).resolve().parents[2]


class AcquisitionUpgradeTests(unittest.TestCase):
    def test_manual_decimation_and_record_length(self):
        with tempfile.TemporaryDirectory() as folder:
            session=Session(ROOT/'data',folder,simulated=True);session.initialize()
            for count,stride in ((256,1),(2048,20),(4096,256)):
                frame=session.capture(dict(sample_count=count,sample_stride=stride))
                self.assertEqual(len(frame['words'][0]),count)
                self.assertEqual(frame['sample_rates_hz'],(50e6/stride,)*2)
                self.assertEqual(frame['adc_sample_rates_hz'],(50e6,)*2)
            with self.assertRaises(ValueError):session.capture(dict(sample_count=256,window_us=20000))
            session.close()

    def test_noncoherent_square_harmonics_and_total_rms(self):
        n=4096;rate=2e6;frequency=17321.;t=np.arange(n)/rate
        for duty in (.5,.3):
            x=np.where((frequency*t+.143)%1<duty,.5,-.5)
            result=spectrum(x,rate,'flattop')
            self.assertTrue(result['resolved'])
            self.assertLess(abs(result['peak_frequency_hz']/frequency-1),.001)
            self.assertLess(abs(result['ac_rms']-math.sqrt(duty*(1-duty))),.002)
            for h in result['harmonics']:
                expected=math.sqrt(2)*abs(math.sin(math.pi*h['order']*duty))/(math.pi*h['order'])
                self.assertLess(abs(h['rms']-expected),.003)

    def test_noncoherent_sine_amplitude_and_unresolved_short_frame(self):
        t=np.arange(1024)
        for fraction in (.1,.25,.49):
            r=spectrum(math.sqrt(2)*np.sin(2*np.pi*(32+fraction)*t/1024),102400,'flattop')
            self.assertLess(abs(r['peak_rms']-1),.001)
        r=spectrum(np.sin(2*np.pi*2*t/1024),102400,'flattop')
        self.assertIsNone(r['peak_rms']);self.assertFalse(r['resolved'])

    def test_result_group_and_remote_path_boundary(self):
        with tempfile.TemporaryDirectory() as folder:
            p=create_run(folder,'pnp_big','output')
            self.assertEqual(p.parent,Path(folder)/'PNP大功率'/'输出特性'/'步进')
            self.assertEqual(relative_run(p.relative_to(folder).as_posix()).name,p.name)
        for path in ('../escape','C:/tmp/file','a/../../b','/absolute','pnp_big/output/file','a\\b','a//b'):
            with self.assertRaises(ValueError):relative_run(path)

    def test_new_pdf_extract_with_negative_limits_conditions_and_provenance(self):
        import pymupdf
        with tempfile.TemporaryDirectory() as folder:
            pdf=Path(folder)/'new_model.pdf';d=pymupdf.open();p=d.new_page()
            rows=[['Parameter','Symbol','Conditions','Min','Typ','Max','Unit'],
                  ['Breakdown','VBR','IC=-1mA','-150','','','V'],
                  ['Gain','hFE','IC=-10mA','100','','300','']]
            for i,row in enumerate(rows):
                for j,cell in enumerate(row):p.insert_text((42+j*75,65+i*30),cell,fontsize=9)
            for i in range(4):p.draw_line((35,45+i*30),(560,45+i*30))
            for i in range(8):p.draw_line((35+i*75,45),(35+i*75,135))
            d.save(pdf);d.close()
            result,target=cached_extract(pdf,Path(folder)/'cache')
            self.assertEqual(len(result['parameters']),2)
            self.assertEqual(result['parameters'][0]['min'],'-150')
            self.assertEqual(result['parameters'][0]['conditions'],'IC=-1mA')
            self.assertEqual(result['parameters'][0]['page'],1)
            self.assertTrue(target.exists());self.assertTrue(result['review_required'])

    def test_bundled_pnp_values_keep_sign_and_distinct_limits(self):
        result=extract(ROOT/'data/datasheets/original_project/changjing_2N5401.pdf')
        rows=result['parameters']
        self.assertEqual(len(rows),18)
        self.assertFalse(any('芯' in r.get(k,'') or '查' in r.get(k,'') for r in rows for k in ('parameter','symbol','unit','min','max','value')))
        self.assertTrue(any(p['excluded_watermarks'] for p in result['pages']))
        self.assertTrue(any('芯' in str(r['raw_cells']) for r in rows))
        self.assertFalse(result['review_required'])
        self.assertTrue(any(r['symbol']=='hFE(1)' and 'VCE=-5 V' in r['conditions'] for r in rows))
        self.assertTrue(any(r['unit']=='°C/W' and r['value']=='200' for r in rows))
        self.assertTrue(any(r['value']=='-150' and 'Collector-Emitter' in r['parameter'] for r in rows))
        self.assertTrue(any(r['min']=='100' and r['max']=='300' and r['unit']=='MHz' for r in rows))


if __name__=='__main__':unittest.main()
