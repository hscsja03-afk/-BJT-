import copy
import unittest
from zynq_bjt.ac_history import progressive_record,reference_identity


class AcDisplayTrendTests(unittest.TestCase):
    def setUp(self):
        self.record=dict(id='example',manufacturer='未确认',model='未确认',identity_confirmed=False,
                         series=[dict(label='sweep (outliers replaced)',points=[[10000,100],[100000,50],[2000000,5]]),
                                 dict(label='stored fit samples',points=[[10000,101],[100000,49],[2000000,4.9]])],rin_series=[])

    def test_extension_follows_acquired_frequency_and_never_changes_original_data(self):
        original=copy.deepcopy(self.record)
        rows=[dict(actual_freq_hz=10000,gain=23),dict(actual_freq_hz=2000000,gain=2)]
        self.assertNotIn('extrapolation',progressive_record(self.record,rows))
        rows.append(dict(actual_freq_hz=3000000,gain=1))
        partial=progressive_record(self.record,rows)['extrapolation']
        self.assertEqual(partial['points'][0],[2000000,5])
        self.assertEqual(partial['frequency_max_hz'],3000000)
        rows.append(dict(actual_freq_hz=5000000,gain=.5))
        shown=progressive_record(self.record,rows)
        extension=shown['extrapolation']
        self.assertEqual(extension['frequency_max_hz'],5000000)
        self.assertTrue(extension['extrapolated'])
        values=[v for _,v in extension['points']]
        self.assertTrue(all(0<b<=a for a,b in zip(values,values[1:])))
        self.assertEqual(self.record,original)
        self.assertEqual(rows[-1]['gain'],.5)
        self.assertEqual(shown['rin_series'],[])

    def test_history_is_revealed_by_frequency_not_future_reference_points(self):
        shown=progressive_record(self.record,[dict(actual_freq_hz=10000)]*10)
        self.assertEqual(shown['series'][0]['points'],[[10000,100]])
        self.assertNotIn('extrapolation',shown)
        self.assertEqual(progressive_record(self.record,[])['series'],[])

    def test_title_fallback_does_not_relabel_the_original_record(self):
        device=dict(manufacturer='当前厂家',model='当前型号')
        self.assertEqual(reference_identity(self.record,device),'当前厂家 当前型号')
        self.assertEqual(self.record['model'],'未确认')
        known=dict(self.record,identity_confirmed=True,manufacturer='原厂家',model='原型号')
        self.assertEqual(reference_identity(known,device),'原厂家 原型号')


if __name__=='__main__':unittest.main()
