import json
from pathlib import Path
import tempfile
import unittest
from zipfile import ZipFile
from locate_epcb import locate


class PlacementTest(unittest.TestCase):
    def test_portable_lookup_and_rejection(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'other-board.epro'
            records = [['ATTR','a',0,'c',3,None,None,'Designator','U99'],
                       ['COMPONENT','c',0,1,123.5,456,90]]
            body = '\n'.join(json.dumps(r) for r in records)
            with ZipFile(path,'w') as z:
                z.writestr('PCB/other.epcb',body)
            result = locate(path,['U99'])
            self.assertEqual(result['placements']['U99']['x'],123.5)
            self.assertFalse(result['photo_position_verified'])
            with self.assertRaises(ValueError): locate(path,['U7'])
            with ZipFile(path,'a') as z: z.writestr('PCB/second.epcb',body)
            with self.assertRaises(ValueError): locate(path,['U99'])
            self.assertEqual(locate(path,['U99'],pcb_member='PCB/other.epcb')['placements']['U99']['rotation'],90)


if __name__ == '__main__': unittest.main()
