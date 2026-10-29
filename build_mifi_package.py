"""Local, exact-device package builder. Never opens USB or writes device Flash.

FBF v11 fields are independently matched to the captured OBMI ARM code.
Verification-only images use commands=2 and erase_size=0. OBMI: 0x7806448
returns without a driver call for zero erase size; 0x780908c skips WriteFlash.
"""
from pathlib import Path
import hashlib, json, struct, functools, operator, lzma

from profile_ma217 import ROOT, OUT, BACKUP, BASELINE_SHA, PATCH_OFFSET, PATCH_SIZE, RECOVERY_OFFSET, RECOVERY_SIZE

def ident(s): return int.from_bytes(s.encode(), 'big')
def sha(b): return hashlib.sha256(b).hexdigest()
def xor32(b): return functools.reduce(operator.xor, struct.unpack('<%dI' % (len(b)//4), b[:len(b)//4*4]), 0)

def signature_check(b, candidate):
    rsa = b[0x530020:0x532000]
    modulus, exponent = struct.unpack_from('<II', rsa)
    result = {}
    for name, sigoff, image, n in [
        ('cp', 0x20, candidate, 100),
        ('webui', 0x6a0, b[0x560000:0x5b0000], 100),
        ('dsp', 0xce0, b[0x450000:0x520000], 100),
        ('obm', 0x1320, b[0x6000:0x20000], 32),
    ]:
        for i in range(n):
            ws = struct.unpack_from('<4I', rsa, sigoff+i*16)
            decoded = bytes(pow(w, exponent, modulus)&255 for w in ws)
            assert decoded == image[i*2048+4:i*2048+8], (name, i)
        result[name] = {'samples_verified': n, 'original_signature_unchanged': True}
    return result

def build(mode):
    assert mode in ('noop', 'recover-original', 'apply-rate-off')
    b = BACKUP.read_bytes()
    assert len(b)==0x800000 and sha(b)==BASELINE_SHA
    original = (ROOT/'OSLO.bin').read_bytes()
    candidate = (OUT/'OSLO-rate-off.bin').read_bytes()
    assert len(original)==len(candidate)==0x410000
    assert candidate[:0x237000]==original[:0x237000]
    assert candidate[0x2c9000:]==original[0x2c9000:]
    raw = lzma.decompress(candidate[0x237000:0x2c9000], format=lzma.FORMAT_ALONE)
    before = (ROOT/'OSLO-unpacked-237000.bin').read_bytes()
    assert len(raw)==len(before)
    diffs = [i for i,(x,y) in enumerate(zip(raw,before)) if x!=y]
    expected = [0x065788a6-0x064a2000, 0x065788a7-0x064a2000,
                0x0656e584-0x064a2000, 0x0656e585-0x064a2000]
    expected += [0x0657ccbe-0x064a2000,0x0657ccbf-0x064a2000]
    assert raw[0x657ccbe-0x64a2000:0x657ccc0-0x64a2000]==bytes.fromhex('0020')
    assert sorted(diffs)==sorted(expected)
    signatures = signature_check(b, candidate)
    # These buffers satisfy the device's existing verifier but cannot write/erase.
    use_candidate = mode=='apply-rate-off'
    images = [('TIMH', b[:0x20000], 0, 0, 2),
              ('OSLO', candidate if use_candidate else original, 0, 0x40000, 2),
              ('GRBI', b[0x450000:0x520000], 0, 0x450000, 2),
              ('WEBI', b[0x560000:0x5b0000], 0, 0x560000, 2),
              ('NTLZ', b[0x530000:0x540000], 0, 0x530000, 2)]
    if mode in ('noop', 'recover-original', 'apply-rate-off'):
        # These entries are verification-only. Preserve every byte sampled by
        # the actual OBMI verifier; avoid sending unused multi-megabyte tails.
        limits={'TIMH':0x20000,'OSLO':0x40000,'GRBI':0x40000,'WEBI':0x40000,'NTLZ':0x2000}
        images=[(name,payload[:limits[name]],erase,addr,cmd) for name,payload,erase,addr,cmd in images]
    write_offset, write_size = PATCH_OFFSET, PATCH_SIZE
    if mode in ('recover-original', 'apply-rate-off'):
        write_offset, write_size = RECOVERY_OFFSET, RECOVERY_SIZE
        assert write_offset % 0x20000 == write_size % 0x20000 == 0
        payload = bytearray(b[write_offset:write_offset+write_size])
        if use_candidate:
            relative = PATCH_OFFSET - write_offset
            payload[relative:relative+PATCH_SIZE] = candidate[0x237000:0x2c9000]
        images.append(('APCH', bytes(payload), write_size, write_offset, 1))
    header = bytearray(0x1000)
    struct.pack_into('<H', header, 0x20, 11)
    struct.pack_into('<II', header, 0x34, 1, 1)
    struct.pack_into('<I', header, 0x3c, 0x100)
    dev = 0x100
    # EraseAll=0, ResetBBT=0, no skipped blocks, reset after download.
    header[dev+0xe4] = 1
    struct.pack_into('<I', header, dev+0xf0, len(images))
    blob = bytearray(header)
    manifest = []
    for i,(name,payload,erase,addr,cmd) in enumerate(images):
        assert len(blob)%0x1000==0 and len(payload)%4==0
        first_sector=len(blob)//0x1000
        words=[ident(name),0,0,erase,cmd,first_sector,len(payload),addr,0,0,0,0,xor32(payload)]
        struct.pack_into('<13I',blob,dev+0xf4+i*0x34,*words)
        blob += payload
        blob += bytes((-len(blob))%0x1000)
        manifest.append({'id':name,'offset':first_sector*0x1000,'length':len(payload),
                         'flash_address':addr,'erase_size':erase,'commands':cmd,'sha256':sha(payload)})
    # A small, RAM-only TIM: all non-FBF entries have FlashEntryAddr=FFFFFFFF.
    tim=bytearray(b[:56])+bytearray(3*96)
    struct.pack_into('<III',tim,44,3,0,0)
    def entry(at,name,nextname,flash,load,size):
        struct.pack_into('<7I',tim,at,ident(name),ident(nextname) if nextname else 0xffffffff,flash,load,size,0,0)
    entry(56,'TIMH','OBMI',0xffffffff,0xd1000000,len(tim))
    entry(152,'OBMI','FBFD',0xffffffff,0x7800000,101212)
    entry(248,'FBFD',None,0,0x6001000,len(blob))
    # ROM's download code copies exactly 0x400 bytes; transmit initialized padding.
    tim += bytes(0x400-len(tim))
    prefix=OUT / mode
    prefix.with_suffix('.fbf').write_bytes(blob)
    prefix.with_suffix('.tim').write_bytes(tim)
    report={'mode':mode,'backup_sha256':sha(b),'fbf_sha256':sha(blob),'tim_sha256':sha(tim),
            'size':len(blob),'images':manifest,'signature_checks':signatures,
            'expected_nonzero_erase_ranges':[] if mode=='noop' else [[write_offset,write_size]],
            'expected_write_ranges':[] if mode=='noop' else [[write_offset,write_size]],
            'legacy_unaligned_unsafe': False,
            'flash_execution':False}
    prefix.with_suffix('.json').write_text(json.dumps(report,indent=2),encoding='utf8')
    print(mode,len(blob),sha(blob),'write ranges',report['expected_write_ranges'])

if __name__=='__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=('noop','recover-original','apply-rate-off'), required=True)
    build(parser.parse_args().mode)
