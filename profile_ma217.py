"""One captured hardware/firmware profile; no guessed fallback addresses."""
import hashlib, json
from pathlib import Path

if not __debug__:
    raise RuntimeError('Do not run device tools with Python -O: validation is required.')

ROOT = Path('artifacts/firmware-extracted')
OUT = ROOT / 'candidate-local-only'
BACKUP = Path('artifacts/original-flash.bin')
PROFILE = Path('artifacts/local-profile.json')
BASELINE_SHA = json.loads(PROFILE.read_text(encoding='utf8'))['backup_sha256'] if PROFILE.exists() else ''
PATCH_OFFSET, PATCH_SIZE = 0x277000, 0x92000
RECOVERY_OFFSET, RECOVERY_SIZE = 0x260000, 0xc0000
ORIGINAL_OSLO_SHA = '640a7c75b41099266979167949c39e57b877091da648a1f2ea6e99d75a7b50f9'
MODIFIED_OSLO_SHA = 'f6fbe10a90201d9269ae43d6e1455c1844556bd0e7be55f27e4e10144c5e0dcb'
OBMI_SHA = '91e9f6087589b456a93916c0c5db8b8918f80fe4b6420e8cf17f0ce659af487d'
AP_BASE, AP_SIZE = 0x064a2000, 1169916
PATCHES = [
    (0x065788a6, '2048', '7047', 'Return before SIMAUTH task creation'),
    (0x0656e584, '0022', '7047', 'Return before MAINSYN callback registration'),
    (0x0657ccbe, '60b9', '0020', 'Take the original disable-both-directions rate-control path'),
]

def sha(data):
    return hashlib.sha256(data).hexdigest()

def check(condition, message):
    if not condition:
        raise ValueError(message)

def validate_backup(data):
    check(len(data) == 0x800000, 'Need an 8 MiB capture; this is not a physical capacity claim.')
    check(sha(data[0x40000:0x450000]) == ORIGINAL_OSLO_SHA, 'Unsupported original OSLO; stop, do not reuse offsets.')
    check(sha(data[0x6000:0x6000+101212]) == OBMI_SHA, 'Unsupported bootloader; stop.')

def validate_modified(original, modified):
    check(sha(original) == ORIGINAL_OSLO_SHA, 'Original OSLO hash mismatch')
    check(sha(modified) == MODIFIED_OSLO_SHA, 'Modified OSLO hash mismatch')
    check(original[:0x237000] == modified[:0x237000] and original[0x2c9000:] == modified[0x2c9000:], 'Changes outside AP slot')
    before = unpack_ap(original)
    after = unpack_ap(modified)
    expected = bytearray(before)
    for address, old, new, purpose in PATCHES:
        offset = address - AP_BASE
        check(before[offset:offset+2] == bytes.fromhex(old), 'Original instruction mismatch: '+hex(address))
        expected[offset:offset+2] = bytes.fromhex(new)
    check(len(before) == AP_SIZE and bytes(expected) == after, 'Unexpected unpacked modification')
    return before, after

def unpack_ap(oslo):
    import lzma
    # Decode exactly one stream. lzma.decompress() may treat slot padding as a
    # second stream; the original slot contains non-stream bytes after EOF.
    slot=oslo[0x237000:0x2c9000]
    check(int.from_bytes(slot[5:13],'little') == AP_SIZE, 'Unexpected AP declared size')
    decoder=lzma.LZMADecompressor(format=lzma.FORMAT_ALONE)
    raw=decoder.decompress(slot,max_length=AP_SIZE+1)
    check(len(raw)==AP_SIZE and decoder.eof,'Unexpected decompressed AP length or incomplete stream')
    return raw
