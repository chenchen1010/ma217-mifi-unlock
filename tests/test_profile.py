"""Offline release checks. Never enumerate USB or send device commands."""
import json, sys, unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from profile_ma217 import validate_modified, validate_backup, unpack_ap, AP_BASE, PATCHES, RECOVERY_OFFSET, RECOVERY_SIZE

class FirmwareProfileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original=Path('firmware/OSLO-original.bin').read_bytes()
        cls.modified=Path('firmware/OSLO-unlocked.bin').read_bytes()

    def test_exact_six_instruction_bytes_and_unmodified_other_slots(self):
        before,after=validate_modified(self.original,self.modified)
        changed={i for i,(a,b) in enumerate(zip(before,after)) if a!=b}
        expected={a-AP_BASE+j for a,_,_,_ in PATCHES for j in range(2)}
        self.assertEqual(changed,expected)

    def test_wrong_original_is_rejected(self):
        bad=bytearray(self.original);bad[0x100]^=1
        with self.assertRaises(ValueError):validate_modified(bytes(bad),self.modified)

    def test_corrupted_modified_is_rejected(self):
        bad=bytearray(self.modified);bad[0x237100]^=1
        with self.assertRaises(ValueError):validate_modified(self.original,bytes(bad))

    def test_full_capture_length_is_required(self):
        with self.assertRaises(ValueError):validate_backup(self.original)

    def test_original_padded_slot_decodes_as_one_stream(self):
        self.assertEqual(len(unpack_ap(self.original)),1169916)

    def test_both_supported_erase_sizes_exactly_cover_complete_blocks(self):
        for block in (0x10000,0x20000):
            self.assertEqual(RECOVERY_OFFSET%block,0)
            self.assertEqual(RECOVERY_SIZE%block,0)
        self.assertEqual(RECOVERY_OFFSET+RECOVERY_SIZE,0x320000)
        self.assertNotEqual(0x92000%0x10000,0)

    def test_local_package_has_only_one_write_and_preserves_boundary_bytes(self):
        root=Path('artifacts/firmware-extracted/candidate-local-only')
        if not (root/'apply-rate-off.fbf').exists():self.skipTest('Run local prepare/build for package checks')
        b=(root/'apply-rate-off.fbf').read_bytes();m=json.loads((root/'apply-rate-off.json').read_text())
        images=m['images'];writes=[x for x in images if x['commands']==1]
        self.assertEqual(len(writes),1);w=writes[0]
        self.assertEqual((w['flash_address'],w['erase_size'],w['length']),(0x260000,0xc0000,0xc0000))
        self.assertTrue(all(x['erase_size']==0 for x in images if x['commands']!=1))
        payload=b[w['offset']:w['offset']+w['length']]
        original=Path('artifacts/original-flash.bin').read_bytes()
        expected=bytearray(original[0x260000:0x320000])
        expected[0x17000:0xa9000]=self.modified[0x237000:0x2c9000]
        self.assertEqual(payload,expected)

if __name__=='__main__':unittest.main()
