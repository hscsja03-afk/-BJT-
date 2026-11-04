import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("check_bundle", ROOT / "check_bundle.py")
module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)


class Tests(unittest.TestCase):
    def test_reuse_with_image_and_motor_peripherals_from_another_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            work = root / 'unrelated_working_directory'
            work.mkdir()
            previous = Path.cwd()
            try:
                os.chdir(work)
                for name, instance, base, size in (
                    ('image_pipeline', 'image_filter_0', 0x40000000, 0x1000),
                    ('motor_control', 'motor_ctrl_1', 0x43c10000, 0x10000),
                ):
                    with self.subTest(project=name):
                        project = root / name
                        project.mkdir()
                        bit = b'synthetic integrity fixture: ' + name.encode()
                        hwh = (f'<SYSTEM><MODULE INSTANCE="ps7">'
                               f'<MEMRANGE INSTANCE="{instance}" BASEVALUE="{hex(base)}" '
                               f'HIGHVALUE="{hex(base + size - 1)}"/></MODULE>'
                               f'<MODULE INSTANCE="{instance}"/></SYSTEM>').encode()
                        (project / 'design.bit').write_bytes(bit)
                        (project / 'design.hwh').write_bytes(hwh)
                        manifest = {
                            'bit': {'path': 'design.bit', 'sha256': hashlib.sha256(bit).hexdigest()},
                            'hwh': {'path': 'design.hwh', 'sha256': hashlib.sha256(hwh).hexdigest()},
                            'peripheral': {'instance': instance, 'base': hex(base), 'size': hex(size)},
                        }
                        path = project / 'manifest.json'
                        path.write_text(json.dumps(manifest), encoding='utf-8')
                        result = module.verify(path)
                        self.assertTrue(result['files_and_address_verified'])
                        self.assertEqual(result['peripheral'], manifest['peripheral'])
                        self.assertFalse(result['hardware_validated'])
            finally:
                os.chdir(previous)

    def test_pairs_addresses_and_corruption(self):
        with tempfile.TemporaryDirectory() as directory:
            d = Path(directory)
            bit = b"synthetic-file-for-integrity-test-not-a-real-bitstream"
            xml = b'<SYSTEM><MODULE INSTANCE="ps7"><MEMRANGE INSTANCE="engine_0" BASEVALUE="0x40000000" HIGHVALUE="0x40000fff"/></MODULE><MODULE INSTANCE="engine_0"/></SYSTEM>'
            (d / "demo.bit").write_bytes(bit); (d / "demo.hwh").write_bytes(xml)
            m = {"bit": {"path": "demo.bit", "sha256": hashlib.sha256(bit).hexdigest()},
                 "hwh": {"path": "demo.hwh", "sha256": hashlib.sha256(xml).hexdigest()},
                 "peripheral": {"instance": "engine_0", "base": "0x40000000", "size": "0x1000"}}
            path = d / "manifest.json"
            path.write_text(json.dumps(m))
            result = module.verify(path)
            self.assertTrue(result["files_and_address_verified"])
            self.assertFalse(result["hardware_validated"])
            m["peripheral"]["base"] = "0x50000000"; path.write_text(json.dumps(m))
            with self.assertRaisesRegex(ValueError, "address range"): module.verify(path)
            m["peripheral"]["base"] = "0x40000000"; path.write_text(json.dumps(m))
            (d / "demo.bit").write_bytes(bit + b"changed")
            with self.assertRaisesRegex(ValueError, "hash mismatch"): module.verify(path)


if __name__ == "__main__": unittest.main()
