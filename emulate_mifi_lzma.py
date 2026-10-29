"""Execute the captured OBMI LZMA decoder locally; no device access."""
from pathlib import Path
import hashlib, json, struct, time
from unicorn import Uc, UcError, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_CODE
from unicorn.arm_const import *

ROOT = Path('artifacts/firmware-extracted')
OUT = ROOT / 'candidate-local-only'

def run(name, source, expected):
    u = Uc(UC_ARCH_ARM, UC_MODE_ARM)
    u.mem_map(0x6000000, 0x2000000)
    u.mem_write(0x7800000, (ROOT / 'OBMI.bin').read_bytes())
    u.mem_write(0x7000000, source)
    u.mem_write(0x7f00000, struct.pack('<I', 0xe00000))
    u.reg_write(UC_ARM_REG_SP, 0x7f80000)
    u.reg_write(UC_ARM_REG_LR, 0x7ff0000)
    for reg, value in [(UC_ARM_REG_R0, 0x64a2000), (UC_ARM_REG_R1, 0x7f00000),
                       (UC_ARM_REG_R2, 0x7000000), (UC_ARM_REG_R3, len(source))]:
        u.reg_write(reg, value)
    def ret(value=0):
        u.reg_write(UC_ARM_REG_R0, value)
        u.reg_write(UC_ARM_REG_PC, u.reg_read(UC_ARM_REG_LR))
    def hook(uc, address, size, data):
        if address in (0x7805008, 0x78096d8, 0x7809734, 0x7813614):
            ret()
        elif address == 0x7803e8c:
            dst, src, length = [u.reg_read(x) for x in (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2)]
            u.mem_write(dst, bytes(u.mem_read(src, length)))
            ret(dst)
    # Hook only external dependencies, leaving the decoder native in Unicorn.
    for addr in (0x7805008, 0x78096d8, 0x7809734, 0x7813614, 0x7803e8c):
        u.hook_add(UC_HOOK_CODE, hook, begin=addr, end=addr)
    started = time.monotonic()
    try:
        u.emu_start(0x780a4b8, 0x7ff0000, timeout=50_000_000, count=200_000_000)
    except UcError as exc:
        print({'error': str(exc), 'pc': hex(u.reg_read(UC_ARM_REG_PC)),
               'registers': [hex(u.reg_read(UC_ARM_REG_R0+i)) for i in range(13)]}, flush=True)
        raise
    length = struct.unpack('<I', u.mem_read(0x7f00000, 4))[0]
    result = bytes(u.mem_read(0x64a2000, len(expected)))
    report = {'name': name, 'offline_only': True, 'returned': u.reg_read(UC_ARM_REG_PC) == 0x7ff0000,
              'return_code': u.reg_read(UC_ARM_REG_R0), 'output_length': length,
              'expected_length': len(expected), 'output_matches_expected': result == expected,
              'elapsed_seconds': time.monotonic() - started,
              'source_sha256': hashlib.sha256(source).hexdigest(),
              'limitations': 'Original ARM decoder; logging, memcpy and pre-heap initialization mocked.'}
    report['passed'] = report['returned'] and report['return_code'] == 0 and length == len(expected) and result == expected
    (OUT / (name + '-target-lzma.json')).write_text(json.dumps(report, indent=2), encoding='utf8')
    print(json.dumps(report), flush=True)
    return report['passed']

if __name__ == '__main__':
    original = (ROOT / 'OSLO.bin').read_bytes()[0x237000:0x2c9000]
    candidate = (OUT / 'OSLO-rate-off.bin').read_bytes()[0x237000:0x2c9000]
    results = [run('original', original, (ROOT / 'OSLO-unpacked-237000.bin').read_bytes()),
               run('rate-off', candidate, (OUT / 'AP-rate-off.bin').read_bytes())]
    if not all(results):
        raise SystemExit(1)
